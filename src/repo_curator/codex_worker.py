from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .prompt_assets import PromptAsset, render_worker_prompt
from .workflow import EditReport, InspectionReport
from .worker import (
    EditRequest,
    InspectionRequest,
    WorkerEditResult,
    WorkerInspectionResult,
    WorkerRuntimeError,
    WorkerUsage,
)


class CodexCliWorker:
    backend = "codex_cli"

    def __init__(self, executable: str = "codex") -> None:
        self.executable = executable

    def inspect(
        self,
        request: InspectionRequest,
        *,
        resume_thread_id: str | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> WorkerInspectionResult:
        report, thread_id, usage = self._run(
            request,
            report_type=InspectionReport,
            prompt=render_worker_prompt(
                PromptAsset.WORKER_INSPECT,
                {**request.prompt_context(), "worker_continuation": resume_thread_id is not None},
            ),
            sandbox="read-only",
            resume_thread_id=resume_thread_id,
            on_event=on_event,
        )
        if not isinstance(report, InspectionReport):
            raise AssertionError("Inspection report type did not match its schema.")
        return WorkerInspectionResult(report=report, thread_id=thread_id, usage=usage)

    def edit(
        self,
        request: EditRequest,
        *,
        resume_thread_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> WorkerEditResult:
        report, thread_id, usage = self._run(
            request,
            report_type=EditReport,
            prompt=render_worker_prompt(PromptAsset.WORKER_EDIT, request.prompt_context()),
            sandbox="workspace-write",
            resume_thread_id=resume_thread_id,
            on_event=on_event,
        )
        if not isinstance(report, EditReport):
            raise AssertionError("Edit report type did not match its schema.")
        return WorkerEditResult(report=report, thread_id=thread_id, usage=usage)

    def _run(
        self,
        request: InspectionRequest | EditRequest,
        *,
        report_type: type[InspectionReport] | type[EditReport],
        prompt: str,
        sandbox: str,
        resume_thread_id: str | None,
        on_event: Callable[[dict[str, Any]], None] | None,
    ) -> tuple[InspectionReport | EditReport, str, WorkerUsage]:
        if not request.repository_path.is_dir():
            raise WorkerRuntimeError(f"Repository path does not exist: {request.repository_path}")
        if shutil.which(self.executable) is None:
            raise WorkerRuntimeError(f"Codex CLI executable not found: {self.executable}")

        with tempfile.TemporaryDirectory(prefix="repo-curator-worker-") as temporary_directory:
            temporary_path = Path(temporary_directory)
            schema_path = temporary_path / "worker-report.schema.json"
            output_path = temporary_path / "worker-report.json"
            schema_path.write_text(
                json.dumps(_strict_schema(report_type.model_json_schema()), indent=2),
                encoding="utf-8",
            )
            command = self._command(
                request,
                schema_path=schema_path,
                output_path=output_path,
                sandbox=sandbox,
                resume_thread_id=resume_thread_id,
                prompt=prompt,
            )
            stderr_path = temporary_path / "codex.stderr"
            try:
                with stderr_path.open("w", encoding="utf-8") as stderr_file:
                    process = subprocess.Popen(
                        command,
                        cwd=request.repository_path,
                        stdout=subprocess.PIPE,
                        stderr=stderr_file,
                        text=True,
                        bufsize=1,
                    )
                    assert process.stdout is not None
                    stdout_lines: list[str] = []
                    for line in process.stdout:
                        stdout_lines.append(line)
                        if on_event is not None:
                            _notify_event_callback(line, on_event)
                    return_code = process.wait()
            except OSError as error:
                raise WorkerRuntimeError(f"Could not start Codex CLI: {error}") from error

            completed = subprocess.CompletedProcess(
                command,
                return_code,
                "".join(stdout_lines),
                stderr_path.read_text(encoding="utf-8"),
            )
            events = _events_from_jsonl(completed.stdout)
            thread_id = _thread_id(events) or resume_thread_id
            usage = _usage_from_events(events)
            if completed.returncode != 0:
                raise WorkerRuntimeError(
                    _failure_message(completed, events),
                    thread_id=thread_id,
                    usage=usage,
                )
            if thread_id is None:
                raise WorkerRuntimeError("Codex did not emit a thread ID.", usage=usage)
            try:
                report = report_type.model_validate_json(output_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise WorkerRuntimeError(
                    f"Codex did not produce a valid {report_type.__name__}: {error}",
                    thread_id=thread_id,
                    usage=usage,
                ) from error
            return report, thread_id, usage

    def _command(
        self,
        request: InspectionRequest | EditRequest,
        *,
        schema_path: Path,
        output_path: Path,
        sandbox: str,
        resume_thread_id: str | None,
        prompt: str,
    ) -> list[str]:
        route = request.routing_decision
        command = [
            self.executable,
            "--cd",
            str(request.repository_path),
            "--model",
            route.provider_model,
            "--config",
            f'model_reasoning_effort="{route.reasoning_effort.value}"',
            "--sandbox",
            sandbox,
            "--ask-for-approval",
            "never",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if resume_thread_id is not None:
            command.extend(["resume", resume_thread_id])
        command.append(prompt)
        return command


def _strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    schema.pop("default", None)
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        properties = schema.get("properties")
        if isinstance(properties, dict):
            schema["required"] = list(properties)
    for value in schema.values():
        if isinstance(value, dict):
            _strict_schema(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strict_schema(item)
    return schema


def _events_from_jsonl(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise WorkerRuntimeError(f"Codex emitted invalid JSONL: {error}") from error
        if not isinstance(event, dict):
            raise WorkerRuntimeError("Codex emitted a JSONL event that was not an object.")
        events.append(event)
    return events


def _notify_event_callback(
    line: str,
    callback: Callable[[dict[str, Any]], None],
) -> None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if isinstance(event, dict):
        callback(event)


def _thread_id(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            return event["thread_id"]
    return None


def _usage_from_events(events: list[dict[str, Any]]) -> WorkerUsage:
    for event in reversed(events):
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if not isinstance(usage, dict):
            continue
        return WorkerUsage(
            input_tokens=_integer_or_none(usage.get("input_tokens")),
            cached_input_tokens=_integer_or_none(usage.get("cached_input_tokens")),
            output_tokens=_integer_or_none(usage.get("output_tokens")),
            reasoning_output_tokens=_integer_or_none(usage.get("reasoning_output_tokens")),
        )
    return WorkerUsage()


def _integer_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _failure_message(completed: subprocess.CompletedProcess[str], events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "error":
            message = event.get("message")
            if isinstance(message, str) and message.strip():
                return _truncate(message)
    message = completed.stderr.strip() or f"Codex exited with status {completed.returncode}."
    return _truncate(message)


def _truncate(value: str, limit: int = 1000) -> str:
    return value[:limit]

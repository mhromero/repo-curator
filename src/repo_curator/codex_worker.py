from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

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
            prompt=_inspection_prompt(request, resuming=resume_thread_id is not None),
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
            prompt=_edit_prompt(request),
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


def _inspection_prompt(request: InspectionRequest, *, resuming: bool) -> str:
    context = json.dumps(request.prompt_context(), indent=2, sort_keys=True)
    instructions = [
        "You are Repo Curator's single repository worker in the inspection phase.",
        "Inspect the repository statically and return the required InspectionReport.",
        "Do not modify files, install dependencies, run project code, run tests, use the network,",
        "or infer or overwrite human-confirmed facts. Treat human-confirmed facts as authoritative.",
        "Use repository evidence to identify concrete findings, proposed work, validation expectations,",
        "facts that need human confirmation, and consequential changes that require approval.",
        "This inspection grants no authority to edit or approve changes.",
    ]
    if resuming:
        instructions.append(
            "This is a continuation after human-confirmed facts were supplied. "
            "Reassess the prior inspection and return a complete revised InspectionReport."
        )
    instructions.extend(["Known context follows:", context])
    return "\n".join(instructions)


def _edit_prompt(request: EditRequest) -> str:
    context = json.dumps(request.prompt_context(), indent=2, sort_keys=True)
    return "\n".join(
        [
            "You are Repo Curator's single repository worker in the approved editing phase.",
            "Resume the existing repository context and perform only the approved cleanup.",
            "You may make clearly safe R2 changes that are within the approved inspection plan,",
            "plus only the explicitly approved R2 change requests in the supplied context.",
            "Safe changes are limited to disposable caches, .gitignore, verified README content or",
            "formatting, and unambiguous dependency metadata or lockfiles that do not change behavior.",
            "Do not silently remove factual README material unless it is demonstrably obsolete,",
            "duplicated, or incorrect.",
            "Do not modify source behavior, tests, dependencies, licensing, meaningful artifacts,",
            "or repository structure unless that exact action is explicitly approved in the context.",
            "Repository identity is controlled outside this worker: do not rename the repository "
            "directory, change Git remotes, invoke GitHub, or request authority for those actions. "
            "The guided controller applies a locally approved directory rename and, after separate "
            "final publication approval, any GitHub repository or remote rename. If a revision note "
            "mentions repository naming, perform only its in-repository file changes.",
            "Do not invent factual claims, attribution, academic context, results, or rights.",
            "Do not use the network or install dependencies. Cheap local sanity checks are allowed",
            "only when non-destructive and relevant to the approved work; they are not final validation.",
            "If additional authority is needed, make no such change and return an ApprovalRequest",
            "in the required EditReport. Return the actual changes and unresolved concerns.",
            "Treat declined R2 requests and their human decision notes as constraints; do not retry",
            "those actions unless the human later requests a revised edit scope.",
            "Known context follows:",
            context,
        ]
    )


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

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_curator.codex_worker import CodexCliWorker, _strict_schema
from repo_curator.models import (
    ChoiceJudgment,
    TriageClarifications,
    TriageJudgments,
    TriageResult,
)
from repo_curator.routing import RoutingConfig
from repo_curator.scanner import scan_repository
from repo_curator.workflow import (
    HumanFact,
    InspectionReport,
    PortfolioClassification,
    route_run,
    set_portfolio_classification,
    start_run,
)
from repo_curator.worker import WorkerRuntimeError, build_inspection_request


def test_codex_worker_uses_route_and_returns_structured_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _inspection_request(tmp_path)
    executable = _fake_codex(tmp_path)
    arguments_path = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_CODEX_ARGUMENTS", str(arguments_path))
    monkeypatch.setenv("FAKE_CODEX_REPORT", json.dumps({"summary": "Inspection complete."}))

    result = CodexCliWorker(str(executable)).inspect(request)

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert result.report.summary == "Inspection complete."
    assert result.thread_id == "thread-123"
    assert result.usage.input_tokens == 12
    assert result.usage.reasoning_output_tokens == 4
    assert arguments[arguments.index("--model") + 1] == "gpt-5.6-luna"
    assert arguments[arguments.index("--config") + 1] == 'model_reasoning_effort="low"'
    assert arguments[arguments.index("--sandbox") + 1] == "read-only"
    assert "--json" in arguments
    assert "--ignore-user-config" in arguments
    assert "--ignore-rules" in arguments
    prompt = arguments[-1]
    assert "Independent work." in prompt
    assert str(request.repository_path) not in prompt


def test_codex_worker_persists_thread_information_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _inspection_request(tmp_path)
    executable = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_CODEX_STATUS", "1")

    with pytest.raises(WorkerRuntimeError) as error:
        CodexCliWorker(str(executable)).inspect(request)

    assert error.value.thread_id == "thread-123"
    assert error.value.usage.output_tokens == 3
    assert "simulated failure" in str(error.value)


def test_codex_worker_resumes_existing_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _inspection_request(tmp_path)
    executable = _fake_codex(tmp_path)
    arguments_path = tmp_path / "arguments.json"
    monkeypatch.setenv("FAKE_CODEX_ARGUMENTS", str(arguments_path))
    monkeypatch.setenv("FAKE_CODEX_REPORT", json.dumps({"summary": "Retried inspection."}))

    result = CodexCliWorker(str(executable)).inspect(request, resume_thread_id="existing-thread")

    arguments = json.loads(arguments_path.read_text(encoding="utf-8"))
    assert result.thread_id == "thread-123"
    assert arguments[arguments.index("exec") + 1] == "--ignore-user-config"
    assert "resume" in arguments
    assert arguments[arguments.index("resume") + 1] == "existing-thread"


def test_codex_output_schema_forbids_extra_properties_at_every_object_level() -> None:
    schema = _strict_schema(InspectionReport.model_json_schema())

    _assert_objects_forbid_extra_properties(schema)


def _assert_objects_forbid_extra_properties(value: object) -> None:
    if isinstance(value, dict):
        assert "default" not in value
        if value.get("type") == "object":
            assert value["additionalProperties"] is False
            properties = value.get("properties")
            if isinstance(properties, dict):
                assert value["required"] == list(properties)
        for nested_value in value.values():
            _assert_objects_forbid_extra_properties(nested_value)
    elif isinstance(value, list):
        for nested_value in value:
            _assert_objects_forbid_extra_properties(nested_value)


def _inspection_request(tmp_path: Path):
    repository = tmp_path / "sample-project"
    repository.mkdir()
    (repository / "README.md").write_text("# Sample\n", encoding="utf-8")
    scan_result = scan_repository(repository)
    judgment = ChoiceJudgment(choice="single_project", confidence=0.8)
    triage_result = TriageResult(
        triage_summary=scan_result.triage_summary,
        judgments=TriageJudgments(
            project_extent=judgment,
            repository_completeness=judgment,
            cleanup_effort=ChoiceJudgment(choice="light", confidence=0.8),
            repository_composition=judgment,
            technical_domain=judgment,
            organization_treatment=judgment,
            readme_expectation=judgment,
            reproducibility_expectation=judgment,
            clarifications=TriageClarifications(
                authorship=0.2,
                academic_context=0.8,
                repository_boundaries=0.3,
                data_asset_rights=0.9,
                intended_execution=0.6,
            ),
        ),
        provider_model="jev-test",
    )
    run = start_run(scan_result.repository_profile, triage_result)
    set_portfolio_classification(run, PortfolioClassification.B)
    run.human_facts["authorship"] = HumanFact(key="authorship", value="Independent work.")
    route_run(run, RoutingConfig.from_environment())
    return build_inspection_request(run)


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
arguments_path = os.environ.get("FAKE_CODEX_ARGUMENTS")
if arguments_path:
    Path(arguments_path).write_text(json.dumps(arguments), encoding="utf-8")
output_path = Path(arguments[arguments.index("--output-last-message") + 1])
if os.environ.get("FAKE_CODEX_STATUS") != "1":
    output_path.write_text(os.environ.get("FAKE_CODEX_REPORT", '{"summary": "Inspection complete."}'), encoding="utf-8")
print(json.dumps({"type": "thread.started", "thread_id": "thread-123"}))
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "cached_input_tokens": 5, "output_tokens": 3, "reasoning_output_tokens": 4}}))
if os.environ.get("FAKE_CODEX_STATUS") == "1":
    print(json.dumps({"type": "error", "message": "simulated failure"}))
    sys.exit(1)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable

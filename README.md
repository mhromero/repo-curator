# Repo Curator

A lightweight, human-in-the-loop workflow for auditing, cleaning, documenting, validating, and preparing software repositories for GitHub portfolio publication.

## Status

Design / early implementation.

The first target use case is old university coursework that should be understandable and presentable without rewriting the original student work.

## Why this project exists

Cleaning many old repositories manually repeats the same work: inspect the repository, decide how much cleanup is justified, resolve missing context, prepare a safe edit plan, update documentation and packaging, validate the result, and review it before publication.

Repo Curator turns that repeated process into a small, explicit workflow while keeping the human in control.

## Design principles

- Preserve authentic work. Imperfection is not a defect.
- Use deterministic code before spending model tokens.
- Use models for judgment and editing, not for checks ordinary software can perform.
- Ask the human for facts the repository cannot establish.
- Require human review after inspection, after editing, and before declaring a GitHub repository finished.
- Prefer the cheapest capable worker and escalate only for concrete blockers.
- Keep documentation and validation proportional to project scope and portfolio value; never manufacture production ceremony for simple coursework.
- Keep one Codex worker context per repository where practical so inspection knowledge is reused during editing and diagnosis.
- Do not silently delete, refactor, modernize, or invent attribution.

## Intended workflow

```text
Target repository
    |
    v
Static scanner
    |
    v
Jev triage
    |
    v
Human clarification
    |
    v
Codex inspection
    |
    v
Human inspection review
    |
    v
Codex editing
    |
    v
Human edit review
    |
    v
Deterministic validation
    |              |
   pass           fail
    |              |
    |         same Codex worker
    |            diagnoses
    |              |
    +--------------+
    |
    v
Final GitHub review
    |
    v
FINISHED
```

## Planned stack

- Python
- `uv`
- Pydantic
- Typer
- Rich
- TypeSafe Python SDK / Jev for structured triage
- Codex as the repository worker
- pytest
- Git and ordinary ecosystem tooling for validation

No LangGraph or n8n is planned for v1. The workflow is intentionally implemented with normal Python so its state, routing, approvals, and failure handling remain visible and understandable.

## Initial scope

V1 should prove one useful loop:

1. Scan a local repository without modifying it.
2. Build a compact triage summary.
3. Use Jev for the small set of judgments that should not be hard-coded.
4. Ask the human for unresolved facts and portfolio priority.
5. Produce a worker route and inspection instructions.
6. Run one persistent Codex worker through inspection and approved editing.
7. Validate the resulting repository deterministically.
8. Require final human review before marking the run finished.

Batch processing, dashboards, databases, autonomous publishing, and complex orchestration frameworks are deliberately out of scope until the single-repository workflow works well.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Workflow and human gates](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)

## Development philosophy

This project is also a learning project. Changes should be incremental and understandable. Prefer a small working implementation with tests and recorded evaluations over a sophisticated framework whose behavior is difficult to explain.

# Repo Curator

Repo Curator is intended to help prepare older software repositories for portfolio publication while preserving original work and keeping consequential decisions with the human.

## Current status

The implemented feature is a local, offline, read-only scanner. `repo-curator scan <path>` returns a `RepositoryProfile` with detailed evidence and a derived `TriageSummary` with compact counts and signals. It inventories files and languages, records ignored directories and available local Git metadata, and detects dependency, README, test, build, package-script, entry-point, artifact, Python-import, secret-risk, local-path, and Git-hygiene signals.

The scanner does not execute target code, install dependencies, call a model, or modify the target. Content checks are bounded; findings identify paths, lines, and rules, not matched secret values. The JSON profile includes the target's absolute path and relative file paths, so review it before sharing.

Jev/TypeSafe triage, human-question and run-state management, Codex inspection/editing, deterministic validation, and final-publication review are not implemented yet. The linked workflow and architecture documents describe plans, not available commands.

## Installation

Requirements: Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).

From a checkout:

```sh
uv sync --dev
```

## Usage

Scan a repository, replacing the example path with the directory to inspect:

```sh
uv run --frozen repo-curator scan /path/to/repository
```

The default output is a concise human-readable summary. Add `--json` to print a JSON object with `repository_profile` and `triage_summary`:

```sh
uv run --frozen repo-curator scan /path/to/repository --json
```

Git metadata is collected when Git is available and the directory belongs to a local Git repository. The scanner does not fetch remote data; it cannot establish whether a remote is a fork.

## Development

Install the development dependencies, then run the test suite:

```sh
uv sync --dev
uv run --frozen pytest -q
```

Smoke-test the scanner against this checkout with `uv run --frozen repo-curator scan .`.

## Planned direction

The intended single-repository workflow adds structured triage, human clarification and approval checkpoints, one persistent Codex worker for inspection and approved edits, deterministic validation, and final human review. These stages remain design work; the current CLI only supports scanning.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Planned workflow](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)

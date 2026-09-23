# Repo Curator

Repo Curator is intended to help prepare older software repositories for portfolio publication while preserving original work and keeping consequential decisions with the human.

## Current status

Implemented features are a local, read-only scanner and TypeSafe/Jev structured triage. `repo-curator scan <path>` returns a detailed `RepositoryProfile` and a redacted `TriageSummary`. `repo-curator triage <path>` scans the target, sends that summary to TypeSafe, and returns typed judgments about repository extent, completeness, portfolio-preparation effort, composition, organization, README and reproducibility expectations, technical domain, and needed human clarification.

The scanner runs offline and does not execute target code, install dependencies, or modify the target. The triage summary contains a budgeted relative repository outline: directories, file metadata, special files, README excerpts, configuration, entry points, imports, artifacts, and risk findings. It excludes source-file bodies, secret and local-path values, package-script command bodies, dependency contents, and remote URLs. Review the JSON before sharing because it includes repository and file names.

Triage identifies hypotheses and human questions; it does not authorize edits, infer personal facts, select a Codex model, or validate the repository. Human-question and run-state management, routing, Codex inspection/editing, validation, and final-publication review are not implemented yet.

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

### TypeSafe triage

Set a TypeSafe API key in your shell, then run triage. Do not add the key to repository files.

```sh
export TYPESAFE_API_KEY='your-key-here'
uv run --frozen repo-curator triage /path/to/repository
```

Set `TYPESAFE_DEFAULT_MODEL` or pass `--model` to choose an available TypeSafe model or alias:

```sh
export TYPESAFE_DEFAULT_MODEL='your-model-or-alias'
uv run --frozen repo-curator triage /path/to/repository --json
uv run --frozen repo-curator triage /path/to/repository --model 'your-model-or-alias'
```

Triage makes a paid external API request. Its JSON result contains the submitted summary, typed choices with confidence/probabilities, clarification probabilities, and reported token usage.

## Development

Install the development dependencies, then run the test suite:

```sh
uv sync --dev
uv run --frozen pytest -q
```

Smoke-test the scanner against this checkout with `uv run --frozen repo-curator scan .`.

## Planned direction

The intended single-repository workflow next adds human clarification and approval checkpoints, deterministic routing, one persistent Codex worker for inspection and approved edits, validation, and final human review. These stages remain design work; the current CLI supports scanning and triage only.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Planned workflow](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)

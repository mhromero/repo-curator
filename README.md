# Repo Curator

Repo Curator is intended to help prepare older software repositories for portfolio publication while preserving original work and keeping consequential decisions with the human.

## Current status

Implemented features are a local, read-only scanner, TypeSafe/Jev structured triage, and persisted human-review run state. `repo-curator scan <path>` returns a detailed `RepositoryProfile` and a redacted `TriageSummary`. `repo-curator triage <path>` scans the target, sends that summary to TypeSafe, and returns typed judgments about repository extent, completeness, portfolio-preparation effort, composition, organization, README and reproducibility expectations, technical domain, and possible human clarification.

The scanner runs offline and does not execute target code, install dependencies, or modify the target. The triage summary contains a budgeted relative repository outline: directories, file metadata, special files, README excerpts, configuration, entry points, imports, artifacts, and risk findings. It excludes source-file bodies, secret and local-path values, package-script command bodies, dependency contents, and remote URLs. Review the JSON before sharing because it includes repository and file names.

Triage identifies hypotheses; it does not authorize edits, infer personal facts, select a Codex model, or validate the repository. Its R4 `Noul` clarification probabilities are advisory signals shown to the human. They do not currently create `FactRequest` records. A/B/C portfolio classification is the only mandatory initial human input; the human may also record confirmed facts for suggested topics. Those facts are the downstream source of truth.

R5 persists a run, applies explicit human input and approval gates, and accepts structured inspection/edit reports. It does not launch Codex, edit the target, route models, perform validation, or publish to GitHub.

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

### Human-review run

Start a persisted run with one scan and one triage request. Run state is stored outside the target repository at `~/.repo-curator/runs/<run-id>/run.json` by default. Use `--state-root` to select a different local state directory.

```sh
export TYPESAFE_API_KEY='your-key-here'
uv run --frozen repo-curator run start /path/to/repository
```

The command prints a run ID and the raw advisory clarification signals. It starts in `WAITING_FOR_INPUT` until you set the human portfolio classification; those signals do not currently create pending facts:

```sh
uv run --frozen repo-curator run classify <run-id> B
uv run --frozen repo-curator run show <run-id>
```

Record a fact when it is relevant to a triage suggestion, or use `not applicable` as the value when that is the human answer:

```sh
uv run --frozen repo-curator run answer <run-id> authorship 'Independent work.'
uv run --frozen repo-curator run facts <run-id>
```

The remaining `run inspection`, `run approval`, `run edit`, and `run final` subcommands enforce review-state boundaries and can record human decisions on structured reports. Inspection may introduce concrete `FactRequest` records. They do not produce inspection or edit reports themselves: Codex integration and deterministic validation remain unimplemented. Automatic conversion of R4 clarification signals into `FactRequest` records is deliberately deferred until real-repository evaluation data supports a policy. In particular, no current command can advance a run from `VALIDATING` to `READY_FOR_FINAL_REVIEW`; only a future validator may do that, and `FINISHED` always requires `run final approve`.

### Deterministic routing

After classification, route the persisted run without making another API request or launching a worker:

```sh
uv run --frozen repo-curator run route <run-id>
```

The route records work depth, a configuration-neutral cost class, resolved model family/provider model, and reasoning effort. A/B/C plus R4 project extent determine work depth; R4 cleanup effort determines the initial cost class and effort. Repository age, size, file count, and importance alone do not select a stronger configuration.

The default mapping is Luna for economy routes, Terra for enhanced routes, and Sol only for future approved escalations. Model identifiers are configured centrally with `REPO_CURATOR_LUNA_MODEL`, `REPO_CURATOR_TERRA_MODEL`, and `REPO_CURATOR_SOL_MODEL`. Each configured family declares supported effort levels; the current defaults support `low`, `medium`, `high`, and `xhigh`.

## Development

Install the development dependencies, then run the test suite:

```sh
uv sync --dev
uv run --frozen pytest -q
```

Smoke-test the scanner against this checkout with `uv run --frozen repo-curator scan .`.

## Planned direction

The intended single-repository workflow next adds one persistent Codex worker for inspection and approved edits, validation, and final-publication verification. The current CLI does not launch a worker or modify a target repository.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Planned workflow](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)

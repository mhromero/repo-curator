# Repo Curator

Repo Curator is intended to help prepare older software repositories for portfolio publication while preserving original work and keeping consequential decisions with the human.

## Current status

Implemented features are a local, read-only scanner, TypeSafe/Jev structured triage, persisted human-review run state, deterministic routing, and a read-only Codex inspection worker. `repo-curator scan <path>` returns a detailed `RepositoryProfile` and a redacted `TriageSummary`. `repo-curator triage <path>` scans the target, sends that summary to TypeSafe, and returns typed judgments about repository extent, completeness, portfolio-preparation effort, composition, organization, README and reproducibility expectations, technical domain, and possible human clarification.

The scanner runs offline and does not execute target code, install dependencies, or modify the target. The triage summary contains a budgeted relative repository outline: directories, file metadata, special files, README excerpts, configuration, entry points, imports, artifacts, and risk findings. It excludes source-file bodies, secret and local-path values, package-script command bodies, dependency contents, and remote URLs. Review the JSON before sharing because it includes repository and file names.

Triage identifies hypotheses; it does not authorize edits, infer personal facts, select a Codex model, or validate the repository. Its R4 `Noul` clarification probabilities are advisory signals shown to the human. They do not currently create `FactRequest` records. A/B/C portfolio classification is the only mandatory initial human input; the human may also record confirmed facts for suggested topics. Those facts are the downstream source of truth.

R5 persists a run and applies explicit human input and approval gates. R6 records the deterministic model and reasoning-effort route. R7 launches only a read-only Codex inspection and records its structured report; it does not edit the target, validate it, or publish it to GitHub.

## Installation

Requirements: Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/). Codex inspection also requires the local Codex CLI authenticated with `codex login`.

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
uv run --frozen repo-curator run start /path/to/repository --interactive
```

The interactive command prompts for the initial A/B/C classification, routes the repository, and launches read-only Codex inspection. If inspection requests facts, it collects them in the same terminal session and resumes the persisted Codex thread. It stops only when a complete inspection report reaches the human review gate. The command prints a run ID and the raw advisory clarification signals; those signals do not currently create pending facts.

Use `run start` without `--interactive` when you need separate, scriptable steps. In that mode, use the interactive batch prompt:

```sh
uv run --frozen repo-curator run input <run-id>
uv run --frozen repo-curator run show <run-id>
```

For an existing run paused for worker-requested facts, continue the same interactive flow with:

```sh
uv run --frozen repo-curator run continue <run-id>
```

It collects all pending answers and resumes the saved Codex thread. `run input`, `run classify`, and `run answer` remain available for scripting or one-off changes. Use `not applicable` when that is the human answer:

```sh
uv run --frozen repo-curator run answer <run-id> authorship 'Independent work.'
uv run --frozen repo-curator run facts <run-id>
```

Inspection may introduce concrete `FactRequest` records. `run approval`, `run edit`, and `run final` continue to enforce review-state boundaries, but editing and validation remain unimplemented. Automatic conversion of R4 clarification signals into `FactRequest` records is deliberately deferred until real-repository evaluation data supports a policy. In particular, no current command can advance a run from `VALIDATING` to `READY_FOR_FINAL_REVIEW`; only a future validator may do that, and `FINISHED` always requires `run final approve`.

### Deterministic routing

After classification, route the persisted run without making another API request or launching a worker:

```sh
uv run --frozen repo-curator run route <run-id>
```

The route records work depth, a configuration-neutral cost class, resolved model family/provider model, and reasoning effort. A/B/C plus R4 project extent determine work depth; R4 cleanup effort determines the initial cost class and effort. Repository age, size, file count, and importance alone do not select a stronger configuration.

The default mapping is `gpt-5.6-luna` for economy routes, `gpt-5.6-terra` for enhanced routes, and `gpt-5.6-sol` only for future approved escalations. Model identifiers remain configurable with `REPO_CURATOR_LUNA_MODEL`, `REPO_CURATOR_TERRA_MODEL`, and `REPO_CURATOR_SOL_MODEL`. Each configured family declares supported effort levels; the current defaults support `low`, `medium`, `high`, and `xhigh`.

### Codex inspection

After routing, authenticate Codex once and launch the read-only inspection worker:

```sh
codex login
uv run --frozen repo-curator run inspection execute <run-id>
```

The command uses the persisted R6 model and reasoning effort, sends a compact R3–R6 context plus confirmed human facts, and requires a schema-valid `InspectionReport`. It prints worker route, thread, and inspection status, then normally ends in `WAITING_INSPECTION_REVIEW` (or `WAITING_FOR_INPUT` when the report requests required facts). Use `run continue <run-id>` to answer those facts and resume inspection. It does not modify the target repository. A failed worker remains in `INSPECTING` with concise failure metadata and can be retried with the same command.

The current runtime is the locally authenticated Codex CLI. An OpenAI Agents SDK adapter remains a possible future backend, but it is not installed or selected because it requires separately billed API Platform credentials, which are not configured for this project.

## Development

Install the development dependencies, then run the test suite:

```sh
uv sync --dev
uv run --frozen pytest -q
```

Smoke-test the scanner against this checkout with `uv run --frozen repo-curator scan .`.

## Planned direction

The intended single-repository workflow next adds approved editing in the persistent Codex context, deterministic validation, and final-publication verification. The current CLI launches only read-only inspection and never modifies a target repository.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Planned workflow](docs/WORKFLOW.md)
- [Requirements](docs/REQUIREMENTS.md)
- [Evaluation strategy](docs/EVALUATION.md)
- [Codex development instructions](AGENTS.md)

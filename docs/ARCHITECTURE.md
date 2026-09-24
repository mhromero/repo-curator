# Architecture

## Goal

Repo Curator is intentionally a small human-in-the-loop orchestration system rather than a collection of autonomous agents.

The architecture separates deterministic evidence collection, structured model judgment, generative repository work, deterministic validation, and human authority.

## Components

The static scanner, structured triage, human-review run state, and deterministic router are implemented today. Components 5–7 describe the planned architecture and are not wired into the current CLI.

### 1. Static scanner

Ordinary Python gathers objective repository evidence without executing or modifying the target project.

`repo-curator scan <path>` returns a `ScanResult` containing:

- `RepositoryProfile`: rich, path-level deterministic evidence for the run;
- `TriageSummary`: a budgeted, redacted repository outline for triage. It contains relative paths and selected README text, but not source-file bodies, secret values, local-path values, package-script commands, dependency contents, or remote URLs.

The scan runs offline and does not execute target code, install dependencies, or modify the target repository. Content-based signals use bounded reads and retain only findings, never matched secret values. Git metadata, including remote names and upstream status, is read locally; remote/fork relationships are not verified.

### 2. Jev triage

`repo-curator triage <path>` scans the local target and sends only its `TriageSummary` to TypeSafe/Jev. It uses centralized `Choice` and `Noul` questions to return typed judgments for later routing, human clarification, and worker inspection context.

Jev does not authorize changes, infer personal facts, choose a Codex model, or validate the repository. Its output is a hypothesis-rich `TriageResult`; the future deterministic router interprets it with human portfolio value and scanner evidence.

Output: `TriageResult`.

### 3. Human clarification and decision gates

`repo-curator run start <path>` scans and triages once, persists both outputs, and requires the human to assign portfolio value A/B/C before the run can leave `WAITING_FOR_INPUT`.

The raw R4 `Noul` clarification probabilities remain advisory model signals displayed to the human; R5 does not turn them into `FactRequest` records. A/B/C is the only mandatory initial human input. The user may record a fact for a suggested topic, and inspection reports may add concrete required facts. Confirmed facts are persisted and are the source of truth for later phases. Automatic conversion of R4 signals into `FactRequest` records is deliberately deferred until real-repository evaluation data supports a policy.

R5 also persists inspection/edit reports and enforces explicit inspection approval, R2 approval requests, edit review, and final-review boundaries. It provides no worker or validator implementation.

### 4. Deterministic router

`repo-curator run route <run-id>` uses deterministic Python to persist a `RoutingDecision`. It requires the human A/B/C classification and an R4 `TriageResult`.

Portfolio value plus R4 project extent determine work depth. R4 cleanup effort determines a configuration-neutral cost class and reasoning effort; centralized configuration resolves that pair to a supported model family and provider model. Model family and reasoning effort are separate dimensions, not a universal capability ladder.

The initial policy resolves C/light to Luna/low, B/moderate to Luna/medium, A/light to Luna/low, and B/A substantial effort to an enhanced/high configuration, which defaults to Terra/high. Sol is never selected initially. Repository size, age, file count, or portfolio importance alone do not select a stronger configuration.

R6 defines and persists concrete escalation requests and decisions, including either a reasoning-effort increase, model-family switch, or both. It does not launch a worker or accept worker requests through the CLI yet.

### 5. Persistent Codex worker

R7 implements the first phase through a small `CodexCliWorker` adapter. It receives a compact `InspectionRequest`, rather than a `RepositoryRun`, then invokes `codex exec` with the R6 provider model, `model_reasoning_effort`, read-only sandboxing, JSONL events, and the existing `InspectionReport` JSON Schema. Repo Curator stores only the Codex thread ID and concise attempt telemetry; Codex owns conversation history. A failed inspection remains `INSPECTING` so it can retry or resume its known thread without inventing a new workflow state.

The locally authenticated Codex CLI is the current backend because it works with the available Codex access. The OpenAI Agents SDK is a viable future adapter for application-managed sessions and sandboxes, but it requires separately billed API Platform credentials that are not configured for this project. It is not an R7 dependency.

One Codex context per repository is preferred.

The same worker moves through phase-specific instructions:

```text
INSPECT -> human review -> EDIT -> human review
                                      |
                                      v
                            validation failure?
                                      |
                                      v
                                  DIAGNOSE
```

Inspection is implemented and read-only. Editing follows the approved plan and R2 authority when implemented. Diagnosis is invoked only when deterministic validation produces a failure requiring reasoning.

Specialization comes from prompts and phase boundaries, not separate agents that reread the repository.

### 6. Deterministic validator

The validator uses ordinary tools where possible:

- dependency installation;
- imports/builds;
- documented run commands;
- existing tests;
- relevant lint/static checks;
- README and metadata checks;
- Git hygiene;
- secret-risk checks;
- final diff checks.

Validation returns structured results rather than asking an LLM whether commands succeeded.

### 7. Human final review

The user reviews the actual GitHub repository. Automated success only makes the repository ready for final review; it does not mark the run finished.

## Why no LangGraph in v1?

The workflow is mostly sequential, has a small number of explicit states, and intentionally stops for human review. Plain Python makes state transitions, approvals, routing, and failure handling easy to inspect and test.

A workflow framework should only be introduced if real usage demonstrates a need for features such as durable distributed execution, complex parallel branches, large-scale persistence, or orchestration complexity that normal Python no longer handles cleanly.

Avoiding LangGraph is not avoiding agent engineering. The core engineering work here is deciding:

- what context models receive;
- where deterministic code is better;
- how human authority is represented;
- how state survives between phases;
- how model capability is routed;
- how failures are diagnosed;
- how behavior is evaluated.

## Provider boundaries

External model/provider concepts should be isolated behind small adapters.

Example:

```text
repo-curator domain
        |
   TriageProvider
        |
   Jev provider
        |
 typesafe-sdk
```

Unit tests should use fake providers rather than making paid API calls.

Likewise, Codex execution should eventually be isolated behind a worker interface so routing and state logic can be tested without launching a real worker.

## State

Repo Curator state must live outside the target repository to prevent accidental publication.

R5 stores one JSON document per run by default:

```text
~/.repo-curator/
  runs/
    <run-id>/run.json
```

The `--state-root` CLI option overrides that location for local use and tests. The document contains the scanner profile, triage result, human facts, portfolio classification, checkpoint reports/decisions, current state, and a compact transition history. It never writes internal state into the target repository.

Important state includes:

- scanner evidence;
- triage decisions;
- human-confirmed facts;
- portfolio value;
- inspection report;
- approved edit plan;
- actual-change report;
- routing decision and escalation history;
- final human approval.

## Target-repository boundary

The target repository should never contain Repo Curator's internal prompts, run state, triage output, or telemetry.

Only intentional portfolio changes belong in the target repository.

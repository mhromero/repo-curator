# Architecture

## Goal

Repo Curator is intentionally a small human-in-the-loop orchestration system rather than a collection of autonomous agents.

The architecture separates deterministic evidence collection, structured model judgment, generative repository work, deterministic validation, and human authority.

## Components

Only the static scanner is implemented today. Components 2–7 describe the planned architecture and are not wired into the current CLI.

### 1. Static scanner

Ordinary Python gathers objective repository evidence without executing or modifying the target project.

`repo-curator scan <path>` returns a `ScanResult` containing:

- `RepositoryProfile`: rich, path-level deterministic evidence for the run;
- `TriageSummary`: compact derived counts and signals for later triage, without absolute paths or file contents.

The scan runs offline and does not execute target code, install dependencies, or modify the target repository. Content-based signals use bounded reads and retain only findings, never matched secret values. Git metadata, including remote names and upstream status, is read locally; remote/fork relationships are not verified.

### 2. Jev triage

TypeSafe/Jev performs a small set of structured judgments that would be brittle to encode as rules.

The exact question contract must be designed against the current official TypeSafe skill and SDK documentation.

Output: `TriageResult`.

### 3. Human clarification

The orchestrator gathers facts that models must not invent and asks the user to assign portfolio value A/B/C.

Answers are persisted as run facts so downstream stages do not repeatedly ask the same questions.

### 4. Deterministic router

Python combines scanner evidence, triage output, human facts, portfolio value, and routing policy.

It decides work depth and initial worker tier. It also enforces escalation policy.

Work depth is proportional: project extent and human-assigned portfolio value determine which checks and documentation are justified. A small archive exercise should follow a deliberately lighter path than a showcase project.

### 5. Persistent Codex worker

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

Inspection is read-only. Editing follows the approved plan and R2 authority. Diagnosis is invoked only when deterministic validation produces a failure requiring reasoning.

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

A future run directory may resemble:

```text
.repo-curator/
  runs/
    <run-id>/
      repository.json
      triage.json
      decisions.json
      inspection.json
      validation.json
      result.json
```

The exact format is not fixed yet.

Important state includes:

- scanner evidence;
- triage decisions;
- human-confirmed facts;
- portfolio value;
- inspection report;
- approved edit plan;
- baseline validation;
- actual changes;
- validation results;
- escalation history;
- final human approval.

## Target-repository boundary

The target repository should never contain Repo Curator's internal prompts, run state, triage output, or telemetry.

Only intentional portfolio changes belong in the target repository.

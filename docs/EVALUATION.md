# Evaluation Strategy

Repo Curator should be evaluated as a workflow, not only as a Python program.

The current implementation includes the static scanner, TypeSafe/Jev triage, and deterministic R5 run-state transitions. Codex execution, routing, and validation have not been implemented or evaluated.

## Unit tests

The current suite has twenty-one deterministic tests covering scanner inventory and language signals, ignored directories, non-execution, R3 evidence, summary redaction and budgeting, local Git metadata, symlinks, TypeSafe question construction, provider response validation, mocked CLI output, R5 state transitions, approval boundaries, persistence, and mocked run CLI output. It makes no paid TypeSafe or Codex calls.

Future unit-test coverage should include:

- router keeps low-priority archive work cheap;
- routing/check policy does not add production-style ceremony to simple coursework;
- router requires a concrete escalation reason;
- invalid provider responses are rejected;
- state transitions require human checkpoints;
- validator detects missing required README information;
- target repositories never receive internal Repo Curator state.

Unit tests should not make paid Jev or Codex calls.

## Planned triage evals

Model behavior needs evals separate from unit tests.

Create small representative cases, eventually based on real sanitized repository profiles:

```text
evals/cases/
  basic-coursework.json
  messy-old-project.json
  important-ml-project.json
  collaborative-project.json
  starter-code-project.json
```

For the first several real repositories:

1. record scanner evidence;
2. let Jev make its structured triage;
3. independently review the result;
4. record corrections;
5. adjust questions/policy only after observing recurring errors.

Potential metrics:

- agreement on project extent;
- agreement on cleanup effort;
- human-clarification recall;
- inappropriate clarification rate;
- whether advisory R4 clarification signals should become fact requests, and under what evaluated policy;
- organization recommendation agreement;
- routing outcome;
- unnecessary escalations.

## Planned workflow metrics

Record enough telemetry to answer whether Repo Curator is actually useful.

Candidate metrics:

- wall-clock time per repository;
- worker model used;
- number of worker turns;
- human checkpoints/interventions;
- escalations;
- validation attempts;
- final verification status;
- tokens and cost when reliably exposed.

Compare this with a small manual baseline: cleaning similar repositories by chatting with Codex directly.

The project should not claim token or time savings until measured.

## Future v1 success criteria

V1 is successful if, across a small set of real university repositories:

- it avoids repeated manual prompting;
- it preserves original work;
- it catches relevant ambiguity before publication;
- its human checkpoints are useful rather than annoying;
- deterministic validation catches regressions or incomplete setup;
- cheap workers complete most routine repositories;
- structured state prevents repeated rediscovery;
- the user prefers the workflow to an unstructured per-repository Codex chat.

## Portfolio evidence

Useful portfolio evidence is not “I used multiple agents.”

Better evidence includes:

- a documented state machine;
- provider boundaries;
- human approval design;
- deterministic/model separation;
- routing policy;
- eval cases;
- measured token/time behavior;
- failure examples and improvements made after evaluation.

These demonstrate practical understanding of agent workflows even when only one persistent generative worker is used.

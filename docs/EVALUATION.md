# Evaluation Strategy

Repo Curator should be evaluated as a workflow, not only as a Python program.

## Unit tests

Unit tests cover deterministic behavior.

Initial examples:

- scanner detects Python project metadata;
- scanner ignores `.venv` contents while recording its existence;
- scanner does not execute target code;
- router keeps low-priority archive work cheap;
- routing/check policy does not add production-style ceremony to simple coursework;
- router requires a concrete escalation reason;
- invalid provider responses are rejected;
- state transitions require human checkpoints;
- validator detects missing required README information;
- target repositories never receive internal Repo Curator state.

Unit tests should not make paid Jev or Codex calls.

## Triage evals

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
- organization recommendation agreement;
- routing outcome;
- unnecessary escalations.

## Workflow metrics

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

## Success criteria for v1

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

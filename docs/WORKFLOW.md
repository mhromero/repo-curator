# Workflow

The implemented CLI supports offline scanning, TypeSafe triage, and persisted R5 human-review gates. Codex execution, routing, validation, and publishing are not implemented.

## Principle

Repo Curator is human-in-the-loop by design.

The worker may reason and edit, but the human controls factual claims, risky changes, and final publication quality.

## Planned end-to-end flow

```text
1. SCAN
   Deterministic, read-only repository analysis.

2. TRIAGE
   Jev makes a small number of structured judgments.

   Implemented as `repo-curator triage <path>`. It receives a bounded redacted scanner outline and returns hypotheses, not edit authority.

3. CLARIFY
   Persist the human portfolio value A/B/C and any confirmed facts.

   Implemented by `repo-curator run start`, `run classify`, and `run answer`.
   R4 clarification `Noul` probabilities are advisory signals displayed to the
   human. They do not currently create `FactRequest` records; A/B/C is the only
   mandatory initial input. Automatic conversion is deferred until evaluation data
   from real repositories supports a policy.

4. INSPECT
   Codex reads the repository and proposes a concrete plan.
   No substantive edits.

5. INSPECTION REVIEW
   Human approves/modifies the plan and resolves approvals.

6. EDIT
   The same Codex context performs the approved work.

7. EDIT REVIEW
   Human reviews the actual diff and requests changes or approves.

8. VALIDATE
   Deterministic checks establish what actually works.

9. DIAGNOSE, if needed
   The same Codex context reasons about validation failures.
   New risky fixes return to human approval.

10. FINAL GITHUB REVIEW
    Human reviews the published repository.

11. FINISHED
    Only explicit final approval closes the run.
```

## Implemented R5 state handling

`repo-curator run start <path>` persists the R3 `RepositoryProfile` and R4
`TriageResult` outside the target repository. It displays R4 clarification signals
without creating fact requests, then enters `WAITING_FOR_INPUT` until the human sets
A/B/C with `run classify`; it then resumes at `TRIAGED`. Inspection may later add
concrete required fact requests.

`WAITING_FOR_INPUT` means a fact or portfolio classification is missing and stores
the state to resume. `WAITING_APPROVAL` means a concrete R2 approval request is
pending. They are distinct states and neither action can substitute for the other.

The state functions and CLI can record structured inspection and edit reports from
a future worker or manual process. They enforce these boundaries:

- inspection reports lead to `WAITING_INSPECTION_REVIEW` unless they introduce a required fact;
- accepted inspection plans with pending R2 requests lead to `WAITING_APPROVAL`;
- only all-approved R2 requests may enter `EDITING`;
- accepted edit reviews lead to `VALIDATING`, never directly to completion;
- only a future validator may reach `READY_FOR_FINAL_REVIEW`;
- only explicit `run final approve` moves `READY_FOR_FINAL_REVIEW` to `FINISHED`.

R5 does not generate reports, execute edits, or run validation. Report-intake
commands exist solely as a narrow seam for the later worker and validator work.

## Why one Codex worker?

Inspection is the expensive context-building step. A separate editing agent would normally need to reread the repository or consume a large handoff.

Keeping one worker context allows the edit and later diagnosis to reuse knowledge acquired during inspection.

The worker is specialized by phase prompt, not by spawning separate agents.

## Inspection checkpoint

The inspection report should be concise and actionable:

- what the repository appears to be;
- important objective findings;
- likely intended setup/use;
- missing or ambiguous facts;
- proposed changes;
- changes requiring explicit approval;
- expected validation plan.

The user may approve, reject, or modify the plan.

## Edit checkpoint

After editing, report:

- files changed;
- files removed;
- source-code changes;
- deviations from plan;
- cheap sanity checks;
- unresolved concerns.

The actual Git diff is authoritative.

## Baseline checks

When practical, run safe baseline checks before editing. Baselines are evidence, not prerequisites.

Example:

```text
before: pytest -> 2 failures
after:  pytest -> 2 failures
```

This is materially different from:

```text
before: pytest -> 14 passed
after:  pytest -> 13 passed, 1 failed
```

The latter strongly suggests a regression introduced during cleanup.

## Validation failure loop

```text
VALIDATE
   |
   +-- pass --> READY_FOR_FINAL_REVIEW
   |
   +-- fail --> same worker DIAGNOSES
                    |
                    +-- safe fix within approved plan
                    |      -> edit -> review/validate as appropriate
                    |
                    +-- new risky change
                           -> WAITING_APPROVAL
```

The implementation should avoid silently broadening an approved plan.

## Completion

`FINISHED` requires:

- required cleanup complete;
- dependencies represented correctly;
- README complete for the chosen portfolio depth;
- attribution resolved;
- documented commands validated where practical;
- tests/checks acceptable for the project;
- no unresolved critical findings;
- final diff intentional;
- final GitHub repository reviewed and approved by the human.

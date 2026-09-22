# Workflow

This is the planned end-to-end workflow, not current CLI behavior. The implemented CLI currently performs only the offline, read-only `repo-curator scan <path>` operation.

## Principle

Repo Curator is human-in-the-loop by design.

The worker may reason and edit, but the human controls factual claims, risky changes, and final publication quality.

## Planned end-to-end flow

```text
1. SCAN
   Deterministic, read-only repository analysis.

2. TRIAGE
   Jev makes a small number of structured judgments.

3. CLARIFY
   Ask the human for unresolved facts and portfolio value.

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

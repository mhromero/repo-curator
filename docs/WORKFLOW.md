# Workflow

The implemented CLI supports offline scanning, TypeSafe triage, persisted R5 human-review gates, deterministic R6 initial routing, R7/R8 inspection and approved editing, deterministic validation, and final GitHub publication after explicit review.

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

   The normal command is `repo-curator run <path>`. It prompts for A/B/C before
   routing and inspection, collects inspection facts in the same session, shows
   the plan and approval requests, and resumes the worker for approved editing.
   Repeating it resumes the latest unfinished run for that repository. `run start`,
   `run continue`, `run input`, `run classify`, and `run answer` remain for
   scripting and recovery.
   R4 clarification `Noul` probabilities are advisory signals displayed to the
   human. They do not currently create `FactRequest` records; A/B/C is the only
   mandatory initial input. Automatic conversion is deferred until evaluation data
   from real repositories supports a policy.

4. ROUTE
   Deterministic Python records proportionate work depth plus a configured model
   family and reasoning effort. It does not launch a worker.

5. INSPECT
   Codex reads the repository and proposes a concrete plan.
   No substantive edits.

   Inspection includes a static, evidence-based organization and visible-reference
   audit. A move, rename, or removal of meaningful files remains an R2 decision;
   uncertain files are surfaced as concerns rather than removed.

   Implemented by `repo-curator run inspection execute <run-id>` after routing.

6. INSPECTION REVIEW
   Human approves/modifies the plan and resolves approvals.

7. EDIT
   The same Codex context performs the approved work.

   Implemented by `repo-curator run continue <run-id>` after inspection approval,
   or by `repo-curator run edit execute <run-id>` for scripting. It receives the
   approved inspection plan, approved R2 requests, and declined R2 requests as
   constraints with the human's explanation.

8. EDIT REVIEW
   Human reviews the actual diff and requests changes or approves.

   Implemented: the guided CLI renders the structured `EditReport` and Git
   change summary, then asks the human to approve or request a revision. Approval
   records `VALIDATING`, after which the guided flow runs deterministic validation;
   rejection resumes the same worker context in `EDITING`. A newly discovered R2 action creates a pending
   approval and stops in `WAITING_APPROVAL` instead.

9. VALIDATE
   Deterministic checks establish what actually works.

   Implemented after edit approval in `repo-curator run <path>` or
   `repo-curator run validation execute <run-id>`. It asks for a human-confirmed
   repository name in the R1 `uni-year-class` format before validating; it never
   invents the values. If that name differs from the local directory, the guided
   flow requires a separate persisted approval before renaming that local directory;
   it never renames a remote repository during validation. `VERIFIED` and `PARTIALLY_VERIFIED` enter
   `READY_FOR_FINAL_REVIEW`; `BLOCKED` stops for human action.

10. DIAGNOSE, if needed
   The same Codex context reasons about validation failures.
   New risky fixes return to human approval.

11. FINAL GITHUB REVIEW AND PUBLICATION
    The guided CLI verifies authenticated GitHub access, renders the target,
    visibility, branch, Git transport, validation outcome, and reviewed Git changes, then asks
    for explicit approval. It commits reviewed changes and performs a normal
    non-force push only after approval. When an authenticated personal `origin`
    has the old local name, the review also shows the exact remote rename before
    it can occur. For a plain local folder, the review instead shows the planned
    `main` branch initialization and exact initial-commit files; Git is not
    initialized until approval. A worker-supplied factual GitHub description is
    also shown exactly and applied only after approval.

    Existing remotes retain their configured transport. A new GitHub repository
    uses the authenticated GitHub CLI `git_protocol` preference. If an approved
    HTTPS push fails with a transport-style error, Repo Curator checks the remote
    branch for the reviewed commit. If the commit is absent and SSH authentication
    is available, the guided CLI may perform one separately confirmed SSH retry to
    the same repository and branch.

    A final-review decline with requested changes returns to `EDITING` and resumes
    the existing Codex context. A decline without requested changes remains at
    `READY_FOR_FINAL_REVIEW` and makes no Git or GitHub changes.

12. FINISHED
    Final approval plus a successful recorded publication closes the run.
```

## Implemented R5 state handling

`repo-curator run <path>` persists the R3 `RepositoryProfile` and R4
`TriageResult` outside the target repository. It displays R4 clarification signals
without creating fact requests, then collects A/B/C and any worker-requested facts
as needed. It presents inspection findings and approval requests in readable form,
resumes the persisted worker context for approved editing, then presents the edit
result for approval or revision. An approved edit review reaches `VALIDATING`,
then the guided command collects naming confirmation and runs deterministic
validation. A naming mismatch is presented as an explicit local-rename approval;
declining it leaves the repository unchanged and `BLOCKED`, where the human can
leave a note and stop safely. `run start` and `run classify` remain available for
scripting.
Inspection may later add concrete required fact requests, which resume the same
Codex inspection context once answered.

`WAITING_FOR_INPUT` means a fact or portfolio classification is missing and stores
the state to resume. `WAITING_APPROVAL` means a concrete R2 approval request is
pending. They are distinct states and neither action can substitute for the other.

R7 launches inspection through one persisted Codex thread and records a schema-valid
report. It receives the compact R3–R6 context and confirmed facts; a worker failure
stays in `INSPECTING` for retry. The state functions and CLI enforce these boundaries:

- inspection reports with required facts lead to `WAITING_FOR_INPUT` and resume `INSPECTING` once answered;
- inspection reports without required facts lead to `WAITING_INSPECTION_REVIEW`;
- accepted inspection plans with pending R2 requests lead to `WAITING_APPROVAL`;
- once every inspection R2 request is decided, the approved plan enters `EDITING`;
- R8 resumes the same Codex thread in `workspace-write` mode with the approved plan,
  confirmed facts, approved R2 requests, and rejected R2 constraints;
- edit reports lead to `WAITING_EDIT_REVIEW` unless they introduce a new R2 approval request;
- newly approved edit-time R2 requests resume `EDITING`; rejected ones lead to edit review;
- accepted edit reviews lead to `VALIDATING`, never directly to completion;
- deterministic validation sends `VERIFIED` and `PARTIALLY_VERIFIED` to
  `READY_FOR_FINAL_REVIEW`, while `BLOCKED` requires human action;
- final approval records authority while the run remains `READY_FOR_FINAL_REVIEW`;
  only a successful recorded publication moves it to `FINISHED`.

R5 supplies the persisted state, human facts, and approval boundaries used by R7/R8;
the deterministic validator records a structured validation report through that
state model. Report-intake commands remain a narrow seam for worker and validator integrations.

## Implemented R6 routing

`repo-curator run route <run-id>` requires `TRIAGED`, an R4 triage result, and a
human A/B/C classification. It records work depth from A/B/C plus R4
`project_extent`, then records cost class and reasoning effort from R4
`cleanup_effort`. Configuration resolves that intent to a supported model family.

The default initial routes are C/light → Luna/low, C/non-light → Luna/medium,
B/moderate → Luna/medium, A/light → Luna/low, and B/A substantial → Terra/high.
Sol is escalation-only. Higher work depth does not itself select a stronger model.

An escalation record requires a concrete blocker, attempts already made, why the
new configuration should help, and confirmation that the work remains within
approved scope. It may increase reasoning effort within a model family, switch
families, or change both. R6 persists and evaluates that contract but does not yet
receive or act on worker escalation requests.

## Why one Codex worker?

Inspection is the expensive context-building step. A separate editing agent would normally need to reread the repository or consume a large handoff.

Keeping one worker context allows the edit and later diagnosis to reuse knowledge acquired during inspection.

The worker is specialized by packaged phase prompt assets, not by spawning
separate agents. Templates receive a structured context block; sandboxing,
approval gates, and state transitions remain deterministic code controls.

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

# Requirements

This document captures the product requirements agreed before implementation. It describes desired behavior rather than a specific implementation.

## R1 — Repository Definition of Done

A repository is finished when it is clean, understandable, correctly attributed, reproducible where practical, and verified to the extent its documented usage allows.

A finished repository should satisfy the following where applicable:

- No obvious local junk such as `.DS_Store`, caches, committed virtual environments, IDE metadata, or temporary files.
- `.gitignore` is appropriate for the project.
- No credentials, API keys, tokens, personal local paths, or accidentally sensitive material are knowingly published.
- Structure is reasonable for the original project's complexity. Working coursework is not refactored merely for aesthetics.
- Dependencies are correctly represented. Suitable Python projects may use `uv` and `pyproject.toml`; other ecosystems use appropriate native tooling. Conversion is never automatic merely for consistency.
- A fresh user has usable installation/setup instructions when installation is relevant.
- README usage commands have been exercised where practical.
- Existing tests pass where practical. Tests are not invented solely to satisfy a checklist.
- At minimum, a representative import, run, compile, build, or equivalent check is performed when the README claims the project is runnable.
- README depth is appropriate to the repository's portfolio value.
- README claims are grounded in repository evidence or human confirmation.
- Academic context and attribution are accurate.
- Existing licenses and copyright notices are preserved. No license is invented when rights are unclear.
- The final diff contains only intentional changes and no Repo Curator state or temporary artifacts.

### Verification status

`VERIFIED`  
Everything documented as usable was successfully validated where practical.

`PARTIALLY_VERIFIED`  
The repository is publishable, but some functionality could not reasonably be executed. The limitation must be documented.

`BLOCKED`  
An important issue requires human action before publication.

Verification status is separate from portfolio value, cleanup effort, and workflow state.

### Proportionality

Validation, documentation, and repository polish must be proportional to both the scope of the work and its portfolio value.

A small academic exercise should not acquire production-oriented infrastructure, documentation, tests, CI, badges, contribution files, architecture documents, or other ceremony solely to satisfy Repo Curator.

Typical expectations:

- **C — Archive / simple exercise:** remove junk and obvious sensitive material, provide concise context and attribution, document basic usage/dependencies where relevant, and perform a representative run/compile/import check when practical.
- **B — Coursework:** add reliable setup and usage instructions, reasonable dependency metadata, and exercise existing tests or normal project functionality.
- **A — Showcase:** justify deeper reproducibility, environment/data documentation, broader validation, and stronger presentation where the project itself warrants it.

Project extent and portfolio value together determine the appropriate depth. Repo Curator should prefer doing less over manufacturing production polish that misrepresents student coursework.

## R2 — Change Authority and Human Approval

Repo Curator preserves original work. Its job is presentation, reproducibility, documentation, and hygiene—not modernization or rewriting.

### Autonomous safe changes

The workflow may perform clearly safe actions within an approved edit phase, including:

- Remove allowlisted disposable files such as `.DS_Store`, Python bytecode, common caches, and notebook checkpoints.
- Remove a committed local virtual environment only after its dependencies have been identified or preserved.
- Update `.gitignore`.
- Create or update README content using verified evidence.
- Fix README formatting, spelling, verified commands, and factual project structure.
- Add dependency metadata when the dependency set is unambiguous and behavior is not changed.
- Generate appropriate lockfiles.
- Run non-destructive installation, import, build, lint, test, and execution checks.
- Store Repo Curator run state outside the target repository.

Existing factual README material must not be silently removed unless it is demonstrably obsolete, duplicated, or incorrect.

### Changes requiring approval

Human approval is required before:

- Deleting source files, notebooks, datasets, results, figures, models, reports, PDFs, or other meaningful artifacts.
- Moving or renaming source files where execution may change.
- Major repository restructuring.
- Modifying source code to fix behavior.
- Refactoring.
- Changing algorithms, models, data processing, or observable behavior.
- Making dependency/version changes that may alter behavior.
- Resolving dependency problems through source changes.
- Modifying tests.
- Adding, removing, or changing licensing.
- Making uncertain attribution decisions.
- Removing substantial existing README information.
- Any action not confidently covered by the safe allowlist.

A request for approval should state the problem, proposed change, reason, affected files, and whether behavior may change.

### Human-authoritative facts

Personal, academic, authorship, licensing, and intentionality claims must come from repository evidence or human confirmation.

Examples include:

- the user's contribution;
- collaborator roles;
- instructor starter code;
- whether work was a lab, assignment, or final project;
- motivations and rationale;
- dataset redistribution rights;
- course identity;
- important results that are not directly evidenced.

### Refactoring policy

**Imperfection is not a defect.**

Do not refactor merely because code is old, verbose, duplicated, non-idiomatic, or architecturally simple. Refactoring becomes eligible only when required to restore documented installation/execution or when explicitly requested, and it still requires approval.

### Human waiting states

`WAITING_FOR_INPUT` means the system needs a fact the human must provide.

`WAITING_APPROVAL` means the system has a proposed action but R2 requires permission.

These states must remain distinct.

## R3 — Static Repository Analysis

The scanner is read-only and should collect objective evidence before any model call.

`repo-curator scan <path>` should work offline without TypeSafe or Codex credentials.

### Collect

- Repository path and directory name.
- Git status, branch, remotes, upstream/fork information when available, tracked/untracked counts, and approximate repository size.
- File inventory, language signals, directory structure, and relevant special files.
- Dependency/environment files for detected ecosystems.
- Python import evidence where useful, while distinguishing standard-library and local imports from probable external packages.
- README presence and objective structure signals.
- Existing tests, test configuration, build configuration, and package scripts.
- Candidate entry points without asserting that a candidate is definitely the intended entry point.
- Data, model, checkpoint, binary, and unusually large files with sizes.
- Secret-risk indicators without storing secret values.
- Hard-coded personal/local path indicators.
- Tracked junk and other Git hygiene findings.

### Ignore while recursively scanning

Common generated/vendor directories such as:

- `.git/`
- `.venv/`
- `venv/`
- `node_modules/`
- Python/tool caches
- `dist/`
- `build/`

Their existence may still be recorded.

### Scanner boundaries

The scanner must not:

- execute project code;
- install dependencies;
- delete or modify files;
- decide portfolio value;
- judge code quality;
- decide that a dataset is unnecessary;
- infer personal contribution;
- infer licensing rights;
- recommend refactoring;
- generate documentation;
- call an LLM.

The scanner produces a rich internal `RepositoryProfile`. A smaller `TriageSummary` is derived for model triage so raw repository contents do not need to be sent unnecessarily.

## R4 — Structured Triage

The exact TypeSafe/Jev contract is intentionally **not frozen in this document** until it is designed with the current official TypeSafe skill and SDK guidance.

The triage stage should only make judgments that are useful and brittle to encode deterministically.

Candidate judgments include:

- project extent;
- current repository completeness;
- expected cleanup effort;
- repository composition;
- repository-level organization treatment such as keep, rename, split candidate, or merge candidate;
- appropriate reproducibility expectations;
- technical domain;
- whether human clarification is required for authorship, academic context, repository boundaries, data/asset rights, or intended execution.

Constraints:

- Use TypeSafe's actual current primitives and syntax rather than locally invented approximations.
- Minimize redundant questions.
- Portfolio value A/B/C belongs to the human, not Jev.
- Jev does not authorize edits, deletions, source changes, or publication.
- Jev does not infer personal contribution or academic facts.
- Jev does not choose the Codex worker model directly.
- The deterministic router interprets structured triage output.
- Triage receives a compact scanner summary, not the entire repository unless a later evaluated need justifies more context.

## R5 — Human Review and Decision Gates

Human review is part of the normal workflow, not only an exception path.

### Checkpoint 1 — inspection review

The Codex worker inspects the repository read-only and returns:

- important findings;
- ambiguities and required human facts;
- proposed work;
- actions requiring R2 approval;
- expected validation;
- a concise edit plan.

Substantive editing does not begin until the human approves or modifies the plan.

Predictable questions should be batched rather than interrupting the human repeatedly.

### Checkpoint 2 — edit review

After editing, the worker stops and reports the real changes, including:

- modified files;
- removed files;
- whether source code changed;
- deviations from the approved plan;
- cheap sanity-check results.

The human reviews the actual diff and may approve it or request another edit iteration.

### Validation

After edit approval, deterministic validation performs the authoritative machine checks. Cheap sanity checks may be run during editing, but they do not replace final validation.

Where practical, non-destructive baseline checks should be recorded before editing. This helps distinguish pre-existing failures from regressions introduced during cleanup.

If validation fails, the same Codex worker context should diagnose the failure when practical. A new approval is required if the proposed fix exceeds previously approved authority.

### Checkpoint 3 — final GitHub review

Passing automated checks is not equivalent to completion.

After validation, the human reviews the actual published GitHub repository. Only explicit human approval marks the workflow `FINISHED`.

### Core workflow states

- `SCANNED`
- `TRIAGED`
- `INSPECTING`
- `WAITING_INSPECTION_REVIEW`
- `EDITING`
- `WAITING_EDIT_REVIEW`
- `VALIDATING`
- `READY_FOR_FINAL_REVIEW`
- `FINISHED`

Side states may include:

- `WAITING_FOR_INPUT`
- `WAITING_APPROVAL`
- `BLOCKED`

## R6 — Routing, Worker Model Selection, and Escalation

The router is deterministic Python.

**Choose the cheapest model reasonably capable of completing the approved work. Complexity determines capability needs; portfolio importance determines how much work is worth doing.**

### Portfolio value

Work depth must be derived from both portfolio value and project extent. Portfolio value alone must not cause a tiny exercise to receive production-style ceremony, and technical messiness alone must not justify disproportionate work on an archive repository.

The human assigns:

`A — Showcase`  
Thorough presentation and reproducibility. Exercise important functionality and investigate meaningful issues within R2 authority.

`B — Coursework`  
Good presentation, reasonable reproducibility, and normal usage validation.

`C — Archive`  
Preserve and explain. Perform minimal hygiene and concise documentation. Do not spend disproportionate effort resurrecting low-priority coursework.

### Provisional initial routing

The exact model table should remain configurable and should be calibrated with real runs.

- C: cheapest suitable worker by default.
- B with low/moderate cleanup effort: cheapest suitable worker.
- B with high cleanup effort: next worker tier may be justified.
- A with low effort: cheap worker may still be sufficient.
- A with moderate/high effort: stronger worker may be justified.
- High-end models are escalation paths, not status symbols.

Current candidate worker progression is Luna → Terra → Sol, with Astra reserved for exceptional cases. Model names must be configuration, not hard-coded business logic, because available models can change.

### Escalation

A worker may request escalation only for a concrete blocker, such as:

- repeated inability to understand relevant architecture;
- difficult dependency conflicts requiring substantial reasoning;
- ambiguous interactions among components;
- unresolved failure diagnosis after reasonable attempts;
- inability to produce a safe plan within current capability.

Repository size, age, portfolio value, file count, or a missing README are not sufficient reasons by themselves.

An escalation request should record:

- current model;
- concrete blocker;
- what was attempted;
- why additional capability is expected to help.

### Worker context

Maintain one Codex worker context per repository whenever practical.

Specialize by phase-specific prompts rather than separate LLM agents:

1. inspection;
2. editing;
3. validation-failure diagnosis when necessary.

This reuses repository understanding and reduces repeated token expenditure.

If escalation requires a new worker context, structured run state provides the handoff: scanner profile, triage result, human decisions, inspection report, approved plan, baseline checks, actual diff, and validation results.

### Telemetry

Record what the execution environment reliably exposes:

- worker model;
- worker turns;
- escalations;
- duration;
- token usage and cost when available;
- human interventions;
- validation attempts;
- final verification status.

Telemetry should support later evaluation of whether routing actually saves time and model usage.

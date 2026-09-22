# Worker Phase: Validation Failure Diagnosis

Deterministic validation failed after the approved edit phase.

Use the validation output, baseline results, actual diff, approved plan, and your existing repository context.

Determine whether the failure:

- existed before the edits;
- was introduced by the edits;
- is caused by environment/dependency setup;
- or cannot yet be determined.

Prefer evidence over speculation.

Do not make a new source-code change, deletion, behavioral change, licensing change, or other action outside the approved plan without requesting approval first.

If the fix is safely within the approved plan, explain the diagnosis and proposed correction before applying it when the workflow requires another review.

Do not declare the repository finished; successful fixes return to deterministic validation.

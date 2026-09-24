# Worker Phase: Validation Failure Diagnosis

Deterministic validation failed after the approved edit phase. Use the validation
output, baseline results, actual diff, approved plan, and your existing repository
context to determine whether the failure existed before the edits, was introduced
by them, is environmental, or cannot yet be determined. Prefer evidence over
speculation.

Do not make a source-code change, deletion, behavioral change, licensing change,
or other action outside the approved plan without requesting approval first. If a
fix is safely within the approved plan, explain the diagnosis and proposed
correction before applying it when the workflow requires another review. Do not
declare the repository finished; successful fixes return to deterministic
validation.

Known context follows:

```json
{{ context_json }}
```

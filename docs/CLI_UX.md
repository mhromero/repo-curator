# CLI User Experience

Repo Curator should expose a guided high-level CLI for normal use.

The user should normally start or resume repository curation with one command:

    repo-curator run <repository>

Repo Curator drives the underlying workflow until it reaches a point requiring
human interaction or the currently implemented workflow is complete.

Lower-level commands may exist for testing, debugging, and recovery, but normal
use should not require knowledge of the internal state machine.

## Interaction principles

- Prompt for required human facts when they are needed.
- Persist answers through the existing workflow state.
- Present approval requests in readable language before asking for a decision.
- When an approval is declined, offer an optional explanation and provide that
  persisted constraint to the resumed worker context.
- Show inspection findings and proposed work before inspection approval.
- Show actual repository changes before edit approval.
- At edit review, let the human approve the completed edits or describe a
  revision; an approved review may advance to a later unimplemented phase.
- Before validation, ask the human for the exact repository name in the R1
  `uni-year-class` convention rather than inferring academic metadata.
- If that name differs from the local directory, show a separate approval request
  to rename only the local directory. Explain that no remote is renamed; on a
  declined rename, offer an optional persisted note and leave the workflow safely
  stopped at `BLOCKED`.
- At final review, show validation status and concerns, source-code-change status,
  the exact GitHub target, visibility, branch, and reviewed Git changes before
  asking for publication approval.
- Do not run Git or GitHub mutating commands until that final approval. Explain
  when a new repository will be created and that pushes are non-force.
- A nonblank final-review decline is a requested repository revision: persist the
  note, offer confirmation of one unambiguous R1-shaped replacement name mentioned
  in that note, and resume the same Codex editing context. It does not ask about
  repository naming when no replacement is mentioned; only ambiguous candidates
  use explicit manual entry. A blank decline stops publication without resuming
  work.
- Resume the existing worker context when continuing worker work.
- Never require the user to manually copy worker output, IDs, or structured
  state between commands.
- Internal structured data should be rendered for humans rather than dumped
  directly to the terminal.
- The CLI should make the current state and next required action clear.

## Example flow

    $ repo-curator run ./project

    Scanning...
    ✓ Scan complete

    Triaging...
    ✓ Triage complete

    Portfolio importance [A/B/C]: B

    Running repository inspection...
    ✓ Inspection complete

    Inspection
    ────────────────────────────────────
    Proposed work:
      • Remove tracked disposable files
      • Add missing dependency metadata
      • Update README setup instructions

    Needs your input:
      Was this project completed with collaborators? [y/N]: y

    Approval required
    ────────────────────────────────────
    Proposed change:
      Add pyproject.toml

    Reason:
      The project has dependencies but no reproducible dependency metadata.

    Expected behavior change:
      None

    Approve? [y/N]: y

    Continuing...

The exact wording and formatting may evolve. The example defines the intended
interaction style, not a byte-for-byte terminal-output requirement.

## Design principle

One guided command for the normal user journey; small composable operations
underneath for implementation, testing, debugging, and recovery.

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

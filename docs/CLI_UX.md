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
- After an approved inspection plan, deciding an individual R2 request must not
  re-present the entire plan. Approved requests grant edit authority; rejected
  requests and their notes become constraints for the same editing context. Only
  declining the inspection plan itself asks for a revised plan.
- Show inspection findings and proposed work before inspection approval.
- Show actual repository changes before edit approval.
- At edit review, let the human approve the completed edits or describe a
  revision; an approved review may advance to a later unimplemented phase.
- Before validation, if the current directory already follows the R1
  `uni-year-class` convention, ask the human to confirm using it without a local
  rename. Otherwise ask for the exact intended name rather than inferring
  academic metadata.
- If that name differs from the local directory, show a separate approval request
  to rename only the local directory. Explain that no remote is renamed; on a
  declined rename, offer an optional persisted note and leave the workflow safely
  stopped at `BLOCKED`.
- When validation flags tracked disposable files, list their exact paths and ask
  the human to delete, keep as an intentional artifact, or stop. A keep decision
  is persisted for that exact path only, then validation is rerun automatically.
- At final review, show validation status and concerns, source-code-change status,
  the exact GitHub target, description, visibility, branch, Git transport, and reviewed Git
  changes before asking for publication approval.
- Before final review, collect the exact English class name needed for the GitHub
  About description. The controller renders `Kind for English Class Name @ UNI
  (Year)` using that confirmed title and the repository name; it never translates
  or invents a course title from a repository slug.
- Do not run Git or GitHub mutating commands until that final approval. Explain
  when a new repository will be created and that pushes are non-force. For a
  folder without Git metadata, explicitly show the planned Git initialization
  branch and initial-commit files before asking for that approval.
- Preserve an existing remote's HTTPS or SSH URL. For a newly created repository,
  use the authenticated GitHub CLI `git_protocol` preference and show it in final
  review. If an approved HTTPS push has a transport-style failure, first verify the
  remote branch did not receive the reviewed commit. Offer an SSH retry only when
  local SSH authentication is available; it must keep the reviewed GitHub target
  and branch unchanged and state that it changes only the local origin URL.
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
- Reports should use consistent headings and an empty line between major sections.
  Use light terminal color when supported, without making color necessary to read
  the output.

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

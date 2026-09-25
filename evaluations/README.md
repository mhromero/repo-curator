# Real-repository evaluation

This directory holds small, sanitized, version-controlled evaluation metadata and
results. It is not a test suite, a benchmark service, or a place to copy target
repositories.

## Layout

```text
evaluations/
  cases/     # sanitized case metadata; one JSON file per repository evaluation
  results/   # sanitized exports, then human qualitative judgments
```

Copy `cases/example-student-coursework.json` to make a case. Its `case_id` is a
safe label, not a repository name or path. Set
`consent_to_publish_sanitized_result` only when the evaluator is permitted to
commit or share the result.

## Run an evaluation

Run the normal guided workflow on a real repository. It continues to use the
existing R6 router; evaluation does not alter routing, Jev questions, worker
prompts, or approval behavior.

After a run reaches a useful stopping point, export only selected evidence:

```sh
uv run --frozen repo-curator evaluation export <run-id> \
  evaluations/cases/my-case.json \
  evaluations/results/my-case-run-01.json
```

The command reads the normal persisted run record and does not invoke Jev, Codex,
Git, or GitHub. It refuses to overwrite a result unless `--overwrite` is passed.
The evaluator then completes the `human` object in the result file using
qualitative judgments and sanitized notes.

Compare two or more exports without calculating a score:

```sh
uv run --frozen repo-curator evaluation compare \
  evaluations/results/my-case-run-01.json \
  evaluations/results/my-case-run-02.json --json
```

The comparison is a side-by-side observation of the actual route, final state,
validation/publication outcome, duration, available worker usage, and human
judgments. It intentionally does not rank runs or tune policy.

## Automatically recorded evidence

The export includes only structured, non-content evidence:

- R4 choices, confidence/probability distributions, clarification probabilities,
  provider model, and reported token usage;
- the actual R6 policy version, route, model family, effort, and reason codes;
- total run duration, elapsed time between persisted transitions, worker attempt
  counts, most-recent worker usage/duration, and whether that attempt failed;
- counts and outcomes for facts, approvals, reviews, validation checks,
  publication, and escalations;
- the final workflow state and whether publication completed.

It excludes target paths, file names, repository profiles and summaries, README
text, source content, human-fact values, review notes, worker reports and errors,
Codex thread IDs/history, Git remote identity, commit IDs, and GitHub repository
identity.

## Human evaluation

The evaluator records qualitative—not numeric—judgments for:

- whether R4 project extent, cleanup effort, and other judgments were supported;
- whether each Jev clarification signal was useful in context;
- whether the executed R6 route was proportionate;
- whether human interventions were useful or unnecessary, overall and by phase;
- whether original student work was preserved;
- whether validation and publication outcomes were appropriate.

`shadow_routing` is an optional, manually added place for offline alternative
route observations. It never changes the route used by a real run.

Keep `sanitized_notes` general. Do not add credentials, source text, repository
names/paths, personal information, remote URLs, raw worker output, or private
course details.

## Known evidence gaps

Current run records retain only the most recent worker attempt's duration and
usage, not a per-attempt history. They do not retain provider billing/cost,
publication plans or post-publication GitHub state, baseline snapshots suitable
for before/after semantic comparison, or an independent measure of student-work
preservation. Those remain human-evaluated or future telemetry work.

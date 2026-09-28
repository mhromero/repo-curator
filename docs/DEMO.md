# Try the offline demo

This short walkthrough is for anyone evaluating Repo Curator from a fresh
checkout. The synthetic coursework fixture in
[`examples/synthetic-coursework/`](../examples/synthetic-coursework/) is a
small, deliberately ordinary local directory. It contains no credentials,
personal data, or hidden test harness. It does not rely on Git metadata. When
scanned from this checkout, Repo Curator correctly reports the enclosing
checkout's Git context. The fixture exists to demonstrate the offline first step
from a clean checkout.

## Run it from scratch

Install Repo Curator from the repository root:

```sh
uv sync --dev
```

Then run the read-only scanner:

```sh
uv run --frozen python examples/synthetic-coursework/prepare_demo.py
uv run --frozen repo-curator scan examples/synthetic-coursework
uv run --frozen python examples/synthetic-coursework/prepare_demo.py --clean
```

The preparation command creates two ignored, disposable files only for this
demo: `.DS_Store` and `editor.swp`. The scanner reports them, and `--clean`
removes them again. The demo requires neither a TypeSafe key nor Codex or GitHub
access, does not execute fixture code, and does not modify the actual project
files.

Selected output from that verified run:

```text
Repository: synthetic-coursework
Inventory entries: 7
Languages: Python (2)
Ecosystems: Python
README files: 1
Risk indicators: 0 secret candidate(s), 0 local-path candidate(s)
Tracked junk candidates: 0
Disposable file candidates:
- .DS_Store
- editor.swp
```

Git status and repository-size fields depend on the enclosing checkout, so they
are intentionally not presented as fixture expectations.

The fixture is intentionally only an offline scanner demo. A credible full
guided-run recording would require a real TypeSafe request, a locally
authenticated Codex session, human decisions, and—in the final phase—optional
GitHub credentials. A canned "successful" end-to-end trace would misrepresent
those external dependencies and the human approval gates.

To perform a real guided run on a repository you control:

```sh
export TYPESAFE_API_KEY='your-key-here'
codex login
uv run --frozen repo-curator run /path/to/repository
```

Do not use the synthetic fixture as a claim that the full workflow was exercised.
Real dogfooding records stay local until they are reviewed separately for public
sharing. The public [evaluation instructions](../evaluations/README.md) describe
the future independent evaluation set; they do not present dogfooding as a
benchmark.

## Screenshots and other images

Optional public screenshots belong in [`docs/images/`](images/). Use a descriptive
filename such as `guided-inspection-review.png` and link it from this document or
the README. Before adding one, remove local paths, repository names, API keys,
human responses, worker transcripts, remote URLs, and other sensitive material.
Do not add screenshots merely to decorate the project: a useful image should
explain a human review gate or a workflow state that prose cannot show clearly.

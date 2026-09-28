from __future__ import annotations

import pytest

from repo_curator.prompt_assets import PromptAsset, load_prompt_asset, render_worker_prompt


def test_all_prompt_assets_are_packaged_and_readable() -> None:
    for asset in PromptAsset:
        assert load_prompt_asset(asset).strip()


@pytest.mark.parametrize(
    "asset",
    [PromptAsset.WORKER_INSPECT, PromptAsset.WORKER_EDIT, PromptAsset.WORKER_DIAGNOSE],
)
def test_worker_prompt_renders_one_structured_context_block(asset: PromptAsset) -> None:
    rendered = render_worker_prompt(
        asset,
        {"run_id": "run-123", "human_confirmed_facts": {"authorship": "Independent work."}},
    )

    assert "{{ context_json }}" not in rendered
    assert '"run_id": "run-123"' in rendered
    assert '"authorship": "Independent work."' in rendered


def test_non_worker_asset_cannot_be_rendered_as_a_worker_prompt() -> None:
    with pytest.raises(ValueError, match="not a worker-phase prompt"):
        render_worker_prompt(PromptAsset.README_TEMPLATE, {})


def test_inspection_prompt_requires_a_static_organization_and_reference_audit() -> None:
    prompt = load_prompt_asset(PromptAsset.WORKER_INSPECT)

    assert "static organization and reference audit" in prompt
    assert "Trace visible local references" in prompt
    assert "Leave uncertain\nfiles in place" in prompt
    assert "Jev Noul probabilities" in prompt
    assert "not a fixed threshold" in prompt
    assert "higher audit\npriority only" in prompt
    assert "do not ask a redundant question" in prompt
    assert "Nested `example`, `examples`, `sample`, `demo`" in prompt
    assert "scattered assets" in prompt
    assert "PDFs and presentation files" in prompt
    assert "including nested lesson/practice directories" in prompt
    assert "theory or" in prompt
    assert "lesson PDFs/PowerPoints" in prompt
    assert "all applicable patterns" in prompt


def test_inspection_prompt_receives_raw_jev_scores_as_structured_context() -> None:
    rendered = render_worker_prompt(
        PromptAsset.WORKER_INSPECT,
        {"triage_judgments": {"clarifications": {"authorship": 0.83}}},
    )

    assert '"authorship": 0.83' in rendered


def test_edit_prompt_uses_a_constrained_github_description_kind() -> None:
    prompt = load_prompt_asset(PromptAsset.WORKER_EDIT)

    assert "github_description_kind" in prompt
    assert "`assignments`, `coursework`, `project`,\nor `labs`" in prompt


def test_edit_prompt_renders_the_adaptive_readme_quality_guide() -> None:
    rendered = render_worker_prompt(PromptAsset.WORKER_EDIT, {"run_id": "run-123"})

    assert "{{ readme_template }}" not in rendered
    assert "--- README quality guide ---" in rendered
    assert "## Getting Started" in rendered
    assert "Omit a section only" in rendered
    assert "it is clearly superfluous" in rendered
    assert "mandatory quality bar" in rendered
    assert "prose and headings in English" in rendered
    assert "intentionally read-only artifact" in rendered
    assert "include the applicable English Academic Context or\nProvenance section" in rendered
    assert "[Report](reports/final-report.pdf)" in rendered
    assert "Never expose an absolute local filesystem" in rendered
    assert "[`hw/`](hw/)" in rendered
    assert "[`Homework 3 report`](hw/hw3/report.pdf)" in rendered
    assert "copyable commands as plain code" in rendered
    assert "MATLAB Image Processing Toolbox" in rendered
    assert "some functions from the image toolbox" in rendered
    assert "reader-oriented map rather than a filesystem inventory" in rendered
    assert "one concise bullet for each meaningful homework assignment or lab" in rendered
    assert "algorithm, model, or technology employed." in rendered
    assert "Do not recursively list directories" in rendered

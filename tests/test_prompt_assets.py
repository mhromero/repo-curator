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

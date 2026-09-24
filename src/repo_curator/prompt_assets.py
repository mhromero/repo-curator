"""Packaged, reviewable prompt assets for the local Codex worker."""

from __future__ import annotations

import json
from enum import StrEnum
from importlib.resources import files
from typing import Mapping


class PromptAsset(StrEnum):
    WORKER_INSPECT = "worker-inspect.md"
    WORKER_EDIT = "worker-edit.md"
    WORKER_DIAGNOSE = "worker-diagnose.md"
    README_TEMPLATE = "README_TEMPLATE.md"


class PromptAssetError(RuntimeError):
    """A packaged prompt is unavailable or does not meet the rendering contract."""


_CONTEXT_PLACEHOLDER = "{{ context_json }}"


def load_prompt_asset(asset: PromptAsset) -> str:
    """Load one prompt from Repo Curator's installed package resources."""
    try:
        return files("repo_curator").joinpath("prompts", asset.value).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as error:
        raise PromptAssetError(f"Packaged prompt asset is unavailable: {asset.value}") from error


def render_worker_prompt(asset: PromptAsset, context: Mapping[str, object]) -> str:
    """Render the sole dynamic worker field as readable, deterministic JSON."""
    if asset not in {
        PromptAsset.WORKER_INSPECT,
        PromptAsset.WORKER_EDIT,
        PromptAsset.WORKER_DIAGNOSE,
    }:
        raise ValueError(f"{asset.value} is not a worker-phase prompt.")
    template = load_prompt_asset(asset)
    if template.count(_CONTEXT_PLACEHOLDER) != 1:
        raise PromptAssetError(
            f"Worker prompt {asset.value} must contain exactly one {_CONTEXT_PLACEHOLDER} placeholder."
        )
    context_json = json.dumps(context, indent=2, sort_keys=True)
    return template.replace(_CONTEXT_PLACEHOLDER, context_json)

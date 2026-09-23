from __future__ import annotations

from pathlib import Path

import typer

from .scanner import scan_repository
from .triage import TriageProviderError, triage_repository

app = typer.Typer(no_args_is_help=True, help="Inspect a repository without modifying it.")


@app.callback()
def _root() -> None:
    pass


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Repository directory to scan."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the complete profile as JSON.",
    ),
) -> None:
    try:
        result = scan_repository(path)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(str(error), param_hint="PATH") from error

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    profile = result.repository_profile
    summary = result.triage_summary
    identity = profile.identity
    typer.echo(f"Repository: {identity.directory_name}")
    typer.echo(f"Path: {identity.path}")
    if identity.git is None:
        typer.echo("Git: not detected")
    else:
        git = identity.git
        typer.echo(f"Git root: {git.root_path}")
        typer.echo(f"Branch: {git.branch or 'unknown'}")
        tracked_count = (
            git.tracked_file_count
            if git.tracked_file_count is not None
            else "unknown"
        )
        untracked_count = (
            git.untracked_entry_count
            if git.untracked_entry_count is not None
            else "unknown"
        )
        typer.echo(f"Tracked files: {tracked_count}")
        typer.echo(f"Untracked entries: {untracked_count}")
        typer.echo(
            "Working tree dirty: "
            + (str(git.is_dirty) if git.is_dirty is not None else "unknown")
        )
        typer.echo(f"Remotes: {', '.join(git.remotes) if git.remotes else 'none'}")
    typer.echo(f"Inventory entries: {len(profile.files)}")
    typer.echo(f"Approximate repository bytes: {profile.approximate_repository_size_bytes}")
    typer.echo(
        "Languages: "
        + (
            ", ".join(
                f"{language} ({count})" for language, count in profile.language_counts.items()
            )
            or "none detected"
        )
    )
    typer.echo(f"Ecosystems: {', '.join(profile.evidence.ecosystems_detected) or 'none detected'}")
    typer.echo(f"Dependency/environment files: {summary.dependency_file_count}")
    typer.echo(f"README files: {summary.readme_count}")
    typer.echo(
        "Test evidence: "
        f"{summary.test_file_count} file(s), {summary.test_config_count} config(s)"
    )
    typer.echo(f"Build configurations: {summary.build_config_count}")
    typer.echo(f"Candidate entry points: {summary.candidate_entry_point_count}")
    typer.echo(
        "Risk indicators: "
        f"{summary.secret_risk_count} secret candidate(s), "
        f"{summary.local_path_risk_count} local-path candidate(s)"
    )
    typer.echo(f"Tracked junk candidates: {summary.tracked_junk_count}")
    typer.echo(
        "Ignored directories: "
        + (", ".join(profile.ignored_directories) or "none")
    )


@app.command()
def triage(
    path: Path = typer.Argument(..., help="Repository directory to scan and triage."),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print the complete triage result as JSON.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="TypeSafe model or alias; defaults to TYPESAFE_DEFAULT_MODEL.",
    ),
) -> None:
    try:
        result = triage_repository(str(path), model=model)
    except (OSError, ValueError, TriageProviderError) as error:
        typer.echo(f"Triage failed: {error}", err=True)
        raise typer.Exit(code=1) from error

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    judgments = result.judgments
    typer.echo(f"Provider model: {result.provider_model}")
    typer.echo(
        f"Project extent: {judgments.project_extent.choice} "
        f"({judgments.project_extent.confidence:.2f} confidence)"
    )
    typer.echo(
        f"Cleanup effort: {judgments.cleanup_effort.choice} "
        f"({judgments.cleanup_effort.confidence:.2f} confidence)"
    )
    typer.echo(f"Repository completeness: {judgments.repository_completeness.choice}")
    typer.echo(f"Organization treatment: {judgments.organization_treatment.choice}")
    typer.echo(f"README expectation: {judgments.readme_expectation.choice}")
    typer.echo(
        "Clarification probabilities: "
        f"authorship={judgments.clarifications.authorship:.2f}, "
        f"academic_context={judgments.clarifications.academic_context:.2f}, "
        f"repository_boundaries={judgments.clarifications.repository_boundaries:.2f}, "
        f"data_asset_rights={judgments.clarifications.data_asset_rights:.2f}, "
        f"intended_execution={judgments.clarifications.intended_execution:.2f}"
    )


def main() -> None:
    app()

from __future__ import annotations

from pathlib import Path

from .workflow import RepositoryRun, WorkflowError, WorkflowState


def default_state_root() -> Path:
    return Path.home() / ".repo-curator" / "runs"


class RunStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_state_root()).expanduser()

    def create(self, run: RepositoryRun) -> Path:
        path = self.path_for(run.id)
        if path.exists():
            raise WorkflowError(f"Run already exists: {run.id}")
        return self.save(run)

    def load(self, run_id: str) -> RepositoryRun:
        path = self.path_for(run_id)
        if not path.is_file():
            raise WorkflowError(f"Run not found: {run_id}")
        try:
            return RepositoryRun.model_validate_json(path.read_text(encoding="utf-8"))
        except OSError as error:
            raise WorkflowError(f"Could not read run {run_id}: {error}") from error

    def save(self, run: RepositoryRun) -> Path:
        path = self.path_for(run.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".tmp")
        try:
            temporary_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
            temporary_path.replace(path)
        except OSError as error:
            raise WorkflowError(f"Could not save run {run.id}: {error}") from error
        return path

    def latest_active_for_repository(self, repository_path: Path) -> RepositoryRun | None:
        """Return the most recently updated unfinished run for a repository path.

        The guided CLI deliberately hides run identifiers during normal use.  The
        low-level commands still expose them for recovery, so selecting the latest
        unfinished record is both convenient and deterministic when a repository
        has been curated more than once.
        """
        try:
            normalized_path = repository_path.expanduser().resolve(strict=False)
        except OSError as error:
            raise WorkflowError(f"Could not resolve repository path {repository_path}: {error}") from error
        if not self.root.is_dir():
            return None

        matching_runs: list[RepositoryRun] = []
        try:
            run_paths = self.root.glob("*/run.json")
            for run_path in run_paths:
                run = RepositoryRun.model_validate_json(run_path.read_text(encoding="utf-8"))
                run_path_value = Path(run.repository_profile.identity.path).expanduser()
                if (
                    run.state != WorkflowState.FINISHED
                    and run_path_value.resolve(strict=False) == normalized_path
                ):
                    matching_runs.append(run)
        except (OSError, ValueError) as error:
            raise WorkflowError(f"Could not inspect saved runs: {error}") from error

        if not matching_runs:
            return None
        return max(matching_runs, key=lambda run: run.updated_at)

    def path_for(self, run_id: str) -> Path:
        if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
            raise WorkflowError(f"Invalid run identifier: {run_id}")
        return self.root / run_id / "run.json"

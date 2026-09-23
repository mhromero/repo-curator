from __future__ import annotations

from pathlib import Path

from .workflow import RepositoryRun, WorkflowError


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

    def path_for(self, run_id: str) -> Path:
        if len(run_id) != 32 or any(character not in "0123456789abcdef" for character in run_id):
            raise WorkflowError(f"Invalid run identifier: {run_id}")
        return self.root / run_id / "run.json"

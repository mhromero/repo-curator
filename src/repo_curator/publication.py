"""Small, conservative Git and GitHub CLI publication adapter."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Protocol

from .workflow import PublicationResult


class PublicationError(ValueError):
    pass


_DESCRIPTION_LABELS = {
    "assignments": "Assignments",
    "coursework": "Coursework",
    "project": "Project",
    "labs": "Labs",
}


def format_github_description(
    repository_name: str,
    kind: str,
    class_name: str,
    year: str,
) -> str:
    """Build the concise About text from a confirmed ``uni-class`` name."""
    university, *class_parts = repository_name.split("-")
    if not university or not class_parts:
        raise PublicationError(
            "GitHub description requires a confirmed repository name in `uni-class` format."
        )
    label = _DESCRIPTION_LABELS.get(kind)
    if label is None:
        raise PublicationError(f'Unsupported GitHub description kind "{kind}".')
    course = class_name.strip()
    if not course:
        raise PublicationError("GitHub description requires a human-confirmed English class name.")
    normalized_year = year.strip()
    if not normalized_year.isdigit() or len(normalized_year) != 4:
        raise PublicationError("GitHub description requires a human-confirmed four-digit year.")
    return f"{label} for {course} @ {university.upper()} ({normalized_year})"


class PublicationInputRequired(PublicationError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f'Publication requires the human-confirmed "{key}" value.')


class PublicationPushError(PublicationError):
    """A push failed after the approved local publication changes were made."""

    def __init__(
        self,
        *,
        plan: "PublicationPlan",
        commit_sha: str,
        detail: str,
        ssh_retry_available: bool,
    ) -> None:
        self.plan = plan
        self.commit_sha = commit_sha
        self.detail = detail
        self.ssh_retry_available = ssh_retry_available
        super().__init__(f"Git push failed: {detail}")


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], Path | None], CommandResult]


@dataclass(frozen=True)
class PublicationPlan:
    repository_path: Path
    owner: str
    name: str
    branch: str
    visibility: str
    remote_name: str | None
    create_repository: bool
    existing_repository_name: str | None
    rename_existing_repository: bool
    existing_remote_url: str | None
    worktree_status: tuple[str, ...]
    initialize_repository: bool = False
    description: str | None = None
    git_transport: str = "https"

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.name}"


class GitHubCliPublisher:
    """Use local Git plus authenticated ``gh`` without rewriting remote history."""

    def __init__(
        self,
        *,
        git_bin: str = "git",
        gh_bin: str = "gh",
        runner: CommandRunner | None = None,
    ) -> None:
        self.git_bin = git_bin
        self.gh_bin = gh_bin
        self._runner = runner or _subprocess_runner

    def prepare(
        self,
        repository_path: Path,
        *,
        expected_name: str,
        visibility: str | None,
        description: str | None = None,
    ) -> PublicationPlan:
        path = repository_path.expanduser().resolve()
        if not path.is_dir():
            raise PublicationError(f"Repository path does not exist: {path}")
        if not self._is_git_repository(path):
            return self._prepare_initial_repository(
                path,
                expected_name=expected_name,
                visibility=visibility,
                description=description,
            )
        branch = self._git(path, "branch", "--show-current").strip()
        if not branch:
            raise PublicationError("Publication requires a checked-out local branch; detached HEAD is not supported.")
        owner = self._authenticated_login(path)
        status = tuple(
            line for line in self._git(path, "status", "--porcelain=v1").splitlines() if line
        )
        remote_url = self._optional_git(path, "remote", "get-url", "origin")
        if remote_url is None:
            if visibility not in {"public", "private"}:
                raise PublicationInputRequired("github_visibility")
            return PublicationPlan(
                repository_path=path,
                owner=owner,
                name=expected_name,
                branch=branch,
                visibility=visibility,
                remote_name=None,
                create_repository=True,
                existing_repository_name=None,
                rename_existing_repository=False,
                existing_remote_url=None,
                worktree_status=status,
                initialize_repository=False,
                description=description,
                git_transport=self._preferred_git_transport(path),
            )

        remote_owner, remote_name = _github_remote_identity(remote_url)
        details = self._github_repository(remote_owner, remote_name, path)
        if details.get("isFork") is True:
            raise PublicationError("Refusing to publish to a fork remote.")
        if remote_owner != owner:
            raise PublicationError(
                f'Refusing to publish to "{remote_owner}/{remote_name}" because it is not owned by '
                f'the authenticated GitHub user "{owner}".'
            )
        if details.get("viewerPermission") != "ADMIN":
            raise PublicationError("Publication requires GitHub ADMIN permission on the existing remote.")
        remote_visibility = details.get("visibility")
        if remote_visibility not in {"PUBLIC", "PRIVATE"}:
            raise PublicationError("Existing GitHub remote has an unsupported visibility setting.")
        return PublicationPlan(
            repository_path=path,
            owner=owner,
            name=expected_name,
            branch=branch,
            visibility=remote_visibility.lower(),
            remote_name="origin",
            create_repository=False,
            existing_repository_name=remote_name,
            rename_existing_repository=remote_name != expected_name,
            existing_remote_url=remote_url,
            worktree_status=status,
            initialize_repository=False,
            description=description,
            git_transport=_git_transport(remote_url),
        )

    def publish(self, plan: PublicationPlan) -> PublicationResult:
        """Commit reviewed changes, create an approved target if needed, and non-force push."""
        current = self.prepare(
            plan.repository_path,
            expected_name=plan.name,
            visibility=plan.visibility,
            description=plan.description,
        )
        if _plan_signature(current) != _plan_signature(plan):
            raise PublicationError(
                "Repository or remote state changed after final review. Re-run the guided final review."
            )

        if current.initialize_repository:
            self._git(current.repository_path, "init", "--initial-branch", current.branch)
        if current.worktree_status:
            self._git(current.repository_path, "add", "-A")
            self._git(
                current.repository_path,
                "commit",
                "-m",
                "Prepare repository for publication",
            )
        commit_sha = self._git(current.repository_path, "rev-parse", "HEAD").strip()
        if not commit_sha:
            raise PublicationError("Publication requires at least one local commit.")

        if current.create_repository:
            self._gh(
                current.repository_path,
                "repo",
                "create",
                current.repository,
                f"--{current.visibility}",
                "--source",
                str(current.repository_path),
                "--remote",
                "origin",
            )
            self._git(
                current.repository_path,
                "remote",
                "set-url",
                "origin",
                _github_remote_url(current.git_transport, current.owner, current.name),
            )
        elif current.rename_existing_repository:
            assert current.existing_repository_name is not None
            assert current.existing_remote_url is not None
            self._gh(
                current.repository_path,
                "repo",
                "rename",
                current.name,
                "--repo",
                f"{current.owner}/{current.existing_repository_name}",
            )
            self._git(
                current.repository_path,
                "remote",
                "set-url",
                "origin",
                _renamed_remote_url(current.existing_remote_url, current.owner, current.name),
            )
        if current.description is not None:
            self._gh(
                current.repository_path,
                "repo",
                "edit",
                current.repository,
                "--description",
                current.description,
            )
        self._push_or_confirm(current, commit_sha)
        return PublicationResult(
            repository=current.repository,
            branch=current.branch,
            commit_sha=commit_sha,
            created_repository=current.create_repository,
        )

    def _authenticated_login(self, path: Path) -> str:
        self._gh(path, "auth", "status", "--hostname", "github.com")
        login = self._gh(path, "api", "user", "--jq", ".login").strip()
        if not login:
            raise PublicationError("GitHub CLI did not return the authenticated user name.")
        return login

    def _prepare_initial_repository(
        self,
        path: Path,
        *,
        expected_name: str,
        visibility: str | None,
        description: str | None,
    ) -> PublicationPlan:
        status = _initial_worktree_status(path)
        if not status:
            raise PublicationError("Publication requires at least one file for the initial commit.")
        owner = self._authenticated_login(path)
        if visibility not in {"public", "private"}:
            raise PublicationInputRequired("github_visibility")
        return PublicationPlan(
            repository_path=path,
            owner=owner,
            name=expected_name,
            branch="main",
            visibility=visibility,
            remote_name=None,
            create_repository=True,
            existing_repository_name=None,
            rename_existing_repository=False,
            existing_remote_url=None,
            worktree_status=status,
            initialize_repository=True,
            description=description,
            git_transport=self._preferred_git_transport(path),
        )

    def retry_push_with_ssh(self, error: PublicationPushError) -> PublicationResult:
        """Retry an approved HTTPS transport failure against the same remote over SSH."""
        if not error.ssh_retry_available:
            raise PublicationError("SSH retry is not available for this publication failure.")
        current = error.plan
        self._git(
            current.repository_path,
            "remote",
            "set-url",
            "origin",
            _github_remote_url("ssh", current.owner, current.name),
        )
        try:
            self._git(
                current.repository_path,
                "push",
                "origin",
                f"HEAD:refs/heads/{current.branch}",
            )
        except PublicationError as push_error:
            if self._remote_branch_matches(current.repository_path, current.branch, error.commit_sha):
                return PublicationResult(
                    repository=current.repository,
                    branch=current.branch,
                    commit_sha=error.commit_sha,
                    created_repository=current.create_repository,
                )
            raise PublicationError(
                "SSH retry did not receive confirmation from GitHub: "
                f"{push_error}"
            ) from push_error
        return PublicationResult(
            repository=current.repository,
            branch=current.branch,
            commit_sha=error.commit_sha,
            created_repository=current.create_repository,
        )

    def _push_or_confirm(self, plan: PublicationPlan, commit_sha: str) -> None:
        try:
            self._git(
                plan.repository_path,
                "push",
                "origin",
                f"HEAD:refs/heads/{plan.branch}",
            )
        except PublicationError as push_error:
            if self._remote_branch_matches(plan.repository_path, plan.branch, commit_sha):
                return
            detail = str(push_error).removeprefix("Git command failed: ")
            raise PublicationPushError(
                plan=plan,
                commit_sha=commit_sha,
                detail=detail,
                ssh_retry_available=(
                    plan.git_transport == "https"
                    and _looks_like_transport_failure(detail)
                    and self._ssh_authentication_available(plan.repository_path)
                ),
            ) from push_error

    def _remote_branch_matches(self, path: Path, branch: str, commit_sha: str) -> bool:
        result = self._run(
            [self.git_bin, "-C", str(path), "ls-remote", "origin", f"refs/heads/{branch}"],
            path,
        )
        if result.returncode != 0:
            return False
        expected_ref = f"refs/heads/{branch}"
        return any(
            line.split(maxsplit=1) == [commit_sha, expected_ref]
            for line in result.stdout.splitlines()
        )

    def _ssh_authentication_available(self, path: Path) -> bool:
        result = self._run(
            ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-T", "git@github.com"],
            path,
        )
        response = f"{result.stdout}\n{result.stderr}".casefold()
        return "successfully authenticated" in response

    def _preferred_git_transport(self, path: Path) -> str:
        protocol = self._gh(path, "config", "get", "git_protocol", "--host", "github.com").strip()
        if protocol not in {"https", "ssh"}:
            raise PublicationError(
                'GitHub CLI git_protocol must be "https" or "ssh" for github.com.'
            )
        return protocol

    def _is_git_repository(self, path: Path) -> bool:
        result = self._run([self.git_bin, "-C", str(path), "rev-parse", "--is-inside-work-tree"], path)
        if result.returncode == 0:
            if result.stdout.strip() == "true":
                return True
            raise PublicationError("Publication requires a non-bare Git working tree.")
        if "not a git repository" in result.stderr.casefold():
            return False
        raise PublicationError(_command_failure("Git", result))

    def _github_repository(self, owner: str, name: str, path: Path) -> dict[str, object]:
        output = self._gh(
            path,
            "repo",
            "view",
            f"{owner}/{name}",
            "--json",
            "nameWithOwner,isFork,viewerPermission,visibility",
        )
        try:
            details = json.loads(output)
        except json.JSONDecodeError as error:
            raise PublicationError("GitHub CLI returned invalid repository metadata.") from error
        if not isinstance(details, dict) or details.get("nameWithOwner") != f"{owner}/{name}":
            raise PublicationError("GitHub CLI returned unexpected repository metadata.")
        return details

    def _git(self, path: Path, *arguments: str) -> str:
        result = self._run([self.git_bin, "-C", str(path), *arguments], path)
        if result.returncode != 0:
            raise PublicationError(_command_failure("Git", result))
        return result.stdout

    def _optional_git(self, path: Path, *arguments: str) -> str | None:
        result = self._run([self.git_bin, "-C", str(path), *arguments], path)
        if result.returncode == 0:
            return result.stdout.strip()
        if arguments == ("remote", "get-url", "origin"):
            return None
        raise PublicationError(_command_failure("Git", result))

    def _gh(self, path: Path, *arguments: str) -> str:
        result = self._run([self.gh_bin, *arguments], path)
        if result.returncode != 0:
            raise PublicationError(_command_failure("GitHub CLI", result))
        return result.stdout

    def _run(self, command: list[str], path: Path) -> CommandResult:
        try:
            return self._runner(command, path)
        except OSError as error:
            raise PublicationError(f"Could not run {command[0]}: {error}") from error


def _subprocess_runner(command: list[str], path: Path | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=path, capture_output=True, text=True, check=False)


def _github_remote_identity(url: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+)/([^/]+?)(?:\.git)?/?",
        url.strip(),
    )
    if match is None:
        raise PublicationError("Origin must be a GitHub repository remote; Repo Curator will not retarget it.")
    return match.group(1), match.group(2)


def _command_failure(tool: str, result: CommandResult) -> str:
    detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
    return f"{tool} command failed: {detail}"


def _plan_signature(plan: PublicationPlan) -> tuple[object, ...]:
    return (
        plan.repository_path,
        plan.owner,
        plan.name,
        plan.branch,
        plan.visibility,
        plan.remote_name,
        plan.create_repository,
        plan.existing_repository_name,
        plan.rename_existing_repository,
        plan.existing_remote_url,
        plan.worktree_status,
        plan.initialize_repository,
        plan.description,
        plan.git_transport,
    )


def _renamed_remote_url(url: str, owner: str, name: str) -> str:
    match = re.fullmatch(
        r"(https://github\.com/|git@github\.com:|ssh://git@github\.com/)[^/]+/[^/]+?(\.git)?/?",
        url.strip(),
    )
    if match is None:
        raise PublicationError("Origin must be a GitHub repository remote; Repo Curator will not retarget it.")
    return f"{match.group(1)}{owner}/{name}{match.group(2) or ''}"


def _git_transport(url: str) -> str:
    if url.strip().startswith("https://github.com/"):
        return "https"
    if url.strip().startswith(("git@github.com:", "ssh://git@github.com/")):
        return "ssh"
    raise PublicationError("Origin must be a GitHub repository remote; Repo Curator will not retarget it.")


def _github_remote_url(transport: str, owner: str, name: str) -> str:
    if transport == "https":
        return f"https://github.com/{owner}/{name}.git"
    if transport == "ssh":
        return f"git@github.com:{owner}/{name}.git"
    raise PublicationError(f"Unsupported Git transport: {transport}")


def _looks_like_transport_failure(detail: str) -> bool:
    normalized = detail.casefold()
    return any(
        signal in normalized
        for signal in (
            "rpc failed",
            "send-pack:",
            "unexpected disconnect",
            "remote end hung up unexpectedly",
            "curl ",
        )
    )


def _initial_worktree_status(path: Path) -> tuple[str, ...]:
    """Preview the exact files Git would add without initializing a repository."""
    files: list[str] = []
    for candidate in sorted(path.rglob("*")):
        if ".git" in candidate.relative_to(path).parts:
            continue
        if candidate.is_file() or candidate.is_symlink():
            files.append(f"?? {candidate.relative_to(path).as_posix()}")
    return tuple(files)

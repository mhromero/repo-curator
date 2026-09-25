from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from repo_curator.publication import (
    GitHubCliPublisher,
    PublicationError,
    PublicationInputRequired,
    PublicationPushError,
    format_github_description,
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], list[tuple[int, str, str]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: list[str], _path: Path | None):
        if command[0] == "git":
            key = ("git", *command[3:])
        else:
            key = tuple(command)
        self.calls.append(key)
        queue = self.responses.get(key)
        if queue is None and key[:3] == ("gh", "repo", "create"):
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if not queue:
            raise AssertionError(f"Unexpected command: {key}")
        code, stdout, stderr = queue.pop(0)
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def test_github_description_uses_human_confirmed_english_class_name() -> None:
    assert format_github_description(
        "ucm-2026-procesamiento-lenguaje-natural",
        "labs",
        "Natural Language Processing",
    ) == "Labs for Natural Language Processing @ UCM (2026)"


def test_github_description_rejects_an_empty_class_name() -> None:
    with pytest.raises(PublicationError, match="English class name"):
        format_github_description("ucm-2026-procesamiento-lenguaje-natural", "labs", " ")


def test_publisher_creates_confirmed_personal_repository_then_non_force_pushes(tmp_path: Path) -> None:
    description = "A coursework implementation of intelligent-systems laboratory exercises."
    responses = _new_repository_responses(
        status=[(0, " M README.md\n", ""), (0, " M README.md\n", "")]
    )
    responses[("gh", "repo", "edit", "maria/vgtu-2024-intelligent-systems", "--description", description)] = [
        (0, "", "")
    ]
    runner = FakeRunner(responses)
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(
        tmp_path,
        expected_name="vgtu-2024-intelligent-systems",
        visibility="public",
        description=description,
    )
    result = publisher.publish(plan)

    assert result.repository == "maria/vgtu-2024-intelligent-systems"
    assert result.created_repository is True
    assert ("gh", "repo", "create", "maria/vgtu-2024-intelligent-systems", "--public", "--source", str(tmp_path.resolve()), "--remote", "origin") in runner.calls
    assert ("gh", "repo", "edit", "maria/vgtu-2024-intelligent-systems", "--description", description) in runner.calls
    assert ("git", "push", "origin", "HEAD:refs/heads/main") in runner.calls
    assert (
        "git",
        "remote",
        "set-url",
        "origin",
        "https://github.com/maria/vgtu-2024-intelligent-systems.git",
    ) in runner.calls
    assert all("--force" not in command for command in runner.calls)


def test_publisher_requires_visibility_before_creating_a_new_repository(tmp_path: Path) -> None:
    runner = FakeRunner(_new_repository_responses(status=[(0, "", "")]))
    publisher = GitHubCliPublisher(runner=runner)

    with pytest.raises(PublicationInputRequired, match="github_visibility"):
        publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility=None)


def test_publisher_initializes_plain_folder_only_during_approved_publish(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Sample\n", encoding="utf-8")
    runner = FakeRunner(
        {
            ("git", "rev-parse", "--is-inside-work-tree"): [
                (128, "", "fatal: not a git repository"),
                (128, "", "fatal: not a git repository"),
            ],
            ("gh", "auth", "status", "--hostname", "github.com"): [(0, "", ""), (0, "", "")],
            ("gh", "api", "user", "--jq", ".login"): [(0, "maria\n", ""), (0, "maria\n", "")],
            ("gh", "config", "get", "git_protocol", "--host", "github.com"): [
                (0, "ssh\n", ""),
                (0, "ssh\n", ""),
            ],
            ("git", "init", "--initial-branch", "main"): [(0, "", "")],
            ("git", "add", "-A"): [(0, "", "")],
            ("git", "commit", "-m", "Prepare repository for publication"): [(0, "", "")],
            ("git", "rev-parse", "HEAD"): [(0, "abc123\n", "")],
            ("git", "remote", "set-url", "origin", "git@github.com:maria/vgtu-2024-intelligent-systems.git"): [(0, "", "")],
            ("git", "push", "origin", "HEAD:refs/heads/main"): [(0, "", "")],
        }
    )
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility="public")

    assert plan.initialize_repository is True
    assert plan.branch == "main"
    assert plan.worktree_status == ("?? README.md",)
    assert ("git", "init", "--initial-branch", "main") not in runner.calls

    publisher.publish(plan)

    assert ("git", "init", "--initial-branch", "main") in runner.calls
    assert ("git", "add", "-A") in runner.calls
    assert ("git", "push", "origin", "HEAD:refs/heads/main") in runner.calls
    assert (
        "git",
        "remote",
        "set-url",
        "origin",
        "git@github.com:maria/vgtu-2024-intelligent-systems.git",
    ) in runner.calls


def test_publisher_refuses_foreign_existing_remote_before_git_mutation(tmp_path: Path) -> None:
    responses = _existing_repository_responses(
        remote="git@github.com:course-org/vgtu-2024-intelligent-systems.git",
        details='{"nameWithOwner":"course-org/vgtu-2024-intelligent-systems","isFork":false,"viewerPermission":"ADMIN","visibility":"PUBLIC"}',
    )
    runner = FakeRunner(responses)
    publisher = GitHubCliPublisher(runner=runner)

    with pytest.raises(PublicationError, match="not owned by the authenticated GitHub user"):
        publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility=None)

    assert not any(command[:2] == ("git", "add") for command in runner.calls)


def test_publisher_preserves_an_existing_https_remote_transport(tmp_path: Path) -> None:
    remote = "https://github.com/maria/vgtu-2024-intelligent-systems.git"
    details = '{"nameWithOwner":"maria/vgtu-2024-intelligent-systems","isFork":false,"viewerPermission":"ADMIN","visibility":"PUBLIC"}'
    runner = FakeRunner(
        {
            ("git", "rev-parse", "--is-inside-work-tree"): [(0, "true\n", ""), (0, "true\n", "")],
            ("git", "branch", "--show-current"): [(0, "main\n", ""), (0, "main\n", "")],
            ("gh", "auth", "status", "--hostname", "github.com"): [(0, "", ""), (0, "", "")],
            ("gh", "api", "user", "--jq", ".login"): [(0, "maria\n", ""), (0, "maria\n", "")],
            ("git", "status", "--porcelain=v1"): [(0, "", ""), (0, "", "")],
            ("git", "remote", "get-url", "origin"): [(0, remote + "\n", ""), (0, remote + "\n", "")],
            ("gh", "repo", "view", "maria/vgtu-2024-intelligent-systems", "--json", "nameWithOwner,isFork,viewerPermission,visibility"): [(0, details, ""), (0, details, "")],
            ("git", "rev-parse", "HEAD"): [(0, "abc123\n", "")],
            ("git", "push", "origin", "HEAD:refs/heads/main"): [(0, "", "")],
        }
    )
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility=None)
    result = publisher.publish(plan)

    assert plan.git_transport == "https"
    assert result.commit_sha == "abc123"
    assert not any(command[:3] == ("gh", "config", "get") for command in runner.calls)
    assert not any(command[:3] == ("git", "remote", "set-url") for command in runner.calls)


def test_publisher_renames_owned_remote_only_in_the_approved_publish_step(tmp_path: Path) -> None:
    remote = "git@github.com:maria/IS_Labs.git"
    details = '{"nameWithOwner":"maria/IS_Labs","isFork":false,"viewerPermission":"ADMIN","visibility":"PUBLIC"}'
    runner = FakeRunner(
        {
            ("git", "rev-parse", "--is-inside-work-tree"): [(0, "true\n", ""), (0, "true\n", "")],
            ("git", "branch", "--show-current"): [(0, "main\n", ""), (0, "main\n", "")],
            ("gh", "auth", "status", "--hostname", "github.com"): [(0, "", ""), (0, "", "")],
            ("gh", "api", "user", "--jq", ".login"): [(0, "maria\n", ""), (0, "maria\n", "")],
            ("git", "status", "--porcelain=v1"): [(0, "", ""), (0, "", "")],
            ("git", "remote", "get-url", "origin"): [(0, remote + "\n", ""), (0, remote + "\n", "")],
            ("gh", "repo", "view", "maria/IS_Labs", "--json", "nameWithOwner,isFork,viewerPermission,visibility"): [(0, details, ""), (0, details, "")],
            ("git", "rev-parse", "HEAD"): [(0, "abc123\n", "")],
            ("gh", "repo", "rename", "vgtu-2024-intelligent-systems", "--repo", "maria/IS_Labs"): [(0, "", "")],
            ("git", "remote", "set-url", "origin", "git@github.com:maria/vgtu-2024-intelligent-systems.git"): [(0, "", "")],
            ("git", "push", "origin", "HEAD:refs/heads/main"): [(0, "", "")],
        }
    )
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility=None)
    assert plan.rename_existing_repository is True
    assert not any(command[:3] == ("gh", "repo", "rename") for command in runner.calls)

    result = publisher.publish(plan)

    assert result.repository == "maria/vgtu-2024-intelligent-systems"
    assert ("gh", "repo", "rename", "vgtu-2024-intelligent-systems", "--repo", "maria/IS_Labs") in runner.calls
    assert ("git", "remote", "set-url", "origin", "git@github.com:maria/vgtu-2024-intelligent-systems.git") in runner.calls


def test_publisher_refuses_to_commit_when_worktree_changes_after_final_review(tmp_path: Path) -> None:
    runner = FakeRunner(
        _new_repository_responses(
            status=[(0, " M README.md\n", ""), (0, "?? surprise.txt\n", "")]
        )
    )
    publisher = GitHubCliPublisher(runner=runner)
    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility="private")

    with pytest.raises(PublicationError, match="changed after final review"):
        publisher.publish(plan)

    assert not any(command[:2] == ("git", "add") for command in runner.calls)


def test_publisher_accepts_a_remote_branch_that_arrived_despite_push_error(tmp_path: Path) -> None:
    responses = _new_repository_responses(status=[(0, "", ""), (0, "", "")])
    responses[("git", "push", "origin", "HEAD:refs/heads/main")] = [
        (1, "", "fatal: the remote end hung up unexpectedly")
    ]
    responses[("git", "ls-remote", "origin", "refs/heads/main")] = [
        (0, "abc123\trefs/heads/main\n", "")
    ]
    runner = FakeRunner(responses)
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility="public")
    result = publisher.publish(plan)

    assert result.commit_sha == "abc123"
    assert ("git", "ls-remote", "origin", "refs/heads/main") in runner.calls


def test_publisher_offers_explicit_ssh_retry_only_for_authenticated_https_transport_failure(
    tmp_path: Path,
) -> None:
    responses = _new_repository_responses(status=[(0, "", ""), (0, "", "")])
    responses[("git", "push", "origin", "HEAD:refs/heads/main")] = [
        (1, "", "error: RPC failed; HTTP 400\nsend-pack: unexpected disconnect"),
        (0, "", ""),
    ]
    responses[("git", "ls-remote", "origin", "refs/heads/main")] = [(0, "", "")]
    responses[("ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-T", "git@github.com")] = [
        (1, "", "Hi maria! You've successfully authenticated, but GitHub does not provide shell access.")
    ]
    responses[("git", "remote", "set-url", "origin", "git@github.com:maria/vgtu-2024-intelligent-systems.git")] = [
        (0, "", "")
    ]
    runner = FakeRunner(responses)
    publisher = GitHubCliPublisher(runner=runner)

    plan = publisher.prepare(tmp_path, expected_name="vgtu-2024-intelligent-systems", visibility="public")
    with pytest.raises(PublicationPushError) as captured:
        publisher.publish(plan)

    error = captured.value
    assert error.ssh_retry_available is True
    result = publisher.retry_push_with_ssh(error)

    assert result.commit_sha == "abc123"
    assert (
        "git",
        "remote",
        "set-url",
        "origin",
        "git@github.com:maria/vgtu-2024-intelligent-systems.git",
    ) in runner.calls


def _new_repository_responses(*, status: list[tuple[int, str, str]]) -> dict[tuple[str, ...], list[tuple[int, str, str]]]:
    return {
        ("git", "rev-parse", "--is-inside-work-tree"): [(0, "true\n", ""), (0, "true\n", "")],
        ("git", "branch", "--show-current"): [(0, "main\n", ""), (0, "main\n", "")],
        ("gh", "auth", "status", "--hostname", "github.com"): [(0, "", ""), (0, "", "")],
        ("gh", "api", "user", "--jq", ".login"): [(0, "maria\n", ""), (0, "maria\n", "")],
        ("gh", "config", "get", "git_protocol", "--host", "github.com"): [
            (0, "https\n", ""),
            (0, "https\n", ""),
        ],
        ("git", "status", "--porcelain=v1"): status,
        ("git", "remote", "get-url", "origin"): [(2, "", "no such remote"), (2, "", "no such remote")],
        ("git", "add", "-A"): [(0, "", "")],
        ("git", "commit", "-m", "Prepare repository for publication"): [(0, "", "")],
        ("git", "rev-parse", "HEAD"): [(0, "abc123\n", "")],
        ("git", "remote", "set-url", "origin", "https://github.com/maria/vgtu-2024-intelligent-systems.git"): [(0, "", "")],
        ("git", "push", "origin", "HEAD:refs/heads/main"): [(0, "", "")],
    }


def _existing_repository_responses(*, remote: str, details: str) -> dict[tuple[str, ...], list[tuple[int, str, str]]]:
    return {
        ("git", "rev-parse", "--is-inside-work-tree"): [(0, "true\n", "")],
        ("git", "branch", "--show-current"): [(0, "main\n", "")],
        ("gh", "auth", "status", "--hostname", "github.com"): [(0, "", "")],
        ("gh", "api", "user", "--jq", ".login"): [(0, "maria\n", "")],
        ("git", "status", "--porcelain=v1"): [(0, "", "")],
        ("git", "remote", "get-url", "origin"): [(0, remote + "\n", "")],
        ("gh", "repo", "view", "course-org/vgtu-2024-intelligent-systems", "--json", "nameWithOwner,isFork,viewerPermission,visibility"): [(0, details, "")],
    }

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from .models import (
    FileRecord,
    GitIdentity,
    GitStatusCounts,
    RepositoryIdentity,
    RepositoryProfile,
    ScanResult,
    TriageGitContext,
    TriageOutline,
    TriageSummary,
)
from .signals import analyze_repository_files

MAX_TRIAGE_OUTLINE_BYTES = 64 * 1_024

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "vendor",
        "__pycache__",
        ".ipynb_checkpoints",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".cache",
        ".gradle",
        ".next",
        ".parcel-cache",
        ".turbo",
        ".vite",
        "dist",
        "build",
        "coverage",
        "target",
    }
)

LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".cc": "C++",
    ".clj": "Clojure",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".cxx": "C++",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".go": "Go",
    ".h": "C/C++",
    ".hh": "C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".ipynb": "Jupyter Notebook",
    ".java": "Java",
    ".jl": "Julia",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".lua": "Lua",
    ".m": "Objective-C/MATLAB",
    ".mm": "Objective-C++",
    ".php": "PHP",
    ".pl": "Perl",
    ".py": "Python",
    ".r": "R",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".sh": "Shell",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
    ".xml": "XML",
}

LANGUAGE_BY_FILENAME = {
    ".bashrc": "Shell",
    "bashrc": "Shell",
    "dockerfile": "Dockerfile",
    "makefile": "Make",
}


def scan_repository(path: str | Path) -> ScanResult:
    """Return deterministic repository evidence and its compact triage summary."""
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Scan path is not a directory: {root}")

    files, directories, ignored_directories = _inventory(root)
    language_counts = Counter(
        record.language for record in files if record.language is not None
    )
    total_file_bytes = sum(
        record.size_bytes for record in files if record.size_bytes is not None
    )
    git_identity, tracked_paths = _git_identity(root)
    scan_tracked_paths = _tracked_paths_within_scan_root(
        root,
        git_identity,
        tracked_paths,
    )
    analysis = analyze_repository_files(
        root,
        files,
        scan_tracked_paths,
        is_git_repository=git_identity is not None,
    )
    object_store_bytes = git_identity.object_store_bytes if git_identity else None
    profile = RepositoryProfile(
        identity=RepositoryIdentity(
            path=str(root),
            directory_name=root.name or str(root),
            git=git_identity,
        ),
        files=files,
        directories=directories,
        ignored_directories=ignored_directories,
        language_counts=dict(sorted(language_counts.items())),
        evidence=analysis.evidence,
        content_scan=analysis.content_scan,
        triage_readmes=analysis.triage_readmes,
        python_import_reference_version=(
            f"{sys.version_info.major}.{sys.version_info.minor}"
        ),
        total_file_bytes=total_file_bytes,
        approximate_repository_size_bytes=total_file_bytes + (object_store_bytes or 0),
    )
    return ScanResult(
        repository_profile=profile,
        triage_summary=derive_triage_summary(profile),
    )


def derive_triage_summary(profile: RepositoryProfile) -> TriageSummary:
    evidence = profile.evidence
    readme_sections = Counter(
        section
        for readme in evidence.readme_signals
        for section in readme.sections_present
    )
    artifact_counts = Counter(
        category
        for artifact in evidence.artifact_files
        for category in artifact.categories
    )
    git = profile.identity.git
    return TriageSummary(
        directory_name=profile.identity.directory_name,
        is_git_repository=git is not None,
        git_branch=git.branch if git else None,
        git_dirty=git.is_dirty if git else None,
        git_upstream_configured=bool(git and git.upstream),
        git_remote_count=len(git.remotes) if git else 0,
        git_tracked_file_count=git.tracked_file_count if git else None,
        git_untracked_entry_count=git.untracked_entry_count if git else None,
        git_status_counts=git.status_counts if git else None,
        file_count=len(profile.files),
        approximate_repository_size_bytes=profile.approximate_repository_size_bytes,
        language_counts=profile.language_counts,
        top_level_directory_count=sum("/" not in path for path in profile.directories),
        ecosystems_detected=evidence.ecosystems_detected,
        python_import_class_counts=dict(
            sorted(Counter(item.classification for item in evidence.python_imports).items())
        ),
        dependency_file_count=len(evidence.dependency_files),
        readme_count=len(evidence.readme_signals),
        readme_sections=dict(sorted(readme_sections.items())),
        test_file_count=len(evidence.test_files),
        test_config_count=len(evidence.test_config_files),
        build_config_count=len(evidence.build_config_files),
        package_script_count=sum(
            len(scripts.script_names) for scripts in evidence.package_scripts
        ),
        candidate_entry_point_count=len(evidence.candidate_entry_points),
        artifact_counts=dict(sorted(artifact_counts.items())),
        secret_risk_count=len(evidence.secret_risks),
        local_path_risk_count=len(evidence.local_path_risks),
        tracked_junk_count=len(evidence.tracked_junk_paths),
        ignored_directory_count=len(profile.ignored_directories),
        content_analysis_limited=profile.content_scan.files_skipped_by_limits > 0,
        repository_outline=_build_triage_outline(profile),
    )


def _build_triage_outline(profile: RepositoryProfile) -> TriageOutline:
    evidence = profile.evidence
    git = profile.identity.git
    outline = TriageOutline(
        directory_name=profile.identity.directory_name,
        git=(
            TriageGitContext(
                branch=git.branch,
                upstream=git.upstream,
                remotes=git.remotes,
                is_dirty=git.is_dirty,
                status_counts=git.status_counts,
                scan_is_git_root=(
                    Path(git.root_path).resolve() == Path(profile.identity.path).resolve()
                ),
            )
            if git is not None
            else None
        ),
        content_scan=profile.content_scan,
        max_serialized_bytes=MAX_TRIAGE_OUTLINE_BYTES,
    )
    for field_name, items in (
        ("readmes", profile.triage_readmes),
        ("dependency_files", evidence.dependency_files),
        ("special_files", evidence.special_files),
        ("test_files", evidence.test_files),
        ("test_config_files", evidence.test_config_files),
        ("build_config_files", evidence.build_config_files),
        ("package_scripts", evidence.package_scripts),
        ("candidate_entry_points", evidence.candidate_entry_points),
        ("artifact_files", evidence.artifact_files),
        ("secret_risks", evidence.secret_risks),
        ("local_path_risks", evidence.local_path_risks),
        ("hygiene_findings", evidence.hygiene_findings),
        ("ignored_directories", profile.ignored_directories),
        ("directories", profile.directories),
        ("python_imports", evidence.python_imports),
        ("files", profile.files),
    ):
        _append_outline_items(outline, field_name, items)
    outline.serialized_bytes = len(outline.model_dump_json().encode("utf-8"))
    return outline


def _append_outline_items(
    outline: TriageOutline,
    field_name: str,
    items: list[object],
) -> None:
    included_items = getattr(outline, field_name)
    if outline.serialized_bytes == 0:
        outline.serialized_bytes = len(outline.model_dump_json().encode("utf-8"))
    for item in items:
        item_json = json.dumps(
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item,
            sort_keys=True,
            separators=(",", ":"),
        )
        item_size = len(item_json.encode("utf-8")) + 1
        if outline.serialized_bytes + item_size > MAX_TRIAGE_OUTLINE_BYTES:
            outline.outline_truncated = True
            outline.omitted_item_counts[field_name] = (
                outline.omitted_item_counts.get(field_name, 0) + 1
            )
            continue
        included_items.append(item)
        outline.serialized_bytes += item_size


def _inventory(root: Path) -> tuple[list[FileRecord], list[str], list[str]]:
    files: list[FileRecord] = []
    directories: list[str] = []
    ignored_directories: list[str] = []
    pending_directories = [root]

    while pending_directories:
        directory = pending_directories.pop()
        with os.scandir(directory) as entries_iterator:
            entries = sorted(entries_iterator, key=lambda entry: entry.name)
        for entry in entries:
            entry_path = Path(entry.path)
            relative_path = entry_path.relative_to(root).as_posix()

            if entry.is_dir(follow_symlinks=False):
                if entry.name in IGNORED_DIRECTORY_NAMES:
                    ignored_directories.append(relative_path)
                else:
                    directories.append(relative_path)
                    pending_directories.append(entry_path)
                continue

            if entry.is_symlink():
                files.append(
                    FileRecord(
                        path=relative_path,
                        size_bytes=None,
                        kind="symlink",
                        language=_language_for(entry.name),
                    )
                )
                continue

            if entry.is_file(follow_symlinks=False):
                file_stat = entry.stat(follow_symlinks=False)
                files.append(
                    FileRecord(
                        path=relative_path,
                        size_bytes=file_stat.st_size,
                        language=_language_for(entry.name),
                    )
                )

    files.sort(key=lambda record: record.path)
    directories.sort()
    ignored_directories.sort()
    return files, directories, ignored_directories


def _language_for(filename: str) -> str | None:
    lowered_name = filename.lower()
    if lowered_name in LANGUAGE_BY_FILENAME:
        return LANGUAGE_BY_FILENAME[lowered_name]
    return LANGUAGE_BY_SUFFIX.get(Path(lowered_name).suffix)


def _tracked_paths_within_scan_root(
    scan_root: Path,
    git_identity: GitIdentity | None,
    tracked_paths: list[str],
) -> list[str]:
    if git_identity is None:
        return []
    try:
        relative_scan_root = scan_root.relative_to(Path(git_identity.root_path))
    except ValueError:
        return []
    if relative_scan_root == Path("."):
        return tracked_paths
    prefix = relative_scan_root.as_posix().rstrip("/") + "/"
    return [
        tracked_path[len(prefix) :]
        for tracked_path in tracked_paths
        if tracked_path.startswith(prefix)
    ]


def _git_identity(path: Path) -> tuple[GitIdentity | None, list[str]]:
    root_result = _run_git(path, "rev-parse", "--show-toplevel")
    if root_result is None:
        return None, []

    git_root = Path(root_result.strip()).resolve()
    status_result = _run_git(
        path,
        "status",
        "--porcelain=v2",
        "--branch",
        "--untracked-files=normal",
        "-z",
    )
    branch, upstream, ahead, behind, status_counts, is_dirty = _parse_status(
        status_result
    )
    tracked_result = _run_git(path, "ls-files", "--cached", "-z")
    tracked_paths = (
        [tracked_path for tracked_path in tracked_result.split("\0") if tracked_path]
        if tracked_result is not None
        else []
    )
    remote_result = _run_git(path, "remote")
    object_store_result = _run_git(path, "count-objects", "-v")

    git_identity = GitIdentity(
        root_path=str(git_root),
        branch=branch,
        upstream=upstream,
        ahead_count=ahead,
        behind_count=behind,
        remotes=sorted(remote_result.splitlines()) if remote_result is not None else [],
        tracked_file_count=len(tracked_paths) if tracked_result is not None else None,
        untracked_entry_count=status_counts.untracked if status_counts else None,
        is_dirty=is_dirty,
        status_counts=status_counts or GitStatusCounts(),
        object_store_bytes=_object_store_size(object_store_result),
        fork_relationship_known=False,
    )
    return git_identity, tracked_paths


def _parse_status(
    output: str | None,
) -> tuple[
    str | None,
    str | None,
    int | None,
    int | None,
    GitStatusCounts | None,
    bool | None,
]:
    if output is None:
        return None, None, None, None, None, None

    branch: str | None = None
    upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    staged = modified = deleted = renamed = conflicted = untracked = 0
    is_dirty = False

    records = output.split("\0")
    record_index = 0
    while record_index < len(records):
        record = records[record_index]
        record_index += 1
        if not record:
            continue
        if record.startswith("# branch.head "):
            branch_value = record.removeprefix("# branch.head ")
            branch = None if branch_value == "(detached)" else branch_value
            continue
        if record.startswith("# branch.upstream "):
            upstream = record.removeprefix("# branch.upstream ")
            continue
        if record.startswith("# branch.ab "):
            ahead_behind = re_match_branch_ab(record)
            if ahead_behind is not None:
                ahead, behind = ahead_behind
            continue
        if record.startswith("# "):
            continue

        is_dirty = True
        if record.startswith("? "):
            untracked += 1
            continue
        if record.startswith("u "):
            conflicted += 1
            continue

        fields = record.split(" ", maxsplit=2)
        if len(fields) < 2:
            continue
        status = fields[1]
        index_status, worktree_status = status[0], status[1]
        if index_status != ".":
            staged += 1
        if "M" in status:
            modified += 1
        if "D" in status:
            deleted += 1
        if "R" in status or "C" in status:
            renamed += 1
        if fields[0] == "2":
            record_index += 1

    return (
        branch,
        upstream,
        ahead,
        behind,
        GitStatusCounts(
            staged=staged,
            modified=modified,
            deleted=deleted,
            renamed=renamed,
            conflicted=conflicted,
            untracked=untracked,
        ),
        is_dirty,
    )


def re_match_branch_ab(record: str) -> tuple[int, int] | None:
    fields = record.split()
    if len(fields) != 4:
        return None
    try:
        return int(fields[2].lstrip("+")), int(fields[3].lstrip("-"))
    except ValueError:
        return None


def _object_store_size(output: str | None) -> int | None:
    if output is None:
        return None
    sizes: dict[str, int] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key in {"size", "size-pack"}:
            try:
                sizes[key] = int(value.strip())
            except ValueError:
                continue
    if not {"size", "size-pack"}.issubset(sizes):
        return None
    return (sizes["size"] + sizes["size-pack"]) * 1024


def _run_git(path: Path, *arguments: str) -> str | None:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None
    return result.stdout

from __future__ import annotations

import ast
import fnmatch
import json
import re
import sys
import tomllib
from pathlib import Path, PurePosixPath

from .models import (
    ArtifactFile,
    CandidateEntryPoint,
    ContentScanInfo,
    DependencyFile,
    FileRecord,
    HygieneFinding,
    PackageScripts,
    PythonImportEvidence,
    ReadmeSignals,
    RepositoryAnalysis,
    RepositoryEvidence,
    RiskIndicator,
    SpecialFileSignal,
    TriageReadme,
)

MAX_CONTENT_FILE_BYTES = 1_048_576
MAX_CONTENT_TOTAL_BYTES = 16 * 1_048_576
LARGE_FILE_BYTES = 10 * 1_048_576
MAX_TRIAGE_README_CHARS = 12_000
PRIVATE_KEY_BLOCK_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
    re.DOTALL,
)

DEPENDENCY_FILE_RULES = (
    ("pyproject.toml", "Python", "project_metadata"),
    ("setup.py", "Python", "package_metadata"),
    ("setup.cfg", "Python", "package_metadata"),
    ("requirements*.txt", "Python", "requirements"),
    ("pipfile", "Python", "dependency_manifest"),
    ("pipfile.lock", "Python", "lockfile"),
    ("poetry.lock", "Python", "lockfile"),
    ("uv.lock", "Python", "lockfile"),
    ("environment.yml", "Python", "environment"),
    ("environment.yaml", "Python", "environment"),
    ("conda.yml", "Python", "environment"),
    ("conda.yaml", "Python", "environment"),
    ("package.json", "JavaScript", "package_manifest"),
    ("package-lock.json", "JavaScript", "lockfile"),
    ("yarn.lock", "JavaScript", "lockfile"),
    ("pnpm-lock.yaml", "JavaScript", "lockfile"),
    ("bun.lock", "JavaScript", "lockfile"),
    ("bun.lockb", "JavaScript", "lockfile"),
    ("cargo.toml", "Rust", "package_manifest"),
    ("cargo.lock", "Rust", "lockfile"),
    ("go.mod", "Go", "module_manifest"),
    ("go.sum", "Go", "lockfile"),
    ("pom.xml", "Java", "build_manifest"),
    ("build.gradle", "Java", "build_manifest"),
    ("build.gradle.kts", "Java", "build_manifest"),
    ("gemfile", "Ruby", "dependency_manifest"),
    ("gemfile.lock", "Ruby", "lockfile"),
    ("composer.json", "PHP", "package_manifest"),
    ("composer.lock", "PHP", "lockfile"),
    ("packages.config", ".NET", "dependency_manifest"),
    ("*.csproj", ".NET", "project_manifest"),
    ("*.fsproj", ".NET", "project_manifest"),
    ("package.swift", "Swift", "package_manifest"),
    ("package.resolved", "Swift", "lockfile"),
    ("mix.exs", "Elixir", "project_manifest"),
    ("mix.lock", "Elixir", "lockfile"),
)

BUILD_FILE_NAMES = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "makefile",
    "justfile",
    "cmakelists.txt",
    "cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "package.json",
    "dockerfile",
    "build.xml",
    "build.sbt",
}
BUILD_FILE_PATTERNS = ("*.csproj", "*.fsproj", "*.xcodeproj", "*.xcworkspace")
RUNTIME_VERSION_FILES = {
    ".java-version",
    ".node-version",
    ".nvmrc",
    ".python-version",
    ".ruby-version",
    ".tool-versions",
}

TEST_CONFIG_NAMES = {
    ".coveragerc",
    "jest.config.js",
    "jest.config.cjs",
    "jest.config.mjs",
    "karma.conf.js",
    "noxfile.py",
    "phpunit.xml",
    "phpunit.xml.dist",
    "pytest.ini",
    "tox.ini",
    "vitest.config.js",
    "vitest.config.ts",
}
TEST_CONFIG_PATTERNS = ("jest.config.*", "vitest.config.*")

SOURCE_ENTRYPOINT_NAMES = {
    "__main__.py",
    "main.py",
    "app.py",
    "run.py",
    "cli.py",
    "index.js",
    "main.js",
    "server.js",
    "index.ts",
    "main.ts",
    "main.go",
    "main.rs",
    "main.c",
    "main.cpp",
    "main.java",
    "program.cs",
    "run.sh",
    "app.r",
}

TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".cxx",
    ".dat",
    ".env",
    ".ex",
    ".exs",
    ".go",
    ".gradle",
    ".h",
    ".hh",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".jl",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".kt",
    ".lua",
    ".m",
    ".md",
    ".mm",
    ".php",
    ".pl",
    ".py",
    ".r",
    ".rb",
    ".rst",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
    ".csv",
    ".ipynb",
    ".log",
    ".properties",
    ".rmd",
}
TEXT_SPECIAL_NAMES = {
    ".env",
    ".gitignore",
    "dockerfile",
    "makefile",
    "readme",
    "license",
    "licence",
}
BINARY_SUFFIXES = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".mp4",
    ".o",
    ".npy",
    ".npz",
    ".onnx",
    ".h5",
    ".hdf5",
    ".pt",
    ".pth",
    ".ckpt",
    ".safetensors",
    ".pkl",
    ".pickle",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".rar",
    ".so",
    ".tar",
    ".tif",
    ".tiff",
    ".wasm",
    ".wav",
    ".webp",
    ".zip",
}
DATA_SUFFIXES = {
    ".arrow",
    ".csv",
    ".db",
    ".feather",
    ".h5",
    ".hdf5",
    ".mat",
    ".npy",
    ".npz",
    ".parquet",
    ".sqlite",
    ".sqlite3",
    ".tsv",
    ".jsonl",
}
MODEL_SUFFIXES = {
    ".ckpt",
    ".h5",
    ".hdf5",
    ".keras",
    ".model",
    ".onnx",
    ".pb",
    ".pth",
    ".pt",
    ".safetensors",
    ".tflite",
}

SECRET_PATTERNS = (
    (
        "private_key_header",
        re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
        None,
    ),
    (
        "aws_access_key_id",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        None,
    ),
    (
        "github_token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
        None,
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?(?:key|token)|secret|password|passwd|token|access[_-]?key)"
            r"\b\s*[:=]\s*[\"']?([A-Za-z0-9_./+=-]{8,})"
        ),
        1,
    ),
)
LOCAL_PATH_PATTERNS = (
    ("unix_user_path", re.compile(r"/(?:Users|home)/[^\s\"'<>]+")),
    ("mac_volume_path", re.compile(r"/Volumes/[^\s\"'<>]+")),
    ("windows_user_path", re.compile(r"(?i)\b[A-Z]:\\(?:Users|Documents and Settings)\\[^\s\"'<>]+")),
)
PLACEHOLDER_VALUES = {
    "changeme",
    "example",
    "password",
    "placeholder",
    "replace_me",
    "replace-this",
    "secret",
    "your_api_key",
    "your_token",
}

README_SECTION_TERMS = {
    "setup": ("setup", "install", "installation", "dependencies", "requirements"),
    "usage": ("usage", "run", "running", "examples", "quick start", "quickstart"),
    "testing": ("test", "testing"),
    "results": ("results", "evaluation", "performance"),
}

LANGUAGE_ECOSYSTEMS = {
    "C#": ".NET",
    "C++": "C/C++",
    "C": "C/C++",
    "Dart": "Dart",
    "Elixir": "Elixir",
    "Go": "Go",
    "Java": "Java",
    "JavaScript": "JavaScript",
    "Jupyter Notebook": "Python",
    "Kotlin": "Kotlin",
    "PHP": "PHP",
    "Python": "Python",
    "Ruby": "Ruby",
    "Rust": "Rust",
    "Scala": "Scala",
    "Swift": "Swift",
    "TypeScript": "JavaScript",
}


def analyze_repository_files(
    root: Path,
    files: list[FileRecord],
    tracked_paths: list[str],
    is_git_repository: bool,
) -> RepositoryAnalysis:
    dependency_files = _dependency_files(files)
    ecosystem_names = {
        dependency.ecosystem for dependency in dependency_files
    }
    for record in files:
        if record.language in LANGUAGE_ECOSYSTEMS:
            ecosystem_names.add(LANGUAGE_ECOSYSTEMS[record.language])

    test_files = sorted(
        record.path for record in files if _is_test_file(record.path)
    )
    test_config_paths = {
        record.path for record in files if _is_test_config(record.path)
    }
    build_config_files = sorted(
        record.path for record in files if _is_build_config(record.path)
    )
    readme_paths = sorted(
        record.path
        for record in files
        if PurePosixPath(record.path).name.lower().startswith("readme")
    )
    file_text, content_scan, detected_binary_paths = _read_text_files(root, files)
    for path, content in file_text.items():
        basename = PurePosixPath(path).name.lower()
        if basename in {"pyproject.toml", "setup.cfg", "tox.ini"} and re.search(
            r"(?im)^\s*\[(?:tool\.pytest(?:\.[^]]+)?|tool:pytest|pytest)\]",
            content,
        ):
            test_config_paths.add(path)
        if basename == "package.json" and re.search(
            r'"(?:jest|vitest)"\s*:', content
        ):
            test_config_paths.add(path)
    test_config_files = sorted(test_config_paths)

    dependency_paths = {dependency.path for dependency in dependency_files}
    special_categories: dict[str, set[str]] = {}
    for record in files:
        path = record.path
        basename = PurePosixPath(path).name.lower()
        categories = special_categories.setdefault(path, set())
        if path in readme_paths:
            categories.add("readme")
        if basename == ".gitignore":
            categories.add("gitignore")
        if basename == ".env" or basename.startswith(".env."):
            categories.add("environment_configuration")
        if basename in RUNTIME_VERSION_FILES:
            categories.add("runtime_version")
        if basename in {"license", "licence", "copying", "notice"} or basename.startswith(
            ("license.", "licence.")
        ):
            categories.add("license_or_notice")
        if path in dependency_paths:
            categories.add("dependency_or_environment")
        if path in test_files:
            categories.add("test_candidate")
        if path in test_config_files:
            categories.add("test_configuration")
        if path in build_config_files:
            categories.add("build_configuration")

    package_scripts = _package_scripts(file_text)
    for scripts in package_scripts:
        special_categories.setdefault(scripts.path, set()).add("package_scripts")

    readme_signals = [
        _readme_signals(path, file_text.get(path)) for path in readme_paths
    ]
    triage_readmes = [
        _triage_readme(path, file_text.get(path)) for path in readme_paths
    ]
    candidate_entry_points = _candidate_entry_points(files, package_scripts)
    python_imports = _python_import_evidence(files, file_text)
    secret_risks, local_path_risks = _risk_indicators(file_text)
    tracked_junk_paths = sorted(
        path for path in tracked_paths if _tracked_junk_reason(path) is not None
    )
    hygiene_findings = _hygiene_findings(
        files,
        tracked_paths,
        tracked_junk_paths,
        is_git_repository,
    )

    return RepositoryAnalysis(
        evidence=RepositoryEvidence(
            ecosystems_detected=sorted(ecosystem_names),
            dependency_files=dependency_files,
            special_files=[
                SpecialFileSignal(path=path, categories=sorted(categories))
                for path, categories in sorted(special_categories.items())
                if categories
            ],
            readme_signals=readme_signals,
            test_files=test_files,
            test_config_files=test_config_files,
            build_config_files=build_config_files,
            package_scripts=package_scripts,
            candidate_entry_points=candidate_entry_points,
            artifact_files=_artifact_files(files, detected_binary_paths),
            python_imports=python_imports,
            secret_risks=secret_risks,
            local_path_risks=local_path_risks,
            tracked_junk_paths=tracked_junk_paths,
            hygiene_findings=hygiene_findings,
            gitignore_present=any(record.path == ".gitignore" for record in files),
        ),
        content_scan=content_scan,
        triage_readmes=triage_readmes,
    )


def _dependency_files(files: list[FileRecord]) -> list[DependencyFile]:
    results: list[DependencyFile] = []
    for record in files:
        basename = PurePosixPath(record.path).name.lower()
        for pattern, ecosystem, kind in DEPENDENCY_FILE_RULES:
            if fnmatch.fnmatchcase(basename, pattern):
                results.append(
                    DependencyFile(
                        path=record.path,
                        ecosystem=ecosystem,
                        kind=kind,
                    )
                )
                break
    return results


def _is_test_file(path: str) -> bool:
    parsed = PurePosixPath(path)
    parts = {part.lower() for part in parsed.parts[:-1]}
    basename = parsed.name.lower()
    return bool(
        parts.intersection({"test", "tests", "spec", "specs"})
        or basename.startswith("test_")
        or basename.endswith(("_test.py", ".test.js", ".test.jsx", ".test.ts", ".test.tsx"))
        or basename.endswith((".spec.js", ".spec.ts", ".spec.tsx", "_test.go"))
    )


def _is_test_config(path: str) -> bool:
    basename = PurePosixPath(path).name.lower()
    return basename in TEST_CONFIG_NAMES or any(
        fnmatch.fnmatchcase(basename, pattern) for pattern in TEST_CONFIG_PATTERNS
    )


def _is_build_config(path: str) -> bool:
    basename = PurePosixPath(path).name.lower()
    return basename in BUILD_FILE_NAMES or any(
        fnmatch.fnmatchcase(basename, pattern) for pattern in BUILD_FILE_PATTERNS
    )


def _read_text_files(
    root: Path,
    files: list[FileRecord],
) -> tuple[dict[str, str], ContentScanInfo, set[str]]:
    text_candidates = [record for record in files if _is_text_candidate(record)]
    text_candidates.sort(key=lambda record: (_content_priority(record.path), record.path))

    results: dict[str, str] = {}
    bytes_read = 0
    skipped = 0
    unreadable_or_binary = 0
    binary_paths: set[str] = set()

    for record in text_candidates:
        file_size = record.size_bytes
        if (
            record.kind != "file"
            or file_size is None
            or file_size > MAX_CONTENT_FILE_BYTES
            or bytes_read + file_size > MAX_CONTENT_TOTAL_BYTES
        ):
            skipped += 1
            continue

        try:
            with (root / record.path).open("rb") as source_file:
                raw_content = source_file.read(MAX_CONTENT_FILE_BYTES + 1)
        except OSError:
            unreadable_or_binary += 1
            continue

        bytes_read += len(raw_content)
        if len(raw_content) > MAX_CONTENT_FILE_BYTES:
            unreadable_or_binary += 1
            continue
        if b"\0" in raw_content[:8192]:
            unreadable_or_binary += 1
            binary_paths.add(record.path)
            continue
        try:
            results[record.path] = raw_content.decode("utf-8")
        except UnicodeDecodeError:
            unreadable_or_binary += 1
            binary_paths.add(record.path)

    return (
        results,
        ContentScanInfo(
            bytes_read=bytes_read,
            files_skipped_by_limits=skipped,
            files_unreadable_or_binary=unreadable_or_binary,
            max_file_bytes=MAX_CONTENT_FILE_BYTES,
            max_total_bytes=MAX_CONTENT_TOTAL_BYTES,
        ),
        binary_paths,
    )


def _is_text_candidate(record: FileRecord) -> bool:
    if record.kind != "file":
        return False
    parsed = PurePosixPath(record.path)
    basename = parsed.name.lower()
    if parsed.suffix.lower() in BINARY_SUFFIXES:
        return False
    return (
        parsed.suffix.lower() in TEXT_SUFFIXES
        or basename in TEXT_SPECIAL_NAMES
        or basename.startswith(".env")
        or not parsed.suffix
    )


def _content_priority(path: str) -> int:
    basename = PurePosixPath(path).name.lower()
    if basename.startswith("readme"):
        return 0
    if basename in TEXT_SPECIAL_NAMES or basename.startswith(".env"):
        return 1
    if PurePosixPath(path).suffix.lower() in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return 2
    return 3


def _readme_signals(path: str, content: str | None) -> ReadmeSignals:
    if content is None:
        return ReadmeSignals(path=path)

    headings = re.findall(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", content)
    lines = content.splitlines()
    for line_index in range(len(lines) - 1):
        title = lines[line_index].strip()
        underline = lines[line_index + 1].strip()
        if title and len(underline) >= 3 and len(set(underline)) == 1:
            if underline[0] in "=-~^\"`:#*+":
                headings.append(title)
    sections: set[str] = set()
    for heading in headings:
        normalized = heading.strip().lower()
        for section, terms in README_SECTION_TERMS.items():
            if any(term in normalized for term in terms):
                sections.add(section)

    lines = content.splitlines()
    for line_index in range(len(lines) - 1):
        title = lines[line_index].strip()
        underline = lines[line_index + 1].strip()
        if title and len(underline) >= 3 and len(set(underline)) == 1:
            if underline[0] in "=-~^\"`:#*+":
                headings.append(title)
                normalized = title.lower()
                for section, terms in README_SECTION_TERMS.items():
                    if any(term in normalized for term in terms):
                        sections.add(section)

    return ReadmeSignals(
        path=path,
        line_count=len(content.splitlines()),
        heading_count=len(headings),
        sections_present=sorted(sections),
        content_analyzed=True,
    )


def _triage_readme(path: str, content: str | None) -> TriageReadme:
    if content is None:
        return TriageReadme(path=path)

    redacted_content, redaction_count = _redact_triage_text(content)
    truncated = len(redacted_content) > MAX_TRIAGE_README_CHARS
    if truncated:
        redacted_content = redacted_content[:MAX_TRIAGE_README_CHARS]
    return TriageReadme(
        path=path,
        text=redacted_content,
        truncated=truncated,
        redaction_count=redaction_count,
    )


def _redact_triage_text(content: str) -> tuple[str, int]:
    redacted, redaction_count = PRIVATE_KEY_BLOCK_PATTERN.subn(
        "[REDACTED_SECRET]", content
    )
    for _, pattern, value_group in SECRET_PATTERNS:
        if value_group is None:
            redacted, replacements = pattern.subn("[REDACTED_SECRET]", redacted)
        else:
            def replace_secret(match: re.Match[str]) -> str:
                value_start, value_end = match.span(value_group)
                return (
                    match.group(0)[: value_start - match.start()]
                    + "[REDACTED_SECRET]"
                    + match.group(0)[value_end - match.start() :]
                )

            redacted, replacements = pattern.subn(replace_secret, redacted)
        redaction_count += replacements

    for _, pattern in LOCAL_PATH_PATTERNS:
        redacted, replacements = pattern.subn("[REDACTED_LOCAL_PATH]", redacted)
        redaction_count += replacements
    return redacted, redaction_count


def _package_scripts(file_text: dict[str, str]) -> list[PackageScripts]:
    results: list[PackageScripts] = []
    for path, content in file_text.items():
        basename = PurePosixPath(path).name.lower()
        try:
            if basename == "package.json":
                document = json.loads(content)
                scripts = document.get("scripts", {})
            elif basename == "pyproject.toml":
                document = tomllib.loads(content)
                scripts = document.get("project", {}).get("scripts", {})
            else:
                continue
        except (json.JSONDecodeError, tomllib.TOMLDecodeError, AttributeError):
            continue
        if isinstance(scripts, dict) and scripts:
            results.append(
                PackageScripts(path=path, script_names=sorted(str(name) for name in scripts))
            )
    return sorted(results, key=lambda item: item.path)


def _candidate_entry_points(
    files: list[FileRecord],
    package_scripts: list[PackageScripts],
) -> list[CandidateEntryPoint]:
    candidates: dict[tuple[str, str], CandidateEntryPoint] = {}
    for record in files:
        basename = PurePosixPath(record.path).name.lower()
        if basename in SOURCE_ENTRYPOINT_NAMES:
            candidates[(record.path, "conventional entry-point filename")] = CandidateEntryPoint(
                path=record.path,
                reason="conventional entry-point filename",
            )
    for scripts in package_scripts:
        for name in scripts.script_names:
            if name.lower() in {"start", "serve", "run", "dev"}:
                reason = f"declares package script named {name}"
                candidates[(scripts.path, reason)] = CandidateEntryPoint(
                    path=scripts.path,
                    reason=reason,
                )
    return sorted(candidates.values(), key=lambda item: (item.path, item.reason))


def _python_import_evidence(
    files: list[FileRecord],
    file_text: dict[str, str],
) -> list[PythonImportEvidence]:
    local_roots = _local_python_roots(files)
    imports: set[tuple[str, str, str]] = set()

    for record in files:
        suffix = PurePosixPath(record.path).suffix.lower()
        if record.kind != "file" or suffix not in {".py", ".ipynb"}:
            continue
        content = file_text.get(record.path)
        if content is None:
            continue
        for source in _python_source_units(content, suffix):
            try:
                syntax_tree = ast.parse(source, filename=record.path)
            except (SyntaxError, ValueError):
                continue

            for node in ast.walk(syntax_tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        classification = _classify_import(alias.name, local_roots)
                        imports.add((record.path, alias.name, classification))
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if node.level:
                        module_name = "." * node.level + module_name
                        classification = "local"
                    else:
                        classification = _classify_import(module_name, local_roots)
                    if module_name:
                        imports.add((record.path, module_name, classification))

    return [
        PythonImportEvidence(path=path, module=module, classification=classification)
        for path, module, classification in sorted(imports)
    ]


def _python_source_units(content: str, suffix: str) -> list[str]:
    if suffix == ".py":
        return [content]
    try:
        notebook = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(notebook, dict):
        return []
    units: list[str] = []
    for cell in notebook.get("cells", []):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = cell.get("source", "")
        if isinstance(source, list):
            units.append("".join(part for part in source if isinstance(part, str)))
        elif isinstance(source, str):
            units.append(source)
    return units


def _local_python_roots(files: list[FileRecord]) -> set[str]:
    roots: set[str] = set()
    source_roots = {"src", "lib", "python"}
    for record in files:
        if record.kind != "file" or PurePosixPath(record.path).suffix.lower() != ".py":
            continue
        parts = list(PurePosixPath(record.path).parts)
        if not parts:
            continue
        if parts[0].lower() in source_roots:
            parts = parts[1:]
        if not parts:
            continue
        top_level = parts[0] if parts[0] != "__init__.py" else ""
        if top_level.endswith(".py"):
            top_level = top_level[:-3]
        if top_level.isidentifier():
            roots.add(top_level)
    return roots


def _classify_import(module: str, local_roots: set[str]) -> str:
    root_module = module.split(".", maxsplit=1)[0]
    if root_module in sys.stdlib_module_names:
        return "standard_library"
    if root_module in local_roots:
        return "local"
    return "probable_external"


def _risk_indicators(
    file_text: dict[str, str],
) -> tuple[list[RiskIndicator], list[RiskIndicator]]:
    secret_risks: set[tuple[str, int, str]] = set()
    local_path_risks: set[tuple[str, int, str]] = set()

    for path, content in file_text.items():
        for line_number, line in enumerate(content.splitlines(), start=1):
            for rule_id, pattern, value_group in SECRET_PATTERNS:
                for match in pattern.finditer(line):
                    if value_group is not None:
                        candidate = match.group(value_group).strip("\"'").lower()
                        if candidate in PLACEHOLDER_VALUES or candidate.startswith(
                            ("your_", "example_", "replace_")
                        ):
                            continue
                    secret_risks.add((path, line_number, rule_id))
            for rule_id, pattern in LOCAL_PATH_PATTERNS:
                if pattern.search(line):
                    local_path_risks.add((path, line_number, rule_id))

    return (
        [
            RiskIndicator(path=path, line_number=line, rule_id=rule)
            for path, line, rule in sorted(secret_risks)
        ],
        [
            RiskIndicator(path=path, line_number=line, rule_id=rule)
            for path, line, rule in sorted(local_path_risks)
        ],
    )


def _artifact_files(
    files: list[FileRecord],
    detected_binary_paths: set[str],
) -> list[ArtifactFile]:
    results: list[ArtifactFile] = []
    for record in files:
        if record.kind != "file" or record.size_bytes is None:
            continue
        suffix = PurePosixPath(record.path).suffix.lower()
        basename = PurePosixPath(record.path).name.lower()
        categories: set[str] = set()
        if suffix in DATA_SUFFIXES:
            categories.add("data")
        if suffix in MODEL_SUFFIXES or "model" in basename:
            categories.add("model_candidate")
        if suffix == ".ckpt" or "checkpoint" in basename:
            categories.add("checkpoint_candidate")
        if suffix in BINARY_SUFFIXES or record.path in detected_binary_paths:
            categories.add("binary")
        if record.size_bytes >= LARGE_FILE_BYTES:
            categories.add("large")
        if categories:
            results.append(
                ArtifactFile(
                    path=record.path,
                    size_bytes=record.size_bytes,
                    categories=sorted(categories),
                )
            )
    return results


def _tracked_junk_reason(path: str) -> str | None:
    parsed = PurePosixPath(path)
    parts = {part.lower() for part in parsed.parts}
    basename = parsed.name.lower()
    if basename in {".ds_store", "thumbs.db"}:
        return "disposable_metadata"
    if (
        basename.endswith((".pyc", ".pyo", ".swp", ".swo", "~"))
        or parts.intersection(
            {
                "__pycache__",
                ".ipynb_checkpoints",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".venv",
                "venv",
                "node_modules",
                ".tox",
                ".nox",
                ".gradle",
                ".next",
                ".parcel-cache",
                ".turbo",
                ".vite",
                "build",
                "coverage",
                "dist",
                "target",
            }
        )
    ):
        return "generated_or_environment_path"
    return None


def _hygiene_findings(
    files: list[FileRecord],
    tracked_paths: list[str],
    tracked_junk_paths: list[str],
    is_git_repository: bool,
) -> list[HygieneFinding]:
    findings: list[HygieneFinding] = []
    if is_git_repository and not any(record.path == ".gitignore" for record in files):
        findings.append(HygieneFinding(kind="gitignore_not_present"))
    findings.extend(
        HygieneFinding(kind="tracked_junk_candidate", path=path)
        for path in tracked_junk_paths
    )
    for path in tracked_paths:
        basename = PurePosixPath(path).name.lower()
        if basename in {".env", "credentials.json", "id_rsa", "id_ed25519"} or basename.endswith(
            (".pem", ".key")
        ):
            findings.append(
                HygieneFinding(kind="tracked_sensitive_filename_candidate", path=path)
            )
    return sorted(
        findings,
        key=lambda finding: (finding.kind, finding.path or ""),
    )

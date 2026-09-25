from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PortfolioClassification(StrEnum):
    A = "A"
    B = "B"
    C = "C"


class GitStatusCounts(BaseModel):
    staged: int = 0
    modified: int = 0
    deleted: int = 0
    renamed: int = 0
    conflicted: int = 0
    untracked: int = 0


class GitIdentity(BaseModel):
    root_path: str
    branch: str | None = None
    upstream: str | None = None
    ahead_count: int | None = None
    behind_count: int | None = None
    remotes: list[str] = Field(default_factory=list)
    tracked_file_count: int | None = None
    untracked_entry_count: int | None = None
    is_dirty: bool | None = None
    status_counts: GitStatusCounts = Field(default_factory=GitStatusCounts)
    object_store_bytes: int | None = None
    fork_relationship_known: bool = False


class RepositoryIdentity(BaseModel):
    path: str
    directory_name: str
    git: GitIdentity | None = None


class FileRecord(BaseModel):
    path: str
    size_bytes: int | None
    kind: Literal["file", "symlink"] = "file"
    language: str | None = None


class DependencyFile(BaseModel):
    path: str
    ecosystem: str
    kind: str


class SpecialFileSignal(BaseModel):
    path: str
    categories: list[str] = Field(default_factory=list)


class ReadmeSignals(BaseModel):
    path: str
    line_count: int | None = None
    heading_count: int | None = None
    sections_present: list[str] = Field(default_factory=list)
    content_analyzed: bool = False


class TriageReadme(BaseModel):
    path: str
    text: str | None = None
    truncated: bool = False
    redaction_count: int = 0


class PackageScripts(BaseModel):
    path: str
    script_names: list[str] = Field(default_factory=list)


class PythonImportEvidence(BaseModel):
    path: str
    module: str
    classification: Literal["standard_library", "local", "probable_external"]


class CandidateEntryPoint(BaseModel):
    path: str
    reason: str


class ArtifactFile(BaseModel):
    path: str
    size_bytes: int
    categories: list[str] = Field(default_factory=list)


class RiskIndicator(BaseModel):
    path: str
    line_number: int
    rule_id: str


class HygieneFinding(BaseModel):
    kind: str
    path: str | None = None


class ContentScanInfo(BaseModel):
    bytes_read: int = 0
    files_skipped_by_limits: int = 0
    files_unreadable_or_binary: int = 0
    max_file_bytes: int = 0
    max_total_bytes: int = 0


class RepositoryEvidence(BaseModel):
    ecosystems_detected: list[str] = Field(default_factory=list)
    dependency_files: list[DependencyFile] = Field(default_factory=list)
    special_files: list[SpecialFileSignal] = Field(default_factory=list)
    readme_signals: list[ReadmeSignals] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    test_config_files: list[str] = Field(default_factory=list)
    build_config_files: list[str] = Field(default_factory=list)
    package_scripts: list[PackageScripts] = Field(default_factory=list)
    candidate_entry_points: list[CandidateEntryPoint] = Field(default_factory=list)
    artifact_files: list[ArtifactFile] = Field(default_factory=list)
    python_imports: list[PythonImportEvidence] = Field(default_factory=list)
    secret_risks: list[RiskIndicator] = Field(default_factory=list)
    local_path_risks: list[RiskIndicator] = Field(default_factory=list)
    tracked_junk_paths: list[str] = Field(default_factory=list)
    disposable_paths: list[str] = Field(default_factory=list)
    hygiene_findings: list[HygieneFinding] = Field(default_factory=list)
    gitignore_present: bool = False


class RepositoryAnalysis(BaseModel):
    evidence: RepositoryEvidence
    content_scan: ContentScanInfo = Field(default_factory=ContentScanInfo)
    triage_readmes: list[TriageReadme] = Field(default_factory=list)


class RepositoryProfile(BaseModel):
    identity: RepositoryIdentity
    files: list[FileRecord] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    ignored_directories: list[str] = Field(default_factory=list)
    language_counts: dict[str, int] = Field(default_factory=dict)
    evidence: RepositoryEvidence = Field(default_factory=RepositoryEvidence)
    python_import_reference_version: str | None = None
    total_file_bytes: int = 0
    approximate_repository_size_bytes: int = 0
    content_scan: ContentScanInfo = Field(default_factory=ContentScanInfo)
    triage_readmes: list[TriageReadme] = Field(default_factory=list)


class TriageGitContext(BaseModel):
    branch: str | None = None
    upstream: str | None = None
    remotes: list[str] = Field(default_factory=list)
    is_dirty: bool | None = None
    status_counts: GitStatusCounts | None = None
    scan_is_git_root: bool = False


class TriageOutline(BaseModel):
    directory_name: str
    git: TriageGitContext | None = None
    directories: list[str] = Field(default_factory=list)
    ignored_directories: list[str] = Field(default_factory=list)
    files: list[FileRecord] = Field(default_factory=list)
    dependency_files: list[DependencyFile] = Field(default_factory=list)
    special_files: list[SpecialFileSignal] = Field(default_factory=list)
    readmes: list[TriageReadme] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    test_config_files: list[str] = Field(default_factory=list)
    build_config_files: list[str] = Field(default_factory=list)
    package_scripts: list[PackageScripts] = Field(default_factory=list)
    candidate_entry_points: list[CandidateEntryPoint] = Field(default_factory=list)
    python_imports: list[PythonImportEvidence] = Field(default_factory=list)
    artifact_files: list[ArtifactFile] = Field(default_factory=list)
    secret_risks: list[RiskIndicator] = Field(default_factory=list)
    local_path_risks: list[RiskIndicator] = Field(default_factory=list)
    hygiene_findings: list[HygieneFinding] = Field(default_factory=list)
    content_scan: ContentScanInfo = Field(default_factory=ContentScanInfo)
    outline_truncated: bool = False
    omitted_item_counts: dict[str, int] = Field(default_factory=dict)
    serialized_bytes: int = 0
    max_serialized_bytes: int = 0


class TriageSummary(BaseModel):
    schema_version: str = "r4-triage-v1"
    directory_name: str
    is_git_repository: bool
    git_branch: str | None = None
    git_dirty: bool | None = None
    git_upstream_configured: bool = False
    git_remote_count: int = 0
    git_tracked_file_count: int | None = None
    git_untracked_entry_count: int | None = None
    git_status_counts: GitStatusCounts | None = None
    file_count: int
    approximate_repository_size_bytes: int
    language_counts: dict[str, int] = Field(default_factory=dict)
    top_level_directory_count: int = 0
    ecosystems_detected: list[str] = Field(default_factory=list)
    python_import_class_counts: dict[str, int] = Field(default_factory=dict)
    dependency_file_count: int = 0
    readme_count: int = 0
    readme_sections: dict[str, int] = Field(default_factory=dict)
    test_file_count: int = 0
    test_config_count: int = 0
    build_config_count: int = 0
    package_script_count: int = 0
    candidate_entry_point_count: int = 0
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    secret_risk_count: int = 0
    local_path_risk_count: int = 0
    tracked_junk_count: int = 0
    ignored_directory_count: int = 0
    content_analysis_limited: bool = False
    repository_outline: TriageOutline


class ChoiceJudgment(BaseModel):
    choice: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)


class TriageClarifications(BaseModel):
    authorship: float
    academic_context: float
    repository_boundaries: float
    data_asset_rights: float
    intended_execution: float


class TriageJudgments(BaseModel):
    project_extent: ChoiceJudgment
    repository_completeness: ChoiceJudgment
    cleanup_effort: ChoiceJudgment
    repository_composition: ChoiceJudgment
    technical_domain: ChoiceJudgment
    organization_treatment: ChoiceJudgment
    readme_expectation: ChoiceJudgment
    reproducibility_expectation: ChoiceJudgment
    clarifications: TriageClarifications


class TriageUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class TriageResult(BaseModel):
    triage_summary: TriageSummary
    judgments: TriageJudgments
    provider_model: str
    usage: TriageUsage = Field(default_factory=TriageUsage)


class ScanResult(BaseModel):
    repository_profile: RepositoryProfile
    triage_summary: TriageSummary

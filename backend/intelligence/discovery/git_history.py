"""
Git History Ingestion — Phase 1 Temporal Intelligence foundation.

Extracts commits, branches, tags, and file-change history from a
local git repository. Feeds the Temporal Intelligence subsystem so
the platform can reason about what changed, when, and why.

Does NOT contact the GitHub API here — that lives in a separate
GitHubAdapter so the git provider is swappable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import structlog
from git import InvalidGitRepositoryError, Repo
from git.objects.commit import Commit
from pydantic import BaseModel

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class FileChange(BaseModel):
    path: str
    change_type: str  # "A" added | "M" modified | "D" deleted | "R" renamed
    insertions: int = 0
    deletions: int = 0
    old_path: str | None = None  # for renames


class CommitRecord(BaseModel):
    sha: str
    short_sha: str
    author_name: str
    author_email: str
    authored_at: datetime
    committed_at: datetime
    message: str
    summary: str  # first line only
    parents: list[str]
    changed_files: list[FileChange]
    total_insertions: int
    total_deletions: int
    branch_names: list[str] = []
    tags: list[str] = []


class BranchRecord(BaseModel):
    name: str
    is_remote: bool
    head_sha: str
    is_active: bool


class TagRecord(BaseModel):
    name: str
    sha: str
    tagged_at: datetime | None
    message: str | None


class GitHistoryResult(BaseModel):
    root: str
    default_branch: str | None
    active_branch: str | None
    commits: list[CommitRecord]
    branches: list[BranchRecord]
    tags: list[TagRecord]
    total_commits: int


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _parse_commit(commit: Commit, sha_to_branches: dict[str, list[str]], sha_to_tags: dict[str, list[str]]) -> CommitRecord:
    changed_files: list[FileChange] = []
    total_ins = 0
    total_del = 0

    try:
        if commit.parents:
            diffs = commit.parents[0].diff(commit)
            stats = commit.stats.files
            for diff in diffs:
                path = diff.b_path or diff.a_path
                file_stats = stats.get(path, {})
                ins = file_stats.get("insertions", 0)
                dels = file_stats.get("deletions", 0)
                total_ins += ins
                total_del += dels
                changed_files.append(
                    FileChange(
                        path=path,
                        change_type=diff.change_type,
                        insertions=ins,
                        deletions=dels,
                        old_path=diff.a_path if diff.change_type == "R" else None,
                    )
                )
        else:
            # Root commit — every file is "added"
            for path, file_stats in commit.stats.files.items():
                ins = file_stats.get("insertions", 0)
                dels = file_stats.get("deletions", 0)
                total_ins += ins
                total_del += dels
                changed_files.append(FileChange(path=path, change_type="A", insertions=ins, deletions=dels))
    except Exception as exc:
        log.warning("git_diff_failed", sha=commit.hexsha[:7], error=str(exc))

    sha = commit.hexsha
    authored_dt = datetime.fromtimestamp(commit.authored_date, tz=timezone.utc)
    committed_dt = datetime.fromtimestamp(commit.committed_date, tz=timezone.utc)
    message = commit.message.strip() if commit.message else ""

    return CommitRecord(
        sha=sha,
        short_sha=sha[:7],
        author_name=str(commit.author.name or ""),
        author_email=str(commit.author.email or ""),
        authored_at=authored_dt,
        committed_at=committed_dt,
        message=message,
        summary=message.splitlines()[0] if message else "",
        parents=[p.hexsha for p in commit.parents],
        changed_files=changed_files,
        total_insertions=total_ins,
        total_deletions=total_del,
        branch_names=sha_to_branches.get(sha, []),
        tags=sha_to_tags.get(sha, []),
    )


def _iter_commits(repo: Repo, max_commits: int) -> Iterator[Commit]:
    try:
        yield from repo.iter_commits(max_count=max_commits)
    except Exception as exc:
        log.error("git_iter_commits_failed", error=str(exc))


def ingest_git_history(root: Path, max_commits: int = 500) -> GitHistoryResult:
    """
    Ingest the git history of a repository.

    Args:
        root: Path to the repository root.
        max_commits: Maximum number of commits to ingest (most recent first).

    Returns:
        GitHistoryResult with commits, branches, and tags.
    """
    try:
        repo = Repo(root, search_parent_directories=True)
    except InvalidGitRepositoryError:
        log.warning("not_a_git_repo", path=str(root))
        return GitHistoryResult(
            root=str(root),
            default_branch=None,
            active_branch=None,
            commits=[],
            branches=[],
            tags=[],
            total_commits=0,
        )

    # Build SHA → branch name index
    sha_to_branches: dict[str, list[str]] = {}
    branches: list[BranchRecord] = []
    try:
        active_branch_name = repo.active_branch.name
    except TypeError:
        active_branch_name = None

    for ref in repo.references:
        try:
            sha = ref.commit.hexsha
            sha_to_branches.setdefault(sha, []).append(ref.name)
            is_remote = ref.name.startswith("origin/") or "/" in ref.name
            branches.append(
                BranchRecord(
                    name=ref.name,
                    is_remote=is_remote,
                    head_sha=sha,
                    is_active=(ref.name == active_branch_name),
                )
            )
        except Exception:
            pass

    # Build SHA → tag index
    sha_to_tags: dict[str, list[str]] = {}
    tags: list[TagRecord] = []
    for tag in repo.tags:
        try:
            sha = tag.commit.hexsha
            sha_to_tags.setdefault(sha, []).append(tag.name)
            tagged_at: datetime | None = None
            tag_message: str | None = None
            if hasattr(tag.tag, "tagged_date"):
                tagged_at = datetime.fromtimestamp(tag.tag.tagged_date, tz=timezone.utc)
                tag_message = str(tag.tag.message).strip() if tag.tag.message else None
            tags.append(TagRecord(name=tag.name, sha=sha, tagged_at=tagged_at, message=tag_message))
        except Exception:
            pass

    # Try to determine the default branch
    default_branch: str | None = None
    try:
        default_branch = repo.remotes.origin.refs.HEAD.reference.remote_head
    except Exception:
        for candidate in ("main", "master"):
            if any(b.name == candidate for b in branches):
                default_branch = candidate
                break

    # Ingest commits
    commit_records: list[CommitRecord] = []
    for commit in _iter_commits(repo, max_commits):
        commit_records.append(_parse_commit(commit, sha_to_branches, sha_to_tags))

    log.info(
        "git_history_ingested",
        root=str(root),
        commits=len(commit_records),
        branches=len(branches),
        tags=len(tags),
    )

    return GitHistoryResult(
        root=str(root),
        default_branch=default_branch,
        active_branch=active_branch_name,
        commits=commit_records,
        branches=branches,
        tags=tags,
        total_commits=len(commit_records),
    )


def get_changed_files_since(root: Path, since_sha: str) -> list[str]:
    """
    Return all files changed in commits after since_sha (exclusive).
    Useful for targeted verification after a new commit.
    """
    try:
        repo = Repo(root, search_parent_directories=True)
        changed: set[str] = set()
        for commit in repo.iter_commits():
            if commit.hexsha == since_sha:
                break
            for diff in commit.diff(commit.parents[0] if commit.parents else None):
                if diff.b_path:
                    changed.add(diff.b_path)
                if diff.a_path:
                    changed.add(diff.a_path)
        return sorted(changed)
    except Exception as exc:
        log.error("get_changed_files_failed", since=since_sha, error=str(exc))
        return []

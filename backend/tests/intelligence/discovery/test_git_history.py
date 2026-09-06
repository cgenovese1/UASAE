"""Tests for git history ingestion."""

from pathlib import Path

import pytest
from git import Repo

from backend.intelligence.discovery.git_history import ingest_git_history


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with two commits."""
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test User").release()
    repo.config_writer().set_value("user", "email", "test@test.com").release()

    f = tmp_path / "README.md"
    f.write_text("# Hello\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")

    f.write_text("# Hello World\n")
    repo.index.add(["README.md"])
    repo.index.commit("update readme")

    return tmp_path


class TestGitHistoryIngestion:
    def test_ingest_returns_commits(self, git_repo: Path) -> None:
        result = ingest_git_history(git_repo)
        assert result.total_commits == 2

    def test_commit_has_required_fields(self, git_repo: Path) -> None:
        result = ingest_git_history(git_repo)
        commit = result.commits[0]
        assert commit.sha
        assert commit.short_sha
        assert commit.author_name == "Test User"
        assert commit.summary

    def test_changed_files_in_second_commit(self, git_repo: Path) -> None:
        result = ingest_git_history(git_repo)
        # Most recent commit first
        latest = result.commits[0]
        assert any(cf.path == "README.md" for cf in latest.changed_files)

    def test_non_repo_returns_empty(self, tmp_path: Path) -> None:
        result = ingest_git_history(tmp_path)
        assert result.total_commits == 0
        assert result.commits == []

    def test_max_commits_limit(self, git_repo: Path) -> None:
        result = ingest_git_history(git_repo, max_commits=1)
        assert result.total_commits == 1

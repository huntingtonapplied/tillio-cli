"""Tests for git module — uses real temp git repos."""

import subprocess
import pytest

from tillio_cli.git import (
    run_git,
    get_repo_url,
    get_branch,
    parse_commits,
    build_submission,
    _get_diff_stats,
)


class TestRunGit:
    def test_runs_simple_command(self, git_repo):
        result = run_git(["rev-parse", "--is-inside-work-tree"], cwd=str(git_repo))
        assert result == "true"

    def test_raises_on_bad_command(self, tmp_path):
        with pytest.raises(RuntimeError, match="failed"):
            run_git(["log"], cwd=str(tmp_path))


class TestGetRepoUrl:
    def test_returns_normalized_https_url(self, git_repo):
        url = get_repo_url(cwd=str(git_repo))
        assert url == "github.com/testuser/testrepo"

    def test_normalizes_ssh_url(self, git_repo):
        subprocess.run(
            ["git", "remote", "set-url", "origin", "git@github.com:org/project.git"],
            cwd=git_repo, capture_output=True,
        )
        url = get_repo_url(cwd=str(git_repo))
        assert url == "github.com/org/project"

    def test_returns_empty_when_no_remote(self, tmp_path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        url = get_repo_url(cwd=str(tmp_path))
        assert url == ""


class TestGetBranch:
    def test_returns_branch_name(self, git_repo):
        branch = get_branch(cwd=str(git_repo))
        assert branch in ("main", "master")


class TestParseCommits:
    def test_parses_single_commit(self, git_repo):
        commits = parse_commits("HEAD", cwd=str(git_repo))
        assert len(commits) == 1
        assert commits[0]["message"] == "Initial commit"
        assert commits[0]["author_email"] == "test@example.com"
        assert commits[0]["author_name"] == "Test User"
        assert len(commits[0]["sha"]) == 40

    def test_parses_multiple_commits(self, git_repo):
        # Add a second commit
        (git_repo / "second.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Second commit"], cwd=git_repo, capture_output=True)

        commits = parse_commits("HEAD~2..HEAD", cwd=str(git_repo))
        assert len(commits) == 2
        assert commits[0]["message"] == "Initial commit"
        assert commits[1]["message"] == "Second commit"

    def test_returns_empty_for_empty_range(self, git_repo):
        commits = parse_commits("HEAD..HEAD", cwd=str(git_repo))
        assert commits == []

    def test_includes_diff_stats(self, git_repo):
        commits = parse_commits("HEAD", cwd=str(git_repo))
        c = commits[0]
        assert c["additions"] >= 1
        assert isinstance(c["deletions"], int)
        assert "hello.py" in c["files_changed"]


class TestGetDiffStats:
    def test_counts_additions(self, git_repo):
        sha = run_git(["rev-parse", "HEAD"], cwd=str(git_repo))
        additions, deletions, files = _get_diff_stats(sha, cwd=str(git_repo))
        assert additions >= 1
        assert deletions == 0
        assert "hello.py" in files


class TestBuildSubmission:
    def test_builds_full_payload(self, git_repo):
        payload = build_submission("HEAD", cwd=str(git_repo))
        assert payload["repository_url"] == "github.com/testuser/testrepo"
        assert payload["branch"] in ("main", "master")
        assert len(payload["commits"]) == 1
        assert payload["commits"][0]["message"] == "Initial commit"

"""Tests for CLI commands using Click's test runner."""

import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from tillio_cli.main import cli
from tillio_cli.api import AuthError, APIError, DuplicateError


class TestLoginCommand:
    def test_saves_key_and_verifies(self, runner, tmp_config):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [{"id": "p1"}, {"id": "p2"}]

        with patch("tillio_cli.commands.login.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["login", "--key", "my-api-key"])

        assert result.exit_code == 0
        assert "API key saved" in result.output
        assert "2 project(s) found" in result.output

    def test_warns_on_verification_failure(self, runner, tmp_config):
        with patch("tillio_cli.commands.login.TillioClient", side_effect=Exception("connection refused")):
            result = runner.invoke(cli, ["login", "--key", "bad-key"])

        assert result.exit_code == 0
        assert "API key saved" in result.output
        assert "verification failed" in result.output

    def test_saves_custom_url(self, runner, tmp_config):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = []

        with patch("tillio_cli.commands.login.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["login", "--key", "k", "--url", "http://localhost:8023"])

        assert result.exit_code == 0
        assert "http://localhost:8023" in result.output


class TestProjectsCommand:
    def test_lists_projects(self, runner, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["projects"])

        assert result.exit_code == 0
        assert "Test Project" in result.output
        assert "Another Project" in result.output

    def test_shows_empty_message(self, runner):
        client = MagicMock()
        client.list_projects.return_value = []
        with patch("tillio_cli.commands.projects.TillioClient", return_value=client):
            result = runner.invoke(cli, ["projects"])

        assert "No projects found" in result.output


class TestContributionsCommand:
    def test_lists_contributions(self, runner, mock_client):
        with patch("tillio_cli.commands.contributions.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["contributions"])

        assert result.exit_code == 0
        assert "Add login feature" in result.output
        assert "Approved" in result.output

    def test_shows_empty_message(self, runner):
        client = MagicMock()
        client.list_contributions.return_value = []
        with patch("tillio_cli.commands.contributions.TillioClient", return_value=client):
            result = runner.invoke(cli, ["contributions"])

        assert "No contributions found" in result.output


class TestEvalCommand:
    def test_requests_evaluation(self, runner, mock_client):
        # Streaming raises 404 -> falls back to polling -> fires async request
        mock_client.evaluate_stream.side_effect = APIError("404 Not Found", status_code=404)
        # Polling: contribution comes back completed after first poll
        mock_client.get.return_value = {
            "status": "APPROVED",
            "evaluation": {"status": "COMPLETED"},
            "actual_value": 42,
        }
        with patch("tillio_cli.commands.eval.TillioClient", return_value=mock_client), \
             patch("tillio_cli.commands.eval.POLL_INTERVAL", 0):
            result = runner.invoke(cli, ["eval", "contrib-123"])

        assert result.exit_code == 0
        mock_client.post.assert_called_with("/v1/contributions/contrib-123/evaluation/request")

    def test_shows_error_on_failure(self, runner, mock_client):
        mock_client.evaluate_stream.side_effect = APIError("Server error", status_code=500)
        with patch("tillio_cli.commands.eval.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["eval", "bad-id"])

        assert result.exit_code != 0


class TestSubmitCommand:
    def _submit_patches(self, mock_client, commits=None):
        """Common patches for submit tests."""
        if commits is None:
            commits = [{
                "sha": "abc123def456",
                "message": "Test commit",
                "author_name": "Test",
                "author_email": "test@example.com",
                "committed_at": "2026-01-01T00:00:00",
                "additions": 10,
                "deletions": 2,
                "files_changed": ["test.py"],
            }]
        return (
            patch("tillio_cli.commands.submit.TillioClient", return_value=mock_client),
            patch("tillio_cli.commands.submit.run_git", return_value="true"),
            patch("tillio_cli.commands.submit.get_repo_url", return_value="github.com/user/repo"),
            patch("tillio_cli.commands.submit.get_branch", return_value="main"),
            patch("tillio_cli.commands.submit.parse_commits", return_value=commits),
        )

    def test_submit_success(self, runner, mock_client):
        # Streaming submits and returns complete event
        mock_client.submit_commits_stream.return_value = iter([
            ("received", {"sha": "abc123de", "status": "created"}),
            ("complete", {"submitted": 1, "evaluated": 0, "duplicates": 0}),
        ])
        patches = self._submit_patches(mock_client)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = runner.invoke(cli, ["submit"])

        assert result.exit_code == 0
        assert "1 commit(s) submitted" in result.output

    def test_submit_no_commits(self, runner, mock_client):
        with patch("tillio_cli.commands.submit.run_git", return_value="true"), \
             patch("tillio_cli.commands.submit.get_repo_url", return_value="github.com/user/repo"), \
             patch("tillio_cli.commands.submit.get_branch", return_value="main"), \
             patch("tillio_cli.commands.submit.parse_commits", return_value=[]):
            result = runner.invoke(cli, ["submit"])

        assert "No commits found" in result.output

    def test_submit_not_git_repo(self, runner):
        with patch("tillio_cli.commands.submit.run_git", side_effect=RuntimeError("not a repo")):
            result = runner.invoke(cli, ["submit"])

        assert result.exit_code != 0
        assert "Not a git repository" in result.output

    def test_submit_duplicate(self, runner, mock_client):
        # Streaming returns duplicate status
        mock_client.submit_commits_stream.return_value = iter([
            ("received", {"sha": "abc123", "status": "duplicate"}),
            ("complete", {"submitted": 0, "evaluated": 0, "duplicates": 1}),
        ])
        patches = self._submit_patches(mock_client, commits=[{
            "sha": "abc123",
            "message": "Dup commit",
            "author_name": "Test",
            "author_email": "test@example.com",
            "committed_at": "2026-01-01T00:00:00",
            "additions": 1,
            "deletions": 0,
            "files_changed": ["x.py"],
        }])
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            result = runner.invoke(cli, ["submit"])

        assert "already submitted" in result.output.lower()

    def test_submit_no_remote_no_project_id(self, runner, mock_client):
        with patch("tillio_cli.commands.submit.TillioClient", return_value=mock_client), \
             patch("tillio_cli.commands.submit.run_git", return_value="true"), \
             patch("tillio_cli.commands.submit.get_repo_url", return_value=""), \
             patch("tillio_cli.commands.submit.get_branch", return_value="main"), \
             patch("tillio_cli.commands.submit.parse_commits", return_value=[{
                 "sha": "abc123",
                 "message": "commit",
                 "author_name": "Test",
                 "author_email": "t@e.com",
                 "committed_at": "2026-01-01T00:00:00",
                 "additions": 1,
                 "deletions": 0,
                 "files_changed": [],
             }]):
            result = runner.invoke(cli, ["submit"])

        assert result.exit_code != 0
        assert "No remote URL" in result.output


class TestStatusCommand:
    def test_shows_status(self, runner, mock_client):
        with patch("tillio_cli.commands.status.run_git", return_value="true"), \
             patch("tillio_cli.commands.status.get_repo_url", return_value="github.com/user/repo"), \
             patch("tillio_cli.commands.status.get_branch", return_value="main"), \
             patch("tillio_cli.commands.status.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["status"])

        assert result.exit_code == 0
        assert "github.com/user/repo" in result.output
        assert "Test Project" in result.output

    def test_status_not_linked(self, runner):
        client = MagicMock()
        client.lookup_project.return_value = None

        with patch("tillio_cli.commands.status.run_git", return_value="true"), \
             patch("tillio_cli.commands.status.get_repo_url", return_value="github.com/user/repo"), \
             patch("tillio_cli.commands.status.get_branch", return_value="main"), \
             patch("tillio_cli.commands.status.TillioClient", return_value=client):
            result = runner.invoke(cli, ["status"])

        assert "Not linked" in result.output


class TestJsonOutput:
    def test_projects_json(self, runner, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["--output", "json", "projects"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["name"] == "Test Project"

    def test_contributions_json(self, runner, mock_client):
        with patch("tillio_cli.commands.contributions.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["--output", "json", "contributions"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["title"] == "Add login feature"

    def test_status_json(self, runner, mock_client):
        with patch("tillio_cli.commands.status.run_git", return_value="true"), \
             patch("tillio_cli.commands.status.get_repo_url", return_value="github.com/user/repo"), \
             patch("tillio_cli.commands.status.get_branch", return_value="main"), \
             patch("tillio_cli.commands.status.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["-o", "json", "status"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert data["repository_url"] == "github.com/user/repo"
        assert data["project"]["name"] == "Test Project"

    def test_submit_json(self, runner, mock_client):
        # Streaming returns JSON events, last one is the complete summary
        mock_client.submit_commits_stream.return_value = iter([
            ("received", {"sha": "abc123de", "status": "created"}),
            ("complete", {"submitted": 1, "evaluated": 0, "duplicates": 0}),
        ])
        with patch("tillio_cli.commands.submit.TillioClient", return_value=mock_client), \
             patch("tillio_cli.commands.submit.run_git", return_value="true"), \
             patch("tillio_cli.commands.submit.get_repo_url", return_value="github.com/user/repo"), \
             patch("tillio_cli.commands.submit.get_branch", return_value="main"), \
             patch("tillio_cli.commands.submit.parse_commits", return_value=[{
                 "sha": "abc123def456",
                 "message": "Test commit",
                 "author_name": "Test",
                 "author_email": "test@example.com",
                 "committed_at": "2026-01-01T00:00:00",
                 "additions": 10,
                 "deletions": 2,
                 "files_changed": ["test.py"],
             }]):
            result = runner.invoke(cli, ["-o", "json", "submit"])

        assert result.exit_code == 0
        import json
        # Each event is pretty-printed JSON. Parse by using a decoder that
        # can consume multiple top-level objects.
        raw = result.output.strip()
        decoder = json.JSONDecoder()
        events = []
        idx = 0
        while idx < len(raw):
            if raw[idx] in ' \n\r\t':
                idx += 1
                continue
            obj, end = decoder.raw_decode(raw, idx)
            events.append(obj)
            idx = end
        assert len(events) >= 1
        last = events[-1]
        assert last.get("submitted") == 1 or last.get("event") == "complete"

    def test_eval_json(self, runner, mock_client):
        # Streaming raises 404 -> falls to polling -> fires --no-wait style
        mock_client.evaluate_stream.side_effect = APIError("404 Not Found", status_code=404)
        mock_client.post.return_value = {"status": "QUEUED", "taskId": "abc"}
        mock_client.get.return_value = {
            "status": "APPROVED",
            "evaluation": {"status": "COMPLETED"},
            "actual_value": 42,
        }
        with patch("tillio_cli.commands.eval.TillioClient", return_value=mock_client), \
             patch("tillio_cli.commands.eval.POLL_INTERVAL", 0):
            result = runner.invoke(cli, ["-o", "json", "eval", "contrib-123"])

        assert result.exit_code == 0
        import json
        data = json.loads(result.output)
        assert data["status"] == "APPROVED"


class TestVersionFlag:
    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "tillio" in result.output


class TestVerboseFlag:
    def test_verbose_accepted(self, runner, tmp_config, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["--verbose", "projects"])
            assert result.exit_code == 0

    def test_debug_accepted(self, runner, tmp_config, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["--debug", "projects"])
            assert result.exit_code == 0


class TestCIMode:
    def test_ci_flag_accepted(self, runner, tmp_config, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["--ci", "projects"])
            assert result.exit_code == 0

    def test_ci_auto_detected_from_env(self, runner, tmp_config, mock_client):
        with patch("tillio_cli.commands.projects.TillioClient", return_value=mock_client):
            result = runner.invoke(cli, ["projects"], env={"CI": "true"})
            assert result.exit_code == 0

    def test_ci_login_requires_key(self, runner, tmp_config):
        result = runner.invoke(cli, ["--ci", "login"])
        assert result.exit_code != 0
        assert "--key is required" in result.output

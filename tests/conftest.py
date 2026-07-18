"""Shared fixtures for CLI tests."""

import os
import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def tmp_config(tmp_path):
    """Redirect config to a temp directory so tests don't touch ~/.tillio."""
    config_dir = tmp_path / ".tillio"
    config_dir.mkdir()
    config_file = config_dir / "config.yaml"

    with patch("tillio_cli.config.CONFIG_DIR", config_dir), \
         patch("tillio_cli.config.CONFIG_FILE", config_file):
        yield config_file


@pytest.fixture
def mock_client():
    """A mocked TillioClient that doesn't make real HTTP calls."""
    client = MagicMock()
    client.api_key = "test-key-123"
    client.api_url = "http://localhost:8023"
    client.list_projects.return_value = [
        {"id": "proj-1", "name": "Test Project", "status": "active"},
        {"id": "proj-2", "name": "Another Project", "status": "active"},
    ]
    client.list_contributions.return_value = [
        {
            "title": "Add login feature",
            "status": "APPROVED",
            "unitsAssigned": 5.0,
            "confidenceScore": 0.92,
        },
        {
            "title": "Fix auth bug",
            "status": "PENDING_REVIEW",
            "unitsAssigned": None,
            "confidenceScore": None,
        },
    ]
    client.lookup_project.return_value = {
        "id": "proj-1",
        "name": "Test Project",
        "status": "active",
    }
    client.submit_commits.return_value = {
        "submitted": 1,
        "duplicates": 0,
        "contributions": [
            {"sha": "abc123", "status": "PENDING_REVIEW"},
        ],
    }
    return client


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repo with a commit for testing."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True)

    # Create two commits so HEAD~1 is always valid
    (repo / "setup.py").write_text("# setup\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Root commit"], cwd=repo, capture_output=True)

    (repo / "hello.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True)

    # Add remote
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/testuser/testrepo.git"],
        cwd=repo, capture_output=True,
    )

    return repo

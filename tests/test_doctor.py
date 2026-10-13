"""Tests for the doctor command."""

import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from tillio_cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestDoctorCommand:
    def test_doctor_runs_without_error(self, runner, tmp_config):
        """Doctor command should run and display checks."""
        with patch("tillio_cli.commands.doctor.get_api_key", return_value=None), \
             patch("tillio_cli.commands.doctor.get_api_url", return_value="http://localhost:8000"):
            result = runner.invoke(cli, ["doctor"])
            assert result.exit_code == 0
            assert "Python >= 3.9" in result.output

    def test_doctor_json_output(self, runner, tmp_config):
        """Doctor should support JSON output."""
        with patch("tillio_cli.commands.doctor.get_api_key", return_value=None), \
             patch("tillio_cli.commands.doctor.get_api_url", return_value="http://localhost:8000"):
            result = runner.invoke(cli, ["-o", "json", "doctor"])
            assert result.exit_code == 0
            import json
            data = json.loads(result.output)
            assert "checks" in data
            assert "version" in data

    def test_doctor_detects_missing_api_key(self, runner, tmp_config):
        """Should report API key as not configured when missing."""
        with patch("tillio_cli.commands.doctor.get_api_key", return_value=None), \
             patch("tillio_cli.commands.doctor.get_api_url", return_value="http://localhost:8000"):
            result = runner.invoke(cli, ["doctor"])
            assert "API key configured" in result.output
            # Should show the cross mark for missing key
            assert "not set" in result.output


class TestConfigValidation:
    def test_validate_config_warns_on_unknown_key(self):
        from tillio_cli.config import validate_config
        warnings = validate_config({"api_key": "x", "typo_key": "y"})
        assert len(warnings) == 1
        assert "Unknown config key: 'typo_key'" in warnings[0]

    def test_validate_config_suggests_close_match(self):
        from tillio_cli.config import validate_config
        warnings = validate_config({"api_kye": "x"})
        assert "did you mean 'api_key'" in warnings[0]

    def test_validate_config_warns_on_bad_url(self):
        from tillio_cli.config import validate_config
        warnings = validate_config({"api_url": "ftp://example.com"})
        assert any("http://" in w for w in warnings)

    def test_validate_config_passes_for_valid_config(self):
        from tillio_cli.config import validate_config
        warnings = validate_config({"api_key": "k", "api_url": "https://api.tillio.ai"})
        assert warnings == []

    def test_validate_config_empty(self):
        from tillio_cli.config import validate_config
        warnings = validate_config({})
        assert warnings == []

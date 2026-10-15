"""Tests for the API client."""

import pytest
from unittest.mock import patch, MagicMock
import httpx

from tillio_cli.api import (
    TillioClient,
    AuthError,
    DuplicateError,
    APIError,
)


def _mock_response(status_code, json_data=None, text=""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    return resp


class TestTillioClient:
    def test_sets_auth_header(self):
        client = TillioClient(api_key="test-key", api_url="http://localhost")
        headers = client._headers()
        assert headers["Authorization"] == "ApiKey test-key"

    def test_raises_auth_error_without_key(self):
        with patch("tillio_cli.api.get_api_key", return_value=None), \
             patch("tillio_cli.api.get_api_url", return_value="http://localhost"):
            with pytest.raises(AuthError, match="Not authenticated"):
                TillioClient()


class TestHandleResponse:
    def setup_method(self):
        self.client = TillioClient(api_key="k", api_url="http://localhost")

    def test_returns_json_on_success(self):
        resp = _mock_response(200, {"data": "ok"})
        assert self.client._handle_response(resp) == {"data": "ok"}

    def test_raises_auth_error_on_401(self):
        resp = _mock_response(401)
        with pytest.raises(AuthError):
            self.client._handle_response(resp)

    def test_raises_duplicate_error_on_409(self):
        resp = _mock_response(409, {
            "detail": "Already submitted",
            "existing_contribution_id": "contrib-123",
        })
        with pytest.raises(DuplicateError) as exc_info:
            self.client._handle_response(resp)
        assert exc_info.value.existing_id == "contrib-123"

    def test_raises_api_error_on_500(self):
        resp = _mock_response(500, {"detail": "Internal error"})
        with pytest.raises(APIError, match="500"):
            self.client._handle_response(resp)

    def test_raises_api_error_on_400(self):
        resp = _mock_response(400, {"detail": "Bad request"})
        with pytest.raises(APIError, match="400"):
            self.client._handle_response(resp)

    def test_handles_non_json_error_body(self):
        resp = _mock_response(502, text="Bad Gateway")
        resp.json.side_effect = Exception("not json")
        with pytest.raises(APIError, match="Bad Gateway"):
            self.client._handle_response(resp)

    def test_403_subscription_gate_includes_checkout_hint(self):
        resp = _mock_response(403, {"detail": "Active subscription required. Subscribe or redeem an access code at /checkout."})
        with pytest.raises(APIError) as exc_info:
            self.client._handle_response(resp)
        msg = str(exc_info.value)
        assert "/checkout" in msg


class TestLookupProject:
    def test_returns_project_on_success(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        project_data = {"id": "proj-1", "name": "My Project"}
        with patch.object(client, "get", return_value=project_data):
            result = client.lookup_project("github.com/user/repo")
            assert result == project_data

    def test_returns_none_on_api_error(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        with patch.object(client, "get", side_effect=APIError("not found")):
            result = client.lookup_project("github.com/user/repo")
            assert result is None


class TestListMethods:
    def test_list_projects_returns_list(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        with patch.object(client, "get", return_value=[{"id": "p1"}]):
            result = client.list_projects()
            assert result == [{"id": "p1"}]

    def test_list_projects_returns_empty_on_error(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        with patch.object(client, "get", side_effect=APIError("fail")):
            assert client.list_projects() == []

    def test_list_contributions_extracts_data_field(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        with patch.object(client, "get", return_value={"data": [{"id": "c1"}]}):
            result = client.list_contributions()
            assert result == [{"id": "c1"}]

    def test_list_contributions_handles_list_response(self):
        client = TillioClient(api_key="k", api_url="http://localhost")
        with patch.object(client, "get", return_value=[{"id": "c1"}]):
            result = client.list_contributions()
            assert result == [{"id": "c1"}]

"""Tests for retry logic in the API client."""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import httpx

from tillio_cli.api import TillioClient, APIError


def _mock_response(status_code, json_data=None, text="", headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    # Mock the request attribute for logging
    resp.request = MagicMock()
    resp.request.url = "http://localhost/test"
    return resp


class TestRetryLogic:
    def setup_method(self):
        self.client = TillioClient(api_key="k", api_url="http://localhost")

    @patch("tillio_cli.api.time.sleep")
    def test_retries_on_429(self, mock_sleep):
        """Should retry on 429 and eventually succeed."""
        resp_429 = _mock_response(429)
        resp_200 = _mock_response(200, {"ok": True})
        self.client._client.get = MagicMock(side_effect=[resp_429, resp_200])

        result = self.client.get("/test")
        assert result == {"ok": True}
        assert self.client._client.get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("tillio_cli.api.time.sleep")
    def test_retries_on_502(self, mock_sleep):
        """Should retry on 502."""
        resp_502 = _mock_response(502, text="Bad Gateway")
        resp_502.json.side_effect = Exception("not json")
        resp_200 = _mock_response(200, {"ok": True})
        self.client._client.get = MagicMock(side_effect=[resp_502, resp_200])

        result = self.client.get("/test")
        assert result == {"ok": True}

    @patch("tillio_cli.api.time.sleep")
    def test_does_not_retry_on_400(self, mock_sleep):
        """400 is not retryable — should fail immediately."""
        resp_400 = _mock_response(400, {"detail": "bad request"})
        self.client._client.get = MagicMock(return_value=resp_400)

        with pytest.raises(APIError, match="400"):
            self.client.get("/test")
        assert self.client._client.get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("tillio_cli.api.time.sleep")
    def test_gives_up_after_max_retries(self, mock_sleep):
        """Should give up after MAX_RETRIES attempts."""
        resp_500 = _mock_response(500, {"detail": "server error"})
        self.client._client.get = MagicMock(return_value=resp_500)

        with pytest.raises(APIError, match="500"):
            with patch("tillio_cli.api.MAX_RETRIES", 2):
                self.client.get("/test")

    @patch("tillio_cli.api.time.sleep")
    def test_retries_on_connect_error(self, mock_sleep):
        """Should retry on connection errors."""
        resp_200 = _mock_response(200, {"ok": True})
        self.client._client.get = MagicMock(
            side_effect=[httpx.ConnectError("refused"), resp_200]
        )

        result = self.client.get("/test")
        assert result == {"ok": True}
        mock_sleep.assert_called_once()

    @patch("tillio_cli.api.time.sleep")
    def test_connect_error_after_max_retries_gives_actionable_message(self, mock_sleep):
        """After all retries exhausted, should show actionable error."""
        self.client._client.get = MagicMock(
            side_effect=httpx.ConnectError("refused")
        )

        with patch("tillio_cli.api.MAX_RETRIES", 0):
            with pytest.raises(APIError, match="Cannot connect"):
                self.client.get("/test")

    @patch("tillio_cli.api.time.sleep")
    def test_timeout_error_after_max_retries_gives_actionable_message(self, mock_sleep):
        """After all retries exhausted, should show timeout message."""
        self.client._client.get = MagicMock(
            side_effect=httpx.TimeoutException("timed out")
        )

        with patch("tillio_cli.api.MAX_RETRIES", 0):
            with pytest.raises(APIError, match="timed out"):
                self.client.get("/test")

    @patch("tillio_cli.api.time.sleep")
    def test_respects_retry_after_header(self, mock_sleep):
        """Should use Retry-After header value for delay."""
        resp_429 = _mock_response(429, headers={"Retry-After": "5"})
        resp_200 = _mock_response(200, {"ok": True})
        self.client._client.get = MagicMock(side_effect=[resp_429, resp_200])

        self.client.get("/test")
        # Delay should be at least 5s (from Retry-After header)
        sleep_val = mock_sleep.call_args[0][0]
        assert sleep_val >= 5.0

    @patch("tillio_cli.api.MAX_RETRIES", 0)
    def test_no_retries_when_disabled(self):
        """TILLIO_MAX_RETRIES=0 should disable retries."""
        resp_500 = _mock_response(500, {"detail": "error"})
        self.client._client.get = MagicMock(return_value=resp_500)

        with pytest.raises(APIError):
            self.client.get("/test")
        assert self.client._client.get.call_count == 1

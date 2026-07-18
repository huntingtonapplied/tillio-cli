"""Tillio API client — thin wrapper around httpx."""

import json
import os
import time
from typing import Any, Dict, Generator, Optional, Tuple

import httpx

from tillio_cli.config import get_api_key, get_api_url, load_config
from tillio_cli.log import logger

# Retry configuration
MAX_RETRIES = int(os.getenv("TILLIO_MAX_RETRIES", "3"))
RETRY_BACKOFF_BASE = 1.0  # seconds
RETRY_BACKOFF_MAX = 30.0  # seconds
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_EXCEPTIONS = (httpx.ConnectError, httpx.TimeoutException)


# Error suggestion hints keyed by status code + context
_ERROR_HINTS = {
    401: [
        "Run: tillio login",
        "Or set TILLIO_API_KEY env var",
    ],
    403: [
        "You may not have access to this resource.",
        "Check project permissions or contact the project owner.",
    ],
    404: [
        "The resource was not found. Check the ID or URL.",
        "Run: tillio projects   to list available projects",
    ],
    422: [
        "The request data is invalid. Check required fields.",
        "Run: tillio <command> --help   for usage details",
    ],
    429: [
        "Rate limit exceeded. Wait a moment and try again.",
    ],
    500: [
        "Server error. The Tillio team has been notified.",
        "Try again in a few minutes.",
    ],
}


def format_error_hint(status_code: int, detail: Optional[str] = None) -> str:
    """Get actionable hint text for an error status code.

    Some endpoints are access-gated (subscription/entitlement). The backend
    currently returns a 403 with a specific detail string; detect that to
    avoid misleading generic 403 guidance.
    """
    if status_code == 403 and detail and "Active subscription required" in detail:
        hints = [
            "An active subscription or entitlement is required for this action.",
            "Subscribe or redeem an access code at /checkout.",
        ]
    else:
        hints = _ERROR_HINTS.get(status_code, [])
    if not hints:
        return ""
    return "\n".join(f"  {h}" for h in hints)


class TillioClient:
    """HTTP client for the Tillio API."""

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        self.api_key = api_key or get_api_key()
        self.api_url = api_url or get_api_url()

        if not self.api_key:
            raise AuthError(
                "Not authenticated.\n"
                "  Run: tillio login\n"
                "  Or set TILLIO_API_KEY env var"
            )

        config = load_config()
        self._timeout = float(os.getenv("TILLIO_TIMEOUT", config.get("timeout", 60)))
        self._client = httpx.Client(
            base_url=self.api_url,
            timeout=self._timeout,
        )
        logger.debug("API client initialized: %s (timeout=%.0fs)", self.api_url, self._timeout)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        return headers

    def _request_with_retry(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Execute an HTTP request with retry logic for transient failures."""
        last_exc = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = getattr(self._client, method)(path, headers=self._headers(), **kwargs)
                if resp.status_code not in RETRYABLE_STATUS_CODES or attempt == MAX_RETRIES:
                    return resp
                # Retryable status — back off and retry
                retry_after = 0.0
                try:
                    retry_after = float(resp.headers.get("Retry-After", 0))
                except (ValueError, TypeError):
                    pass
                delay = max(retry_after, RETRY_BACKOFF_BASE * (2 ** attempt))
                delay = min(delay, RETRY_BACKOFF_MAX)
                logger.info(
                    "Retrying %s %s (status %d, attempt %d/%d, waiting %.1fs)",
                    method.upper(), path, resp.status_code, attempt + 1, MAX_RETRIES, delay,
                )
                time.sleep(delay)
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    if isinstance(exc, httpx.ConnectError):
                        raise APIError(
                            f"Cannot connect to {self.api_url}\n"
                            "  Check your network connection\n"
                            "  Verify API URL: tillio doctor",
                            status_code=0,
                        ) from exc
                    if isinstance(exc, httpx.TimeoutException):
                        raise APIError(
                            f"Request timed out after {self._timeout:.0f}s\n"
                            "  Try: TILLIO_TIMEOUT=120 tillio <command>\n"
                            "  Or add 'timeout: 120' to ~/.tillio/config.yaml",
                            status_code=0,
                        ) from exc
                    raise
                delay = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                logger.info(
                    "Retrying %s %s (%s, attempt %d/%d, waiting %.1fs)",
                    method.upper(), path, exc.__class__.__name__, attempt + 1, MAX_RETRIES, delay,
                )
                time.sleep(delay)
        # Should not reach here, but just in case
        raise last_exc or APIError(f"Request failed after {MAX_RETRIES} retries")

    def get(self, path: str, params: Optional[Dict] = None) -> Any:
        logger.debug("GET %s params=%s", path, params)
        resp = self._request_with_retry("get", path, params=params)
        return self._handle_response(resp)

    def post(self, path: str, data: Optional[Dict] = None) -> Any:
        logger.debug("POST %s", path)
        resp = self._request_with_retry("post", path, json=data)
        return self._handle_response(resp)

    def patch(self, path: str, data: Optional[Dict] = None) -> Any:
        logger.debug("PATCH %s", path)
        resp = self._request_with_retry("patch", path, json=data)
        return self._handle_response(resp)

    def delete(self, path: str) -> Any:
        logger.debug("DELETE %s", path)
        resp = self._request_with_retry("delete", path)
        if resp.status_code == 204:
            return None
        return self._handle_response(resp)

    def _handle_response(self, resp: httpx.Response) -> Any:
        logger.debug("Response %d (%s)", resp.status_code, resp.request.url)
        if resp.status_code == 401:
            raise AuthError(
                "Not authenticated.\n"
                "  Run: tillio login\n"
                "  Or set TILLIO_API_KEY env var"
            )
        if resp.status_code == 409:
            data = resp.json()
            raise DuplicateError(
                data.get("detail", "Already submitted"),
                existing_id=data.get("existing_contribution_id"),
            )
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail", "")
                if isinstance(detail, dict):
                    detail = detail.get("message", str(detail))
                if not detail:
                    detail = resp.text
            except Exception:
                detail = resp.text

            hint = format_error_hint(resp.status_code, detail=detail)
            msg = f"API error {resp.status_code}: {detail}"
            if hint:
                msg += f"\n{hint}"
            raise APIError(msg, status_code=resp.status_code)

        return resp.json()

    def lookup_project(self, repo_url: str) -> Optional[Dict]:
        """Find a project by repository URL."""
        try:
            return self.get("/v1/projects/by-repo", params={"url": repo_url})
        except APIError:
            return None

    def submit_commits(self, project_id: str, payload: Dict) -> Dict:
        """Submit commits to a project (non-streaming)."""
        return self.post(f"/v1/projects/{project_id}/commits/submit", payload)

    def _stream_sse(self, method: str, url: str, **kwargs) -> Generator[Tuple[str, Dict], None, None]:
        """Stream SSE events with retry on initial connection.

        Yields (event_type, data) tuples. Retries transient connection errors
        but does not retry once bytes start flowing.
        """
        headers = self._headers()
        stream_timeout = max(self._timeout, 300.0)
        last_exc = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(base_url=self.api_url, timeout=stream_timeout) as client:
                    with client.stream(method, url, headers=headers, **kwargs) as resp:
                        if resp.status_code == 401:
                            raise AuthError(
                                "Not authenticated.\n"
                                "  Run: tillio login\n"
                                "  Or set TILLIO_API_KEY env var"
                            )
                        if resp.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                            delay = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                            logger.info(
                                "Retrying stream %s (status %d, attempt %d/%d)",
                                url, resp.status_code, attempt + 1, MAX_RETRIES,
                            )
                            time.sleep(delay)
                            continue
                        if resp.status_code >= 400:
                            resp.read()
                            detail = ""
                            try:
                                detail = resp.json().get("detail", resp.text)
                            except Exception:
                                detail = resp.text
                            hint = format_error_hint(resp.status_code, detail=detail)
                            msg = f"API error {resp.status_code}: {detail}"
                            if hint:
                                msg += f"\n{hint}"
                            raise APIError(msg, status_code=resp.status_code)

                        event_type = ""
                        for line in resp.iter_lines():
                            if line.startswith("event: "):
                                event_type = line[7:]
                            elif line.startswith("data: "):
                                data = json.loads(line[6:])
                                yield event_type, data
                                event_type = ""
                        return  # completed successfully
            except RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    if isinstance(exc, httpx.ConnectError):
                        raise APIError(
                            f"Cannot connect to {self.api_url}\n"
                            "  Check your network connection\n"
                            "  Verify API URL: tillio doctor",
                            status_code=0,
                        ) from exc
                    raise
                delay = min(RETRY_BACKOFF_BASE * (2 ** attempt), RETRY_BACKOFF_MAX)
                logger.info(
                    "Retrying stream %s (%s, attempt %d/%d)",
                    url, exc.__class__.__name__, attempt + 1, MAX_RETRIES,
                )
                time.sleep(delay)

    def submit_commits_stream(self, project_id: str, payload: Dict) -> Generator[Tuple[str, Dict], None, None]:
        """Submit commits with streaming evaluation (SSE).

        Yields (event_type, data) tuples as the server processes each commit.
        Event types: received, evaluating, scored, error, complete.
        """
        url = f"/v1/projects/{project_id}/commits/submit/stream"
        yield from self._stream_sse("POST", url, json=payload)

    def evaluate_stream(self, contribution_id: str) -> Generator[Tuple[str, Dict], None, None]:
        """Evaluate a contribution with streaming (SSE).

        Yields (event_type, data) tuples.
        Event types: evaluating, scored, error.
        """
        url = f"/v1/contributions/{contribution_id}/evaluate/stream"
        yield from self._stream_sse("POST", url)

    def eval_repo(self, url: str, category: str = "TECHNICAL") -> Dict:
        """Evaluate a remote repository by URL (synchronous)."""
        return self.post("/v1/eval/repo", {"url": url, "category": category})

    def eval_repo_stream(self, url: str, category: str = "TECHNICAL") -> Generator[Tuple[str, Dict], None, None]:
        """Evaluate a remote repository with SSE streaming progress.

        Yields (event_type, data) tuples.
        Event types: cloning, sampling, evaluating, scored, complete, error.
        """
        yield from self._stream_sse(
            "POST", "/v1/eval/repo/stream",
            json={"url": url, "category": category},
        )

    def list_projects(self, params: Optional[Dict] = None) -> list:
        """List user's projects."""
        try:
            return self.get("/v1/projects", params=params)
        except APIError:
            return []

    def score_paths(self, payload: Dict) -> Dict:
        """Score files/directories by path content."""
        return self.post("/v1/contributions/score-paths", payload)

    def list_contributions(self, params: Optional[Dict] = None) -> list:
        """List user's contributions. Raises APIError on failure."""
        data = self.get("/v1/contributions", params=params)
        return data.get("data", data) if isinstance(data, dict) else data


class AuthError(Exception):
    pass


class DuplicateError(Exception):
    def __init__(self, message: str, existing_id: Optional[str] = None):
        super().__init__(message)
        self.existing_id = existing_id


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code

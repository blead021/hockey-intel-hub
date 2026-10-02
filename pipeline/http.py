"""Shared HTTP client: retries with backoff, honors Retry-After, never puts query strings in errors."""

import random
import time

import httpx

USER_AGENT = "HockeyIntelHub/0.1 (+https://hockey-intel-hub.hockey-intel-web.workers.dev)"
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_WAIT_SECONDS = 60


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def client(**kwargs) -> httpx.Client:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.Client(headers=headers, timeout=httpx.Timeout(20.0), follow_redirects=True, **kwargs)


def request(http: httpx.Client, method: str, url: str, *, attempts: int = 4, **kwargs) -> httpx.Response:
    """Sends a request, retrying network errors, rate limits, and server errors.

    Pass API keys through `params`, never in `url`: error messages include the url only.
    """
    for attempt in range(1, attempts + 1):
        try:
            response = http.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt == attempts:
                raise HttpError(f"{method} {url} failed: {type(exc).__name__}") from None
            _wait(attempt)
            continue
        if response.status_code in RETRY_STATUSES and attempt < attempts:
            _wait(attempt, response.headers.get("Retry-After"))
            continue
        if response.is_error:
            raise HttpError(
                f"{method} {url} returned {response.status_code}",
                status=response.status_code,
                body=response.text[:500],
            )
        return response
    raise AssertionError("unreachable")


def get_json(http: httpx.Client, url: str, **kwargs):
    return request(http, "GET", url, **kwargs).json()


def _wait(attempt: int, retry_after: str | None = None) -> None:
    if retry_after and retry_after.isdigit():
        seconds = int(retry_after)
    else:
        seconds = 2**attempt + random.random()
    time.sleep(min(seconds, MAX_WAIT_SECONDS))

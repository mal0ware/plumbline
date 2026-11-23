"""A small, polite JSON client: fixed spacing between requests and backoff on errors.

Only the standard library is used. The client sends a generic User-Agent and no
credentials of any kind. Every endpoint this project calls is public and keyless.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "plumbline-research/0.1"

Transport = Callable[[str], tuple[int, bytes]]


class HttpError(RuntimeError):
    """A request failed after every retry, or failed in a way retrying cannot fix."""

    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url


def _urllib_transport(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), b""
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return 0, b""


class PoliteClient:
    """GET JSON with a minimum interval between calls and exponential backoff.

    Status 429, 5xx and network failures (reported as status 0) are retried. Any
    other non-200 status raises at once: a 400 or 404 will not get better.
    """

    def __init__(
        self,
        min_interval: float,
        *,
        max_retries: int = 6,
        backoff: float = 2.0,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff = backoff
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.requests_made = 0

    def _wait(self) -> None:
        if self._last is not None:
            remaining = self.min_interval - (self._clock() - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = self._clock()

    def get_json(self, url: str) -> Any:
        """Return the decoded JSON body of ``url``."""
        delay = self.backoff
        for attempt in range(self.max_retries + 1):
            self._wait()
            self.requests_made += 1
            status, body = self._transport(url)
            if status == 200:
                return json.loads(body)
            retryable = status == 0 or status == 429 or status >= 500
            if not retryable or attempt == self.max_retries:
                raise HttpError(status, url)
            self._sleep(delay)
            delay *= 2
        raise HttpError(0, url)  # pragma: no cover - the loop always returns or raises

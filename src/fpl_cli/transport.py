from __future__ import annotations

import email.utils
import logging
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_USER_AGENT = "fpl-cli/0.1"
DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

logger = logging.getLogger(__name__)


class FplError(RuntimeError):
    """Base for all errors raised by the FPL CLI's API layer."""


class TransportError(FplError):
    def __init__(self, message: str, *, url: str, status_code: int | None, attempts: int) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code
        self.attempts = attempts


class RequestTimeout(TransportError):
    pass


class RateLimited(TransportError):
    def __init__(
        self, message: str, *, url: str, status_code: int | None, attempts: int, retry_after: float | None
    ) -> None:
        super().__init__(message, url=url, status_code=status_code, attempts=attempts)
        self.retry_after = retry_after


class ServerError(TransportError):
    pass


class AccessDenied(TransportError):
    pass


class NotFound(TransportError):
    pass


class MalformedResponse(TransportError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 4.0
    jitter: float = 0.25
    max_retry_after: float = 5.0


class FplTransport:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = BASE_URL,
        policy: RetryPolicy = RetryPolicy(),
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._base_url = base_url.rstrip("/")
        self._policy = policy
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FplTransport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        attempts = 0
        last_exc: TransportError | None = None

        while attempts < self._policy.attempts:
            attempts += 1
            try:
                response = self._client.get(url, params=params)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ReadError) as exc:
                last_exc = RequestTimeout(
                    f"Timed out contacting the FPL API: {exc}",
                    url=url,
                    status_code=None,
                    attempts=attempts,
                )
                if attempts < self._policy.attempts:
                    self._backoff_sleep(attempts, url=url, status_code=None)
                    continue
                raise last_exc from exc

            status = response.status_code

            if status == 429:
                retry_after = self._retry_after_seconds(response)
                if (
                    retry_after is not None
                    and retry_after <= self._policy.max_retry_after
                    and attempts < self._policy.attempts
                ):
                    logger.debug("429 from %s, retrying after Retry-After=%.2fs", url, retry_after)
                    self._sleep(retry_after)
                    continue
                raise RateLimited(
                    "FPL API rate-limited this client (HTTP 429). Not retrying to avoid "
                    "extending the block; falling back to cache is recommended.",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                    retry_after=retry_after,
                )

            if status in (401, 403):
                raise AccessDenied(
                    f"FPL API denied the request (HTTP {status}). This usually means a "
                    "blocked User-Agent or a Cloudflare/region challenge, not a credentials "
                    "problem — this CLI does not use FPL credentials.",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                )

            if status == 404:
                raise NotFound(
                    f"FPL API endpoint not found (HTTP 404): {url}",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                )

            if 500 <= status < 600:
                last_exc = ServerError(
                    f"FPL API returned a server error (HTTP {status}).",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                )
                if attempts < self._policy.attempts:
                    self._backoff_sleep(attempts, url=url, status_code=status)
                    continue
                raise last_exc

            if status >= 400:
                raise TransportError(
                    f"FPL API request failed (HTTP {status}).",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise MalformedResponse(
                    f"FPL API returned a body that was not valid JSON: {exc}",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                ) from exc

            if not isinstance(payload, (dict, list)):
                raise MalformedResponse(
                    f"FPL API returned unexpected JSON shape ({type(payload).__name__}).",
                    url=url,
                    status_code=status,
                    attempts=attempts,
                )

            return payload

        assert last_exc is not None
        raise last_exc

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        header = response.headers.get("Retry-After")
        if header is None:
            return None
        header = header.strip()
        try:
            seconds = float(header)
        except ValueError:
            pass
        else:
            return seconds if seconds >= 0 else None
        try:
            parsed_date = email.utils.parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError):
            return None
        if parsed_date is None:
            return None
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=UTC)
        delta = (parsed_date - datetime.now(UTC)).total_seconds()
        return max(delta, 0.0)

    def _backoff_sleep(self, attempt: int, *, url: str, status_code: int | None) -> None:
        policy = self._policy
        delay = min(policy.max_delay, policy.base_delay * (2 ** (attempt - 1)))
        low = delay * (1 - policy.jitter)
        high = delay * (1 + policy.jitter)
        delay = random.uniform(low, high)
        logger.debug("retrying %s (status=%s) after %.2fs", url, status_code, delay)
        self._sleep(delay)

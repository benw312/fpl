from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fpl_cli.api.models import Fixture
from fpl_cli.api.snapshots import SnapshotService
from fpl_cli.storage.cache import JsonDocumentCache
from fpl_cli.transport import RateLimited, RequestTimeout


class StubApi:
    def __init__(self, fixtures: list[Fixture] | None = None, error: Exception | None = None) -> None:
        self._fixtures = fixtures
        self._error = error
        self.closed = False

    def fixtures(self) -> list[Fixture]:
        if self._error is not None:
            raise self._error
        assert self._fixtures is not None
        return self._fixtures

    def close(self) -> None:
        self.closed = True


def _timeout_error() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


def _fixtures_from_payload(payload: list[dict[str, Any]]) -> list[Fixture]:
    return [Fixture.model_validate(item) for item in payload]


def _load_cached_fixtures(cache: JsonDocumentCache) -> list[Fixture] | None:
    return cache.load_typed(
        lambda payload, fetched_at: [Fixture.model_validate(item) for item in payload]
    )


def test_load_fixtures_saves_cache_on_successful_fetch(
    tmp_path: Path, fixtures_payload: list[dict[str, Any]]
) -> None:
    fetched = _fixtures_from_payload(fixtures_payload)
    cache = JsonDocumentCache(tmp_path / "fixtures.json")
    service = SnapshotService(api=StubApi(fixtures=fetched), fixtures_cache=cache)

    result = service.load_fixtures()

    assert result.stale is False
    assert cache.path.exists()
    reloaded = _load_cached_fixtures(JsonDocumentCache(cache.path))
    assert reloaded is not None
    assert len(reloaded) == len(fetched) == 2


def test_load_fixtures_falls_back_to_cache_on_fpl_error(
    tmp_path: Path, fixtures_payload: list[dict[str, Any]]
) -> None:
    cache_path = tmp_path / "fixtures.json"
    cache_path.write_text(json.dumps(fixtures_payload), encoding="utf-8")
    cache = JsonDocumentCache(cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), fixtures_cache=cache)

    result = service.load_fixtures()

    assert result.stale is True
    assert result.reason is not None
    assert "timed out" in result.reason.lower()
    assert len(result.fixtures) == 2
    assert result.fixtures[1].event is None


def test_load_fixtures_reraises_original_error_when_no_cache(tmp_path: Path) -> None:
    cache = JsonDocumentCache(tmp_path / "fixtures.json")
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    service = SnapshotService(api=StubApi(error=error), fixtures_cache=cache)

    with pytest.raises(RateLimited) as excinfo:
        service.load_fixtures()

    assert excinfo.value is error


def test_load_fixtures_reraises_original_error_when_cache_corrupt(tmp_path: Path) -> None:
    cache_path = tmp_path / "fixtures.json"
    cache_path.write_text("not json", encoding="utf-8")
    cache = JsonDocumentCache(cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), fixtures_cache=cache)

    with pytest.raises(RequestTimeout):
        service.load_fixtures()


def test_refresh_fixtures_saves_cache_on_successful_fetch(
    tmp_path: Path, fixtures_payload: list[dict[str, Any]]
) -> None:
    fetched = _fixtures_from_payload(fixtures_payload)
    cache = JsonDocumentCache(tmp_path / "fixtures.json")
    service = SnapshotService(api=StubApi(fixtures=fetched), fixtures_cache=cache)

    result = service.refresh_fixtures()

    assert result == fetched
    reloaded = _load_cached_fixtures(JsonDocumentCache(cache.path))
    assert reloaded is not None
    assert len(reloaded) == 2


def test_refresh_fixtures_raises_and_does_not_touch_existing_cache(
    tmp_path: Path, fixtures_payload: list[dict[str, Any]]
) -> None:
    cache_path = tmp_path / "fixtures.json"
    cache_path.write_text(json.dumps(fixtures_payload), encoding="utf-8")
    original_mtime = cache_path.stat().st_mtime
    cache = JsonDocumentCache(cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), fixtures_cache=cache)

    with pytest.raises(RequestTimeout):
        service.refresh_fixtures()

    assert cache_path.stat().st_mtime == original_mtime

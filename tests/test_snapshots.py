from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from datetime import UTC, datetime

from fpl_cli.api import snapshots as snapshots_module
from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import SnapshotService
from fpl_cli.storage.cache import SnapshotCache
from fpl_cli.transport import RateLimited, RequestTimeout


class StubApi:
    def __init__(self, snapshot: BootstrapSnapshot | None = None, error: Exception | None = None) -> None:
        self._snapshot = snapshot
        self._error = error
        self.closed = False

    def bootstrap_static(self) -> BootstrapSnapshot:
        if self._error is not None:
            raise self._error
        assert self._snapshot is not None
        return self._snapshot

    def close(self) -> None:
        self.closed = True


def _timeout_error() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


def test_load_saves_cache_on_successful_fetch(tmp_path: Path, bootstrap_payload: dict[str, Any]) -> None:
    fetched_snapshot = BootstrapSnapshot.from_payload(bootstrap_payload, fetched_at=datetime.now(UTC))
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    service = SnapshotService(api=StubApi(snapshot=fetched_snapshot), cache=cache)

    result = service.load()

    assert result.stale is False
    assert cache.path.exists()
    reloaded = SnapshotCache(path=cache.path).load()
    assert reloaded is not None
    assert len(reloaded.elements) == len(fetched_snapshot.elements) == 15


def test_load_falls_back_to_cache_on_fpl_error(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    cache_path = tmp_path / "bootstrap-static.json"
    cache_path.write_text(json.dumps(bootstrap_payload), encoding="utf-8")
    cache = SnapshotCache(path=cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), cache=cache)

    result = service.load()

    assert result.stale is True
    assert "timed out" in result.reason.lower()
    assert len(result.snapshot.elements) == 15


def test_load_reraises_original_error_when_no_cache(tmp_path: Path) -> None:
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    service = SnapshotService(api=StubApi(error=error), cache=cache)

    with pytest.raises(RateLimited) as excinfo:
        service.load()

    assert excinfo.value is error


def test_load_reraises_original_error_when_cache_corrupt(tmp_path: Path) -> None:
    cache_path = tmp_path / "bootstrap-static.json"
    cache_path.write_text("not json", encoding="utf-8")
    cache = SnapshotCache(path=cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), cache=cache)

    with pytest.raises(RequestTimeout):
        service.load()


def test_refresh_saves_cache_on_successful_fetch(tmp_path: Path, bootstrap_payload: dict[str, Any]) -> None:
    fetched_snapshot = BootstrapSnapshot.from_payload(bootstrap_payload, fetched_at=datetime.now(UTC))
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    service = SnapshotService(api=StubApi(snapshot=fetched_snapshot), cache=cache)

    result = service.refresh()

    assert result is fetched_snapshot
    reloaded = SnapshotCache(path=cache.path).load()
    assert reloaded is not None
    assert len(reloaded.elements) == 15


def test_refresh_raises_and_does_not_touch_existing_cache(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    cache_path = tmp_path / "bootstrap-static.json"
    cache_path.write_text(json.dumps(bootstrap_payload), encoding="utf-8")
    original_mtime = cache_path.stat().st_mtime
    cache = SnapshotCache(path=cache_path)
    service = SnapshotService(api=StubApi(error=_timeout_error()), cache=cache)

    with pytest.raises(RequestTimeout):
        service.refresh()

    assert cache_path.stat().st_mtime == original_mtime


def test_close_closes_owned_api(monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot) -> None:
    stub = StubApi(snapshot=bootstrap_snapshot)
    monkeypatch.setattr(snapshots_module, "OfficialFplApi", lambda: stub)
    service = SnapshotService()

    service.close()

    assert stub.closed is True


def test_close_does_not_close_injected_api(bootstrap_snapshot: BootstrapSnapshot) -> None:
    stub = StubApi(snapshot=bootstrap_snapshot)
    service = SnapshotService(api=stub)

    service.close()

    assert stub.closed is False

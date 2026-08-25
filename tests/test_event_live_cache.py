from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl_cli.api.models import BootstrapSnapshot, GameSettings, Gameweek, LiveEvent
from fpl_cli.api.snapshots import SnapshotService
from fpl_cli.transport import RateLimited, RequestTimeout


def _snapshot() -> BootstrapSnapshot:
    """Event 1 is finalised (finished + data_checked); event 2 is in-flight."""
    return BootstrapSnapshot(
        events=[
            Gameweek(id=1, name="GW1", finished=True, data_checked=True),
            Gameweek(id=2, name="GW2", finished=False, data_checked=False),
        ],
        teams=[],
        element_types=[],
        elements=[],
        game_settings=GameSettings(),
        raw={},
        fetched_at=datetime.now(UTC),
        season="test",
    )


class StubApi:
    def __init__(self, live: LiveEvent | None = None, error: Exception | None = None) -> None:
        self._live = live
        self._error = error
        self.calls = 0

    def event_live(self, event: int) -> LiveEvent:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._live is not None
        return self._live

    def close(self) -> None:
        pass


def _timeout_error() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


def _live_event(payload: dict[str, Any]) -> LiveEvent:
    return LiveEvent.model_validate(payload)


def test_finalised_event_persists_cache_on_successful_fetch(
    tmp_path: Path, live_event_payload: dict[str, Any]
) -> None:
    live = _live_event(live_event_payload)
    api = StubApi(live=live)
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    result = service.load_event_live(1, _snapshot())

    assert result.stale is False
    assert api.calls == 1
    assert (tmp_path / "1-live.json").exists()
    assert len(result.live.elements) == 2


def test_in_flight_event_never_persists_and_always_refetches(
    tmp_path: Path, live_event_payload: dict[str, Any]
) -> None:
    live = _live_event(live_event_payload)
    api = StubApi(live=live)
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    service.load_event_live(2, _snapshot())
    service.load_event_live(2, _snapshot())

    assert api.calls == 2
    assert not (tmp_path / "2-live.json").exists()


def test_finalised_event_cache_hit_skips_the_live_fetch(
    tmp_path: Path, live_event_payload: dict[str, Any]
) -> None:
    live = _live_event(live_event_payload)
    warm = SnapshotService(api=StubApi(live=live), event_live_cache_dir=tmp_path)
    warm.load_event_live(1, _snapshot())

    api = StubApi(error=AssertionError("should not be called — cache is immutable once finalised"))
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    result = service.load_event_live(1, _snapshot())

    assert api.calls == 0
    assert result.stale is False
    assert len(result.live.elements) == 2


def test_finalised_event_fetch_fails_with_no_cache_raises(tmp_path: Path) -> None:
    service = SnapshotService(api=StubApi(error=_timeout_error()), event_live_cache_dir=tmp_path)

    with pytest.raises(RequestTimeout):
        service.load_event_live(1, _snapshot())


def test_in_flight_event_fetch_fails_raises_with_no_fallback(tmp_path: Path) -> None:
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    service = SnapshotService(api=StubApi(error=error), event_live_cache_dir=tmp_path)

    with pytest.raises(RateLimited):
        service.load_event_live(2, _snapshot())


def test_unknown_event_is_treated_as_not_finalised(tmp_path: Path, live_event_payload: dict[str, Any]) -> None:
    live = _live_event(live_event_payload)
    api = StubApi(live=live)
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    service.load_event_live(99, _snapshot())

    assert api.calls == 1
    assert not (tmp_path / "99-live.json").exists()

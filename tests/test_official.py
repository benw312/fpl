from __future__ import annotations

from typing import Any

import pytest

from fpl_cli.api.official import FplApiError, OfficialFplApi
from fpl_cli.transport import RateLimited


class StubTransport:
    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.closed = False

    def get_json(self, path: str, *, params: Any = None) -> Any:
        if self._error is not None:
            raise self._error
        return self._payload

    def close(self) -> None:
        self.closed = True


def test_bootstrap_static_builds_snapshot(bootstrap_payload) -> None:
    api = OfficialFplApi(transport=StubTransport(payload=bootstrap_payload))

    snapshot = api.bootstrap_static()

    assert len(snapshot.elements) == 15
    assert snapshot.season == "2025-26_a1b2c3"


def test_bootstrap_static_falls_back_to_unknown_season(bootstrap_payload) -> None:
    bootstrap_payload = dict(bootstrap_payload)
    bootstrap_payload["game_config"] = {}
    api = OfficialFplApi(transport=StubTransport(payload=bootstrap_payload))

    snapshot = api.bootstrap_static()

    assert snapshot.season == "unknown"


def test_schema_mismatch_raises_fpl_api_error(bootstrap_payload) -> None:
    bootstrap_payload = dict(bootstrap_payload)
    bootstrap_payload["elements"] = "not-a-list"
    api = OfficialFplApi(transport=StubTransport(payload=bootstrap_payload))

    with pytest.raises(FplApiError) as excinfo:
        api.bootstrap_static()

    assert not isinstance(excinfo.value, RateLimited)


def test_transport_errors_propagate_unwrapped() -> None:
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    api = OfficialFplApi(transport=StubTransport(error=error))

    with pytest.raises(RateLimited):
        api.bootstrap_static()


def test_fixtures_builds_list(fixtures_payload: list[dict[str, Any]]) -> None:
    api = OfficialFplApi(transport=StubTransport(payload=fixtures_payload))

    fixtures = api.fixtures()

    assert len(fixtures) == 2
    assert fixtures[0].event == 1
    assert fixtures[1].event is None


def test_fixtures_schema_mismatch_raises_fpl_api_error() -> None:
    api = OfficialFplApi(transport=StubTransport(payload=[{"id": "not-an-int"}]))

    with pytest.raises(FplApiError) as excinfo:
        api.fixtures()

    assert not isinstance(excinfo.value, RateLimited)


def test_fixtures_transport_errors_propagate_unwrapped() -> None:
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    api = OfficialFplApi(transport=StubTransport(error=error))

    with pytest.raises(RateLimited):
        api.fixtures()


def test_event_live_builds_live_event(live_event_payload: dict[str, Any]) -> None:
    api = OfficialFplApi(transport=StubTransport(payload=live_event_payload))

    live = api.event_live(1)

    assert len(live.elements) == 2
    element = live.elements[0]
    assert element.stats["total_points"] == 6
    assert element.explain[0].fixture == 1
    assert element.explain[0].stats[0].identifier == "minutes"


def test_event_live_schema_mismatch_raises_fpl_api_error() -> None:
    api = OfficialFplApi(transport=StubTransport(payload={"elements": [{"id": "not-an-int"}]}))

    with pytest.raises(FplApiError) as excinfo:
        api.event_live(1)

    assert not isinstance(excinfo.value, RateLimited)


def test_event_live_transport_errors_propagate_unwrapped() -> None:
    error = RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None)
    api = OfficialFplApi(transport=StubTransport(error=error))

    with pytest.raises(RateLimited):
        api.event_live(1)

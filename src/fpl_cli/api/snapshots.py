from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.api.official import OfficialFplApi
from fpl_cli.storage.cache import JsonDocumentCache, SnapshotCache
from fpl_cli.transport import FplError

_DEFAULT_FIXTURES_PATH = Path.home() / ".fpl-cli" / "fixtures.json"
_DEFAULT_EVENT_LIVE_DIR = Path.home() / ".fpl-cli" / "events"


@dataclass(frozen=True)
class SnapshotResult:
    snapshot: BootstrapSnapshot
    stale: bool
    reason: str | None = None


@dataclass(frozen=True)
class FixturesResult:
    fixtures: list[Fixture]
    fetched_at: datetime
    stale: bool
    reason: str | None = None


def _parse_fixtures_cache(payload: object, fetched_at: datetime) -> FixturesResult:
    if not isinstance(payload, list):
        raise TypeError("fixtures cache payload must be a list")
    fixtures = [Fixture.model_validate(item) for item in payload]
    return FixturesResult(fixtures=fixtures, fetched_at=fetched_at, stale=True)


@dataclass(frozen=True)
class LiveEventResult:
    live: LiveEvent
    event: int
    stale: bool
    reason: str | None = None


def _parse_live_event_cache(payload: object, fetched_at: datetime) -> LiveEvent:
    if not isinstance(payload, dict):
        raise TypeError("event-live cache payload must be a dict")
    return LiveEvent.model_validate(payload)


def _is_finalised(snapshot: BootstrapSnapshot, event: int) -> bool:
    gameweek = next((gameweek for gameweek in snapshot.events if gameweek.id == event), None)
    return gameweek is not None and gameweek.finished and gameweek.data_checked


class SnapshotService:
    def __init__(
        self,
        api: OfficialFplApi | None = None,
        cache: SnapshotCache | None = None,
        fixtures_cache: JsonDocumentCache | None = None,
        event_live_cache_dir: Path | None = None,
    ) -> None:
        self._api = api or OfficialFplApi()
        self._owns_api = api is None
        self._cache = cache or SnapshotCache()
        self._fixtures_cache = fixtures_cache or JsonDocumentCache(_DEFAULT_FIXTURES_PATH)
        self._event_live_cache_dir = event_live_cache_dir or _DEFAULT_EVENT_LIVE_DIR

    def close(self) -> None:
        if self._owns_api:
            self._api.close()

    def load(self) -> SnapshotResult:
        """Fetch the live snapshot, falling back to the cache on any FplError.

        Saves the snapshot to cache whenever a live fetch succeeds.
        """
        try:
            snapshot = self._api.bootstrap_static()
        except FplError as exc:
            cached = self._cache.load()
            if cached is None:
                raise
            return SnapshotResult(snapshot=cached, stale=True, reason=str(exc))
        self._cache.save(snapshot)
        return SnapshotResult(snapshot=snapshot, stale=False)

    def refresh(self) -> BootstrapSnapshot:
        """Force a live fetch with no fallback. Raises FplError on failure."""
        snapshot = self._api.bootstrap_static()
        self._cache.save(snapshot)
        return snapshot

    def load_fixtures(self) -> FixturesResult:
        """Fetch the live fixtures list, falling back to the cache on any FplError.

        Saves the fixtures to cache whenever a live fetch succeeds.
        """
        try:
            fixtures = self._api.fixtures()
        except FplError as exc:
            cached = self._fixtures_cache.load_typed(_parse_fixtures_cache)
            if cached is None:
                raise
            return replace(cached, reason=str(exc))
        self._fixtures_cache.save_raw([fixture.model_dump(mode="json") for fixture in fixtures])
        return FixturesResult(fixtures=fixtures, fetched_at=datetime.now(UTC), stale=False)

    def refresh_fixtures(self) -> list[Fixture]:
        """Force a live fixtures fetch with no fallback. Raises FplError on failure."""
        fixtures = self._api.fixtures()
        self._fixtures_cache.save_raw([fixture.model_dump(mode="json") for fixture in fixtures])
        return fixtures

    def load_event_live(self, event: int, snapshot: BootstrapSnapshot) -> LiveEventResult:
        """Fetch one gameweek's live data.

        Only cached once `snapshot.events[event]` reports `finished and
        data_checked` (Decision 6) — an in-flight gameweek's bonus and
        `points_modification` are provisional, so it is always fetched fresh
        and never persisted. A finalised gameweek is immutable, so a cache
        hit for one is returned without a live fetch at all — unlike
        `load()`/`load_fixtures()`, which always try live first, there is
        nothing live fetching could tell us that the cache doesn't already
        have. `snapshot` is passed explicitly (rather than read from the
        bootstrap cache) so the check is against whichever snapshot the
        caller is actually evaluating with.
        """
        cache = JsonDocumentCache(self._event_live_cache_dir / f"{event}-live.json")
        finalised = _is_finalised(snapshot, event)

        if finalised:
            cached = cache.load_typed(_parse_live_event_cache)
            if cached is not None:
                return LiveEventResult(live=cached, event=event, stale=False)

        live = self._api.event_live(event)
        if finalised:
            cache.save_raw(live.model_dump(mode="json"))
        return LiveEventResult(live=live, event=event, stale=False)

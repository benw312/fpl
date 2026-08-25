from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.api.official import OfficialFplApi
from fpl_cli.storage.cache import JsonDocumentCache, SnapshotCache
from fpl_cli.transport import FplError

_DEFAULT_FIXTURES_PATH = Path.home() / ".fpl-cli" / "fixtures.json"


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


class SnapshotService:
    def __init__(
        self,
        api: OfficialFplApi | None = None,
        cache: SnapshotCache | None = None,
        fixtures_cache: JsonDocumentCache | None = None,
    ) -> None:
        self._api = api or OfficialFplApi()
        self._owns_api = api is None
        self._cache = cache or SnapshotCache()
        self._fixtures_cache = fixtures_cache or JsonDocumentCache(_DEFAULT_FIXTURES_PATH)

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

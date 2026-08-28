from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.api.official import OfficialFplApi
from fpl_cli.storage.cache import JsonDocumentCache, SnapshotCache
from fpl_cli.transport import FplError

_DEFAULT_FIXTURES_PATH = Path.home() / ".fpl-cli" / "fixtures.json"
_DEFAULT_EVENT_LIVE_DIR = Path.home() / ".fpl-cli" / "events"
DEFAULT_ARCHIVE_DIR = Path.home() / ".fpl-cli" / "archive"


@dataclass(frozen=True)
class SnapshotResult:
    snapshot: BootstrapSnapshot
    stale: bool
    reason: str | None = None


class PinnedSnapshotError(FplError):
    """A pinned run could not read an input it was told to use.

    Deliberately terminal. Falling back to the live API or to the cache would
    reintroduce the drift `--snapshot` exists to remove: the run would quietly
    measure something other than the capture it was pointed at, which is the
    defect, not the recovery from it (snapshot-pinning.md §2).
    """


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


def _capture_time(path: Path) -> datetime:
    """When a capture on disk was taken, as far as the filesystem knows."""
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


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
        archive_dir: Path | None = None,
    ) -> None:
        self._api = api or OfficialFplApi()
        self._owns_api = api is None
        self._cache = cache or SnapshotCache()
        self._fixtures_cache = fixtures_cache or JsonDocumentCache(_DEFAULT_FIXTURES_PATH)
        self._event_live_cache_dir = event_live_cache_dir or _DEFAULT_EVENT_LIVE_DIR
        self._archive_dir = archive_dir or DEFAULT_ARCHIVE_DIR

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

    def archive(self, snapshot: BootstrapSnapshot) -> Path:
        """Write a dated, leak-free-evaluation snapshot (Decision 6).

        `fpl plan evaluate` needs player stats as they stood *before* a
        gameweek's deadline — today's snapshot already contains the result
        being scored. One file per calendar day (UTC): idempotent within a
        day by construction, since a second call the same day overwrites the
        same path rather than accumulating.
        """
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        path = self._archive_dir / f"bootstrap-{datetime.now(UTC).date().isoformat()}.json"
        path.write_text(json.dumps(snapshot.raw, ensure_ascii=False), encoding="utf-8")
        return path


class PinnedSnapshotService:
    """`SnapshotService`'s read-only twin, behind `--snapshot` / `FPL_SNAPSHOT`.

    The same `load` / `load_fixtures` / `load_event_live` / `close` surface, so
    the CLI can hold either without knowing which. No `refresh*` and no
    `archive`: a pinned run has no business writing, and leaving them off makes
    that a type error rather than a convention.

    Bootstrap-static comes from the pinned capture. Fixtures and event-live
    have no pinned equivalent — the capture format is bootstrap-static alone —
    so they come from their ordinary caches, read-only. No method here opens a
    socket and none writes a byte, which is what makes a figure measured under
    a pinned run re-measurable against the same inputs later
    (snapshot-pinning.md §2; §5 records what that still does not pin).
    """

    def __init__(
        self,
        path: Path,
        fixtures_cache: JsonDocumentCache | None = None,
        event_live_cache_dir: Path | None = None,
    ) -> None:
        self.path = path
        self._fixtures_cache = fixtures_cache or JsonDocumentCache(_DEFAULT_FIXTURES_PATH)
        self._event_live_cache_dir = event_live_cache_dir or _DEFAULT_EVENT_LIVE_DIR

    def close(self) -> None:
        """No API client is ever constructed, so there is nothing to close."""

    def load(self) -> SnapshotResult:
        """Read the pinned capture. Never fetches, never writes, never falls back.

        `fetched_at` is the file's mtime, matching `JsonDocumentCache`. It is
        therefore a property of the capture rather than of the run, which is
        what lets two pinned runs produce byte-identical `--json`.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PinnedSnapshotError(f"Could not read the pinned snapshot {self.path}: {exc}") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise PinnedSnapshotError(f"The pinned snapshot {self.path} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise PinnedSnapshotError(
                f"The pinned snapshot {self.path} is not a bootstrap-static payload: its top "
                f"level is a {type(payload).__name__}, not an object."
            )
        try:
            snapshot = BootstrapSnapshot.from_payload(payload, fetched_at=_capture_time(self.path))
        except (ValidationError, TypeError, AttributeError) as exc:
            raise PinnedSnapshotError(
                f"The pinned snapshot {self.path} did not match the expected shape: {exc}"
            ) from exc
        return SnapshotResult(snapshot=snapshot, stale=False)

    def load_fixtures(self) -> FixturesResult:
        """Read the fixtures cache. Never fetches, never writes, never falls back."""
        cached = self._fixtures_cache.load_typed(_parse_fixtures_cache)
        if cached is None:
            raise PinnedSnapshotError(
                f"A pinned run never fetches, and there is no readable fixtures cache at "
                f"{self._fixtures_cache.path}. Run `fpl sync` first, or drop --snapshot."
            )
        return cached

    def load_event_live(self, event: int, snapshot: BootstrapSnapshot) -> LiveEventResult:
        """Read one gameweek's live cache. Never fetches, never writes, never falls back.

        Unlike `SnapshotService.load_event_live` this does not consult
        `finished and data_checked`: that gate chooses between a cache hit and
        a live fetch, and here there is no live fetch to choose. Whatever the
        cache holds is what a pinned run gets (snapshot-pinning.md §5).
        """
        cache = JsonDocumentCache(self._event_live_cache_dir / f"{event}-live.json")
        cached = cache.load_typed(_parse_live_event_cache)
        if cached is None:
            raise PinnedSnapshotError(
                f"A pinned run never fetches, and there is no readable GW{event} live cache at "
                f"{cache.path}. Run `fpl plan evaluate --event {event}` without --snapshot "
                f"first, or drop --snapshot."
            )
        return LiveEventResult(live=cached, event=event, stale=False)

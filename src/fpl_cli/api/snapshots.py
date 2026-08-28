from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.api.official import OfficialFplApi
from fpl_cli.storage import capture
from fpl_cli.storage.cache import JsonDocumentCache, SnapshotCache
from fpl_cli.transport import FplError

_DEFAULT_FIXTURES_PATH = Path.home() / ".fpl-cli" / "fixtures.json"
_DEFAULT_EVENT_LIVE_DIR = Path.home() / ".fpl-cli" / "events"
DEFAULT_ARCHIVE_DIR = Path.home() / ".fpl-cli" / "archive"


@dataclass(frozen=True)
class ArchivedCapture:
    """Where `sync` filed a capture, and what it found already there.

    `quarantined` is set when something unusable was occupying the day's slot
    and had to be renamed aside. It is never deleted, so the caller's job is to
    say where it went and let someone look.
    """

    path: Path
    role: str
    quarantined: Path | None = None
    problem: capture.CaptureProblem | None = None


@dataclass(frozen=True)
class SnapshotResult:
    snapshot: BootstrapSnapshot
    stale: bool
    reason: str | None = None


@dataclass(frozen=True)
class SnapshotProvenance:
    """Where the data behind a run's numbers actually came from.

    Recorded in `--json` so a figure quoted in a plan or a commit message
    carries the capture it was measured against, instead of "the cached
    snapshot" — which names a file, not a version of it (FU-40).

    `source` is `pinned`, `cache` or `live`. `path` is set only for `pinned`:
    the cache's location is fixed and implied, whereas a capture's is the whole
    point. `captured_at` is the snapshot's `fetched_at`, which for a pinned
    capture and for a cache read is the file's mtime and for a live fetch is
    the moment of the fetch.
    """

    source: str
    captured_at: datetime
    path: Path | None = None

    def as_json(self) -> dict[str, str]:
        payload = {"source": self.source, "captured_at": self.captured_at.isoformat()}
        if self.path is not None:
            payload["path"] = str(self.path)
        return payload


class PinnedSnapshotError(FplError):
    """A pinned run could not read an input it was told to use.

    Deliberately terminal. Falling back to the live API or to the cache would
    reintroduce the drift `--snapshot` exists to remove: the run would quietly
    measure something other than the capture it was pointed at, which is the
    defect, not the recovery from it (snapshot-pinning.md §2).
    """


@dataclass(frozen=True)
class FixturesResult:
    """`stale` and `source` are not the same question.

    `stale` drives the header warning and the per-projection assumption:
    "this list may no longer describe the schedule". `source` says which file
    or fetch produced it. They agree everywhere except a pinned capture, whose
    fixtures came off disk but are exactly the ones captured alongside the
    snapshot — not stale, and not `cache` either.
    """

    fixtures: list[Fixture]
    fetched_at: datetime
    stale: bool
    reason: str | None = None
    source: str = "live"
    path: Path | None = None


def _parse_fixtures_cache(payload: object, fetched_at: datetime) -> FixturesResult:
    if not isinstance(payload, list):
        raise TypeError("fixtures cache payload must be a list")
    fixtures = [Fixture.model_validate(item) for item in payload]
    return FixturesResult(fixtures=fixtures, fetched_at=fetched_at, stale=True, source="cache")


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


def _current_event_record(snapshot: BootstrapSnapshot, captured_at: datetime) -> dict | None:
    """The manifest's `current_event`: which gameweek was live, and whether its
    deadline had already passed when the fetch happened.

    A capture's filename says nothing about this. The archive is written by a
    `Persistent=true` timer, whose catch-up firings land hours from the
    schedule they are catching up on — `bootstrap-2026-08-25.json` was written
    at 15:12 and `bootstrap-2026-08-26.json` at 22:32, neither at the 00:30 the
    dates imply. A backtest has to be able to check rather than assume.
    """
    gameweek = next((event for event in snapshot.events if event.is_current), None)
    if gameweek is None:
        return None
    deadline = gameweek.deadline_time
    return {
        "id": gameweek.id,
        "deadline_time": deadline.isoformat() if deadline is not None else None,
        "deadline_passed": None if deadline is None else deadline <= captured_at,
    }


def _next_event_record(snapshot: BootstrapSnapshot, captured_at: datetime) -> dict | None:
    """The manifest's `next_event`: the gameweek this capture is a *candidate*
    for, and whether the capture precedes its deadline.

    `current_event` cannot answer that. For `gw2-pre-deadline.json` the current
    gameweek is GW1, whose deadline had passed a week earlier — the capture is
    named for GW2 because GW2 is what it is useful for. Both are recorded, and
    each is phrased as the fact its own consumer needs: the leak check asks
    whether the current gameweek's deadline has *passed*, a candidate check asks
    whether the capture *precedes* the next one's.
    """
    gameweek = next((event for event in snapshot.events if event.is_next), None)
    if gameweek is None:
        return None
    deadline = gameweek.deadline_time
    return {
        "id": gameweek.id,
        "deadline_time": deadline.isoformat() if deadline is not None else None,
        "captured_before_deadline": None if deadline is None else captured_at < deadline,
    }


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
            return replace(cached, reason=str(exc), path=self._fixtures_cache.path)
        self._fixtures_cache.save_raw([fixture.model_dump(mode="json") for fixture in fixtures])
        return FixturesResult(fixtures=fixtures, fetched_at=datetime.now(UTC), stale=False, source="live")

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

    def archive(self, snapshot: BootstrapSnapshot, fixtures: list[Fixture]) -> ArchivedCapture:
        """Write a dated capture directory (Decision 6, FU-41).

        `fpl plan evaluate` needs the inputs as they stood *before* a
        gameweek's deadline — today's snapshot already contains the result
        being scored. Before FU-41 that meant bootstrap-static alone, which
        was never enough: `_build_schedule` turns the fixtures list into
        opponent *and* venue for every projected cell, so an evaluation run
        against a rewritten `fixtures.json` is not measuring what it reports.
        Both files are captured together, with a manifest.

        One canonical slot per **UK** date, dated by the *fetch* rather than
        the clock at write time. The first valid capture of a day claims the
        slot; anything later that day is written ad-hoc, keyed by the instant,
        and stays readable through `--snapshot` without becoming a candidate for
        automatic selection. Nothing inspects timer state: a sync that finds the
        slot empty claims it, which is what makes the offline case — the timer
        did not run, someone syncs by hand at noon — come out right by itself.
        """
        captured_at = snapshot.fetched_at
        slot = capture.canonical_slot(self._archive_dir, captured_at)
        claimed = capture.slot_claimed(self._archive_dir, captured_at)

        # An occupied slot holding something unusable is moved aside, and this
        # capture still files ad-hoc rather than taking the vacated slot: the
        # slot was occupied when we looked, and quietly promoting ourselves over
        # a capture nobody has examined is how the examination never happens.
        quarantined: Path | None = None
        problem: capture.CaptureProblem | None = None
        if slot.exists():
            problem = capture.inspect_capture(slot)
            if problem is not None:
                quarantined = capture.quarantine(slot, captured_at)

        role = capture.ROLE_ADHOC if claimed else capture.ROLE_CANONICAL
        destination = capture.adhoc_path(self._archive_dir, captured_at) if claimed else slot
        path = capture.write_capture(
            destination,
            bootstrap=snapshot.raw,
            fixtures=[fixture.model_dump(mode="json") for fixture in fixtures],
            captured_at=captured_at,
            current_event=_current_event_record(snapshot, captured_at),
            next_event=_next_event_record(snapshot, captured_at),
            role=role,
        )
        return ArchivedCapture(path=path, role=role, quarantined=quarantined, problem=problem)


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
        # A stat, deliberately, and no reading: `load_snapshot` constructs the
        # service outside its own `except PinnedSnapshotError`, so a raise here
        # would escape as a traceback instead of the error naming the path. A
        # path that does not exist classifies as a bare file and fails in
        # `load()`, which is where the message belongs.
        self.is_capture_directory = path.is_dir()
        self._manifest: dict | None = None
        self._fixtures_cache = fixtures_cache or JsonDocumentCache(_DEFAULT_FIXTURES_PATH)
        self._event_live_cache_dir = event_live_cache_dir or _DEFAULT_EVENT_LIVE_DIR

    def manifest(self) -> dict | None:
        """The capture manifest, or `None` for a bare-file pin.

        Read once and kept: a run reads the capture from two service instances
        (snapshot, then fixtures), and re-verifying is cheap but re-reporting a
        different manifest would not be.
        """
        if not self.is_capture_directory:
            return None
        if self._manifest is None:
            try:
                self._manifest = capture.read_manifest(self.path)
            except OSError as exc:
                raise PinnedSnapshotError(
                    f"The pinned capture directory {self.path} has no readable "
                    f"{capture.MANIFEST_FILENAME}: {exc}. Pin the bootstrap-static file "
                    f"itself if this is not a capture directory."
                ) from exc
            except ValueError as exc:
                raise PinnedSnapshotError(f"The pinned capture {self.path} has an unusable manifest: {exc}") from exc
        return self._manifest

    def captured_at(self) -> datetime:
        """The capture's own timestamp: the manifest's for a directory, the
        file's mtime for a bare file, which records nothing better."""
        manifest = self.manifest()
        if manifest is None:
            return _capture_time(self.path)
        try:
            return capture.manifest_captured_at(manifest)
        except ValueError as exc:
            raise PinnedSnapshotError(f"The pinned capture {self.path} has an unusable manifest: {exc}") from exc

    def _verified_file(self, filename: str) -> Path:
        """A file from the capture, checked against the manifest's digest.

        Verified on read rather than all at once on open, so the error names
        the file the run actually depended on and a command that never reads
        fixtures is not failed by a corrupt fixtures file it never touches.
        """
        manifest = self.manifest()
        assert manifest is not None  # only reached for a directory pin
        path = self.path / filename
        try:
            recorded = capture.recorded_sha256(manifest, filename)
        except ValueError as exc:
            raise PinnedSnapshotError(f"The pinned capture {self.path} has an unusable manifest: {exc}") from exc
        try:
            actual = capture.sha256_file(path)
        except OSError as exc:
            raise PinnedSnapshotError(
                f"The pinned capture {self.path} records {filename} in its manifest but the "
                f"file cannot be read: {exc}"
            ) from exc
        if actual != recorded:
            raise PinnedSnapshotError(
                f"{path} does not match the pinned capture's manifest: the file hashes to "
                f"{actual}, the manifest records {recorded}. The capture has been modified "
                f"since it was written, so a measurement taken from it would not be reproducible."
            )
        return path

    def close(self) -> None:
        """No API client is ever constructed, so there is nothing to close."""

    def load(self) -> SnapshotResult:
        """Read the pinned capture. Never fetches, never writes, never falls back.

        `fetched_at` is the capture's own timestamp — the manifest's
        `captured_at` for a directory, the file's mtime for a bare file. Either
        way it is a property of the capture rather than of the run, which is
        what lets two pinned runs produce byte-identical `--json`.
        """
        source = self._verified_file(capture.BOOTSTRAP_FILENAME) if self.is_capture_directory else self.path
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise PinnedSnapshotError(f"Could not read the pinned snapshot {source}: {exc}") from exc
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise PinnedSnapshotError(f"The pinned snapshot {source} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise PinnedSnapshotError(
                f"The pinned snapshot {source} is not a bootstrap-static payload: its top "
                f"level is a {type(payload).__name__}, not an object."
            )
        # After the read, not before: for a bare file this is the path's mtime,
        # and stat-ing a missing file here would raise `FileNotFoundError` past
        # the handler that exists to name it.
        captured_at = self.captured_at()
        try:
            snapshot = BootstrapSnapshot.from_payload(payload, fetched_at=captured_at)
        except (ValidationError, TypeError, AttributeError) as exc:
            raise PinnedSnapshotError(
                f"The pinned snapshot {source} did not match the expected shape: {exc}"
            ) from exc
        return SnapshotResult(snapshot=snapshot, stale=False)

    def load_fixtures(self) -> FixturesResult:
        """Read the capture's fixtures, or the fixtures cache for a bare-file pin.

        Never fetches, never writes, never falls back. A capture's fixtures are
        not `stale`: they are the list that was live when the snapshot was
        taken, which is the whole reason FU-41 keeps them together.
        """
        if self.is_capture_directory:
            path = self._verified_file(capture.FIXTURES_FILENAME)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise PinnedSnapshotError(f"Could not read the pinned fixtures {path}: {exc}") from exc
            except ValueError as exc:
                raise PinnedSnapshotError(f"The pinned fixtures {path} are not valid JSON: {exc}") from exc
            try:
                result = _parse_fixtures_cache(payload, self.captured_at())
            except (ValidationError, TypeError) as exc:
                raise PinnedSnapshotError(
                    f"The pinned fixtures {path} did not match the expected shape: {exc}"
                ) from exc
            return replace(result, stale=False, source="pinned", path=path)

        cached = self._fixtures_cache.load_typed(_parse_fixtures_cache)
        if cached is None:
            raise PinnedSnapshotError(
                f"A pinned run never fetches, and there is no readable fixtures cache at "
                f"{self._fixtures_cache.path}. Run `fpl sync` first, or drop --snapshot."
            )
        return replace(cached, path=self._fixtures_cache.path)

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

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


# The event-live cache is an envelope around the payload, not the payload
# itself. Version 1 introduced it; before that the file was the bare API
# response, which recorded nothing about the gameweek it described.
#
# The point of the envelope is that a reader must not have to trust that the
# writer was gated correctly. `SnapshotService` only ever persists a settled
# gameweek, so in principle every file on disk is final — but "in principle"
# is exactly what a backtest cannot rely on: a file written by an older build,
# copied from another machine, or edited by hand looks identical, and the
# gameweek's *current* settled-ness says nothing about the state the bytes were
# captured in. Recording it makes the payload self-describing, so both services
# check evidence rather than inferring from the writer's good intentions.
LIVE_CACHE_VERSION = 1
SUPPORTED_LIVE_CACHE_VERSIONS = (1,)

# A cached payload is in one of three states, and the third is not a variant of
# the second. `unsettled` means the file records that the gameweek had not
# settled; `unknown` means the file records nothing either way, which is a
# different problem with a different remedy and must not be reported as though
# we had established the payload was provisional.
LIVE_SETTLED = "settled"
LIVE_UNSETTLED = "unsettled"
LIVE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class LiveEventProvenance:
    """Whether a gameweek's outcome data was final when it was captured.

    FU-40's rule applied to the third input. `bootstrap-static` and `fixtures`
    both carry where they came from; event-live did not, so a figure from
    `plan evaluate` could not say whether the actuals it scored against were
    final. FPL awards bonus points and applies stat corrections after the final
    whistle, so a payload taken at full time is materially wrong rather than
    merely early — a model evaluation against one is a wrong number, not an
    early one.

    `state` is `settled`, `unsettled` or `unknown`. `finished` and
    `data_checked` are the two flags behind it, `None` when the payload predates
    the envelope and records neither. `source` is `live` or `cache`.
    """

    state: str
    source: str
    finished: bool | None = None
    data_checked: bool | None = None
    path: Path | None = None
    detail: str | None = None

    @property
    def settled(self) -> bool:
        return self.state == LIVE_SETTLED


@dataclass(frozen=True)
class LiveEventResult:
    live: LiveEvent
    event: int
    stale: bool
    provenance: LiveEventProvenance
    reason: str | None = None


@dataclass(frozen=True)
class _DecodedLiveCache:
    """A cached event-live payload and what it records about its own finality."""

    live: LiveEvent
    state: str
    finished: bool | None = None
    data_checked: bool | None = None
    detail: str | None = None


def _parse_live_event_cache(payload: object, fetched_at: datetime) -> _DecodedLiveCache:
    """Decode either envelope shape. `fetched_at` is the file's mtime, unused.

    A payload with no `version` is the pre-envelope shape: the bare API
    response. It is decoded rather than rejected — the elements are perfectly
    good — but its state is `unknown`, because the file genuinely does not say.
    Inferring settled-ness from the contents (say, "some players have bonus, so
    bonus must have been applied") would be a heuristic dressed as evidence,
    and wrong for exactly the gameweek where it mattered.
    """
    if not isinstance(payload, dict):
        raise TypeError("event-live cache payload must be a dict")
    if "version" not in payload:
        return _DecodedLiveCache(
            live=LiveEvent.model_validate(payload),
            state=LIVE_UNKNOWN,
            detail="written before the cache recorded gameweek finality",
        )
    version = payload.get("version")
    if version not in SUPPORTED_LIVE_CACHE_VERSIONS:
        # Refused the way an unrecognised manifest version is (FU-41): a newer
        # build probably wrote it and this reader is behind, so the flags may
        # not mean what this build would take them to mean.
        return _DecodedLiveCache(
            live=LiveEvent.model_validate(payload.get("live") or {}),
            state=LIVE_UNKNOWN,
            detail=(
                f"cache version {version!r}; this build writes {LIVE_CACHE_VERSION} and reads "
                f"{', '.join(str(v) for v in SUPPORTED_LIVE_CACHE_VERSIONS)}"
            ),
        )
    live = LiveEvent.model_validate(payload.get("live") or {})
    finished = payload.get("finished")
    data_checked = payload.get("data_checked")
    if not isinstance(finished, bool) or not isinstance(data_checked, bool):
        return _DecodedLiveCache(
            live=live,
            state=LIVE_UNKNOWN,
            detail=f"records finished={finished!r}, data_checked={data_checked!r}",
        )
    settled = finished and data_checked
    return _DecodedLiveCache(
        live=live,
        state=LIVE_SETTLED if settled else LIVE_UNSETTLED,
        finished=finished,
        data_checked=data_checked,
    )


def _encode_live_cache(
    live: LiveEvent, *, event: int, finished: bool, data_checked: bool, fetched_at: datetime
) -> dict:
    """The envelope written to disk. The flags are the gameweek's state at the
    moment of the fetch, which is what a later reader needs and cannot recover."""
    return {
        "version": LIVE_CACHE_VERSION,
        "event": event,
        "fetched_at": fetched_at.isoformat(),
        "finished": finished,
        "data_checked": data_checked,
        "live": live.model_dump(mode="json"),
    }


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


def _settled_flags(snapshot: BootstrapSnapshot, event: int) -> tuple[bool, bool]:
    """`(finished, data_checked)` for one gameweek; `(False, False)` if unknown.

    The two are reported separately rather than collapsed because they mean
    different things and the gap between them is the realistic case:
    `finished=True, data_checked=False` is a gameweek whose last whistle has
    gone and whose bonus points and stat corrections have not yet been applied.
    That payload is materially wrong, not nearly right.
    """
    gameweek = next((gameweek for gameweek in snapshot.events if gameweek.id == event), None)
    if gameweek is None:
        return (False, False)
    return (gameweek.finished, gameweek.data_checked)


def _is_finalised(snapshot: BootstrapSnapshot, event: int) -> bool:
    finished, data_checked = _settled_flags(snapshot, event)
    return finished and data_checked


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

        Two gates, not one. The gameweek must be settled *now* — otherwise the
        data will still change and no cache hit is worth having — and the
        cached payload must itself record that it was settled when it was
        written. The second gate is the one this branch added: the first says
        the outcome is final today, which is a fact about the gameweek and not
        about the bytes on disk. A file written by a build without the write
        gate, or copied from a machine mid-gameweek, satisfies the first and
        fails the second, and before this it was served as final.

        An unsettled or unrecorded cache is refetched rather than refused: this
        service can reach the API, so the situation is repairable without
        troubling anyone, and the refetch rewrites the file in the recording
        format. Refusing here would be a hard failure with a live fix
        available. Only the pinned twin, which cannot fetch, refuses.
        """
        cache = JsonDocumentCache(self._event_live_cache_dir / f"{event}-live.json")
        finished, data_checked = _settled_flags(snapshot, event)
        finalised = finished and data_checked

        if finalised:
            cached = cache.load_typed(_parse_live_event_cache)
            if cached is not None and cached.state == LIVE_SETTLED:
                return LiveEventResult(
                    live=cached.live,
                    event=event,
                    stale=False,
                    provenance=LiveEventProvenance(
                        state=LIVE_SETTLED,
                        source="cache",
                        finished=cached.finished,
                        data_checked=cached.data_checked,
                        path=cache.path,
                    ),
                )

        live = self._api.event_live(event)
        if finalised:
            cache.save_raw(
                _encode_live_cache(
                    live,
                    event=event,
                    finished=finished,
                    data_checked=data_checked,
                    fetched_at=datetime.now(UTC),
                )
            )
        # A live fetch of an unsettled gameweek is served, and marked. It is the
        # freshest data in existence — there is nothing better to fall back to
        # and nothing to wait for — so refusing would deny the only answer
        # available rather than protecting anyone from a worse one. What must
        # not happen is serving it *silently*, which is what the provenance and
        # the caller's warning exist to prevent.
        return LiveEventResult(
            live=live,
            event=event,
            stale=False,
            provenance=LiveEventProvenance(
                state=LIVE_SETTLED if finalised else LIVE_UNSETTLED,
                source="live",
                finished=finished,
                data_checked=data_checked,
            ),
        )

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

        **`snapshot` is deliberately not consulted.** It is the pinned capture,
        and a capture worth pinning is a *pre-deadline* one — it says the
        gameweek is unfinished because it was taken before the gameweek was
        played, which is the whole point of it. Gating on it would refuse every
        correct backtest there is. Projection inputs and outcome data come from
        opposite sides of the deadline by design; only the payload's own record
        of its finality can speak for the outcome data.

        That record is what is checked instead. An unsettled or unrecorded
        payload is refused outright rather than warned about, because this
        service cannot fetch to repair it and a pinned run exists to produce a
        citable measurement. Scoring a model against provisional actuals does
        not yield an approximate figure — bonus points and stat corrections
        land after the whistle and fall disproportionately on the players a
        model is judged by, so it yields a wrong figure that looks valid, which
        is the failure FU-41 was urgent about for fixtures. The refusal also
        costs nothing: the only caller loads this before any projection runs
        (`cli.evaluate_plan`), so nothing has been computed or printed, and the
        remedy is one command. Refusing a missing cache and serving an
        unusable one would be the inconsistency, not the reverse.
        """
        cache = JsonDocumentCache(self._event_live_cache_dir / f"{event}-live.json")
        cached = cache.load_typed(_parse_live_event_cache)
        if cached is None:
            raise PinnedSnapshotError(
                f"A pinned run never fetches, and there is no readable GW{event} live cache at "
                f"{cache.path}. Run `fpl plan evaluate --event {event}` without --snapshot "
                f"first, or drop --snapshot."
            )
        if cached.state == LIVE_UNSETTLED:
            raise PinnedSnapshotError(
                f"The GW{event} live cache at {cache.path} was written before the gameweek "
                f"settled (finished={cached.finished}, data_checked={cached.data_checked}). FPL "
                f"awards bonus points and applies stat corrections after the final whistle, so "
                f"scoring against this payload would produce a figure that looks like a backtest "
                f"and is not one. A pinned run never fetches, so it cannot refresh it for you: "
                f"run `fpl plan evaluate --event {event}` without --snapshot once the gameweek "
                f"has settled, then pin again."
            )
        if cached.state != LIVE_SETTLED:
            raise PinnedSnapshotError(
                f"The GW{event} live cache at {cache.path} does not record whether the gameweek "
                f"had settled when it was written ({cached.detail}). A pinned run never fetches, "
                f"so it cannot establish that, and reading finality off the payload's contents "
                f"would be a guess rather than evidence — wrong for exactly the gameweek where "
                f"it mattered. Run `fpl plan evaluate --event {event}` without --snapshot once "
                f"to rewrite the cache in a format that records it, then pin again."
            )
        return LiveEventResult(
            live=cached.live,
            event=event,
            stale=False,
            provenance=LiveEventProvenance(
                state=LIVE_SETTLED,
                source="cache",
                finished=cached.finished,
                data_checked=cached.data_checked,
                path=cache.path,
            ),
        )

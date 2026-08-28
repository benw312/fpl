"""`fpl sync --archive-dir` (FU-42).

Every test here runs a real `SnapshotService` over a stub API and lets it write
to disk, because the property under test is where the bytes land — a test that
stubbed `archive()` would be asserting that an argument was passed on, which is
not the same claim.

Each assertion is mutation-tested in place: for every "nothing was written
here" there is a control run proving the same code path *does* write there
without the flag, and the byte-identity comparison is shown failing on a
payload that differs. An isolation test that passes because nothing happened at
all is the failure mode worth spending the lines on.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl_cli import cli
from fpl_cli.api import snapshots
from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.storage import capture

from test_snapshot_pinning import (  # the same synthetic capture, written by sync rather than by hand
    _capture_payload,
    fpl_home,  # noqa: F401 — re-exported pytest fixture
)

CAPTURED_AT = datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC)
UK_DATE = "2026-08-28"

_FIXTURES = [
    {"id": 1, "event": 2, "team_h": 1, "team_a": 2},
    {"id": 2, "event": 2, "team_h": 3, "team_a": 4},
]


class StubApi:
    """Returns the same payload every call, at a fixed `fetched_at`.

    The fixed time is what makes byte-identity testable at all: `captured_at`
    goes into the manifest, so two captures taken a millisecond apart would
    differ for a reason that has nothing to do with the flag.
    """

    def __init__(self, payload: dict[str, Any], fixtures: list[dict[str, Any]] | None = None) -> None:
        self._payload = payload
        self._fixtures = fixtures if fixtures is not None else _FIXTURES
        self.closed = False

    def bootstrap_static(self) -> BootstrapSnapshot:
        return BootstrapSnapshot.from_payload(copy.deepcopy(self._payload), fetched_at=CAPTURED_AT)

    def fixtures(self) -> list[Fixture]:
        return [Fixture.model_validate(fixture) for fixture in self._fixtures]

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def stub_api(monkeypatch: pytest.MonkeyPatch, bootstrap_payload: dict[str, Any]) -> StubApi:
    """Wire a stub into the API constructor `SnapshotService()` reaches for.

    `SnapshotService` is left entirely real, so the archive write under test is
    the production one.
    """
    stub = StubApi(_capture_payload(bootstrap_payload, star_name="Star"))
    monkeypatch.setattr(snapshots, "OfficialFplApi", lambda: stub)
    return stub


def _tree(directory: Path) -> dict[str, bytes]:
    """Every file in a capture, keyed by name relative to the capture root.

    The bytes, not the file list: a manifest that recorded which archive it was
    written into would produce identical names and different contents, which is
    precisely the leak this comparison exists to catch.
    """
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _captures_in(archive_dir: Path) -> list[str]:
    """Capture directory names in `archive_dir`, or `[]` if it was never created."""
    if not archive_dir.is_dir():
        return []
    return sorted(path.name for path in archive_dir.iterdir())


# --- the flag keeps a sync out of the real archive ---------------------------


def test_a_sync_with_archive_dir_writes_nothing_to_the_default_archive(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi  # noqa: F811
) -> None:
    """With the control that makes the claim mean something: the same sync
    without the flag does file into the default archive, so the empty archive
    above is the flag working rather than a sync that never archives."""
    scratch = tmp_path / "scratch"
    default_archive = fpl_home / "archive"

    cli.sync(archive_dir=scratch)

    assert _captures_in(scratch) == [UK_DATE]
    assert capture.is_valid_capture(scratch / UK_DATE)
    assert _captures_in(default_archive) == []

    # The mutation: drop the flag and the very same call writes where the
    # assertion above said nothing was written.
    cli.sync()

    assert _captures_in(default_archive) == [UK_DATE]


def test_a_scratch_capture_claims_its_own_slot_and_not_the_real_one(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi  # noqa: F811
) -> None:
    """Slot occupancy is per archive directory. A verification sync must not
    burn the day's canonical slot in the real archive — that slot is claimed
    once and never overwritten (FU-41), so spending it on a test run costs the
    day's real capture."""
    scratch = tmp_path / "scratch"

    scratch_capture = cli_sync_result(scratch)
    real_capture = cli_sync_result(None)

    # Both are canonical: the scratch run did not consume the real archive's slot.
    assert scratch_capture.role == capture.ROLE_CANONICAL
    assert real_capture.role == capture.ROLE_CANONICAL
    assert real_capture.path == fpl_home / "archive" / UK_DATE

    # The mutation: a second sync into the same archive is ad-hoc, which is what
    # the first assertion would have shown had the scratch run claimed the slot.
    assert cli_sync_result(None).role == capture.ROLE_ADHOC


def cli_sync_result(archive_dir: Path | None) -> snapshots.ArchivedCapture:
    """Run `fpl sync`, returning the `ArchivedCapture` it filed.

    `cli.sync` returns nothing and prints, so the capture is intercepted at the
    service rather than parsed back out of the console.
    """
    filed: list[snapshots.ArchivedCapture] = []
    real_archive = snapshots.SnapshotService.archive

    def recording(self: snapshots.SnapshotService, *args: Any, **kwargs: Any) -> snapshots.ArchivedCapture:
        archived = real_archive(self, *args, **kwargs)
        filed.append(archived)
        return archived

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(snapshots.SnapshotService, "archive", recording)
    try:
        cli.sync(archive_dir=archive_dir)
    finally:
        monkeypatch.undo()
    assert len(filed) == 1
    return filed[0]


# --- no environment variable redirects the archive ---------------------------


def _probe_default_archive_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    """`DEFAULT_ARCHIVE_DIR` as a *fresh* import of `api.snapshots` derives it.

    The defaults are module globals computed once at import, and the `fpl_home`
    fixture overwrites them — so a test that set a variable and then ran `sync`
    would report the fixture's value whatever the code consulted, and would pass
    just as happily against an archive wired to the variable. Executing the
    module again under the environment being tested is what makes the
    resolution observable at all. The fresh instance is loaded under a throwaway
    name and removed again, so `sys.modules` and every module holding a
    reference to the real one are untouched. It has to be registered *during*
    execution rather than after: the module defines dataclasses, and
    `dataclasses` resolves their annotations by looking the defining module up
    in `sys.modules`.
    """
    name = "_snapshots_probe"
    spec = importlib.util.spec_from_file_location(name, snapshots.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[name]
    return module.DEFAULT_ARCHIVE_DIR


def test_the_default_archive_is_derived_from_home_and_ignores_fpl_cache_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FPL_CACHE_DIR is read by nothing (FU-42): it was exported from `.envrc`
    set to the hardcoded default, so it never had an observable effect, and this
    branch removed the export rather than wiring it up.

    Pinned here so that half-wiring it later — the archive following the
    variable while the caches do not — fails rather than shipping as silent
    partial isolation.
    """
    decoy = tmp_path / "decoy-cache"
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    # The control first: the probe genuinely re-derives the default from the
    # environment it is imported under, so a variable that *were* honoured
    # would show up in it. Without this the assertion below proves nothing.
    assert _probe_default_archive_dir(monkeypatch) == fake_home / ".fpl-cli" / "archive"

    monkeypatch.setenv("FPL_CACHE_DIR", str(decoy))

    assert _probe_default_archive_dir(monkeypatch) == fake_home / ".fpl-cli" / "archive"
    assert decoy not in _probe_default_archive_dir(monkeypatch).parents


def test_a_set_fpl_cache_dir_changes_nothing_about_where_a_sync_files(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """The same claim end to end: with the variable set to somewhere obvious, a
    bare sync still files into the real archive and a flagged sync still files
    where the flag says. The flag is the only thing that moves a capture."""
    decoy = tmp_path / "decoy-cache"
    monkeypatch.setenv("FPL_CACHE_DIR", str(decoy))
    flagged = tmp_path / "flagged"

    cli.sync()
    cli.sync(archive_dir=flagged)

    assert _captures_in(fpl_home / "archive") == [UK_DATE]
    assert _captures_in(flagged) == [UK_DATE]
    assert not decoy.exists()

    # The mutation: `decoy` is a path this test can in fact write to and
    # observe, so `not decoy.exists()` is a real measurement rather than an
    # assertion about a path that could never have been created.
    cli.sync(archive_dir=decoy)
    assert _captures_in(decoy) == [UK_DATE]


def test_the_flag_beats_the_snapshot_environment_variable_being_set(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    """The one variable the CLI does read is FPL_SNAPSHOT, and `sync` is the
    command it must not reach: a pinned shell pins what runs *read*, and a sync
    that quietly stopped fetching because a variable was set would archive
    nothing while reporting success."""
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, str(tmp_path / "some-capture"))
    scratch = tmp_path / "scratch"

    cli.sync(archive_dir=scratch)

    assert _captures_in(scratch) == [UK_DATE]
    assert _captures_in(fpl_home / "archive") == []


# --- a scratch capture is a real capture -------------------------------------


def test_a_scratch_capture_is_byte_identical_to_a_default_one(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi  # noqa: F811
) -> None:
    """The flag must not put the write path into a mode. Given the same payload
    at the same instant, the two captures agree on every byte of every file,
    manifest included — so a capture filed to scratch during verification is
    still a capture, pinnable and promotable by moving the directory."""
    scratch = tmp_path / "scratch"

    cli.sync(archive_dir=scratch)
    cli.sync()

    assert _tree(scratch / UK_DATE) == _tree(fpl_home / "archive" / UK_DATE)
    # Not vacuous: there is something in there to compare.
    assert sorted(_tree(scratch / UK_DATE)) == [
        capture.BOOTSTRAP_FILENAME,
        capture.FIXTURES_FILENAME,
        capture.MANIFEST_FILENAME,
    ]


def test_the_byte_comparison_detects_a_capture_that_differs(
    tmp_path: Path, fpl_home: Path, monkeypatch: pytest.MonkeyPatch, bootstrap_payload: dict[str, Any]  # noqa: F811
) -> None:
    """The mutation control for the test above. Change one field of the payload
    and the trees must diverge — otherwise `_tree` compares nothing that varies
    and byte-identity is proved by construction rather than observed."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    monkeypatch.setattr(
        snapshots, "OfficialFplApi", lambda: StubApi(_capture_payload(bootstrap_payload, star_name="Star"))
    )
    cli.sync(archive_dir=first)
    monkeypatch.setattr(
        snapshots, "OfficialFplApi", lambda: StubApi(_capture_payload(bootstrap_payload, star_name="Different"))
    )
    cli.sync(archive_dir=second)

    assert _tree(first / UK_DATE) != _tree(second / UK_DATE)
    # Specifically in the payload and in the digest that attests to it, not in
    # some incidental field: the manifest would differ on `captured_at` alone.
    assert _tree(first / UK_DATE)[capture.BOOTSTRAP_FILENAME] != (
        _tree(second / UK_DATE)[capture.BOOTSTRAP_FILENAME]
    )
    assert capture.recorded_sha256(capture.read_manifest(first / UK_DATE), capture.BOOTSTRAP_FILENAME) != (
        capture.recorded_sha256(capture.read_manifest(second / UK_DATE), capture.BOOTSTRAP_FILENAME)
    )


def test_the_flagged_sync_still_refreshes_the_caches_in_place(
    tmp_path: Path, fpl_home: Path, stub_api: StubApi  # noqa: F811
) -> None:
    """The limitation the flag does *not* cover, asserted so it stays visible
    (FU-42). `--archive-dir` isolates the capture, which is the irreplaceable
    thing; the bootstrap and fixtures caches are still rewritten under the real
    cache root, and per FU-40 a rewritten fixtures file moves every projected
    cell. A verification sync is safe for the archive and still disruptive to an
    in-flight measurement."""
    fixtures_cache = fpl_home / "fixtures.json"
    bootstrap_cache = fpl_home / "bootstrap-static.json"
    assert not fixtures_cache.exists() and not bootstrap_cache.exists()

    cli.sync(archive_dir=tmp_path / "scratch")

    assert bootstrap_cache.is_file()
    assert fixtures_cache.is_file()

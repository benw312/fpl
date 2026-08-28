"""Capture directories (FU-41, docs/plans/snapshot-pinning.md §5).

Each test demonstrates its property rather than asserting it: the pinning tests
prove the caches *would* have been read had the capture not supplied both
files, the bare-file test proves the old shape still resolves fixtures from the
cache, and the digest test proves the capture is refused only because it was
modified, by mutating one byte of a capture that worked a line earlier.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api import snapshots
from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.storage import capture

from test_snapshot_pinning import (  # the shapes are the same capture, one directory deeper
    NetworkTouched,
    _capture_payload,
    _events,
    _write_capture,
    _write_fixtures_cache,
    _write_squad_ledger,
    fpl_home,  # noqa: F401 — re-exported pytest fixture
)

_FIXTURES = [
    {"id": 1, "event": 2, "team_h": 1, "team_a": 2},
    {"id": 2, "event": 2, "team_h": 3, "team_a": 4},
    {"id": 3, "event": 2, "team_h": 5, "team_a": 6},
]


def _write_capture_directory(
    directory: Path,
    bootstrap_payload: dict[str, Any],
    *,
    star_name: str = "Star",
    captured_at: datetime | None = None,
    fixtures: list[dict[str, Any]] | None = None,
    role: str = capture.ROLE_CANONICAL,
) -> Path:
    """A capture directory in the shape `fpl sync` writes."""
    payload = _capture_payload(bootstrap_payload, star_name=star_name)
    when = captured_at or datetime(2026, 8, 28, 7, 26, 38, tzinfo=UTC)
    return capture.write_capture(
        directory,
        bootstrap=payload,
        fixtures=fixtures if fixtures is not None else _FIXTURES,
        captured_at=when,
        current_event={"id": 1, "deadline_time": "2026-08-21T17:30:00+00:00", "deadline_passed": True},
        next_event={"id": 2, "deadline_time": "2099-01-01T17:30:00+00:00", "captured_before_deadline": True},
        role=role,
    )


def _optimise(squad_path: Path, *, snapshot_path: Path | None, json_output: bool = True) -> None:
    cli.optimise_plan(
        squad_path,
        horizon=1,
        from_event=2,
        paths=3,
        max_hit=None,
        model="naive",
        decay=0.84,
        robustness="off",
        explain=False,
        output=None,
        json_output=json_output,
        snapshot_path=snapshot_path,
    )


def _refuse_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)


def _fingerprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


# --- what sync writes -------------------------------------------------------


def _snapshot_with_current_event(
    bootstrap_snapshot: BootstrapSnapshot, *, current: int, deadline: datetime, fetched_at: datetime
) -> BootstrapSnapshot:
    for event in bootstrap_snapshot.events:
        event.is_current = event.id == current
        if event.id == current:
            event.deadline_time = deadline
    bootstrap_snapshot.fetched_at = fetched_at
    return bootstrap_snapshot


def test_archive_writes_a_capture_directory_with_a_manifest(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    fetched_at = datetime(2026, 8, 28, 0, 32, 58, tzinfo=UTC)
    snapshot = _snapshot_with_current_event(
        bootstrap_snapshot, current=1, deadline=datetime(2026, 8, 21, 17, 30, tzinfo=UTC), fetched_at=fetched_at
    )
    service = snapshots.SnapshotService(api=object(), cache=object(), archive_dir=tmp_path)

    archived = service.archive(snapshot, [Fixture(id=1, event=2, team_h=1, team_a=2)])
    directory = archived.path

    assert archived.role == capture.ROLE_CANONICAL
    assert directory == tmp_path / "2026-08-28"
    assert sorted(path.name for path in directory.iterdir()) == [
        "bootstrap-static.json",
        "fixtures.json",
        "manifest.json",
    ]
    manifest = capture.read_manifest(directory)
    # Dated by the fetch, not the clock at write time: a catch-up firing writes
    # hours late and would otherwise stamp itself with the wrong moment.
    assert manifest["captured_at"] == fetched_at.isoformat()
    assert manifest["files"]["bootstrap-static.json"]["sha256"] == capture.sha256_file(
        directory / "bootstrap-static.json"
    )
    assert manifest["files"]["fixtures.json"]["sha256"] == capture.sha256_file(directory / "fixtures.json")
    assert json.loads((directory / "fixtures.json").read_text())[0]["id"] == 1


def test_the_manifest_deadline_flag_is_true_for_a_capture_taken_after_the_deadline(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """Constructed, not waited for: a `Persistent=true` timer's catch-up firing
    lands hours from the schedule it is catching up on, so a capture dated for
    one day can easily post-date the deadline its filename appears to precede."""
    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    snapshot = _snapshot_with_current_event(
        bootstrap_snapshot, current=1, deadline=deadline, fetched_at=deadline + timedelta(hours=5)
    )
    service = snapshots.SnapshotService(api=object(), cache=object(), archive_dir=tmp_path)

    manifest = capture.read_manifest(service.archive(snapshot, []).path)

    assert manifest["current_event"] == {
        "id": 1,
        "deadline_time": deadline.isoformat(),
        "deadline_passed": True,
    }


def test_the_manifest_deadline_flag_is_false_for_a_capture_taken_before_the_deadline(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The control. Without it, `deadline_passed` could be hardcoded true —
    which is nearly always the right answer for `is_current` and so nearly
    always passes."""
    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    snapshot = _snapshot_with_current_event(
        bootstrap_snapshot, current=1, deadline=deadline, fetched_at=deadline - timedelta(minutes=1)
    )
    service = snapshots.SnapshotService(api=object(), cache=object(), archive_dir=tmp_path)

    manifest = capture.read_manifest(service.archive(snapshot, []).path)

    assert manifest["current_event"]["deadline_passed"] is False


# --- pinning to a directory -------------------------------------------------


def test_a_directory_capture_pins_both_files_and_touches_neither_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    """The capture's fixtures are used, and the fixtures cache — which holds a
    *different* list — is neither read nor written."""
    _refuse_network(monkeypatch)
    directory = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    # A cache that would give a visibly different answer if it were consulted:
    # club 6 has no GW2 fixture here, so the star player would blank.
    fixtures_cache = fpl_home / "fixtures.json"
    fixtures_cache.write_text(json.dumps([{"id": 9, "event": 2, "team_h": 1, "team_a": 2}]), encoding="utf-8")
    bootstrap_cache = fpl_home / "bootstrap-static.json"
    bootstrap_cache.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name="Cached")), encoding="utf-8")
    before = (_fingerprint(bootstrap_cache), _fingerprint(fixtures_cache))
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=directory)
    payload = json.loads(capsys.readouterr().out)

    assert payload["recommendation"]["description"].startswith("P3→Star")
    assert payload["provenance"]["snapshot"]["source"] == "pinned"
    assert payload["provenance"]["fixtures"]["source"] == "pinned"
    # Each names the file it was read from, not the directory holding both:
    # `provenance.capture.path` names that, and FU-40's citation wants a path a
    # reader can hash.
    assert payload["provenance"]["snapshot"]["path"] == str(directory / "bootstrap-static.json")
    assert payload["provenance"]["fixtures"]["path"] == str(directory / "fixtures.json")
    assert (_fingerprint(bootstrap_cache), _fingerprint(fixtures_cache)) == before


def test_the_capture_block_reports_the_manifests_captured_at_and_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    _refuse_network(monkeypatch)
    when = datetime(2026, 8, 26, 22, 32, 11, tzinfo=UTC)
    directory = _write_capture_directory(tmp_path / "2026-08-26", bootstrap_payload, captured_at=when)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=directory)
    payload = json.loads(capsys.readouterr().out)

    assert payload["provenance"]["capture"] == {
        "path": str(directory),
        "captured_at": when.isoformat(),
        "current_event": {"id": 1, "deadline_time": "2026-08-21T17:30:00+00:00", "deadline_passed": True},
    }
    # The snapshot's own captured_at is the manifest's, not a file mtime — the
    # directory was written seconds ago, the capture was taken in August.
    assert payload["provenance"]["snapshot"]["captured_at"] == when.isoformat()


def test_two_runs_against_one_capture_directory_produce_identical_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    _refuse_network(monkeypatch)
    directory = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=directory)
    first = capsys.readouterr().out
    _optimise(squad_path, snapshot_path=directory)
    second = capsys.readouterr().out

    assert first == second
    assert json.loads(first)["provenance"]["capture"]["captured_at"]  # not identically empty


def test_a_copied_capture_keeps_its_captured_at(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    """The manifest is the authority, so `cp -r` does not re-date a capture —
    which is exactly what mtime-dating got wrong."""
    _refuse_network(monkeypatch)
    when = datetime(2026, 8, 25, 15, 12, 3, tzinfo=UTC)
    original = _write_capture_directory(tmp_path / "original", bootstrap_payload, captured_at=when)
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=copied)
    payload = json.loads(capsys.readouterr().out)

    assert payload["provenance"]["snapshot"]["captured_at"] == when.isoformat()
    assert datetime.fromtimestamp(copied.stat().st_mtime, UTC) > when  # the copy really is newer


# --- the bare-file shape still works ----------------------------------------


def test_a_bare_file_capture_still_pins_and_reports_fixtures_as_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    """The four pre-FU-41 archives are bare files, and one of them is the only
    pre-deadline capture for GW2. Breaking them is not an option."""
    _refuse_network(monkeypatch)
    bare = _write_capture(tmp_path / "gw2-pre-deadline.json", bootstrap_payload)
    fixtures_cache = _write_fixtures_cache(fpl_home)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=bare)
    payload = json.loads(capsys.readouterr().out)

    assert payload["recommendation"]["description"].startswith("P3→Star")
    assert payload["provenance"]["snapshot"]["source"] == "pinned"
    assert payload["provenance"]["snapshot"]["path"] == str(bare)
    # Fixtures came from the cache, and say so — the whole reason FU-41 exists.
    assert payload["provenance"]["fixtures"]["source"] == "cache"
    assert payload["provenance"]["fixtures"]["path"] == str(fixtures_cache)
    assert payload["provenance"]["capture"] is None


# --- integrity --------------------------------------------------------------


def test_a_sha256_mismatch_is_a_hard_error_naming_the_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    """Demonstrated by mutation: the same capture is loaded successfully first,
    then one byte of its fixtures file is changed and the run is refused."""
    _refuse_network(monkeypatch)
    directory = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=directory)
    assert json.loads(capsys.readouterr().out)["provenance"]["fixtures"]["source"] == "pinned"

    fixtures_file = directory / "fixtures.json"
    tampered = json.loads(fixtures_file.read_text())
    tampered[0]["event"] = 3
    fixtures_file.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        _optimise(squad_path, snapshot_path=directory)

    assert exit_info.value.exit_code == 1
    err = capsys.readouterr().err
    assert str(fixtures_file) in err
    assert "manifest" in err.lower()


def test_a_tampered_bootstrap_file_is_refused_too(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    _refuse_network(monkeypatch)
    directory = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    bootstrap_file = directory / "bootstrap-static.json"
    payload = json.loads(bootstrap_file.read_text())
    payload["elements"][0]["now_cost"] = 999
    bootstrap_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=directory
        )

    assert exit_info.value.exit_code == 1
    err = capsys.readouterr().err
    assert str(bootstrap_file) in err
    assert "manifest" in err.lower()


def test_a_directory_without_a_manifest_is_a_hard_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    """A directory is never silently treated as something else."""
    _refuse_network(monkeypatch)
    directory = tmp_path / "not-a-capture"
    directory.mkdir()
    _write_capture(directory / "bootstrap-static.json", bootstrap_payload)

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=directory
        )

    assert exit_info.value.exit_code == 1
    err = capsys.readouterr().err
    assert str(directory) in err
    assert "manifest.json" in err


def test_an_unreadable_manifest_version_is_refused_rather_than_guessed_at(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,  # noqa: F811
    bootstrap_payload: dict[str, Any],
) -> None:
    _refuse_network(monkeypatch)
    directory = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = capture.MANIFEST_VERSION + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=directory
        )

    assert exit_info.value.exit_code == 1
    assert str(manifest_path) in capsys.readouterr().err


# --- plan evaluate keeps finding archives -----------------------------------


def test_the_archive_scan_reads_both_shapes_and_prefers_the_newer_capture(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    """The four pre-FU-41 bare files stay selectable, and a capture directory
    is dated by its manifest rather than by its mtime — which is why a capture
    written moments ago can still be the *older* candidate."""
    from fpl_cli.domain.evaluation import select_archived_snapshot

    bare = tmp_path / "bootstrap-2026-08-25.json"
    bare.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name="Bare")), encoding="utf-8")
    old = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    _write_capture_directory(tmp_path / "2026-08-20", bootstrap_payload, captured_at=old)

    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    # The bare file's mtime is now, so it does not qualify; the directory does,
    # on its manifest date rather than its own mtime.
    assert select_archived_snapshot(tmp_path, deadline) == tmp_path / "2026-08-20" / "bootstrap-static.json"

    # And with a deadline after both, the bare file wins on recency.
    assert select_archived_snapshot(tmp_path, datetime(2099, 1, 1, tzinfo=UTC)) == bare


# --- capture roles (FU-41) --------------------------------------------------


def _sync_service(archive_dir: Path) -> snapshots.SnapshotService:
    return snapshots.SnapshotService(api=object(), cache=object(), archive_dir=archive_dir)


def _capture_snapshot(
    bootstrap_snapshot: BootstrapSnapshot, *, fetched_at: datetime
) -> BootstrapSnapshot:
    for event in bootstrap_snapshot.events:
        event.is_current = event.id == 1
        event.is_next = event.id == 2
        if event.id == 1:
            event.deadline_time = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
        if event.id == 2:
            event.deadline_time = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)
    bootstrap_snapshot.fetched_at = fetched_at
    return bootstrap_snapshot


def test_the_first_capture_of_a_day_is_canonical_and_the_second_is_adhoc(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """Demonstrated by writing both: the same call claims the slot once, and
    files itself by instant the second time."""
    service = _sync_service(tmp_path)
    # `_capture_snapshot` mutates the shared fixture, so the morning timestamp
    # is held here rather than read back off the object afterwards.
    morning_at = datetime(2026, 8, 28, 0, 32, 58, tzinfo=UTC)
    first = service.archive(_capture_snapshot(bootstrap_snapshot, fetched_at=morning_at), [])

    assert first.role == capture.ROLE_CANONICAL
    assert first.path == tmp_path / "2026-08-28"
    assert capture.read_manifest(first.path)["role"] == "canonical"

    evening = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 8, 28, 20, 11, 4, tzinfo=UTC))
    second = service.archive(evening, [])

    assert second.role == capture.ROLE_ADHOC
    assert second.path == tmp_path / "2026-08-28T201104Z"
    assert capture.read_manifest(second.path)["role"] == "adhoc"
    # The canonical capture is untouched, not overwritten by the later one.
    assert capture.manifest_captured_at(capture.read_manifest(first.path)) == morning_at


def test_an_empty_slot_is_claimed_whenever_the_day_s_first_capture_arrives(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The offline case, without inspecting timer state: nothing ran overnight,
    someone syncs at noon, and that capture is the day's canonical one."""
    noon = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC))

    archived = _sync_service(tmp_path).archive(noon, [])

    assert archived.role == capture.ROLE_CANONICAL
    assert archived.path == tmp_path / "2026-08-28"


def test_a_legacy_bare_file_holds_the_slot_against_a_later_capture(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The state this branch actually left on disk: `bootstrap-2026-08-28.json`
    from 00:32 and a directory written the same morning."""
    (tmp_path / "bootstrap-2026-08-28.json").write_text("{}", encoding="utf-8")
    later = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC))

    archived = _sync_service(tmp_path).archive(later, [])

    assert archived.role == capture.ROLE_ADHOC
    assert archived.path == tmp_path / "2026-08-28T090135Z"
    assert (tmp_path / "bootstrap-2026-08-28.json").read_text() == "{}"  # not migrated, not deleted


def _tree(directory: Path) -> dict[str, bytes]:
    """Every file in a capture, by relative name. The comparison for "nothing
    was touched" has to be the bytes; a surviving directory with rewritten
    contents is exactly the failure being guarded against."""
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_an_occupied_slot_blocks_the_claim_even_when_this_build_cannot_read_it(
    tmp_path: Path, bootstrap_payload: dict[str, Any], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """A capture claims a slot only when the slot is empty.

    "This build cannot read it" and "this is rubbish" are indistinguishable from
    inside, and the difference between them is a day's snapshot that can never
    be fetched again. So occupancy blocks the claim, and the occupant is moved
    aside rather than cleared away.
    """
    slot = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    when = datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC)
    assert capture.slot_claimed(tmp_path, when)

    tampered = json.loads((slot / "fixtures.json").read_text())
    tampered.append({"id": 99, "event": 2, "team_h": 1, "team_a": 2})
    (slot / "fixtures.json").write_text(json.dumps(tampered), encoding="utf-8")

    # Still claimed: the slot is occupied, whether or not the occupant verifies.
    assert capture.slot_claimed(tmp_path, when)
    assert not capture.is_valid_capture(slot)

    archived = _sync_service(tmp_path).archive(_capture_snapshot(bootstrap_snapshot, fetched_at=when), [])

    assert archived.role == capture.ROLE_ADHOC
    assert archived.problem.kind == capture.PROBLEM_UNVERIFIABLE


def test_writing_never_replaces_anything_at_all(tmp_path: Path, bootstrap_payload: dict[str, Any]) -> None:
    """Not "never replaces a *valid* capture": an existing directory is refused
    whatever is in it, because deciding it was worthless is the mistake."""
    slot = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    before = _tree(slot)

    with pytest.raises(FileExistsError):
        _write_capture_directory(slot, bootstrap_payload, star_name="Replacement")

    assert _tree(slot) == before

    unreadable = tmp_path / "2026-08-27"
    unreadable.mkdir()
    (unreadable / "bootstrap-static.json").write_text('{"elements": [', encoding="utf-8")
    rubble = _tree(unreadable)

    with pytest.raises(FileExistsError):
        _write_capture_directory(unreadable, bootstrap_payload, star_name="Replacement")

    assert _tree(unreadable) == rubble


def test_a_failed_write_leaves_no_capture_in_the_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    """Staging plus rename, demonstrated: a write that dies partway leaves the
    slot empty rather than partially filled."""
    real_sha = capture.sha256_file
    calls: list[Path] = []

    def explode(path: Path) -> str:
        calls.append(path)
        if len(calls) > 1:  # after bootstrap-static.json, before the manifest
            raise OSError("disk full")
        return real_sha(path)

    monkeypatch.setattr(capture, "sha256_file", explode)

    with pytest.raises(OSError):
        _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)

    assert not (tmp_path / "2026-08-28").exists()
    assert list(tmp_path.iterdir()) == []  # not even a staging directory left behind


# --- UK dates ---------------------------------------------------------------


def test_the_canonical_slot_uses_the_uk_date_not_the_utc_date(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """23:30 UTC in summer is 00:30 the next day in London. Filing it under the
    UTC date would put it in the slot the following night's capture is entitled
    to — and `captured_at` stays UTC either way."""
    late = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 7, 15, 23, 30, tzinfo=UTC))

    archived = _sync_service(tmp_path).archive(late, [])

    assert archived.path == tmp_path / "2026-07-16"
    assert capture.read_manifest(archived.path)["captured_at"] == "2026-07-15T23:30:00+00:00"


def test_a_winter_capture_at_the_same_clock_time_files_under_the_utc_date(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The control: in January the UK is on UTC, so the same 23:30 stays on the
    same date. Without it, the test above would also pass under a hardcoded
    +1 day."""
    late = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 1, 15, 23, 30, tzinfo=UTC))

    assert _sync_service(tmp_path).archive(late, []).path == tmp_path / "2026-01-15"


# --- manifest deadline fields ----------------------------------------------


def test_the_manifest_records_the_next_event_and_whether_the_capture_precedes_it(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """`current_event` cannot answer this: for a GW2 pre-deadline capture the
    current gameweek is GW1, whose deadline passed a week earlier."""
    before = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 8, 28, 7, 26, 38, tzinfo=UTC))

    manifest = capture.read_manifest(_sync_service(tmp_path).archive(before, []).path)

    assert manifest["current_event"] == {
        "id": 1,
        "deadline_time": "2026-08-21T17:30:00+00:00",
        "deadline_passed": True,
    }
    assert manifest["next_event"] == {
        "id": 2,
        "deadline_time": "2026-08-28T17:30:00+00:00",
        "captured_before_deadline": True,
    }


def test_the_next_event_flag_is_false_for_a_capture_taken_after_that_deadline(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    after = _capture_snapshot(bootstrap_snapshot, fetched_at=datetime(2026, 8, 28, 20, 11, 4, tzinfo=UTC))

    manifest = capture.read_manifest(_sync_service(tmp_path).archive(after, []).path)

    assert manifest["next_event"]["captured_before_deadline"] is False
    # And the leak-check field still reports the current gameweek, unchanged.
    assert manifest["current_event"]["deadline_passed"] is True


# --- the archive scan and roles --------------------------------------------


def test_the_archive_scan_skips_adhoc_captures_unless_asked_for_them(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    from fpl_cli.domain.evaluation import select_archived_snapshot

    canonical = _write_capture_directory(
        tmp_path / "2026-08-20", bootstrap_payload, captured_at=datetime(2026, 8, 20, 0, 30, tzinfo=UTC)
    )
    adhoc = _write_capture_directory(
        tmp_path / "2026-08-20T191500Z",
        bootstrap_payload,
        captured_at=datetime(2026, 8, 20, 19, 15, tzinfo=UTC),
        role=capture.ROLE_ADHOC,
    )
    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)

    # The ad-hoc capture is newer, and would win if it were a candidate at all.
    assert select_archived_snapshot(tmp_path, deadline) == canonical / "bootstrap-static.json"
    assert (
        select_archived_snapshot(tmp_path, deadline, include_adhoc=True) == adhoc / "bootstrap-static.json"
    )


def test_a_version_1_capture_reads_as_adhoc_so_the_bare_file_keeps_its_day(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    """The state on disk today: a v1 directory beside the bare file that has
    held 2026-08-28 since 00:32. A manifest that records no role must not claim
    a slot retrospectively."""
    from fpl_cli.domain.evaluation import select_archived_snapshot

    directory = _write_capture_directory(
        tmp_path / "2026-08-28", bootstrap_payload, captured_at=datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC)
    )
    manifest_path = directory / "manifest.json"
    legacy = json.loads(manifest_path.read_text())
    legacy["version"] = 1
    del legacy["role"]
    manifest_path.write_text(json.dumps(legacy), encoding="utf-8")

    bare = tmp_path / "bootstrap-2026-08-28.json"
    bare.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name="Bare")), encoding="utf-8")

    assert capture.manifest_role(capture.read_manifest(directory)) == capture.ROLE_ADHOC
    assert select_archived_snapshot(tmp_path, datetime(2099, 1, 1, tzinfo=UTC)) == bare
    # Still readable when pinned to explicitly — excluded from selection, not rejected.
    assert capture.is_valid_capture(directory)


# --- plan evaluate dates by the manifest ------------------------------------


def test_the_projection_snapshot_is_dated_by_the_manifest_not_the_mtime(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    """Fails if a capture's mtime and `captured_at` disagree and mtime wins —
    which is the state every ad-hoc and every copied capture is in."""
    from fpl_cli.domain.evaluation import archived_capture_time

    when = datetime(2026, 8, 20, 0, 30, tzinfo=UTC)
    directory = _write_capture_directory(tmp_path / "2026-08-20", bootstrap_payload, captured_at=when)
    bootstrap = directory / "bootstrap-static.json"
    mtime = datetime.fromtimestamp(bootstrap.stat().st_mtime, UTC)

    assert mtime != when  # the disagreement the test turns on
    assert archived_capture_time(bootstrap) == when


def test_a_bare_archive_is_still_dated_by_its_mtime(tmp_path: Path, bootstrap_payload: dict[str, Any]) -> None:
    """The control, and the reason the pre-FU-41 archives keep working: mtime is
    all a bare file records."""
    from fpl_cli.domain.evaluation import archived_capture_time

    bare = tmp_path / "bootstrap-2026-08-25.json"
    bare.write_text("{}", encoding="utf-8")

    assert archived_capture_time(bare) == datetime.fromtimestamp(bare.stat().st_mtime, UTC)


# --- an existing capture is never destroyed ---------------------------------


def _sync_over(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot, *, at: datetime
) -> snapshots.ArchivedCapture:
    return _sync_service(tmp_path).archive(_capture_snapshot(bootstrap_snapshot, fetched_at=at), [])


def test_a_capture_from_a_newer_build_survives_a_sync_byte_for_byte(
    tmp_path: Path, bootstrap_payload: dict[str, Any], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The case a `git bisect` reaches. An older checkout cannot read a newer
    manifest, and must not conclude from that that the capture is rubbish — a
    day's snapshot cannot be fetched again."""
    slot = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload, star_name="Newer")
    manifest_path = slot / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = capture.MANIFEST_VERSION + 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _tree(slot)

    archived = _sync_over(tmp_path, bootstrap_snapshot, at=datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC))

    assert archived.role == capture.ROLE_ADHOC
    assert archived.problem.kind == capture.PROBLEM_UNRECOGNISED_VERSION
    # Present, under a new name, and identical in every byte.
    assert archived.quarantined == tmp_path / "2026-08-28.unreadable-20260828T090135Z"
    assert archived.quarantined.is_dir()
    assert _tree(archived.quarantined) == before
    assert not slot.exists()  # moved, not copied


def test_a_corrupt_capture_survives_a_sync_byte_for_byte(
    tmp_path: Path, bootstrap_payload: dict[str, Any], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The other kind. Preserved on exactly the same terms — the point is that
    the two are indistinguishable from inside, so neither is ever deleted."""
    slot = _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload, star_name="Corrupt")
    (slot / "manifest.json").write_text('{"version": 2, "captured_at":', encoding="utf-8")
    before = _tree(slot)

    archived = _sync_over(tmp_path, bootstrap_snapshot, at=datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC))

    assert archived.role == capture.ROLE_ADHOC
    assert archived.problem.kind == capture.PROBLEM_UNVERIFIABLE
    assert _tree(archived.quarantined) == before


def test_quarantining_twice_in_one_second_does_not_overwrite_the_first(
    tmp_path: Path, bootstrap_payload: dict[str, Any], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The quarantine name is timestamped, so two in the same second would
    collide — and a collision here would destroy the thing being preserved."""
    at = datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC)
    _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload, star_name="First")
    (tmp_path / "2026-08-28" / "manifest.json").write_text("{", encoding="utf-8")
    first = _sync_over(tmp_path, bootstrap_snapshot, at=at).quarantined

    _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload, star_name="Second")
    (tmp_path / "2026-08-28" / "manifest.json").write_text("{", encoding="utf-8")
    second = _sync_over(tmp_path, bootstrap_snapshot, at=at).quarantined

    assert first != second
    assert b"First" in (first / "bootstrap-static.json").read_bytes()
    assert b"Second" in (second / "bootstrap-static.json").read_bytes()
    # The ad-hoc captures collide on the same truncated timestamp and must
    # de-duplicate too — the refuse-to-overwrite guard turns a collision there
    # into a crashed sync rather than a lost capture, but a crashed sync is
    # still a sync that did not archive.
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("2026-08-28T")) == [
        "2026-08-28T090135Z",
        "2026-08-28T090135Z-2",
    ]


def test_an_empty_slot_still_claims_after_a_quarantine_clears_it(
    tmp_path: Path, bootstrap_payload: dict[str, Any], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The quarantined run files ad-hoc even though the slot it vacated is now
    empty — promoting yourself over a capture nobody has looked at is how the
    looking never happens. The *next* day's sync claims normally."""
    _write_capture_directory(tmp_path / "2026-08-28", bootstrap_payload)
    (tmp_path / "2026-08-28" / "manifest.json").write_text("{", encoding="utf-8")

    quarantining = _sync_over(tmp_path, bootstrap_snapshot, at=datetime(2026, 8, 28, 9, 1, 35, tzinfo=UTC))
    assert quarantining.role == capture.ROLE_ADHOC
    assert not (tmp_path / "2026-08-28").exists()

    tomorrow = _sync_over(tmp_path, bootstrap_snapshot, at=datetime(2026, 8, 29, 0, 30, 0, tzinfo=UTC))
    assert tomorrow.role == capture.ROLE_CANONICAL
    assert tomorrow.path == tmp_path / "2026-08-29"


def test_the_archive_scan_never_selects_a_quarantined_capture(
    tmp_path: Path, bootstrap_payload: dict[str, Any]
) -> None:
    """Quarantine exists to make someone look. A capture a later build happens
    to be able to read must not slide back into automatic use first."""
    from fpl_cli.domain.evaluation import select_archived_snapshot

    canonical = _write_capture_directory(
        tmp_path / "2026-08-20", bootstrap_payload, captured_at=datetime(2026, 8, 20, 0, 30, tzinfo=UTC)
    )
    quarantined = _write_capture_directory(
        tmp_path / "2026-08-21.unreadable-20260828T090135Z",
        bootstrap_payload,
        captured_at=datetime(2026, 8, 21, 0, 30, tzinfo=UTC),
    )
    deadline = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)

    # Readable, newer, canonical in its own manifest — and still not a candidate.
    assert capture.is_valid_capture(quarantined)
    assert select_archived_snapshot(tmp_path, deadline) == canonical / "bootstrap-static.json"
    assert select_archived_snapshot(tmp_path, deadline, include_adhoc=True) == (
        canonical / "bootstrap-static.json"
    )


# --- what sync tells the operator -------------------------------------------


def _sync_with(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot, archived: snapshots.ArchivedCapture
) -> None:
    class Stub:
        def __init__(self, archive_dir: Path | None = None) -> None:
            # `sync` now constructs the service with `--archive-dir`; these
            # tests are about what it prints, so the value is accepted and
            # ignored. Its routing is covered in `test_archive_dir.py`.
            self.archive_dir = archive_dir

        def refresh(self) -> BootstrapSnapshot:
            return bootstrap_snapshot

        def refresh_fixtures(self) -> list[Fixture]:
            return []

        def archive(self, snapshot: BootstrapSnapshot, fixtures: list[Fixture]) -> snapshots.ArchivedCapture:
            return archived

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli, "SnapshotService", Stub)
    cli.sync()


def test_sync_warns_that_an_unreadable_capture_may_be_from_a_newer_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    _sync_with(
        monkeypatch,
        bootstrap_snapshot,
        snapshots.ArchivedCapture(
            path=Path("/archive/2026-08-28T090135Z"),
            role=capture.ROLE_ADHOC,
            quarantined=Path("/archive/2026-08-28.unreadable-20260828T090135Z"),
            problem=capture.CaptureProblem(capture.PROBLEM_UNRECOGNISED_VERSION, "manifest version 3"),
        ),
    )

    out = capsys.readouterr().out
    assert "newer build" in out
    assert "Nothing has been deleted" in out
    assert "/archive/2026-08-28.unreadable-20260828T090135Z" in out
    assert "manifest version 3" in out


def test_sync_says_a_corrupt_capture_did_not_verify_rather_than_blaming_the_build(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The control: the two kinds must not produce the same sentence, or the
    distinction is decorative."""
    _sync_with(
        monkeypatch,
        bootstrap_snapshot,
        snapshots.ArchivedCapture(
            path=Path("/archive/2026-08-28T090135Z"),
            role=capture.ROLE_ADHOC,
            quarantined=Path("/archive/2026-08-28.unreadable-20260828T090135Z"),
            problem=capture.CaptureProblem(capture.PROBLEM_UNVERIFIABLE, "fixtures.json hashes to abc"),
        ),
    )

    out = capsys.readouterr().out
    assert "does not verify" in out
    assert "newer build" not in out
    assert "Nothing has been deleted" in out


def test_sync_says_nothing_about_quarantine_when_there_was_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    _sync_with(
        monkeypatch,
        bootstrap_snapshot,
        snapshots.ArchivedCapture(path=Path("/archive/2026-08-28"), role=capture.ROLE_CANONICAL),
    )

    out = capsys.readouterr().out
    assert "as canonical" in out
    assert "moved aside" not in out

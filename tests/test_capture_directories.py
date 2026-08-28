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

    directory = service.archive(snapshot, [Fixture(id=1, event=2, team_h=1, team_a=2)])

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

    manifest = capture.read_manifest(service.archive(snapshot, []))

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

    manifest = capture.read_manifest(service.archive(snapshot, []))

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

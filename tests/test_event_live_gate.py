"""The event-live settled-ness gate, on both services (snapshot-pinning.md §5).

`SnapshotService` gated on the *gameweek's* finality before preferring a cached
payload; `PinnedSnapshotService` did not gate at all. Neither checked what the
payload on disk recorded about itself, because until this branch it recorded
nothing — so a cache written at full time, before bonus points and stat
corrections landed, was served as final once the gameweek settled.

Every test demonstrates its property rather than asserting it. "Not served
silently" is shown by giving the cache and the live API *different* payloads and
reading which one came back, so a test cannot pass because nothing was served;
and each demonstration carries its control — the same setup with the payload
marked settled, which must behave the opposite way. An assertion that only ever
sees one arm of the branch is not measuring the branch.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl_cli import cli
from fpl_cli.api import snapshots
from fpl_cli.api.models import BootstrapSnapshot, GameSettings, Gameweek, LiveEvent
from fpl_cli.api.snapshots import (
    LIVE_SETTLED,
    LIVE_UNKNOWN,
    LIVE_UNSETTLED,
    LiveEventProvenance,
    LiveEventResult,
    PinnedSnapshotError,
    PinnedSnapshotService,
    SnapshotService,
)

# The two payloads are told apart by `total_points`, because that is what
# `actuals_from_live_event` reads and therefore what a wrong answer would
# corrupt. FROM_CACHE is a full-time payload: bonus not yet applied. FROM_LIVE
# is the same player after settlement, three bonus points richer — the exact
# difference the gate exists to keep out of a backtest.
CACHE_POINTS = 6
LIVE_POINTS = 9


def _payload(total_points: int) -> dict[str, Any]:
    return {
        "elements": [
            {
                "id": 1,
                "stats": {"minutes": 90, "total_points": total_points, "played": True},
                "explain": [],
                "modified": False,
            }
        ]
    }


def _snapshot(*, finished: bool = True, data_checked: bool = True) -> BootstrapSnapshot:
    """A current snapshot whose GW1 is in whatever state the test needs."""
    return BootstrapSnapshot(
        events=[
            Gameweek(id=1, name="GW1", finished=finished, data_checked=data_checked),
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
    """Serves `FROM_LIVE` and counts how often it was asked."""

    def __init__(self, total_points: int = LIVE_POINTS) -> None:
        self._live = LiveEvent.model_validate(_payload(total_points))
        self.calls = 0

    def event_live(self, event: int) -> LiveEvent:
        self.calls += 1
        return self._live

    def close(self) -> None:
        pass


def _write_cache(
    directory: Path,
    event: int = 1,
    *,
    finished: bool | None = True,
    data_checked: bool | None = True,
    total_points: int = CACHE_POINTS,
    version: int | None = snapshots.LIVE_CACHE_VERSION,
    legacy: bool = False,
) -> Path:
    """Write an event-live cache file in whichever shape the test needs.

    `legacy=True` writes the pre-envelope shape — the bare API response, which
    is what is actually on this machine today and records nothing about
    finality. Otherwise an envelope is written, with `finished` and
    `data_checked` set to whatever is asked for including non-boolean rubbish,
    so the reader's handling of a malformed record is exercised by a real file
    rather than by a mock.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{event}-live.json"
    if legacy:
        payload: dict[str, Any] = _payload(total_points)
    else:
        payload = {
            "version": version,
            "event": event,
            "fetched_at": datetime(2026, 8, 23, 20, 0, tzinfo=UTC).isoformat(),
            "finished": finished,
            "data_checked": data_checked,
            "live": _payload(total_points),
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _points(result: LiveEventResult) -> int:
    return result.live.elements[0].stats["total_points"]


# --- an unsettled cached payload is never served silently --------------------


def test_the_unpinned_service_refetches_an_unsettled_cache_instead_of_serving_it(
    tmp_path: Path,
) -> None:
    """Demonstrated by making the two sources disagree: the cache says 6 points,
    the API says 9. Whichever number comes back names the source."""
    _write_cache(tmp_path, finished=True, data_checked=False)
    api = StubApi()
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    result = service.load_event_live(1, _snapshot())

    assert _points(result) == LIVE_POINTS
    assert api.calls == 1

    # The control. The identical file marked settled is served from disk and the
    # API is never touched — so the refetch above was caused by the recorded
    # state, not by an unreadable file or a service that always fetches.
    _write_cache(tmp_path, finished=True, data_checked=True)
    control_api = StubApi()
    control = SnapshotService(api=control_api, event_live_cache_dir=tmp_path).load_event_live(1, _snapshot())

    assert _points(control) == CACHE_POINTS
    assert control_api.calls == 0


def test_a_pinned_run_refuses_an_unsettled_cache_rather_than_serving_it(tmp_path: Path) -> None:
    """The pinned twin cannot refetch, so the same condition is a hard error.
    Demonstrated through the message: it must name the file and both flags, or
    it cannot be acted on."""
    path = _write_cache(tmp_path, finished=True, data_checked=False)
    service = PinnedSnapshotService(tmp_path / "capture.json", event_live_cache_dir=tmp_path)

    with pytest.raises(PinnedSnapshotError) as error:
        service.load_event_live(1, _snapshot())

    message = str(error.value)
    assert str(path) in message
    assert "data_checked=False" in message
    assert "bonus" in message
    assert "without --snapshot" in message  # the remedy, not just the diagnosis

    # The control: the identical file marked settled is served, so the refusal
    # is the recorded state and not the pinned service refusing caches at large.
    _write_cache(tmp_path, finished=True, data_checked=True)
    assert _points(service.load_event_live(1, _snapshot())) == CACHE_POINTS


def test_a_legacy_cache_recording_no_finality_is_not_served_as_final(tmp_path: Path) -> None:
    """The pre-envelope shape, which is what `~/.fpl-cli/events/1-live.json`
    holds today. It cannot be shown to be settled, so the unpinned service
    refetches it and the pinned one refuses — the same two answers as for an
    unsettled payload, reached for a different reason, and the pinned message
    must say which reason or the remedy is wrong.

    The two services get their own cache directories because the unpinned one
    repairs what it refetches — sharing a directory would leave the pinned
    service reading a healed file and passing for the wrong reason.
    """
    unpinned_dir, pinned_dir = tmp_path / "unpinned", tmp_path / "pinned"
    _write_cache(unpinned_dir, legacy=True)
    path = _write_cache(pinned_dir, legacy=True)
    api = StubApi()

    result = SnapshotService(api=api, event_live_cache_dir=unpinned_dir).load_event_live(1, _snapshot())

    assert _points(result) == LIVE_POINTS
    assert api.calls == 1

    with pytest.raises(PinnedSnapshotError) as error:
        PinnedSnapshotService(tmp_path / "capture.json", event_live_cache_dir=pinned_dir).load_event_live(
            1, _snapshot()
        )

    message = str(error.value)
    assert str(path) in message
    assert "does not record whether" in message
    # Distinct from the unsettled message: reporting "written before it settled"
    # for a file that says nothing either way would be inventing the finding.
    assert "was written before the gameweek settled" not in message


def test_a_refetch_rewrites_the_cache_in_the_recording_format(tmp_path: Path) -> None:
    """The refetch is a repair, not just an avoidance: the legacy file that
    forced it is replaced by one that records its own finality, so the next
    pinned run works. Without this the unpinned path would refetch for ever and
    the pinned path would refuse for ever."""
    _write_cache(tmp_path, legacy=True)
    assert "version" not in json.loads((tmp_path / "1-live.json").read_text())

    SnapshotService(api=StubApi(), event_live_cache_dir=tmp_path).load_event_live(1, _snapshot())

    rewritten = json.loads((tmp_path / "1-live.json").read_text())
    assert rewritten["version"] == snapshots.LIVE_CACHE_VERSION
    assert (rewritten["finished"], rewritten["data_checked"]) == (True, True)
    # And the pinned service, which refused a moment ago, now serves it.
    pinned = PinnedSnapshotService(tmp_path / "capture.json", event_live_cache_dir=tmp_path)
    assert _points(pinned.load_event_live(1, _snapshot())) == LIVE_POINTS


# --- finished and data_checked are separate questions ------------------------


@pytest.mark.parametrize(
    ("finished", "data_checked", "expected"),
    [
        (True, True, LIVE_SETTLED),
        (True, False, LIVE_UNSETTLED),  # the realistic post-whistle case
        (False, False, LIVE_UNSETTLED),
        (False, True, LIVE_UNSETTLED),
    ],
)
def test_only_finished_and_data_checked_together_mean_final(
    tmp_path: Path, finished: bool, data_checked: bool, expected: str
) -> None:
    """The pairs are exercised separately because collapsing them is the exact
    mistake: `finished=True, data_checked=False` is a gameweek whose last
    whistle has gone and whose bonus has not been applied, and reading
    `finished` alone would call that final."""
    _write_cache(tmp_path, finished=finished, data_checked=data_checked)

    decoded = snapshots._parse_live_event_cache(
        json.loads((tmp_path / "1-live.json").read_text()), datetime.now(UTC)
    )

    assert decoded.state == expected
    assert (decoded.finished, decoded.data_checked) == (finished, data_checked)


def test_the_post_whistle_case_is_refused_end_to_end_by_both_services(tmp_path: Path) -> None:
    """`finished=True, data_checked=False` carried all the way through both
    services, not just through the decoder — a gate that classified correctly
    and then served anyway would pass the test above.

    A directory each: the unpinned service rewrites the file it refetches, and
    a shared directory would hand the pinned service a healed cache."""
    unpinned_dir, pinned_dir = tmp_path / "unpinned", tmp_path / "pinned"
    _write_cache(unpinned_dir, finished=True, data_checked=False)
    _write_cache(pinned_dir, finished=True, data_checked=False)
    api = StubApi()

    assert _points(
        SnapshotService(api=api, event_live_cache_dir=unpinned_dir).load_event_live(1, _snapshot())
    ) == LIVE_POINTS
    with pytest.raises(PinnedSnapshotError, match="finished=True, data_checked=False"):
        PinnedSnapshotService(tmp_path / "capture.json", event_live_cache_dir=pinned_dir).load_event_live(
            1, _snapshot()
        )


def test_a_malformed_finality_record_is_unknown_rather_than_unsettled(tmp_path: Path) -> None:
    """A file recording `finished: "yes"` says nothing this build can read. It
    must classify as unknown, not as unsettled — the remedies differ, and
    claiming the gameweek had not settled would be a finding we do not have."""
    _write_cache(tmp_path, finished="yes", data_checked=None)  # type: ignore[arg-type]

    decoded = snapshots._parse_live_event_cache(
        json.loads((tmp_path / "1-live.json").read_text()), datetime.now(UTC)
    )

    assert decoded.state == LIVE_UNKNOWN
    assert decoded.finished is None

    # The control: the same writer producing a well-formed record classifies.
    _write_cache(tmp_path, finished=True, data_checked=False)
    assert snapshots._parse_live_event_cache(
        json.loads((tmp_path / "1-live.json").read_text()), datetime.now(UTC)
    ).state == LIVE_UNSETTLED


def test_a_newer_cache_version_is_not_read_as_final(tmp_path: Path) -> None:
    """Refused the way an unrecognised manifest version is (FU-41): a newer
    build wrote it and this reader is behind, so its flags may not mean what
    this build would take them to mean."""
    _write_cache(tmp_path, version=99, finished=True, data_checked=True)

    decoded = snapshots._parse_live_event_cache(
        json.loads((tmp_path / "1-live.json").read_text()), datetime.now(UTC)
    )

    assert decoded.state == LIVE_UNKNOWN
    assert "99" in (decoded.detail or "")
    # The control: version 1 with the identical flags is settled, so the refusal
    # is the version and not the flags.
    _write_cache(tmp_path, version=snapshots.LIVE_CACHE_VERSION, finished=True, data_checked=True)
    assert snapshots._parse_live_event_cache(
        json.loads((tmp_path / "1-live.json").read_text()), datetime.now(UTC)
    ).state == LIVE_SETTLED


# --- a pinned run reads outcome data from after the deadline it pins ---------


def test_a_pre_deadline_pin_still_serves_settled_actuals(tmp_path: Path) -> None:
    """The pinned service must not gate on the pinned snapshot.

    A capture worth pinning is a pre-deadline one: it says the gameweek is
    unfinished because it was taken before the gameweek was played. Projection
    inputs and outcome data come from opposite sides of the deadline by design,
    so gating the actuals on the capture's view of the gameweek would refuse
    every correct backtest there is. Only the payload's own record speaks for
    the payload.
    """
    _write_cache(tmp_path, finished=True, data_checked=True)
    pre_deadline = _snapshot(finished=False, data_checked=False)
    service = PinnedSnapshotService(tmp_path / "capture.json", event_live_cache_dir=tmp_path)

    result = service.load_event_live(1, pre_deadline)

    assert _points(result) == CACHE_POINTS
    assert result.provenance.settled is True

    # The control: the capture's view is genuinely unsettled, so a service that
    # did consult it would have refused above. This asserts the input to that
    # mistake was present, not merely that the mistake was absent.
    assert snapshots._is_finalised(pre_deadline, 1) is False


# --- provenance ---------------------------------------------------------------


def test_provenance_reports_a_settled_cache_read(tmp_path: Path) -> None:
    path = _write_cache(tmp_path, finished=True, data_checked=True)

    result = SnapshotService(api=StubApi(), event_live_cache_dir=tmp_path).load_event_live(1, _snapshot())

    assert result.provenance == LiveEventProvenance(
        state=LIVE_SETTLED, source="cache", finished=True, data_checked=True, path=path
    )
    assert result.provenance.settled is True


def test_provenance_reports_an_unsettled_live_fetch(tmp_path: Path) -> None:
    """An in-flight gameweek: nothing is cached, the fetch is live, and the data
    is the freshest in existence and still provisional. It is served — there is
    nothing better and nothing to wait for — and marked."""
    api = StubApi()
    service = SnapshotService(api=api, event_live_cache_dir=tmp_path)

    result = service.load_event_live(1, _snapshot(finished=True, data_checked=False))

    assert _points(result) == LIVE_POINTS  # served, not refused
    assert result.provenance.state == LIVE_UNSETTLED
    assert result.provenance.settled is False
    assert (result.provenance.source, result.provenance.finished, result.provenance.data_checked) == (
        "live",
        True,
        False,
    )
    # And it is not persisted: an unsettled payload must not become tomorrow's
    # cache hit. This is the pre-existing write gate, asserted because the
    # read gate would be pointless without it.
    assert not (tmp_path / "1-live.json").exists()


def test_provenance_reports_a_settled_live_fetch(tmp_path: Path) -> None:
    """The control for the pair above: same service, same code path, settled
    gameweek. Without it `state` could be hardcoded to unsettled for live."""
    result = SnapshotService(api=StubApi(), event_live_cache_dir=tmp_path).load_event_live(1, _snapshot())

    assert result.provenance.state == LIVE_SETTLED
    assert result.provenance.source == "live"
    assert (tmp_path / "1-live.json").exists()  # settled, so persisted


# --- what `plan evaluate` tells the operator ---------------------------------


def _report(state: str, **kwargs: Any) -> str:
    result = LiveEventResult(
        live=LiveEvent.model_validate(_payload(1)),
        event=2,
        stale=False,
        provenance=LiveEventProvenance(state=state, **kwargs),
    )
    cli._report_live_provenance(result)
    return ""


def test_evaluate_says_plainly_that_the_actuals_were_final(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Printed rather than left implicit: "no warning appeared" is
    indistinguishable from "the check was skipped"."""
    _report(LIVE_SETTLED, source="cache", finished=True, data_checked=True)

    out = capsys.readouterr().out
    assert "GW2 actuals: final" in out
    assert "NOT final" not in out


def test_evaluate_warns_loudly_when_the_actuals_are_not_final(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The control: the two states must not produce the same sentence, or the
    distinction is decorative. The warning has to say the figure is not a
    backtest, because that is the decision it changes."""
    _report(LIVE_UNSETTLED, source="live", finished=True, data_checked=False)

    out = capsys.readouterr().out
    assert "NOT final" in out
    assert "finished=True, data_checked=False" in out
    assert "not a backtest" in out


def test_evaluate_reports_an_unrecorded_finality_without_inventing_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`finished` and `data_checked` are `None` here. Printing "finished=None"
    would read as a finding; the recorded detail is what there is to say."""
    _report(LIVE_UNKNOWN, source="cache", detail="written before the cache recorded gameweek finality")

    out = capsys.readouterr().out
    assert "NOT final" in out
    assert "written before the cache recorded gameweek finality" in out
    assert "None" not in out


def test_plan_evaluate_actually_reports_provenance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """The tests above call the reporter directly, so none of them would notice
    the call site being dropped from `evaluate_plan`. This one drives the whole
    command and reads its console output.

    The warning is the arm asserted, because it is the one that changes what an
    operator does with the number printed underneath it.
    """

    class Stub:
        def __init__(self, **_: Any) -> None:
            pass

        def load(self) -> Any:
            from fpl_cli.api.snapshots import SnapshotResult

            return SnapshotResult(snapshot=bootstrap_snapshot, stale=False)

        def load_fixtures(self) -> Any:
            from fpl_cli.api.snapshots import FixturesResult

            return FixturesResult(fixtures=[], fetched_at=datetime.now(UTC), stale=False)

        def load_event_live(self, event: int, snapshot: BootstrapSnapshot) -> LiveEventResult:
            return LiveEventResult(
                live=LiveEvent.model_validate(_payload(1)),
                event=event,
                stale=False,
                provenance=LiveEventProvenance(
                    state=LIVE_UNSETTLED, source="live", finished=True, data_checked=False
                ),
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(cli, "SnapshotService", Stub)
    # An empty archive, so the command takes its no-capture path and reaches the
    # evaluation rather than exiting early.
    monkeypatch.setattr(cli, "DEFAULT_ARCHIVE_DIR", tmp_path / "archive")

    cli.evaluate_plan(event=1, snapshot_path=None)

    out = capsys.readouterr().out
    assert "GW1 actuals are NOT final" in out
    assert "not a backtest" in out

"""`fpl plan evaluate --model`, repeatable (task/model-versioning, commit c).

The point of the flag is that a comparison is **one run**. Two runs diffed by
hand may have selected different archives or different event-live payloads
between them, so the columns would not be comparable even when they look it.

Every assertion was demonstrated failing against a mutation of the line it
covers before being kept — named in each test's docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.api.snapshots import (
    LIVE_SETTLED,
    FixturesResult,
    LiveEventProvenance,
    LiveEventResult,
    SnapshotResult,
)

EVENT = 1


def _live_payload(player_ids: list[int]) -> dict[str, Any]:
    """Actuals that vary by player, so Spearman is not degenerate."""
    return {
        "elements": [
            {
                "id": pid,
                "stats": {"minutes": 90, "total_points": (pid % 7) + 1, "played": True},
                "explain": [],
                "modified": False,
            }
            for pid in player_ids
        ]
    }


def _install(monkeypatch: pytest.MonkeyPatch, snapshot: BootstrapSnapshot) -> None:
    fixtures = [
        Fixture(id=11, event=EVENT, team_h=1, team_a=2),
        Fixture(id=12, event=EVENT, team_h=3, team_a=4),
        Fixture(id=13, event=EVENT, team_h=5, team_a=1),
    ]
    player_ids = [player.id for player in snapshot.elements]

    class Stub:
        def __init__(self, **_: Any) -> None:
            pass

        def load(self) -> SnapshotResult:
            return SnapshotResult(snapshot=snapshot, stale=False)

        def load_fixtures(self) -> FixturesResult:
            return FixturesResult(fixtures=fixtures, fetched_at=datetime.now(UTC), stale=False)

        def load_event_live(self, event: int, _snapshot: BootstrapSnapshot) -> LiveEventResult:
            return LiveEventResult(
                live=LiveEvent.model_validate(_live_payload(player_ids)),
                event=event,
                stale=False,
                provenance=LiveEventProvenance(
                    state=LIVE_SETTLED, source="cache", finished=True, data_checked=True
                ),
            )

        def close(self) -> None:
            pass

    # Rich ellipsises a long column header at the default 80-column test
    # terminal, and `component/1.0-fixture-minsub205+banded` is long enough to
    # lose the half that identifies it. Width is a display artefact, not the
    # property under test, so it is forced wide rather than asserted around.
    monkeypatch.setattr(cli.console, "_width", 220)

    # `PinnedSnapshotService` is deliberately left alone: every test here runs
    # unpinned, and substituting the same Stub for both would make
    # `isinstance(service, PinnedSnapshotService)` true in `load_snapshot` and
    # send it looking for a manifest the Stub has no reason to own.
    monkeypatch.setattr(cli, "SnapshotService", Stub)
    # No archive: the command falls back to the current snapshot and says so.
    monkeypatch.setattr(cli, "select_archived_snapshot", lambda *_a, **_k: None)


def test_two_variants_render_as_distinct_columns_in_one_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """The branch's whole purpose: two registered variants scored against one
    set of actuals, from one capture, in a single invocation.

    Both component variants must appear under their own version strings, and
    the flat baseline alongside them.

    Mutation: `for variant in chosen[:1]` scores only the first and drops the
    second column; scoring the same built model twice makes the two names
    identical. Both fail here.
    """
    _install(monkeypatch, bootstrap_snapshot)
    cli.evaluate_plan(
        event=EVENT,
        model=["component/1.0", "component/1.0-fixture-minsub205"],
        snapshot_path=None,
    )
    out = capsys.readouterr().out

    assert "component/1.0+banded" in out
    assert "component/1.0-fixture-minsub205+banded" in out
    assert "baseline/flat-ppg" in out
    # Not requested, so not scored — the flag selects rather than adds.
    assert "naive/1.0" not in out


def test_the_default_model_set_is_unchanged_by_the_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """Adding `--model` must not change what a bare `plan evaluate` scores.

    Mutation: dropping `naive/1.0` from `_DEFAULT_EVALUATE_MODELS`, or
    defaulting to `("component/1.1-price",)`, fails here.
    """
    _install(monkeypatch, bootstrap_snapshot)
    cli.evaluate_plan(event=EVENT, model=None, snapshot_path=None)
    out = capsys.readouterr().out

    assert "baseline/flat-ppg" in out
    assert "naive/1.0" in out
    assert "component/1.1-price+banded" in out
    # The fixture variant is registered but must never be scored by default.
    assert "fixture-minsub205" not in out


def test_the_short_aliases_still_resolve(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`--model component` is the surface every other command already takes.

    Mutation: dropping `_MODEL_ALIASES` from `resolve_variant` makes
    `"component"` an unknown variant and raises instead of rendering.
    """
    _install(monkeypatch, bootstrap_snapshot)
    cli.evaluate_plan(event=EVENT, model=["component", "naive"], snapshot_path=None)
    out = capsys.readouterr().out
    # `component` resolves to whichever variant is default, 1.2 since FU-60's
    # pair completed on 2026-09-19.
    assert "component/1.2+banded" in out
    assert "naive/1.0" in out


def test_an_unknown_model_is_refused_before_anything_is_scored(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """Resolution happens up front, so a typo in the third `--model` does not
    surface only after the first two have been scored and printed.

    Mutation: resolving inside the scoring loop instead of before it lets the
    first model's table print before the error, and the stdout assertion fails.
    """
    _install(monkeypatch, bootstrap_snapshot)
    with pytest.raises(typer.BadParameter) as excinfo:
        cli.evaluate_plan(
            event=EVENT, model=["component/1.0", "component/9.9"], snapshot_path=None
        )
    assert "component/9.9" in str(excinfo.value)
    assert "component/1.0" in str(excinfo.value)
    assert "Projection evaluation" not in capsys.readouterr().out


def test_the_same_model_twice_is_refused(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """Two identical columns would be a comparison of a model with itself,
    which is a typo rather than a request.

    Mutation: dropping the duplicate check renders two identical columns and
    this stops raising.
    """
    _install(monkeypatch, bootstrap_snapshot)
    with pytest.raises(typer.BadParameter, match="more than once"):
        cli.evaluate_plan(
            event=EVENT, model=["component/1.0", "component/1.0"], snapshot_path=None
        )


def test_a_model_that_cannot_score_the_event_is_skipped_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`official-ep` refuses any event but the snapshot's own next one. It must
    not take the other columns down with it — the comparison is the point, and
    losing it to one unscoreable model would defeat the flag.

    The conftest snapshot's `is_next` is GW3, so scoring GW1 is refused.

    Mutation: removing the `try/except ValueError` around `_project_single_event`
    propagates the error and this fails; `continue` -> `break` drops the
    component column that follows it.
    """
    _install(monkeypatch, bootstrap_snapshot)
    cli.evaluate_plan(
        event=EVENT, model=["official-ep/1.0", "component/1.0"], snapshot_path=None
    )
    out = capsys.readouterr().out

    assert "not evaluable" in out
    assert "official-ep/1.0" in out
    assert "component/1.0+banded" in out
    assert "Projection evaluation" in out


def test_every_model_is_scored_against_one_shared_set_of_actuals(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The claim the flag exists to make: one capture, one event-live payload,
    one `actuals_from_live_event` call, however many models.

    Counting the loads is what makes this a demonstration rather than a
    restatement — two runs diffed by hand would show two of each.

    Mutation: moving `load_event_live` or `actuals_from_live_event` inside the
    per-model loop raises the counts to 3 and fails.
    """
    _install(monkeypatch, bootstrap_snapshot)
    calls = {"live": 0, "actuals": 0}

    original_live = cli.SnapshotService.load_event_live

    def counting_live(self, event: int, snapshot: BootstrapSnapshot) -> LiveEventResult:
        calls["live"] += 1
        return original_live(self, event, snapshot)

    monkeypatch.setattr(cli.SnapshotService, "load_event_live", counting_live)

    original_actuals = cli.actuals_from_live_event

    def counting_actuals(live: LiveEvent) -> dict:
        calls["actuals"] += 1
        return original_actuals(live)

    monkeypatch.setattr(cli, "actuals_from_live_event", counting_actuals)

    cli.evaluate_plan(
        event=EVENT,
        model=["component/1.0", "component/1.0-fixture-minsub205", "naive/1.0"],
        snapshot_path=None,
    )
    assert calls == {"live": 1, "actuals": 1}

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot, Club, Fixture, Player
from fpl_cli.api.snapshots import FixturesResult, SnapshotResult
from fpl_cli.domain.transfers import parse_transfers_plan

from conftest import add_players


class StubService:
    def __init__(self, snapshot: BootstrapSnapshot, fixtures: list[Fixture] | None = None) -> None:
        self._snapshot = snapshot
        self._fixtures = fixtures or []
        self.closed = False

    def load(self) -> SnapshotResult:
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def load_fixtures(self) -> FixturesResult:
        return FixturesResult(fixtures=self._fixtures, fetched_at=datetime.now(UTC), stale=False)

    def close(self) -> None:
        self.closed = True


def _future_deadline(snapshot: BootstrapSnapshot, event: int, when: datetime) -> None:
    for gameweek in snapshot.events:
        if gameweek.id == event:
            gameweek.deadline_time = when


def _write_squad_ledger(path: Path, player_ids: list[int], *, price: int = 50, event: int = 1) -> None:
    log = ", ".join(f'{{"event": {event}, "type": "buy", "player": {pid}, "price": {price}}}' for pid in player_ids)
    path.write_text(f'{{"version": 1, "genesis_event": {event}, "log": [{log}]}}', encoding="utf-8")


def _rigged_snapshot(bootstrap_snapshot: BootstrapSnapshot) -> BootstrapSnapshot:
    """Rig points_per_game so `fpl plan optimise --model naive` has a unique,
    hand-computable best move: DEF ids 4-7 get a small nonzero rate, id 3
    stays at the default 0.0, and a new DEF (101, club 6 — otherwise unused)
    gets a rate that dwarfs the squad. Selling the *worst* held DEF (3) for
    it strictly beats selling any other DEF, so the search has one winner,
    not a tie — see the derivation in this file's main test.
    """
    _future_deadline(bootstrap_snapshot, 2, datetime(2099, 1, 1, tzinfo=UTC))
    for player_id in (4, 5, 6, 7):
        bootstrap_snapshot.players_by_id[player_id].points_per_game = "1.0"
    bootstrap_snapshot.teams.append(Club(id=6, name="Club 6", short_name="C6"))
    bootstrap_snapshot.__dict__.pop("clubs", None)
    add_players(
        bootstrap_snapshot,
        Player(id=101, web_name="Star", team=6, element_type=2, now_cost=50, points_per_game="20.0"),
    )
    return bootstrap_snapshot


def _fixtures_covering_six_clubs() -> list[Fixture]:
    return [
        Fixture(id=1, event=2, team_h=1, team_a=2),
        Fixture(id=2, event=2, team_h=3, team_a=4),
        Fixture(id=3, event=2, team_h=5, team_a=6),
    ]


def test_optimise_plan_recommends_the_hand_computed_best_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """End to end against a fixture rigged so the winner is computable by
    hand (see `_rigged_snapshot`): selling DEF 3 (rate 0.0) for the new DEF
    101 (rate 20.0) gives a GW2 XI of {101: 20, 4/5/6/7: 1 each} = 24,
    captain 101 doubles to +20 more = 44.0. Holding gives {3,4,5,6,7} = 4,
    captain (any of 4-7 at 1.0) doubles to +1 = 5.0. Net = 44.0 - 5.0 = 39.0,
    no hit (1 free transfer accrues from genesis to GW2).
    """
    snapshot = _rigged_snapshot(bootstrap_snapshot)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(snapshot, _fixtures_covering_six_clubs()))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

    cli.optimise_plan(
        squad_path,
        horizon=1,
        from_event=2,
        paths=3,
        max_hit=None,
        model="naive",
        decay=0.84,
        robustness="rescore",
        explain=False,
        output=None,
        json_output=False,
    )
    out = capsys.readouterr().out

    assert "naive/1.0" in out
    assert "£25.0m" in out  # bank at GW2: 1000 - 15*50, tenths of £1m
    assert "1 free transfer" in out
    assert "RECOMMENDED" in out
    assert "P3" in out and "Star" in out
    assert "44.0" in out  # winner's GW2 gross points
    assert "HOLD (no transfers)" in out
    assert "5.0" in out  # hold's GW2 gross points
    assert "robustness:" in out
    assert "UNVALIDATED" in out and "never been scored" not in out  # false since GW2
    # FU-28 is closed: dominance pruning is exact, so the header must no
    # longer carry the banner admitting it isn't. Inverted rather than
    # deleted — the banner's absence is part of what the fix delivers.
    assert "FU-28" not in out
    assert "DOMINANCE PRUNING IS UNSOUND" not in out


def test_optimise_plan_explain_shows_raw_vs_realised(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    snapshot = _rigged_snapshot(bootstrap_snapshot)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(snapshot, _fixtures_covering_six_clubs()))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

    cli.optimise_plan(
        squad_path,
        horizon=1,
        from_event=2,
        paths=3,
        max_hit=None,
        model="naive",
        decay=0.84,
        robustness="off",
        explain=True,
        output=None,
        json_output=False,
    )
    out = capsys.readouterr().out

    assert "Why —" in out
    assert "raw player delta" in out
    assert "realised in XI" in out
    assert "+20.0" in out  # raw delta: in(20.0) - out(0.0)
    assert "+39.0" in out  # realised total: 44.0 - 5.0, and the why-view's net (no hit)


def test_optimise_plan_output_round_trips(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    snapshot = _rigged_snapshot(bootstrap_snapshot)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(snapshot, _fixtures_covering_six_clubs()))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))
    output_path = tmp_path / "plan.json"

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
        output=output_path,
        json_output=False,
    )
    capsys.readouterr()

    plan = parse_transfers_plan(output_path)
    assert list(plan.keys()) == [2]
    assert len(plan[2]) == 1
    assert plan[2][0].out_id == 3
    assert plan[2][0].in_id == 101


def test_optimise_plan_json_output_is_valid_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    snapshot = _rigged_snapshot(bootstrap_snapshot)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(snapshot, _fixtures_covering_six_clubs()))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

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
        json_output=True,
    )
    out = capsys.readouterr().out

    payload = json.loads(out)
    assert payload["from_event"] == 2
    assert payload["unvalidated"] is True
    # FU-28 is closed, so the machine-readable admission goes with the console
    # banner. Inverted rather than deleted: a consumer keying off this field
    # must see it disappear, not see it silently stay true.
    assert "dominance_pruning_unsound" not in payload
    assert payload["recommendation"]["description"]
    assert any(row["net"] == 0.0 for row in payload["paths"])  # HOLD row


def test_optimise_plan_errors_when_no_open_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    # bootstrap_snapshot's synthetic deadlines are all in 2025, already past.
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

    with pytest.raises(typer.Exit) as exc_info:
        cli.optimise_plan(
            squad_path,
            horizon=1,
            from_event=None,
            paths=3,
            max_hit=None,
            model="component",
            decay=0.84,
            robustness="off",
            explain=False,
            output=None,
            json_output=False,
        )
    assert exc_info.value.exit_code == 1


def test_optimise_plan_clamps_horizon_past_scheduled_gameweeks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """bootstrap_snapshot only schedules gameweeks 1-5; horizon 5 from GW4
    would reach GW8, so it must clamp to 2 and say so. Both GW4 and GW5 need
    a future deadline — real deadlines are monotonic across gameweeks, but
    this synthetic snapshot's are not unless every horizon event is patched."""
    _future_deadline(bootstrap_snapshot, 4, datetime(2099, 1, 1, tzinfo=UTC))
    _future_deadline(bootstrap_snapshot, 5, datetime(2099, 1, 8, tzinfo=UTC))
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

    cli.optimise_plan(
        squad_path,
        horizon=5,
        from_event=4,
        paths=3,
        max_hit=None,
        model="naive",
        decay=0.84,
        robustness="off",
        explain=False,
        output=None,
        json_output=False,
    )
    out = capsys.readouterr().out
    assert "clamped to 2" in out
    assert "GW4–GW5" in out


def test_optimise_plan_rejects_official_ep_beyond_horizon_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))

    with pytest.raises(typer.Exit) as exc_info:
        cli.optimise_plan(
            squad_path,
            horizon=2,
            from_event=None,
            paths=3,
            max_hit=None,
            model="official-ep",
            decay=0.84,
            robustness="off",
            explain=False,
            output=None,
            json_output=False,
        )
    assert exc_info.value.exit_code == 1

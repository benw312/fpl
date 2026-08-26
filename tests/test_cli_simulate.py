from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot, Fixture, Player
from fpl_cli.api.snapshots import FixturesResult, SnapshotResult
from fpl_cli.domain.projections import ComponentProjection
from fpl_cli.domain.squad import best_xi, objective_points
from fpl_cli.domain.strength import BandedTeamRates

from conftest import add_players


class StubService:
    def __init__(self, snapshot: BootstrapSnapshot, fixtures: list[Fixture] | None = None) -> None:
        self._snapshot = snapshot
        self._fixtures = fixtures or []
        self.closed = False

    def load(self) -> SnapshotResult:
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def load_fixtures(self) -> FixturesResult:
        # No fixtures by default: every player projects 0 xP that gameweek.
        # Most of these tests assert on hits/bank/legacy warnings, not on
        # the Points column, so an empty schedule is fine for them.
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


def test_simulate_plan_reports_valid_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    _future_deadline(bootstrap_snapshot, 2, datetime(2099, 1, 1, tzinfo=UTC))
    add_players(
        bootstrap_snapshot,
        Player(id=101, web_name="P101", team=bootstrap_snapshot.players_by_id[1].team, element_type=1, now_cost=50),
    )
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text('[{"event": 2, "transfers": [{"out": 1, "in": 101}]}]', encoding="utf-8")

    cli.simulate_plan(squad_path, transfers_path)

    out = capsys.readouterr().out
    assert "Total hit points: 0" in out
    assert "Bank:" in out
    assert "Free transfers:" in out


def test_simulate_plan_exits_1_on_rejected_gameweek(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    _future_deadline(bootstrap_snapshot, 2, datetime(2099, 1, 1, tzinfo=UTC))
    # Player 4's club already has 3 players; a same-position, same-club
    # replacement pushes it to 4 and fails structural validation.
    add_players(
        bootstrap_snapshot,
        Player(id=101, web_name="P101", team=bootstrap_snapshot.players_by_id[4].team, element_type=1, now_cost=50),
    )
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text('[{"event": 2, "transfers": [{"out": 2, "in": 101}]}]', encoding="utf-8")

    with pytest.raises(typer.Exit) as exc_info:
        cli.simulate_plan(squad_path, transfers_path)

    assert exc_info.value.exit_code == 1
    out = capsys.readouterr().out
    assert "the limit is 3" in out


def test_simulate_plan_warns_on_legacy_squad_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    _future_deadline(bootstrap_snapshot, 3, datetime(2099, 1, 1, tzinfo=UTC))
    add_players(
        bootstrap_snapshot,
        Player(id=102, web_name="P102", team=bootstrap_snapshot.players_by_id[1].team, element_type=1, now_cost=50),
    )
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    squad_path = tmp_path / "squad.json"
    squad_path.write_text('{"players": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]}', encoding="utf-8")
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text('[{"event": 3, "transfers": [{"out": 1, "in": 102}]}]', encoding="utf-8")

    cli.simulate_plan(squad_path, transfers_path)

    out = capsys.readouterr().out
    assert "Legacy squad file" in out


def test_simulate_plan_exits_on_malformed_transfers_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text("not json", encoding="utf-8")

    with pytest.raises(typer.Exit):
        cli.simulate_plan(squad_path, transfers_path)


def test_simulate_plan_exits_on_malformed_squad_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    squad_path = tmp_path / "squad.json"
    squad_path.write_text("not json", encoding="utf-8")
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text("[]", encoding="utf-8")

    with pytest.raises(typer.Exit):
        cli.simulate_plan(squad_path, transfers_path)


def test_simulate_plan_prints_the_optimiser_objective(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """The Points column must be the same number the optimiser will produce:
    best_xi's XI selection, run through objective_points' captain-doubling
    sum — not some other aggregate computed independently in the CLI.
    """
    _future_deadline(bootstrap_snapshot, 2, datetime(2099, 1, 1, tzinfo=UTC))
    # Covers all 5 synthetic clubs (`_bootstrap_snapshot` assigns team =
    # player_id % 5 + 1), so every squad player has a fixture leg that
    # gameweek and xp_appearance is non-zero even with every player's
    # attacking rates at their Player default of 0.0.
    fixtures = [
        Fixture(id=1, event=2, team_h=1, team_a=2),
        Fixture(id=2, event=2, team_h=3, team_a=4),
        Fixture(id=3, event=2, team_h=5, team_a=1),
    ]
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot, fixtures))

    squad_path = tmp_path / "squad.json"
    _write_squad_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text('[{"event": 2, "transfers": []}]', encoding="utf-8")

    cli.simulate_plan(squad_path, transfers_path)
    out = capsys.readouterr().out

    model = ComponentProjection(bootstrap_snapshot, fixtures, BandedTeamRates(bootstrap_snapshot))
    player_ids = list(range(1, 16))
    projections = {player_id: model.project([player_id], [2])[(player_id, 2)] for player_id in player_ids}
    xi = best_xi(player_ids, projections, bootstrap_snapshot)
    expected_points = objective_points(xi, projections)

    assert expected_points > 0.0
    assert f"{expected_points:.1f}" in out

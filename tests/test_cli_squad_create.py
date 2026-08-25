from __future__ import annotations

from pathlib import Path

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import SnapshotResult


class StubService:
    def __init__(self, snapshot: BootstrapSnapshot) -> None:
        self._snapshot = snapshot

    def load(self) -> SnapshotResult:
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def close(self) -> None:
        pass


def test_create_squad_requires_an_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    with pytest.raises(typer.Exit) as exc_info:
        cli.create_squad(output=tmp_path / "squad.json", force=False)

    assert exc_info.value.exit_code == 1
    assert "interactive terminal" in capsys.readouterr().out


def test_create_squad_refuses_to_overwrite_without_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot))

    output = tmp_path / "squad.json"
    output.write_text("{}", encoding="utf-8")

    with pytest.raises(typer.Exit) as exc_info:
        cli.create_squad(output=output, force=False)

    assert exc_info.value.exit_code == 1
    assert "already exists" in capsys.readouterr().out


def test_create_squad_writes_a_valid_ledger_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    builder_snapshot: BootstrapSnapshot,
) -> None:
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from fpl_cli.domain.squad import SquadSlots, eligible_players

    slots = SquadSlots.empty(builder_snapshot)
    for slot in slots.slots:
        candidates = eligible_players(slots, slot.index, builder_snapshot)
        chosen = min(candidates, key=lambda player: player.now_cost)
        slots = slots.with_pick(slot.index, chosen.id)

    lines: list[str] = []
    for player_id in slots.player_ids:
        lines.append("")
        lines.append(builder_snapshot.players_by_id[player_id].display_name)
    lines.append("")
    input_text = "\n".join(lines) + "\n"

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(builder_snapshot))

    from fpl_cli.builder import SquadBuilder as RealSquadBuilder

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(input_text)
        monkeypatch.setattr(
            cli,
            "SquadBuilder",
            lambda snapshot: RealSquadBuilder(snapshot, input=pipe_input, output=DummyOutput()),
        )
        output = tmp_path / "squad.json"
        cli.create_squad(output=output, force=False)

    from fpl_cli.domain.transfers import Ledger, replay

    ledger = Ledger.from_file(output, builder_snapshot)
    assert ledger.legacy is False
    assert len(ledger.log) == 15

    state = replay(ledger, builder_snapshot)
    result = cli.validate_squad_players(state.player_ids, builder_snapshot)
    assert result.valid, result.errors

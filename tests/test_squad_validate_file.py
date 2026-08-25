from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.squad import validate_squad_file


def _write_ledger(path: Path, player_ids: list[int], *, price: int = 50, event: int = 2) -> None:
    log = [{"event": event, "type": "buy", "player": player_id, "price": price} for player_id in player_ids]
    path.write_text(json.dumps({"version": 1, "genesis_event": event, "log": log}), encoding="utf-8")


def _write_plan(path: Path, player_ids: list[int], *, starters: list[int] | None = None) -> None:
    # `bootstrap_snapshot`'s 15 players are 2 GKP (1-2), 5 DEF (3-7), 5 MID (8-12),
    # 3 FWD (13-15). Default to a legal 1-4-4-2 XI (min/max: GKP 1/1, DEF 3/5,
    # MID 2/5, FWD 1/3) rather than an arbitrary slice, which would be illegal.
    if starters is None:
        starters = [player_ids[0], *player_ids[2:6], *player_ids[7:11], *player_ids[12:14]]
    payload = {
        "players": player_ids,
        "starters": starters,
        "captain": starters[0],
        "vice_captain": starters[1],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_validate_squad_file_accepts_a_ledger(tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot) -> None:
    path = tmp_path / "squad.json"
    _write_ledger(path, list(range(1, 16)))

    result = validate_squad_file(path, bootstrap_snapshot)

    assert result.valid, result.errors


def test_validate_squad_file_accepts_a_squad_plan(tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot) -> None:
    path = tmp_path / "squad.json"
    _write_plan(path, list(range(1, 16)))

    result = validate_squad_file(path, bootstrap_snapshot)

    assert result.valid, result.errors


def test_validate_squad_file_rejects_unrecognised_shape(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    path = tmp_path / "squad.json"
    path.write_text(json.dumps({"not_a_squad": True}), encoding="utf-8")

    with pytest.raises(ValueError, match="not a recognised squad plan or ledger"):
        validate_squad_file(path, bootstrap_snapshot)


def test_validate_squad_file_rejects_an_illegal_formation(
    tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    path = tmp_path / "squad.json"
    player_ids = list(range(1, 16))
    # 11 starters, but both GKP (1-2) play: squad_max_play for GKP is 1.
    illegal_starters = [1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13]
    _write_plan(path, player_ids, starters=illegal_starters)

    result = validate_squad_file(path, bootstrap_snapshot)

    assert not result.valid
    assert any("GKP" in error for error in result.errors)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.squad import validate_squad_file


def _write_ledger(path: Path, player_ids: list[int], *, price: int = 50, event: int = 2) -> None:
    log = [{"event": event, "type": "buy", "player": player_id, "price": price} for player_id in player_ids]
    path.write_text(json.dumps({"version": 1, "genesis_event": event, "log": log}), encoding="utf-8")


def _write_plan(path: Path, player_ids: list[int]) -> None:
    payload = {
        "players": player_ids,
        "starters": player_ids[:11],
        "captain": player_ids[0],
        "vice_captain": player_ids[1],
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

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.rules import ValidationResult, validate_squad


@dataclass(frozen=True)
class SquadPlan:
    players: list[int]
    starters: list[int]
    captain: int | None = None
    vice_captain: int | None = None

    @classmethod
    def from_file(cls, path: Path) -> SquadPlan:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            players=[int(player_id) for player_id in payload.get("players", [])],
            starters=[int(player_id) for player_id in payload.get("starters", [])],
            captain=payload.get("captain"),
            vice_captain=payload.get("vice_captain"),
        )


def validate_plan(plan: SquadPlan, snapshot: BootstrapSnapshot) -> ValidationResult:
    result = validate_squad(plan.players, snapshot)
    errors = list(result.errors)

    if len(plan.starters) != snapshot.game_settings.squad_squadplay:
        errors.append(f"The starting XI must contain exactly {snapshot.game_settings.squad_squadplay} players.")
    if not set(plan.starters).issubset(set(plan.players)):
        errors.append("Every starter must be in the squad.")
    if plan.captain is None or plan.captain not in plan.starters:
        errors.append("The captain must be one of the starters.")
    if plan.vice_captain is None or plan.vice_captain not in plan.starters:
        errors.append("The vice-captain must be one of the starters.")
    if plan.captain is not None and plan.captain == plan.vice_captain:
        errors.append("Captain and vice-captain must be different players.")

    return ValidationResult(errors, result.warnings, result.season, result.fetched_at)

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import json

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.rules import ValidationResult, validate_squad
from fpl_cli.domain.transfers import Ledger, current_event_id, replay


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

    players_by_id = snapshot.players_by_id
    starter_counts: dict[int, int] = {}
    for player_id in plan.starters:
        player = players_by_id.get(player_id)
        if player is None:
            continue
        starter_counts[player.element_type] = starter_counts.get(player.element_type, 0) + 1
    for position in snapshot.element_types:
        count = starter_counts.get(position.id, 0)
        if count < position.squad_min_play or count > position.squad_max_play:
            errors.append(
                f"The starting XI must include between {position.squad_min_play} and "
                f"{position.squad_max_play} {position.singular_name_short} players; found {count}."
            )

    if plan.captain is None or plan.captain not in plan.starters:
        errors.append("The captain must be one of the starters.")
    if plan.vice_captain is None or plan.vice_captain not in plan.starters:
        errors.append("The vice-captain must be one of the starters.")
    if plan.captain is not None and plan.captain == plan.vice_captain:
        errors.append("Captain and vice-captain must be different players.")

    return ValidationResult(errors, result.warnings, result.season, result.fetched_at)


def validate_squad_file(path: Path, snapshot: BootstrapSnapshot) -> ValidationResult:
    """Validate a squad file, accepting either a `SquadPlan` or a transfer ledger.

    A ledger (`"log" in payload`) is replayed to its final state and
    validated on structure and budget, skipping the starters/captain/
    vice-captain checks a ledger has no data for. A `SquadPlan`
    (`"players" in payload`) validates as before. Anything else raises
    `ValueError` rather than silently validating an empty squad.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "log" in payload:
        ledger = Ledger.from_file(path, snapshot)
        state = replay(ledger, snapshot)
        return validate_squad(state.player_ids, snapshot)
    if "players" in payload:
        return validate_plan(SquadPlan.from_file(path), snapshot)
    raise ValueError(f"{path} is not a recognised squad plan or ledger (missing 'players' or 'log').")


@dataclass(frozen=True)
class Slot:
    """One numbered position in the squad builder's 15-slot grid."""

    index: int
    position_id: int
    player_id: int | None = None


@dataclass(frozen=True)
class SquadSlots:
    """The in-progress state of an interactively built squad."""

    slots: tuple[Slot, ...]

    @classmethod
    def empty(cls, snapshot: BootstrapSnapshot) -> SquadSlots:
        slots: list[Slot] = []
        index = 1
        for position in snapshot.element_types:
            for _ in range(position.squad_select):
                slots.append(Slot(index=index, position_id=position.id))
                index += 1
        return cls(slots=tuple(slots))

    def slot(self, index: int) -> Slot:
        return next(slot for slot in self.slots if slot.index == index)

    def with_pick(self, slot_index: int, player_id: int) -> SquadSlots:
        slots = tuple(
            replace(slot, player_id=player_id) if slot.index == slot_index else slot for slot in self.slots
        )
        return SquadSlots(slots=slots)

    def with_clear(self, slot_index: int) -> SquadSlots:
        slots = tuple(replace(slot, player_id=None) if slot.index == slot_index else slot for slot in self.slots)
        return SquadSlots(slots=slots)

    @property
    def picked_ids(self) -> set[int]:
        return {slot.player_id for slot in self.slots if slot.player_id is not None}

    @property
    def player_ids(self) -> list[int]:
        return sorted(self.picked_ids)

    @property
    def empty_slots(self) -> list[Slot]:
        return [slot for slot in self.slots if slot.player_id is None]

    @property
    def is_complete(self) -> bool:
        return not self.empty_slots


def _club_counts(slots: SquadSlots, snapshot: BootstrapSnapshot) -> dict[int, int]:
    players_by_id = snapshot.players_by_id
    counts: dict[int, int] = {}
    for player_id in slots.picked_ids:
        player = players_by_id.get(player_id)
        if player is None:
            continue
        counts[player.team] = counts.get(player.team, 0) + 1
    return counts


def _bank(slots: SquadSlots, snapshot: BootstrapSnapshot) -> int:
    players_by_id = snapshot.players_by_id
    spent = sum(players_by_id[player_id].now_cost for player_id in slots.picked_ids if player_id in players_by_id)
    return snapshot.game_settings.squad_total_spend - spent


def _selectable(
    position_id: int,
    slots: SquadSlots,
    snapshot: BootstrapSnapshot,
    *,
    club_counts: dict[int, int],
) -> list[Player]:
    """Players of `position_id` not already picked, selectable, under the club limit."""
    settings = snapshot.game_settings
    picked = slots.picked_ids
    return [
        player
        for player in snapshot.elements
        if player.element_type == position_id
        and player.id not in picked
        and player.can_select
        and not player.removed
        and club_counts.get(player.team, 0) < settings.squad_team_limit
    ]


def eligible_players(slots: SquadSlots, slot_index: int, snapshot: BootstrapSnapshot) -> list[Player]:
    """Players that can legally fill this slot right now.

    Excludes: wrong position, already picked, a club already at the team
    limit, not selectable, and anything that would leave a still-empty slot
    unaffordable once budget is reserved for it.
    """
    slot = slots.slot(slot_index)
    club_counts = _club_counts(slots, snapshot)
    bank = _bank(slots, snapshot)

    reserve = 0
    for other in slots.empty_slots:
        if other.index == slot_index:
            continue
        candidates = _selectable(other.position_id, slots, snapshot, club_counts=club_counts)
        if candidates:
            reserve += min(player.now_cost for player in candidates)

    budget = bank - reserve
    return [
        player
        for player in _selectable(slot.position_id, slots, snapshot, club_counts=club_counts)
        if player.now_cost <= budget
    ]


def to_ledger_payload(slots: SquadSlots, snapshot: BootstrapSnapshot) -> dict[str, Any]:
    """A completed squad as a transfer ledger, in `Ledger.from_file`'s schema."""
    if not slots.is_complete:
        raise ValueError("Cannot build a ledger from an incomplete squad.")
    players_by_id = snapshot.players_by_id
    genesis_event = current_event_id(snapshot)
    return {
        "version": 1,
        "genesis_event": genesis_event,
        "log": [
            {
                "event": genesis_event,
                "type": "buy",
                "player": slot.player_id,
                "price": players_by_id[slot.player_id].now_cost,
            }
            for slot in slots.slots
        ],
        "chips_played": [],
    }

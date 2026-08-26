from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import product
from math import inf
from pathlib import Path
from typing import Any
import json

import numpy as np

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.projections import Projection
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
class BestXI:
    starters: list[int]
    captain: int


@lru_cache(maxsize=None)
def _formations_for(spec: tuple[tuple[int, int], ...], target: int) -> tuple[tuple[int, ...], ...]:
    """Every per-position starter count summing to `target` within `spec`.

    Cached on the derived `(min, max)` bounds rather than on the snapshot,
    which is a Pydantic model and unhashable. The spec is a handful of
    integers, so every snapshot of a season shares one entry.
    """
    return tuple(
        combo for combo in product(*(range(low, high + 1) for low, high in spec)) if sum(combo) == target
    )


def legal_formations(snapshot: BootstrapSnapshot) -> tuple[tuple[int, ...], ...]:
    """The legal starter counts per position, in `snapshot.element_types` order.

    A snapshot-level constant — 8 combinations on the live snapshot. Bounds
    are `squad_min_play`/`squad_max_play`, capped by `squad_select` since a
    squad cannot start more of a position than it may own; the total is
    `squad_squadplay`. All read from the snapshot, nothing hardcoded.

    `xi_value` and `best_xi` both enumerate through this one function rather
    than each iterating its own `product(...)`, so the fast path cannot drift
    from the rule `validate_plan` checks (optimizer-search.md §6.2). FU-26's
    vectorised scorer is the third caller.

    Squad-specific feasibility is deliberately *not* applied here: whether a
    given squad can field a formation depends on who is in it. That check
    belongs with the squad, in `xi_structure`.

    Returns a tuple, not the `list` optimizer-search.md §6.2 named: the value
    is cached and shared between callers, so it must not be mutable.
    """
    spec = tuple(
        (position.squad_min_play, min(position.squad_max_play, position.squad_select))
        for position in snapshot.element_types
    )
    return _formations_for(spec, snapshot.game_settings.squad_squadplay)


@dataclass(frozen=True)
class XiStructure:
    """What both `xi_value` and `best_xi` need, built once per squad.

    `prefix_xp[i][k]` is the total xP of the best `k` players in position
    `position_ids[i]`, so a formation's XI total is one lookup per position
    and no sorted tuple has to exist to score it — which is the whole of
    FU-24.

    This is the seam FU-26 vectorises: `NodeScorer` builds its numpy arrays
    from one of these per `(node, event)` and derives every child's prefix
    sums from the parent's rather than re-sorting, so the ranking that the
    batch kernel scores against is the ranking `best_xi` would have used.
    """

    position_ids: tuple[int, ...]
    ranked: tuple[tuple[int, ...], ...]
    prefix_xp: tuple[tuple[float, ...], ...]
    top_xp: tuple[float, ...]
    formations: tuple[tuple[int, ...], ...]
    target: int
    invariant_captain_xp: float | None


def xi_structure(
    player_ids: Sequence[int], projections: Mapping[int, Projection], snapshot: BootstrapSnapshot
) -> XiStructure:
    """Rank each position by xP, build its prefix sums, and keep the
    formations this particular squad can actually field."""
    players_by_id = snapshot.players_by_id

    def xp(player_id: int) -> float:
        return projections[player_id].xp_total

    by_position: dict[int, list[int]] = {}
    for player_id in player_ids:
        by_position.setdefault(players_by_id[player_id].element_type, []).append(player_id)

    position_ids: list[int] = []
    ranked: list[tuple[int, ...]] = []
    prefix_xp: list[tuple[float, ...]] = []
    top_xp: list[float] = []
    every_position_starts = True
    for position in snapshot.element_types:
        candidates = sorted(by_position.get(position.id, []), key=lambda player_id: (-xp(player_id), player_id))
        if len(candidates) < position.squad_min_play:
            raise ValueError(
                f"Cannot field a legal formation: {position.singular_name_short} needs at least "
                f"{position.squad_min_play} starters but only {len(candidates)} are available."
            )
        sums = [0.0]
        for player_id in candidates:
            sums.append(sums[-1] + xp(player_id))
        position_ids.append(position.id)
        ranked.append(tuple(candidates))
        prefix_xp.append(tuple(sums))
        top_xp.append(xp(candidates[0]) if candidates else -inf)
        every_position_starts = every_position_starts and position.squad_min_play >= 1

    formations = tuple(
        combo
        for combo in legal_formations(snapshot)
        if all(k <= len(candidates) for k, candidates in zip(combo, ranked))
    )

    # Every position starting at least one player means each position's top
    # scorer is always a starter, so the captain is the squad's best player
    # whatever the formation (optimizer-search.md §6.2). Hoisting it keeps the
    # scoring loop comparing the same sums the pre-FU-24 code compared.
    invariant_captain_xp = max(top_xp) if every_position_starts and top_xp else None

    return XiStructure(
        position_ids=tuple(position_ids),
        ranked=tuple(ranked),
        prefix_xp=tuple(prefix_xp),
        top_xp=tuple(top_xp),
        formations=formations,
        target=snapshot.game_settings.squad_squadplay,
        invariant_captain_xp=invariant_captain_xp,
    )


def _best_formations(structure: XiStructure) -> tuple[float, list[tuple[int, ...]]]:
    """The best objective value, and every formation achieving it.

    The objective is optimizer-ux.md §3's `Σ xP(XI) + xP(captain)`, so the
    captain term belongs inside the maximisation, not bolted on after. Where
    it is formation-invariant — always, on a snapshot whose positions all
    have `squad_min_play >= 1` — it is added once at the end instead, which
    both saves the per-formation `max` and leaves the comparison between
    formations bit-for-bit what it was before FU-24.

    Returning *every* tied formation rather than one is what lets `best_xi`
    keep its documented tie-break (lexicographically smallest starters) while
    `xi_value` materialises nothing: tied formations have equal value by
    definition, so only the witness has to choose between them.
    """
    invariant = structure.invariant_captain_xp
    best_value = -inf
    winners: list[tuple[int, ...]] = []

    for combo in structure.formations:
        total = sum(sums[k] for sums, k in zip(structure.prefix_xp, combo))
        if invariant is None:
            total += max(top for top, k in zip(structure.top_xp, combo) if k)
        if total > best_value:
            best_value = total
            winners = [combo]
        elif total == best_value:
            winners.append(combo)

    if not winners:
        raise ValueError(
            f"No legal formation of exactly {structure.target} starters is possible from this squad."
        )
    if invariant is not None:
        best_value += invariant
    return best_value, winners


def xi_value(
    player_ids: Sequence[int], projections: Mapping[int, Projection], snapshot: BootstrapSnapshot
) -> float:
    """The objective value of the best legal XI — the value alone (FU-24).

    Equal to `objective_points(best_xi(...))` by construction: both take the
    same formation set from `legal_formations` and score it from the same
    prefix sums, differing only in whether the winning XI is written down.
    `best_xi` materialises one sorted 11-tuple; this materialises none, which
    is the point on a hot path that scores ~10⁸ candidates.

    The equality is asserted directly by the property test in
    `tests/test_xi_value.py` (optimizer-search.md §8), and that test is the
    contract FU-26's numpy kernel inherits.

    Raises the same `ValueError`s as `best_xi` for a squad that cannot field
    a legal XI.
    """
    value, _ = _best_formations(xi_structure(player_ids, projections, snapshot))
    return value


def best_xi(
    player_ids: Sequence[int], projections: Mapping[int, Projection], snapshot: BootstrapSnapshot
) -> BestXI:
    """The highest-xP legal starting XI from `player_ids`, and its captain.

    "Legal" means each position's starter count falls within that position's
    `squad_min_play`/`squad_max_play` (`api/models.Position`) — the same
    constraint `validate_plan` checks, so manual planning and the optimiser
    select and validate an XI through one rule (CLAUDE.md).

    Ties on `xp_total` are broken by player ID ascending — both for which
    player fills the last slot in a position and, if several formations tie
    on total xP, for which formation wins — so the result is stable across
    runs.

    The witness half of the FU-24 split: `xi_value` computes the same number
    without building any of the tuples below. Only formations that tie for
    the win are materialised here, so the common case builds exactly one.
    """
    structure = xi_structure(player_ids, projections, snapshot)
    _, winners = _best_formations(structure)

    best_starters = min(
        tuple(sorted(player_id for candidates, k in zip(structure.ranked, combo) for player_id in candidates[:k]))
        for combo in winners
    )
    captain = min(best_starters, key=lambda player_id: (-projections[player_id].xp_total, player_id))
    return BestXI(starters=list(best_starters), captain=captain)


def objective_points(xi: BestXI, projections: Mapping[int, Projection]) -> float:
    """`Σ xP(starting XI) + xP(captain)` (optimizer-ux.md §3) — the points a
    gameweek is actually worth: bench players contribute nothing, and the
    captain's xP is counted twice (once as a starter, once for the armband).
    """
    return sum(projections[player_id].xp_total for player_id in xi.starters) + projections[xi.captain].xp_total


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


class NodeScorer:
    """Scores every child of one `(node, event)` as batched array operations.

    **FU-26.** `xi_value` costs ~44 µs per child because it re-sorts and
    re-sums the whole squad for each one. Almost none of that work differs
    between siblings: a transfer perturbs one or two positions and leaves the
    rest identical. This class does the shared work once per node and scores a
    whole candidate grid with a handful of numpy operations.

    **The identity it rests on** (optimizer-search.md §6.2): for a position
    whose prefix sums after the outgoing player is removed are `B`, inserting
    incoming values gives new prefix sums by *the best k either contains a new
    player or it does not* —

        one incoming x:    S'[k] = max( B[k],  x + B[k-1] )
        two incoming x,y:  S'[k] = max( B[k],  max(x,y) + B[k-1],  x+y + B[k-2] )

    Every term broadcasts over the candidate axes, so all candidates for a
    slot are scored at once and a two-slot move becomes an outer sum.

    **This object is valid only for the `(node, event)` pair it was built
    for.** A position's xP ranking changes every gameweek, so reusing one
    across events silently scores against the wrong ranking — §6.2 calls this
    the most dangerous bug available in the design. Build it inside the
    per-event expansion and let it die there; `event` is recorded and
    `assert_event` is provided so a caller can be checked rather than trusted.

    **Not a fallback for `xi_value`, and `xi_value` is not a fallback for it.**
    The pure-Python path is the reference implementation this is tested
    against (`tests/test_node_scorer.py`); both are expressions of the one
    objective `validate_plan` checks, which is what §8's property test ties
    together.
    """

    __slots__ = (
        "_captain_base",
        "_extended",
        "_formations",
        "_position_index",
        "_rank_of",
        "_structure",
        "_tops",
        "_values",
        "event",
    )

    def __init__(
        self,
        player_ids: Sequence[int],
        projections: Mapping[int, Projection],
        snapshot: BootstrapSnapshot,
        *,
        event: int | None = None,
    ) -> None:
        structure = xi_structure(player_ids, projections, snapshot)
        if structure.invariant_captain_xp is None:
            raise ValueError(
                "NodeScorer requires every position to have squad_min_play >= 1, so that each "
                "position's top scorer always starts and the captain is formation-invariant. "
                "Use xi_value for a snapshot where that does not hold."
            )

        self._structure = structure
        self.event = event
        self._formations = np.asarray(structure.formations, dtype=np.intp)
        self._position_index = {
            position_id: index for index, position_id in enumerate(structure.position_ids)
        }
        self._rank_of = {
            player_id: (index, rank)
            for index, ranked in enumerate(structure.ranked)
            for rank, player_id in enumerate(ranked)
        }
        # Per position, xP sorted descending — the same order `best_xi` ranks in.
        self._values = [
            np.fromiter(
                (projections[player_id].xp_total for player_id in ranked),
                dtype=np.float64,
                count=len(ranked),
            )
            for ranked in structure.ranked
        ]
        self._extended = [self._extend(values, index) for index, values in enumerate(self._values)]
        self._tops = np.array(
            [values[0] if values.size else -np.inf for values in self._values], dtype=np.float64
        )

    # -- internals ---------------------------------------------------------

    def _max_starters(self, position_index: int) -> int:
        return int(self._formations[:, position_index].max())

    def _extend(self, values, position_index: int):
        """Prefix sums padded with `-inf` at both ends.

        `E[k + 2] = B[k]`, so `E[k+2]`, `E[k+1]` and `E[k]` are `B[k]`,
        `B[k-1]` and `B[k-2]` with no bounds test — negative k reads a
        left pad, and a formation asking for more starters than the position
        holds reads a right pad. Both are `-inf`, so such a formation loses
        the `max` rather than needing a branch.
        """
        span = self._max_starters(position_index)
        extended = np.full(span + 3, -np.inf, dtype=np.float64)
        usable = min(span, values.size)
        extended[2 : 3 + usable] = np.concatenate(([0.0], np.cumsum(values[:usable])))
        return extended

    def _after_removal(self, position_index: int, ranks: Sequence[int]):
        values = np.delete(self._values[position_index], ranks)
        return values, self._extend(values, position_index)

    def assert_event(self, event: int) -> None:
        """Raise if this scorer was built for a different gameweek."""
        if self.event is not None and event != self.event:
            raise ValueError(
                f"NodeScorer was built for gameweek {self.event} but is being used for {event}. "
                "A position's xP ranking changes every gameweek; rebuild it per event."
            )

    # -- the batch ---------------------------------------------------------

    def value(self) -> float:
        """The node's own XI value, with nothing transferred."""
        return _best_formations(self._structure)[0]

    def score_children(self, out_ids: Sequence[int], in_xp: Sequence[object]):
        """XI values for every combination of incoming candidates.

        `out_ids[i]` leaves the squad and is replaced by one of the candidates
        whose xP is `in_xp[i]`, a 1-D array. FPL fixes each position's squad
        count, so a replacement is always the same position as the player it
        replaces, and slot `i` occupies axis `i` of the result — shape
        `(len(in_xp[0]), len(in_xp[1]), ...)`.

        An infeasible combination scores `-inf` rather than raising, so
        callers mask instead of branching. Feasibility that is not about the
        XI — budget, club limit, already held — is the caller's to mask.
        """
        if len(out_ids) != len(in_xp):
            raise ValueError(f"{len(out_ids)} outgoing players but {len(in_xp)} candidate arrays.")
        if not out_ids:
            raise ValueError("score_children needs at least one outgoing player.")

        arrays = [np.asarray(values, dtype=np.float64) for values in in_xp]
        if any(values.ndim != 1 for values in arrays):
            raise ValueError("Each candidate array must be 1-D.")
        shape = tuple(values.size for values in arrays)
        axes = len(arrays)

        slots_by_position: dict[int, list[int]] = {}
        for slot, player_id in enumerate(out_ids):
            try:
                position_index, _ = self._rank_of[player_id]
            except KeyError:
                raise ValueError(f"Player {player_id} is not in this node's squad.") from None
            slots_by_position.setdefault(position_index, []).append(slot)

        def broadcast(values, slot: int):
            return values.reshape(tuple(values.size if a == slot else 1 for a in range(axes)))

        formation_count = self._formations.shape[0]
        lead = (formation_count,) + (1,) * axes

        # Positions no transfer touches contribute the same per-formation
        # total to every child, so they are summed into one `(F,)` vector
        # *before* any candidate axis exists. Folding them in afterwards costs
        # a full-grid add each: 743 ns/child against 699 on the measured root
        # expansion.
        fixed = np.zeros(formation_count, dtype=np.float64)
        fixed_captain = -np.inf
        terms = []
        captain = None

        for position_index in range(len(self._values)):
            counts = self._formations[:, position_index]
            slots = slots_by_position.get(position_index)

            if slots is None:
                fixed = fixed + self._extended[position_index][counts + 2]
                fixed_captain = max(fixed_captain, float(self._tops[position_index]))
                continue

            ranks = [self._rank_of[out_ids[slot]][1] for slot in slots]
            values, extended = self._after_removal(position_index, ranks)
            base = extended[counts + 2].reshape(lead)
            prev = extended[counts + 1].reshape(lead)
            best_remaining = values[0] if values.size else -np.inf

            if len(slots) == 1:
                incoming = broadcast(arrays[slots[0]], slots[0])
                terms.append(np.maximum(base, prev + incoming))
                position_top = np.maximum(best_remaining, incoming)
            elif len(slots) == 2:
                prev2 = extended[counts].reshape(lead)
                first = broadcast(arrays[slots[0]], slots[0])
                second = broadcast(arrays[slots[1]], slots[1])
                higher = np.maximum(first, second)
                terms.append(
                    np.maximum(np.maximum(base, prev + higher), prev2 + (first + second))
                )
                position_top = np.maximum(best_remaining, higher)
            else:
                raise ValueError(
                    f"score_children handles at most 2 incoming players per position; "
                    f"got {len(slots)} for position {self._structure.position_ids[position_index]}."
                )
            captain = position_top if captain is None else np.maximum(captain, position_top)

        # Each term carries only its own candidate axes, so the full grid is
        # materialised once, by the last addition, rather than once per
        # position.
        total = fixed.reshape(lead)
        for term in terms:
            total = total + term

        # `-inf + finite` is `-inf`, so a child no formation can field stays
        # `-inf` without a guard; the captain term cannot resurrect it.
        best = total.max(axis=0)
        return (best + np.maximum(captain, fixed_captain)).reshape(shape)

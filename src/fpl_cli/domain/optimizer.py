"""The search (docs/plans/optimizer-search.md).

Beam search over an exactly-pruned candidate set, with the root gameweek
enumerated exhaustively and DP dominance folded in (§4.4's decision). Public
entry point is `optimise(...)`: a plain function taking a `SquadState` and a
projection table and returning ranked `Path`s. No strategy `Protocol`, no
solver seam — §4.4 explains why one is not needed yet.

**Scope.** This module implements the free search at a fixed `k_enum = 2`
(§5.3/§5.5): every legal move of up to two transfers is enumerated at the
root and at every beam level. `--schedule` (§5.7), `--max-transfers-per-gw 3`
at the root (§5.4) and the decision-margin threshold (§6.4) are out of
scope for this branch.

**Why children are never materialised as a list.** §7.2 records what an
earlier design's `list[Node]` per level cost: 200 nodes x 162,792 children at
horizon 5 exhausted a 12 GB machine. Every candidate set here is scored as
one numpy grid via `squad.NodeScorer`, reduced to its top-`w` survivors with
`_top_k_indices` (which itself streams in chunks bounded by
`GRID_CHUNK_CELLS`), and only those survivors are ever built as `Node`
objects.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.squad import BestXI, NodeScorer, best_xi, xi_value
from fpl_cli.domain.transfers import (
    SquadState,
    Transfer,
    TransferRules,
    apply_transfers,
    selling_price,
)

# --- Knobs (optimizer-search.md §1, §5.3, §6.1, §7.3) -----------------------

K_ENUM = 2
DEFAULT_DECAY = 0.84
DEFAULT_FT_VALUE = 1.5
DEFAULT_MAX_HIT = 4
DEFAULT_BEAM = 4
DEFAULT_FIRST_MOVES = 50
DEFAULT_MAX_CELLS = 400_000_000

# §7.2: the size at which one out-combination's candidate grid is chunked
# rather than built whole. Nothing in the live snapshot's measured pool
# (~180 survivors, grids in the tens of thousands of cells) comes close to
# this; it exists so a much wider pool degrades in wall clock, not memory.
GRID_CHUNK_CELLS = 2**21


# --- Node, Path, result types (optimizer-search.md §5.1) --------------------


@dataclass(frozen=True)
class Node:
    """One point in the search: a squad state reached by a sequence of moves.

    `score` and `net` are cumulative *up to and including* `event`, per §1's
    formulas, excluding terminal value (§6.1), which is added only at the
    end of a path. `xi`/`captain` are a cache of a deterministic argmax
    (§6.2), reproducible from `state.player_ids` and the projection table —
    never a source of truth.
    """

    parent: Node | None
    transfers: tuple[Transfer, ...]
    event: int
    state: SquadState
    score: float
    net: float
    hit_points: int
    xi: BestXI | None
    total_transfers: int
    path_ids: tuple[int, ...]
    exclusions: dict[int, str] = field(default_factory=dict)

    def sort_key(self) -> tuple[float, int, tuple[int, ...]]:
        """(-score, transfers_made, sorted transfer ids) — optimizer-search.md §5.5."""
        return (-self.score, self.total_transfers, self.path_ids)


@dataclass(frozen=True)
class Path:
    """A terminal node plus the figures that only make sense at the end of a path."""

    node: Node
    score: float
    net: float
    hit_points: int
    terminal_value: float

    @property
    def first_move(self) -> tuple[Transfer, ...]:
        node = self.node
        while node.parent is not None and node.parent.parent is not None:
            node = node.parent
        return node.transfers

    def chain(self) -> list[Node]:
        """Root-to-terminal chain of nodes, root excluded."""
        chain: list[Node] = []
        node: Node | None = self.node
        while node is not None and node.parent is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


@dataclass(frozen=True)
class ScopeGap:
    """optimizer-search.md §5.3: an event where the rules permit more transfers
    than this search enumerates."""

    event: int
    free_transfers: int
    k_rules: int
    k_enum: int = K_ENUM


@dataclass(frozen=True)
class CostProjection:
    expansions: int
    cells_per_node: int
    projected_cells: int


@dataclass(frozen=True)
class OptimiseResult:
    paths: list[Path]
    hold: Path
    events: list[int]
    dominance_exclusions: dict[int, str]
    scope_gaps: list[ScopeGap]
    cost: CostProjection


class SearchTooExpensive(RuntimeError):
    """§7.3's guard: refused before the first grid is allocated."""

    def __init__(self, cost: CostProjection, max_cells: int) -> None:
        self.cost = cost
        self.max_cells = max_cells
        super().__init__(
            f"Refusing to start: this search projects {cost.projected_cells:.3e} scored "
            f"candidates ({cost.expansions} node expansions) against --max-cells {max_cells}. "
            "Reduce --horizon, --beam or --first-moves, or raise --max-cells."
            # [gap: a runtime/memory estimate belongs in this message per
            # optimizer-search.md §7.3's worked example. This branch does not
            # measure throughput (that is the deferred beam-width/§7
            # re-record branch), so no figure is fabricated here.]
        )


# --- The dominance-pruned candidate pool (optimizer-search.md §5.2) --------


@dataclass(frozen=True)
class _Pool:
    by_position: dict[int, tuple[int, ...]]


def _dominance_pool(
    snapshot: BootstrapSnapshot,
    projections_by_event: dict[int, dict[int, Projection]],
    events: Sequence[int],
) -> tuple[list[int], dict[int, str]]:
    """The exact `(position, club)` Pareto frontier over every transactable player.

    Non-strict: A dominates B if `now_cost(A) <= now_cost(B)` and
    `xP(A, e) >= xP(B, e)` for every event. Ties (equal cost, equal xP at
    every event) are broken by player ID ascending, matching `best_xi`'s
    tie-break — so of two mutually-dominating players only one is excluded.
    """
    transactable = [player for player in snapshot.elements if player.can_transact and not player.removed]
    buckets: dict[tuple[int, int], list[Player]] = {}
    for player in transactable:
        buckets.setdefault((player.element_type, player.team), []).append(player)

    survivors: list[int] = []
    reasons: dict[int, str] = {}
    for bucket in buckets.values():
        bucket_sorted = sorted(bucket, key=lambda player: player.id)
        xp = {
            player.id: [projections_by_event[event][player.id].xp_total for event in events]
            for player in bucket_sorted
        }
        for candidate in bucket_sorted:
            dominator: Player | None = None
            for other in bucket_sorted:
                if other.id == candidate.id:
                    continue
                if other.now_cost > candidate.now_cost:
                    continue
                if any(o < c for o, c in zip(xp[other.id], xp[candidate.id])):
                    continue
                strictly_better = other.now_cost < candidate.now_cost or any(
                    o > c for o, c in zip(xp[other.id], xp[candidate.id])
                )
                if strictly_better or other.id < candidate.id:
                    dominator = other
                    break
            if dominator is None:
                survivors.append(candidate.id)
            else:
                shortfall = (candidate.now_cost - dominator.now_cost) / 10
                reasons[candidate.id] = (
                    f"dominated by {dominator.id}: costs £{shortfall:.1f}m less (or the same) and "
                    "projects at least as many points in every gameweek of the horizon"
                )
    return sorted(survivors), reasons


def _build_pool(survivor_ids: Sequence[int], snapshot: BootstrapSnapshot) -> _Pool:
    by_position: dict[int, list[int]] = {}
    for player_id in survivor_ids:
        position = snapshot.players_by_id[player_id].element_type
        by_position.setdefault(position, []).append(player_id)
    return _Pool(by_position={position: tuple(sorted(ids)) for position, ids in by_position.items()})


def _candidates_for(out_id: int, held: set[int], snapshot: BootstrapSnapshot, pool: _Pool) -> list[int]:
    """The buy candidates for one outgoing slot: pool survivors of the same
    position, minus whatever this node already holds (re-evaluated per node,
    per optimizer-search.md §5.3 — a player sold at depth 1 is a candidate
    again at depth 2)."""
    position = snapshot.players_by_id[out_id].element_type
    return [player_id for player_id in pool.by_position.get(position, ()) if player_id not in held]


# --- Free-transfer accrual, mirroring transfers.py's `_fold_event` ---------


def _accrue(free_transfers: int, rules: TransferRules) -> int:
    return min(free_transfers + rules.free_transfers_per_event, rules.free_transfer_cap)


def _hit_points(k: int, free_transfers_available: int, rules: TransferRules) -> int:
    return max(0, k - free_transfers_available) * rules.points_per_extra_transfer


def _k_max(free_transfers_available: int, rules: TransferRules, max_hit: int) -> int:
    for k in range(K_ENUM, -1, -1):
        if _hit_points(k, free_transfers_available, rules) <= max_hit:
            return k
    return 0


# --- Feasibility masks (shared by the guard and real generation) -----------


def _club_counts(holdings: Sequence[int], snapshot: BootstrapSnapshot) -> dict[int, int]:
    counts: dict[int, int] = {}
    players_by_id = snapshot.players_by_id
    for player_id in holdings:
        club = players_by_id[player_id].team
        counts[club] = counts.get(club, 0) + 1
    return counts


def _mask_k1(
    out_id: int, in_ids: Sequence[int], node: Node, snapshot: BootstrapSnapshot, rules: TransferRules
) -> np.ndarray:
    players_by_id = snapshot.players_by_id
    out_player = players_by_id[out_id]
    holding = node.state.holdings[out_id]
    sale = selling_price(holding.purchase_price, out_player.now_cost, rules)
    bank_after = node.state.bank + sale

    counts = _club_counts(node.state.holdings, snapshot)
    counts[out_player.team] = counts.get(out_player.team, 0) - 1
    limit = snapshot.game_settings.squad_team_limit

    now_cost = np.array([players_by_id[player_id].now_cost for player_id in in_ids])
    affordable = now_cost <= bank_after
    club_ok = np.array([counts.get(players_by_id[player_id].team, 0) + 1 <= limit for player_id in in_ids])
    return affordable & club_ok


def _mask_k2(
    out_a: int,
    out_b: int,
    in_ids_a: Sequence[int],
    in_ids_b: Sequence[int],
    node: Node,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
) -> np.ndarray:
    players_by_id = snapshot.players_by_id
    holding_a = node.state.holdings[out_a]
    holding_b = node.state.holdings[out_b]
    sale = selling_price(holding_a.purchase_price, players_by_id[out_a].now_cost, rules) + selling_price(
        holding_b.purchase_price, players_by_id[out_b].now_cost, rules
    )
    bank_after = node.state.bank + sale

    counts = _club_counts(node.state.holdings, snapshot)
    counts[players_by_id[out_a].team] = counts.get(players_by_id[out_a].team, 0) - 1
    counts[players_by_id[out_b].team] = counts.get(players_by_id[out_b].team, 0) - 1
    limit = snapshot.game_settings.squad_team_limit

    cost_a = np.array([players_by_id[player_id].now_cost for player_id in in_ids_a])
    cost_b = np.array([players_by_id[player_id].now_cost for player_id in in_ids_b])
    affordable = (cost_a[:, None] + cost_b[None, :]) <= bank_after

    club_a = [players_by_id[player_id].team for player_id in in_ids_a]
    club_b = [players_by_id[player_id].team for player_id in in_ids_b]
    clubs = sorted(set(club_a) | set(club_b))
    index = {club: i for i, club in enumerate(clubs)}
    base = np.array([counts.get(club, 0) for club in clubs])

    add_a = np.zeros((len(in_ids_a), len(clubs)), dtype=np.int8)
    add_a[np.arange(len(in_ids_a)), [index[club] for club in club_a]] = 1
    add_b = np.zeros((len(in_ids_b), len(clubs)), dtype=np.int8)
    add_b[np.arange(len(in_ids_b)), [index[club] for club in club_b]] = 1

    totals = base[None, None, :] + add_a[:, None, :] + add_b[None, :, :]
    club_ok = (totals <= limit).all(axis=2)

    mask = affordable & club_ok
    same_position = players_by_id[out_a].element_type == players_by_id[out_b].element_type
    if same_position:
        # Both slots draw from the identical candidate list in the identical
        # order, so index comparison both drops the diagonal (in_a == in_b)
        # and de-duplicates the unordered pair (optimizer-search.md §5.3).
        i, j = np.meshgrid(np.arange(len(in_ids_a)), np.arange(len(in_ids_b)), indexing="ij")
        mask &= i < j
    return mask


def _out_combinations(held: Sequence[int], k_max: int) -> list[tuple[int, ...]]:
    combos: list[tuple[int, ...]] = []
    if k_max >= 1:
        combos.extend((player_id,) for player_id in held)
    if k_max >= 2:
        combos.extend(itertools.combinations(sorted(held), 2))
    return combos


# --- The pre-flight guard (optimizer-search.md §7.3) ------------------------


def _cells_for_node(node: Node, snapshot: BootstrapSnapshot, rules: TransferRules, pool: _Pool, max_hit: int) -> int:
    held = set(node.state.holdings)
    free_available = _accrue(node.state.free_transfers, rules)
    k_max = _k_max(free_available, rules, max_hit)
    total = 0
    for combo in _out_combinations(node.state.player_ids, k_max):
        if len(combo) == 1:
            (out_id,) = combo
            in_ids = _candidates_for(out_id, held, snapshot, pool)
            if not in_ids:
                continue
            mask = _mask_k1(out_id, in_ids, node, snapshot, rules)
            total += int(mask.sum())
        else:
            out_a, out_b = combo
            in_ids_a = _candidates_for(out_a, held, snapshot, pool)
            in_ids_b = in_ids_a if snapshot.players_by_id[out_a].element_type == snapshot.players_by_id[
                out_b
            ].element_type else _candidates_for(out_b, held, snapshot, pool)
            if not in_ids_a or not in_ids_b:
                continue
            mask = _mask_k2(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
            total += int(mask.sum())
    return total


def project_cost(
    root: Node,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    pool: _Pool,
    *,
    horizon: int,
    beam: int,
    first_moves: int,
    max_hit: int,
) -> CostProjection:
    """optimizer-search.md §7.3's formula, exact: `cells_per_node` runs the
    generator's own enumeration and mask, skipping only the (expensive)
    scoring step."""
    expansions = 1 + first_moves + first_moves * beam * max(0, horizon - 2)
    cells_per_node = _cells_for_node(root, snapshot, rules, pool, max_hit)
    projected_cells = cells_per_node * (horizon + expansions - 1)
    return CostProjection(expansions=expansions, cells_per_node=cells_per_node, projected_cells=projected_cells)


# --- Streamed top-k extraction (optimizer-search.md §7.2) -------------------


def _top_k_indices(values: np.ndarray, k: int, chunk_cells: int = GRID_CHUNK_CELLS) -> tuple[np.ndarray, np.ndarray]:
    """Flat indices of the top-`k` values, descending, streamed in chunks so
    peak memory never scales with the grid's total size."""
    flat = values.reshape(-1)
    n = flat.size
    if k <= 0 or n == 0:
        return np.array([], dtype=np.intp), np.array([], dtype=np.float64)

    best_idx = np.array([], dtype=np.intp)
    best_val = np.array([], dtype=np.float64)
    for start in range(0, n, chunk_cells):
        end = min(start + chunk_cells, n)
        chunk = flat[start:end]
        kk = min(k, chunk.size)
        part = np.argpartition(-chunk, kk - 1)[:kk] if kk < chunk.size else np.arange(chunk.size)
        merged_idx = np.concatenate([best_idx, part + start])
        merged_val = np.concatenate([best_val, chunk[part]])
        kk2 = min(k, merged_val.size)
        top = np.argpartition(-merged_val, kk2 - 1)[:kk2] if kk2 < merged_val.size else np.arange(merged_val.size)
        best_idx, best_val = merged_idx[top], merged_val[top]

    order = np.argsort(-best_val)
    finite = np.isfinite(best_val[order])
    return best_idx[order][finite], best_val[order][finite]


# --- Materialising a retained candidate (apply_transfers is the authority) -


def _materialize(
    parent: Node,
    event: int,
    transfers: list[Transfer],
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    projections_at_event: Mapping[int, Projection],
    decay_factor: float,
    delta_from_grid: float,
    now: datetime | None,
) -> Node | None:
    """§5.3: the generator does arithmetic; `apply_transfers` is the
    authority. A candidate it rejects is dropped here — the property test in
    `tests/test_optimizer.py` is what asserts this never happens."""
    result = apply_transfers(parent.state, transfers, event, snapshot, rules, now=now)
    if not result.validation.valid:
        return None
    net = parent.net + delta_from_grid - result.hit_points
    score = parent.score + decay_factor * delta_from_grid - result.hit_points
    xi = best_xi(result.state.player_ids, projections_at_event, snapshot)
    new_ids = {player_id for transfer in transfers for player_id in (transfer.out_id, transfer.in_id)}
    return Node(
        parent=parent,
        transfers=tuple(transfers),
        event=event,
        state=result.state,
        score=score,
        net=net,
        hit_points=parent.hit_points + result.hit_points,
        xi=xi,
        total_transfers=parent.total_transfers + len(transfers),
        path_ids=tuple(sorted(set(parent.path_ids) | new_ids)),
        exclusions={},
    )


# --- Root: exhaustive enumeration, scored over the full horizon (§5.4) -----


def _expand_root(
    root: Node,
    events: Sequence[int],
    projections_by_event: dict[int, dict[int, Projection]],
    hold_objective: dict[int, float],
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    pool: _Pool,
    decay: float,
    max_hit: int,
    first_moves: int,
) -> list[Node]:
    root_event = events[0]
    decay_factors = {event: decay ** (event - root_event) for event in events}
    scorers = {event: NodeScorer(root.state.player_ids, projections_by_event[event], snapshot, event=event) for event in events}

    held = set(root.state.holdings)
    free_available = _accrue(root.state.free_transfers, rules)
    k_max = _k_max(free_available, rules, max_hit)

    local_retain = first_moves + 1
    ranked: list[tuple[float, tuple[int, ...], tuple[int, ...], float]] = []  # (ranking_score, out_ids, in_ids, root_event_delta)

    for combo in _out_combinations(root.state.player_ids, k_max):
        if len(combo) == 1:
            (out_id,) = combo
            in_ids = tuple(_candidates_for(out_id, held, snapshot, pool))
            if not in_ids:
                continue
            mask = _mask_k1(out_id, in_ids, root, snapshot, rules)
            in_id_lists = [in_ids]
        else:
            out_a, out_b = combo
            in_ids_a = tuple(_candidates_for(out_a, held, snapshot, pool))
            same_position = snapshot.players_by_id[out_a].element_type == snapshot.players_by_id[out_b].element_type
            in_ids_b = in_ids_a if same_position else tuple(_candidates_for(out_b, held, snapshot, pool))
            if not in_ids_a or not in_ids_b:
                continue
            mask = _mask_k2(out_a, out_b, in_ids_a, in_ids_b, root, snapshot, rules)
            in_id_lists = [in_ids_a, in_ids_b]

        hit = _hit_points(len(combo), free_available, rules)
        root_delta_grid = None
        full_score_grid = None
        for event in events:
            xp_arrays = [
                np.array([projections_by_event[event][pid].xp_total for pid in ids], dtype=np.float64)
                for ids in in_id_lists
            ]
            values = scorers[event].score_children(list(combo), xp_arrays)
            delta = values - hold_objective[event]
            contribution = decay_factors[event] * delta
            full_score_grid = contribution if full_score_grid is None else full_score_grid + contribution
            if event == root_event:
                root_delta_grid = delta

        full_score_grid = np.where(mask, full_score_grid - hit, -np.inf)
        top_idx, top_val = _top_k_indices(full_score_grid, local_retain)
        if top_idx.size == 0:
            continue
        multi = np.unravel_index(top_idx, full_score_grid.shape)
        for rank in range(top_idx.size):
            in_ids = tuple(in_id_lists[slot][multi[slot][rank]] for slot in range(len(combo)))
            root_event_delta = float(root_delta_grid[tuple(m[rank] for m in multi)])
            ranked.append((float(top_val[rank]), combo, in_ids, root_event_delta))

    ranked.sort(key=lambda item: -item[0])

    seen_transfer_sets: set[frozenset[tuple[int, int]]] = set()
    selected: list[tuple[tuple[int, ...], tuple[int, ...], float]] = []
    for _, out_ids, in_ids, root_event_delta in ranked:
        key = frozenset(zip(out_ids, in_ids))
        if key in seen_transfer_sets:
            continue
        seen_transfer_sets.add(key)
        selected.append((out_ids, in_ids, root_event_delta))
        if len(selected) >= first_moves:
            break

    if not any(len(out_ids) == 0 for out_ids, _, _ in selected):
        selected.append(((), (), 0.0))  # HOLD, forced in per §5.4

    nodes: list[Node] = []
    for out_ids, in_ids, root_event_delta in selected:
        transfers = [Transfer(out_id=o, in_id=i) for o, i in zip(out_ids, in_ids)]
        decay_factor = decay_factors[root_event]
        node = _materialize(
            root, root_event, transfers, snapshot, rules, projections_by_event[root_event], decay_factor, root_event_delta
        )
        if node is not None:
            nodes.append(node)
    return nodes


# --- Beam levels (optimizer-search.md §5.5) ---------------------------------


def _expand_node(
    node: Node,
    event: int,
    projections_at_event: dict[int, Projection],
    hold_objective_value: float,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    pool: _Pool,
    decay_factor: float,
    max_hit: int,
    local_retain: int,
) -> list[Node]:
    held = set(node.state.holdings)
    free_available = _accrue(node.state.free_transfers, rules)
    k_max = _k_max(free_available, rules, max_hit)

    scorer = NodeScorer(node.state.player_ids, projections_at_event, snapshot, event=event)
    candidates: list[Node] = []

    # k = 0: hold. `apply_transfers` folds idle-event accrual itself, so this
    # is not a special case, and it is never top-k'd away.
    hold_node = _materialize(node, event, [], snapshot, rules, projections_at_event, decay_factor, 0.0)
    if hold_node is not None:
        candidates.append(hold_node)

    for combo in _out_combinations(node.state.player_ids, k_max):
        if len(combo) == 1:
            (out_id,) = combo
            in_ids = tuple(_candidates_for(out_id, held, snapshot, pool))
            if not in_ids:
                continue
            mask = _mask_k1(out_id, in_ids, node, snapshot, rules)
            in_id_lists = [in_ids]
        else:
            out_a, out_b = combo
            in_ids_a = tuple(_candidates_for(out_a, held, snapshot, pool))
            same_position = snapshot.players_by_id[out_a].element_type == snapshot.players_by_id[out_b].element_type
            in_ids_b = in_ids_a if same_position else tuple(_candidates_for(out_b, held, snapshot, pool))
            if not in_ids_a or not in_ids_b:
                continue
            mask = _mask_k2(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
            in_id_lists = [in_ids_a, in_ids_b]

        hit = _hit_points(len(combo), free_available, rules)
        xp_arrays = [
            np.array([projections_at_event[pid].xp_total for pid in ids], dtype=np.float64) for ids in in_id_lists
        ]
        values = scorer.score_children(list(combo), xp_arrays)
        delta = values - hold_objective_value
        grid = np.where(mask, delta - hit, -np.inf)

        top_idx, _ = _top_k_indices(grid, local_retain)
        if top_idx.size == 0:
            continue
        multi = np.unravel_index(top_idx, grid.shape)
        for rank in range(top_idx.size):
            in_ids = tuple(in_id_lists[slot][multi[slot][rank]] for slot in range(len(combo)))
            root_event_delta = float(delta[tuple(m[rank] for m in multi)])
            transfers = [Transfer(out_id=o, in_id=i) for o, i in zip(combo, in_ids)]
            child = _materialize(
                node, event, transfers, snapshot, rules, projections_at_event, decay_factor, root_event_delta
            )
            if child is not None:
                candidates.append(child)

    return candidates


def _beats(a: Node, b: Node) -> bool:
    """optimizer-search.md §4.1's DP dominance test, non-strict with a
    deterministic tie-break so mutual dominance cannot discard both nodes."""
    if not (a.state.bank >= b.state.bank and a.state.free_transfers >= b.state.free_transfers and a.score >= b.score):
        return False
    strictly_better = a.state.bank > b.state.bank or a.state.free_transfers > b.state.free_transfers or a.score > b.score
    if strictly_better:
        return True
    return a.sort_key() < b.sort_key()


def _dp_prune(nodes: Sequence[Node]) -> list[Node]:
    groups: dict[frozenset[int], list[Node]] = {}
    for node in nodes:
        groups.setdefault(frozenset(node.state.holdings), []).append(node)
    survivors: list[Node] = []
    for group in groups.values():
        survivors.extend(node for node in group if not any(_beats(other, node) for other in group if other is not node))
    return survivors


def _expand_level(
    bucket: list[Node],
    event: int,
    projections_at_event: dict[int, Projection],
    hold_objective_value: float,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    pool: _Pool,
    decay_factor: float,
    max_hit: int,
    beam: int,
) -> list[Node]:
    children: list[Node] = []
    for node in bucket:
        children.extend(
            _expand_node(
                node,
                event,
                projections_at_event,
                hold_objective_value,
                snapshot,
                rules,
                pool,
                decay_factor,
                max_hit,
                local_retain=beam,
            )
        )
    survivors = _dp_prune(children)
    survivors.sort(key=Node.sort_key)
    return survivors[:beam]


# --- Terminal value (optimizer-search.md §6.1) ------------------------------


def _terminal_value(node: Node, rules: TransferRules, decay: float, horizon: int, ft_value: float) -> float:
    free_transfers = min(node.state.free_transfers, rules.free_transfer_cap)
    return (decay ** (horizon - 1)) * ft_value * free_transfers


# --- Orchestration ------------------------------------------------------------


def _by_event(
    projections: Mapping[tuple[int, int], Projection], events: Sequence[int]
) -> dict[int, dict[int, Projection]]:
    events_set = set(events)
    result: dict[int, dict[int, Projection]] = {event: {} for event in events}
    for (player_id, event), projection in projections.items():
        if event in events_set:
            result[event][player_id] = projection
    return result


def optimise(
    state: SquadState,
    snapshot: BootstrapSnapshot,
    projections: Mapping[tuple[int, int], Projection],
    rules: TransferRules,
    *,
    from_event: int,
    horizon: int,
    decay: float = DEFAULT_DECAY,
    ft_value: float = DEFAULT_FT_VALUE,
    max_hit: int = DEFAULT_MAX_HIT,
    beam: int = DEFAULT_BEAM,
    first_moves: int = DEFAULT_FIRST_MOVES,
    max_cells: int = DEFAULT_MAX_CELLS,
) -> OptimiseResult:
    """optimizer-search.md §4.4: beam search over an exactly-pruned candidate
    set, root enumerated exhaustively, `k_enum = 2` at every level, DP
    dominance folded into the beam.

    `from_event` must be strictly ahead of `state.event` — the same
    constraint `apply_transfers` enforces, checked here up front so the
    error names both gameweeks rather than surfacing from deep inside the
    root expansion.
    """
    if from_event <= state.event:
        raise ValueError(f"from_event {from_event} must be ahead of the ledger's last event {state.event}.")
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1; got {horizon}.")

    events = [from_event + offset for offset in range(horizon)]
    projections_by_event = _by_event(projections, events)
    for event in events:
        missing_root = [player_id for player_id in state.player_ids if player_id not in projections_by_event[event]]
        if missing_root:
            raise ValueError(f"No projection for gameweek {event}, players {missing_root}.")

    dominance_pool, dominance_exclusions = _dominance_pool(snapshot, projections_by_event, events)
    pool = _build_pool(dominance_pool, snapshot)

    hold_objective = {
        event: xi_value(state.player_ids, projections_by_event[event], snapshot) for event in events
    }

    root = Node(
        parent=None,
        transfers=(),
        event=state.event,
        state=state,
        score=0.0,
        net=0.0,
        hit_points=0,
        xi=None,
        total_transfers=0,
        path_ids=(),
    )

    cost = project_cost(root, snapshot, rules, pool, horizon=horizon, beam=beam, first_moves=first_moves, max_hit=max_hit)
    if cost.projected_cells > max_cells:
        raise SearchTooExpensive(cost, max_cells)

    scope_gaps: list[ScopeGap] = []
    running_free = state.free_transfers
    prior_event = state.event
    for event in events:
        running_free = min(running_free + rules.free_transfers_per_event * (event - prior_event), rules.free_transfer_cap)
        prior_event = event
        k_rules = min(running_free + max_hit // rules.points_per_extra_transfer, rules.transfers_cap)
        if k_rules > K_ENUM:
            scope_gaps.append(ScopeGap(event=event, free_transfers=running_free, k_rules=k_rules))

    root_level_nodes = _expand_root(
        root, events, projections_by_event, hold_objective, snapshot, rules, pool, decay, max_hit, first_moves
    )

    buckets: list[list[Node]] = [[node] for node in root_level_nodes]
    hold_bucket_index = next(
        (index for index, node in enumerate(root_level_nodes) if not node.transfers), None
    )

    for event in events[1:]:
        decay_factor = decay ** (event - events[0])
        projections_at_event = projections_by_event[event]
        for index, bucket in enumerate(buckets):
            hold_objective_value = hold_objective[event]
            buckets[index] = _expand_level(
                bucket, event, projections_at_event, hold_objective_value, snapshot, rules, pool, decay_factor, max_hit, beam
            )

    paths: list[Path] = []
    for bucket in buckets:
        for node in bucket:
            terminal_value = _terminal_value(node, rules, decay, horizon, ft_value)
            paths.append(Path(node=node, score=node.score + terminal_value, net=node.net, hit_points=node.hit_points, terminal_value=terminal_value))
    paths.sort(key=lambda path: (-path.score, path.node.total_transfers, path.node.path_ids))

    if hold_bucket_index is not None and buckets[hold_bucket_index]:
        hold_node = max(buckets[hold_bucket_index], key=lambda node: node.score)
        hold_terminal = _terminal_value(hold_node, rules, decay, horizon, ft_value)
        hold_path = Path(
            node=hold_node, score=hold_node.score + hold_terminal, net=hold_node.net, hit_points=hold_node.hit_points, terminal_value=hold_terminal
        )
    else:
        hold_path = paths[0]  # pragma: no cover - HOLD is always retained per §5.4

    return OptimiseResult(
        paths=paths,
        hold=hold_path,
        events=events,
        dominance_exclusions=dominance_exclusions,
        scope_gaps=scope_gaps,
        cost=cost,
    )

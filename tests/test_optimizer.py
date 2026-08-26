"""optimizer-search.md §8's five tests, on the search itself.

Not covered here (already exist, or out of scope for this branch per
`optimizer.py`'s module docstring): `xi_value`/`NodeScorer` equivalence
(`tests/test_node_scorer.py`, `tests/test_xi_value.py`), `--schedule`,
the round-trip against `plan simulate`, and horizon/`from_event` clamping.
"""

from __future__ import annotations

import itertools
import random
import tracemalloc
from datetime import UTC, datetime

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings, Gameweek, Player, Position
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.optimizer import Transfer as OptTransfer
from fpl_cli.domain.optimizer import DEFAULT_BEAM, _dominance_pool, optimise
from fpl_cli.domain.transfers import Holding, SquadState, TransferRules, apply_transfers

from conftest import add_players

NOW = datetime(2025, 8, 1, tzinfo=UTC)


def _projection(player_id: int, event: int, xp: float) -> Projection:
    return Projection(
        player=player_id,
        event=event,
        xp_total=xp,
        xp_appearance=0.0,
        xp_attack=0.0,
        xp_clean_sheet=0.0,
        xp_conceded=0.0,
        xp_saves=0.0,
        xp_defcon=0.0,
        xp_bonus=0.0,
        xp_cards=0.0,
        p_start=1.0,
        xmins=90.0,
        fixtures=1,
        model_version="test",
    )


# --- Known outcomes: brute force every k <= 2, same-position path over a ----
# --- 2-gameweek horizon, against a pool small enough to enumerate exactly. -


def _tiny_snapshot() -> BootstrapSnapshot:
    """6-a-side squad (1 GKP, 2 DEF, 2 MID, 1 FWD; XI forces exactly 1 of
    each), 2 extra pool candidates per position. Small enough to brute-force
    every same-position k <= 2 swap over 2 gameweeks, big enough that
    `first_moves`/`beam` well below the candidate count still truncate.
    """
    positions = [
        Position(id=1, singular_name_short="GKP", squad_select=1, squad_min_play=1, squad_max_play=1),
        Position(id=2, singular_name_short="DEF", squad_select=2, squad_min_play=1, squad_max_play=2),
        Position(id=3, singular_name_short="MID", squad_select=2, squad_min_play=1, squad_max_play=2),
        Position(id=4, singular_name_short="FWD", squad_select=1, squad_min_play=1, squad_max_play=1),
    ]
    # id -> (element_type, club); all same price, all distinct clubs so the
    # team limit (3) never binds and every combination is a clean read on xP.
    layout = {
        1: (1, 1), 2: (1, 2), 3: (1, 3),  # GKP: 1 held, 2 pool
        4: (2, 4), 5: (2, 5), 6: (2, 6), 7: (2, 7),  # DEF: 2 held, 2 pool
        8: (3, 1), 9: (3, 2), 10: (3, 3), 11: (3, 4),  # MID: 2 held, 2 pool
        12: (4, 5), 13: (4, 6), 14: (4, 7),  # FWD: 1 held, 2 pool
    }
    players = [
        Player(id=pid, web_name=f"P{pid}", team=club, element_type=position, now_cost=40)
        for pid, (position, club) in layout.items()
    ]
    return BootstrapSnapshot(
        events=[
            Gameweek(
                id=event_id,
                name=f"GW{event_id}",
                deadline_time=datetime(2025, 8, 8 + 7 * event_id, 17, 30, tzinfo=UTC),
                is_current=event_id == 1,
                is_next=event_id == 2,
                is_previous=False,
                finished=False,
            )
            for event_id in (1, 2, 3)
        ],
        teams=[Club(id=index, name=f"Club {index}") for index in range(1, 8)],
        element_types=positions,
        elements=players,
        game_settings=GameSettings(squad_squadsize=6, squad_squadplay=4, squad_team_limit=3, squad_total_spend=300),
        raw={"game_config": {"scoring": {}}},
        fetched_at=datetime.now(UTC),
        season="test",
    )


_TINY_HELD = [1, 4, 5, 8, 9, 12]


def _same_position_swaps(snapshot: BootstrapSnapshot, held: list[int], k_max: int) -> list[tuple[OptTransfer, ...]]:
    """Every legal-shape (same position per slot) combination of 0, 1 or 2
    transfers out of `held`, drawing replacements from every other player in
    the snapshot. This is deliberately a from-scratch enumeration, not a
    call into `optimizer.py`'s own candidate generator — the point is an
    independent oracle.
    """
    by_position: dict[int, list[int]] = {}
    for player in snapshot.elements:
        by_position.setdefault(player.element_type, []).append(player.id)

    moves: list[tuple[OptTransfer, ...]] = [()]
    if k_max >= 1:
        for out_id in held:
            position = snapshot.players_by_id[out_id].element_type
            for in_id in by_position[position]:
                if in_id in held:
                    continue
                moves.append((OptTransfer(out_id=out_id, in_id=in_id),))
    if k_max >= 2:
        for out_a, out_b in itertools.combinations(held, 2):
            pos_a = snapshot.players_by_id[out_a].element_type
            pos_b = snapshot.players_by_id[out_b].element_type
            in_choices_a = [pid for pid in by_position[pos_a] if pid not in held]
            in_choices_b = [pid for pid in by_position[pos_b] if pid not in held]
            for in_a in in_choices_a:
                for in_b in in_choices_b:
                    if in_a == in_b:
                        continue
                    moves.append((OptTransfer(out_id=out_a, in_id=in_a), OptTransfer(out_id=out_b, in_id=in_b)))
    return moves


def _brute_force_best_score(
    state: SquadState,
    snapshot: BootstrapSnapshot,
    projections_by_event: dict[int, dict[int, Projection]],
    rules: TransferRules,
    events: list[int],
    decay: float,
    ft_value: float,
) -> float:
    """optimizer-search.md §1's Score formula, computed by direct enumeration
    of every same-position k <= 2 path over the two gameweeks, using
    `apply_transfers` (the authority) and `xi_value` (the reference
    objective) — independent of anything in `optimizer.py`'s search.
    """
    from fpl_cli.domain.squad import xi_value

    root_event, next_event = events
    hold_objective = {
        event: xi_value(state.player_ids, projections_by_event[event], snapshot) for event in events
    }

    best = float("-inf")
    for root_transfers in _same_position_swaps(snapshot, state.player_ids, k_max=2):
        root_result = apply_transfers(state, list(root_transfers), root_event, snapshot, rules, now=NOW)
        if not root_result.validation.valid:
            continue
        state_1 = root_result.state
        score_1 = xi_value(state_1.player_ids, projections_by_event[root_event], snapshot) - hold_objective[root_event]
        hits_1 = root_result.hit_points

        for next_transfers in _same_position_swaps(snapshot, state_1.player_ids, k_max=2):
            next_result = apply_transfers(state_1, list(next_transfers), next_event, snapshot, rules, now=NOW)
            if not next_result.validation.valid:
                continue
            state_2 = next_result.state
            score_2 = (
                xi_value(state_2.player_ids, projections_by_event[next_event], snapshot) - hold_objective[next_event]
            )
            hits_2 = next_result.hit_points

            terminal = (decay ** (len(events) - 1)) * ft_value * min(state_2.free_transfers, rules.free_transfer_cap)
            score = score_1 + decay * score_2 - rules.points_per_extra_transfer * 0 - hits_1 - hits_2 + terminal
            best = max(best, score)
    return best


def test_known_outcome_matches_brute_force_enumeration() -> None:
    snapshot = _tiny_snapshot()
    rules = TransferRules.from_snapshot(snapshot)
    holdings = {pid: Holding(player=pid, purchase_price=40, bought_event=0) for pid in _TINY_HELD}
    state = SquadState(holdings=holdings, bank=60, event=1, free_transfers=1)

    # M2(9) is clearly worth replacing by M4(11) in both gameweeks; nothing
    # else improves at either event, so the true optimum is a single root
    # transfer followed by holding it into the second gameweek — the shape
    # that most banks-a-transfer FPL play actually takes. Everything else is
    # deliberately flat so brute force has to search ~110 candidates per
    # gameweek to confirm it.
    xp = {
        1: {2: 3.0, 3: 3.0}, 2: {2: 2.0, 3: 2.0}, 3: {2: 2.0, 3: 2.0},
        4: {2: 3.0, 3: 3.0}, 5: {2: 3.0, 3: 3.0}, 6: {2: 2.0, 3: 2.0}, 7: {2: 2.0, 3: 2.0},
        8: {2: 3.0, 3: 3.0}, 9: {2: 3.0, 3: 3.0}, 10: {2: 2.0, 3: 2.0}, 11: {2: 7.0, 3: 7.0},
        12: {2: 3.0, 3: 3.0}, 13: {2: 2.0, 3: 2.0}, 14: {2: 2.0, 3: 2.0},
    }
    projections_by_event: dict[int, dict[int, Projection]] = {2: {}, 3: {}}
    for pid, by_event in xp.items():
        for event, value in by_event.items():
            projections_by_event[event][pid] = _projection(pid, event, value)
    projections = {(pid, event): proj for event, table in projections_by_event.items() for pid, proj in table.items()}

    first_moves, beam = 5, 2
    result = optimise(
        state,
        snapshot,
        projections,
        rules,
        from_event=2,
        horizon=2,
        decay=0.84,
        ft_value=1.5,
        max_hit=4,
        beam=beam,
        first_moves=first_moves,
        max_cells=10**9,
        now=NOW,
    )

    # Sizing check: the fixture must be big enough that first_moves/beam
    # actually cut something, or this test proves nothing about the beam.
    total_root_candidates = len(_same_position_swaps(snapshot, _TINY_HELD, k_max=2))
    assert total_root_candidates > first_moves + 1
    assert total_root_candidates > beam

    expected_best = _brute_force_best_score(state, snapshot, projections_by_event, rules, [2, 3], decay=0.84, ft_value=1.5)
    assert result.paths[0].score == pytest.approx(expected_best, abs=1e-9)


# --- The generator is a filter, not a bypass --------------------------------


def test_generator_children_are_all_accepted_by_apply_transfers(bootstrap_snapshot: BootstrapSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """optimizer-search.md §5.3: every child the search materialises must
    pass `apply_transfers`. Wrap the real function so a rejection — which
    `_materialize` would otherwise swallow by returning `None` — fails the
    test instead of silently vanishing.
    """
    import fpl_cli.domain.optimizer as optimizer_module
    from fpl_cli.domain.transfers import apply_transfers as real_apply_transfers

    # Spread across 15 clubs (rather than 5) so a club-legal random hold squad
    # is cheap to find by rejection sampling below.
    next_id = max(player.id for player in bootstrap_snapshot.elements) + 1
    extras = []
    for position_id, count in {1: 2, 2: 5, 3: 5, 4: 3}.items():
        for _ in range(6):
            extras.append(
                Player(id=next_id, web_name=f"P{next_id}", team=(next_id % 15) + 1, element_type=position_id, now_cost=45)
            )
            next_id += 1
    add_players(bootstrap_snapshot, *extras)
    rules = TransferRules.from_snapshot(bootstrap_snapshot)
    team_limit = bootstrap_snapshot.game_settings.squad_team_limit

    rng = random.Random("fu-optimizer-generator-is-a-filter")
    by_position: dict[int, list[int]] = {}
    for player in bootstrap_snapshot.elements:
        by_position.setdefault(player.element_type, []).append(player.id)

    def _club_legal_squad(squad_select: dict[int, int]) -> list[int]:
        """Rejection-sample a squad respecting `squad_team_limit` — an
        already-illegal starting squad would make `apply_transfers` reject
        transfers for a reason that has nothing to do with the generator.
        """
        for _ in range(200):
            held: list[int] = []
            club_counts: dict[int, int] = {}
            complete = True
            for position_id, count in squad_select.items():
                candidates = by_position[position_id][:]
                rng.shuffle(candidates)
                picked = []
                for pid in candidates:
                    if len(picked) == count:
                        break
                    club = bootstrap_snapshot.players_by_id[pid].team
                    if club_counts.get(club, 0) >= team_limit:
                        continue
                    club_counts[club] = club_counts.get(club, 0) + 1
                    picked.append(pid)
                if len(picked) < count:
                    complete = False
                    break
                held.extend(picked)
            if complete:
                return held
        raise RuntimeError("could not sample a club-legal squad")

    calls = []

    def wrapper(*args, **kwargs):
        result = real_apply_transfers(*args, **kwargs)
        calls.append(result)
        assert result.validation.valid, f"generator emitted a child apply_transfers rejected: {result.validation.errors}"
        return result

    monkeypatch.setattr(optimizer_module, "apply_transfers", wrapper)

    for trial in range(6):
        held = _club_legal_squad({1: 2, 2: 5, 3: 5, 4: 3})
        holdings = {pid: Holding(player=pid, purchase_price=45, bought_event=0) for pid in held}
        state = SquadState(holdings=holdings, bank=rng.randint(0, 100), event=1, free_transfers=rng.randint(0, 3))
        projections = {
            (pid, event): _projection(pid, event, rng.uniform(0.0, 12.0))
            for pid in bootstrap_snapshot.players_by_id
            for event in (2, 3)
        }
        optimise(
            state,
            bootstrap_snapshot,
            projections,
            rules,
            from_event=2,
            horizon=2,
            beam=2,
            first_moves=5,
            max_hit=4,
            max_cells=10**9,
            now=NOW,
        )

    assert calls, "the property was never exercised — no apply_transfers calls were made"


# --- Dominance is exact ------------------------------------------------------


def _bucket_snapshot(players: list[Player]) -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=[],
        teams=[Club(id=1, name="Club 1")],
        element_types=[],
        elements=players,
        game_settings=GameSettings(),
        fetched_at=datetime.now(UTC),
        season="test",
    )


def test_dominance_excludes_only_players_a_survivor_can_always_replace() -> None:
    """optimizer-search.md §5.2: for every budget, the best single pick from
    the bucket's survivors must equal the best single pick from the whole
    bucket. If it doesn't, some excluded player was necessary — a false
    exclusion.

    Scoped to picking **one** player from the bucket (`_candidates_for`'s own
    usage: one incoming slot at a time). §5.2's own argument for exactness is
    pairwise substitution ("interchangeable under every constraint"), which
    only proves 1-for-1 replacement. [gap: `_mask_k2` can draw *two* in-slots
    from the same `(position, club)` bucket in one k=2 move (its `i < j`
    dedup exists for exactly this case); whether dominance survives a
    *simultaneous* two-pick from one bucket under a tight aggregate budget is
    not proven by §5.2 and is not asserted here — a same-bucket pair where
    one dominates the other on a tied price is the case that could break it.]
    """
    rng = random.Random("fu-optimizer-dominance-is-exact")
    events = [2, 3]

    for trial in range(8):
        count = rng.randint(6, 9)
        players = [
            Player(id=100 * trial + i, web_name=f"B{trial}-{i}", team=1, element_type=2, now_cost=rng.randrange(30, 90, 5))
            for i in range(count)
        ]
        projections_by_event = {
            event: {player.id: _projection(player.id, event, rng.uniform(0.0, 15.0)) for player in players}
            for event in events
        }
        snapshot = _bucket_snapshot(players)

        survivor_ids, reasons = _dominance_pool(snapshot, projections_by_event, events)
        assert set(survivor_ids) | set(reasons) == {player.id for player in players}

        def best_single_pick(candidates: list[int], budget: int, event: int) -> float:
            affordable = [pid for pid in candidates if snapshot.players_by_id[pid].now_cost <= budget]
            if not affordable:
                return float("-inf")
            return max(projections_by_event[event][pid].xp_total for pid in affordable)

        all_ids = [player.id for player in players]
        budgets = sorted({player.now_cost for player in players})
        for event in events:
            for budget in budgets:
                full = best_single_pick(all_ids, budget, event)
                survivors_only = best_single_pick(survivor_ids, budget, event)
                assert survivors_only == pytest.approx(full, abs=1e-9), (
                    f"trial {trial}, event {event}, budget={budget}: "
                    f"survivors achieve {survivors_only} but the full bucket achieves {full} — "
                    "an excluded player was necessary"
                )


# --- Memory is flat by construction ------------------------------------------


def _memory_fixture(pool_per_position: int) -> tuple[SquadState, BootstrapSnapshot, dict, TransferRules]:
    """Same 6-a-side shape as `_tiny_snapshot` (small `held`, so combo count
    stays low), `pool_per_position` extra candidates per position, one club
    per player so the team limit never masks out the grid — the point is to
    vary *only* the candidate-pool size.
    """
    positions = [
        Position(id=1, singular_name_short="GKP", squad_select=1, squad_min_play=1, squad_max_play=1),
        Position(id=2, singular_name_short="DEF", squad_select=2, squad_min_play=1, squad_max_play=2),
        Position(id=3, singular_name_short="MID", squad_select=2, squad_min_play=1, squad_max_play=2),
        Position(id=4, singular_name_short="FWD", squad_select=1, squad_min_play=1, squad_max_play=1),
    ]
    players: list[Player] = []
    next_id = 1
    held: list[int] = []
    for position_id, held_count in [(1, 1), (2, 2), (3, 2), (4, 1)]:
        for _ in range(held_count):
            players.append(Player(id=next_id, web_name=f"H{next_id}", team=next_id, element_type=position_id, now_cost=45))
            held.append(next_id)
            next_id += 1
    for position_id in (1, 2, 3, 4):
        for _ in range(pool_per_position):
            players.append(Player(id=next_id, web_name=f"X{next_id}", team=next_id, element_type=position_id, now_cost=45))
            next_id += 1

    deadlines = {
        1: datetime(2025, 8, 15, 17, 30, tzinfo=UTC),
        2: datetime(2025, 8, 22, 17, 30, tzinfo=UTC),
        3: datetime(2025, 8, 29, 17, 30, tzinfo=UTC),
    }
    snapshot = BootstrapSnapshot(
        events=[
            Gameweek(id=i, name=f"GW{i}", deadline_time=d, is_current=i == 1, is_next=i == 2, is_previous=False, finished=False)
            for i, d in deadlines.items()
        ],
        teams=[Club(id=index, name=f"Club {index}") for index in range(1, next_id)],
        element_types=positions,
        elements=players,
        game_settings=GameSettings(squad_squadsize=6, squad_squadplay=4, squad_team_limit=len(players), squad_total_spend=1000),
        raw={"game_config": {"scoring": {}}},
        fetched_at=datetime.now(UTC),
        season="test",
    )
    holdings = {pid: Holding(player=pid, purchase_price=45, bought_event=0) for pid in held}
    state = SquadState(holdings=holdings, bank=100, event=1, free_transfers=1)
    rules = TransferRules.from_snapshot(snapshot)
    projections = {
        (pid, event): _projection(pid, event, float((pid * 37 + event) % 15))
        for pid in snapshot.players_by_id
        for event in (2, 3)
    }
    return state, snapshot, projections, rules


def _search_peak_bytes(pool_per_position: int) -> int:
    """Peak Python-allocated bytes during one `optimise()` call at a fixed,
    ordinary `--beam` (4, the project default), varying only the candidate
    pool size — isolated from the interpreter/numpy/pydantic import
    baseline by measuring in-process with `tracemalloc`.

    Pool size, not beam width, is the axis that actually reproduces §7.2's
    defect: `--beam 1` vs `--beam 8` at a *fixed* pool did not distinguish
    the two designs at `horizon=2` (a single beam level's input is always
    one node, regardless of beam), and at `horizon=3` it conflated the
    defect with an unrelated, bounded `O(bucket_size x beam)` cost that the
    current, correct design also pays (accumulating one bucket's children
    before pruning) — beam=1 vs beam=6 differed by ~10 MB even on unmodified
    code. Growth with the *candidate pool* isolates the actual defect: the
    old design built one Node per scored cell (`~pool^2` for k=2) before
    ranking; the current one scores a numpy grid and only ever materialises
    `beam` winners.
    """
    state, snapshot, projections, rules = _memory_fixture(pool_per_position)
    tracemalloc.start()
    try:
        result = optimise(
            state, snapshot, projections, rules,
            from_event=2, horizon=2, beam=DEFAULT_BEAM, first_moves=1, max_hit=4,
            max_cells=10**9, now=NOW,
        )
        assert result.paths
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def test_peak_memory_does_not_grow_with_candidate_pool_size() -> None:
    """optimizer-search.md §7.2/§8: the streamed top-k design (§7.2's
    `_top_k_indices`) scores each candidate set as one numpy grid and
    materialises only the top-`beam` survivors as `Node` objects, so peak
    memory is bounded by the grid (compact floats) plus `O(beam)` objects —
    not by the candidate pool. A regression to materialising every scored
    child as a `Node` before ranking would make peak memory scale with the
    pool size (quadratically, at k = 2); this is the only kind of test that
    would catch it, since both designs produce identical output and
    asymptotic runtime.
    """
    narrow = _search_peak_bytes(pool_per_position=5)
    wide = _search_peak_bytes(pool_per_position=30)
    margin_bytes = 8 * 1024 * 1024  # generous against the grid itself (a 30^2 float64 grid is ~7 KB); §7.2's defect cost gigabytes.
    assert wide - narrow < margin_bytes, f"pool=5 peak {narrow} B vs pool=30 peak {wide} B — memory grew with the candidate pool"


# --- Determinism --------------------------------------------------------------


def test_optimise_is_deterministic(bootstrap_snapshot: BootstrapSnapshot) -> None:
    next_id = max(player.id for player in bootstrap_snapshot.elements) + 1
    extras = [
        Player(id=next_id + i, web_name=f"P{next_id + i}", team=(i % 5) + 1, element_type=1 + (i % 4), now_cost=45)
        for i in range(20)
    ]
    add_players(bootstrap_snapshot, *extras)
    rules = TransferRules.from_snapshot(bootstrap_snapshot)

    held = bootstrap_snapshot.players_by_id.keys()
    held = sorted(list(held))[:15]
    holdings = {pid: Holding(player=pid, purchase_price=45, bought_event=0) for pid in held}
    state = SquadState(holdings=holdings, bank=50, event=1, free_transfers=1)

    rng = random.Random("fu-optimizer-determinism")
    projections = {
        (pid, event): _projection(pid, event, rng.uniform(0.0, 12.0))
        for pid in bootstrap_snapshot.players_by_id
        for event in (2, 3)
    }

    kwargs = dict(
        from_event=2, horizon=2, beam=3, first_moves=6, max_hit=4, max_cells=10**9, now=NOW,
    )
    first = optimise(state, bootstrap_snapshot, projections, rules, **kwargs)
    second = optimise(state, bootstrap_snapshot, projections, rules, **kwargs)

    assert first.paths == second.paths
    assert first.hold == second.hold
    assert first.cost == second.cost
    assert first.dominance_exclusions == second.dominance_exclusions
    assert first.scope_gaps == second.scope_gaps

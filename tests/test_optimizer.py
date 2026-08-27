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

import numpy as np
import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings, Gameweek, Player, Position
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.optimizer import Transfer as OptTransfer
from fpl_cli.domain.optimizer import DEFAULT_BEAM, Node, SearchTooExpensive, _club_counts, _dominance_pool, _mask_k2, optimise
from fpl_cli.domain.transfers import Holding, SquadState, TransferRules, apply_transfers, selling_price

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
    # id -> (element_type, club); all distinct clubs so the team limit (3)
    # never binds and every combination is a clean read on xP.
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
    # FU-36: prices were uniform, so the affordability mask blocked 0 cells —
    # a milder instance of the same vacuous-guard shape as the generator
    # test below. Player 10 (a flat, already-non-optimal MID pool candidate:
    # see the `xp` table in the test) is priced far beyond any reachable
    # bank, so the mask actually binds without changing the known optimum.
    for player in players:
        if player.id == 10:
            player.now_cost = 500
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

    # Sizing check (FU-36): id 10 must be unaffordable under any reachable
    # bank — selling the entire held squad included — or the affordability
    # mask never actually blocks a cell and this fixture is back to proving
    # nothing about it.
    max_possible_bank_after = state.bank + sum(snapshot.players_by_id[pid].now_cost for pid in _TINY_HELD)
    assert snapshot.players_by_id[10].now_cost > max_possible_bank_after

    expected_best = _brute_force_best_score(state, snapshot, projections_by_event, rules, [2, 3], decay=0.84, ft_value=1.5)
    assert result.paths[0].score == pytest.approx(expected_best, abs=1e-9)


# --- The generator is a filter, not a bypass --------------------------------


def test_generator_children_are_all_accepted_by_apply_transfers(bootstrap_snapshot: BootstrapSnapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """optimizer-search.md §5.3: "the generator is a filter, not a bypass" —
    a candidate `apply_transfers` rejects must never survive into the
    search's output. `_materialize` enforces this by returning `None`
    (dropping the candidate) rather than wrapping the rejected result into a
    `Node`.

    FU-36: the previous version of this test asserted the *opposite* and
    stronger claim — that no candidate is ever rejected — which is false on
    live data (FU-35: `_dominance_pool` doesn't filter `can_select`, so an
    unselectable player can reach `apply_transfers` and be rejected there;
    335 times per default run). The fixture had no `can_select=False`
    player, so that branch was never reachable and the assertion could not
    fail: 0 of 8,712 `_materialize` calls across the whole suite. This
    version adds one dominant-but-unselectable candidate so the rejection
    path is actually exercised, and checks the property that is actually
    true of the current code — rejects get dropped, not smuggled through —
    rather than the one that was never true of it.
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

    # FU-36: added after the held-squad sampling pool above is captured, so
    # it can only ever be offered as a *buy* candidate, never dealt into a
    # starting squad — `can_select=False` there would just make the fixture
    # illegal from the outset, testing nothing about the generator.
    unselectable_id = next_id
    add_players(
        bootstrap_snapshot,
        Player(
            id=unselectable_id, web_name=f"P{unselectable_id}", team=(unselectable_id % 15) + 1,
            element_type=3, now_cost=45, can_select=False,
        ),
    )

    calls = []
    rejections = []

    def wrapper(*args, **kwargs):
        result = real_apply_transfers(*args, **kwargs)
        calls.append(result)
        if not result.validation.valid:
            rejections.append(result)
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
        # Dominate the MID pool on xP so the unselectable candidate is
        # (almost) always the top pick for a MID out-slot, forcing the
        # rejection branch rather than leaving it to chance.
        for event in (2, 3):
            projections[(unselectable_id, event)] = _projection(unselectable_id, event, 100.0)

        result = optimise(
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

        for path in result.paths:
            for node in path.chain():
                assert unselectable_id not in node.path_ids, (
                    "an apply_transfers-rejected candidate reached the search output — "
                    "the generator bypassed apply_transfers instead of filtering through it"
                )

    assert calls, "the property was never exercised — no apply_transfers calls were made"
    # Sizing check (FU-36), following test_known_outcome's pattern: without
    # this, the assertion above can't fail either, for the same reason the
    # original version of this test couldn't — nothing ever gets rejected.
    assert rejections, (
        "the can_select guard was never exercised — the unselectable player was never "
        "offered to apply_transfers, so the loop above proves nothing"
    )


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


# --- FU-33: _mask_k2's club check, tensor reference vs O(a + b + a·b) -------


def _mask_k2_tensor_reference(
    out_a: int,
    out_b: int,
    in_ids_a: list[int],
    in_ids_b: list[int],
    node: Node,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
) -> np.ndarray:
    """The pre-FU-33 implementation: a `(len_a, len_b, n_clubs)` int8 tensor,
    reduced with `.all(axis=2)`. Kept only as this test's reference — `_mask_k2`
    itself no longer does this."""
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
        i, j = np.meshgrid(np.arange(len(in_ids_a)), np.arange(len(in_ids_b)), indexing="ij")
        mask &= i < j
    return mask


def _club_mask_scenario(
    rng: random.Random, n_clubs: int, limit: int, pool_per_club: int
) -> tuple[BootstrapSnapshot, Node, TransferRules, int, int, list[int], list[int]]:
    """A snapshot + node with a random, *valid* held-squad club distribution
    (every club's held count in `[0, limit]`, matching the invariant
    `_mask_k2`'s O(a + b + a·b) formulation relies on: no club can already be
    over the limit) and candidate pools drawn from every club — the scenario
    the club check must be exact over, including the boundary slots-free
    counts of 0, 1, 2 and 3 that a `squad_team_limit` of 3 admits.
    """
    rules = TransferRules(
        sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000
    )
    players: list[Player] = []
    next_id = 1

    def add_player(team: int, element_type: int = 1) -> int:
        nonlocal next_id
        pid = next_id
        next_id += 1
        players.append(Player(id=pid, web_name=f"P{pid}", team=team, element_type=element_type, now_cost=0))
        return pid

    holdings: dict[int, Holding] = {}
    for club in range(1, n_clubs + 1):
        for _ in range(rng.randint(0, limit)):
            pid = add_player(club)
            holdings[pid] = Holding(player=pid, purchase_price=0, bought_event=0)
    while len(holdings) < 2:  # need two held players to serve as out_a/out_b
        pid = add_player(rng.randint(1, n_clubs))
        holdings[pid] = Holding(player=pid, purchase_price=0, bought_event=0)

    out_a, out_b = rng.sample(sorted(holdings), 2)
    same_position = rng.random() < 0.5
    element_type_b = 1 if same_position else 2
    for index, player in enumerate(players):
        if player.id == out_a:
            players[index] = player.model_copy(update={"element_type": 1})
        elif player.id == out_b:
            players[index] = player.model_copy(update={"element_type": element_type_b})

    candidates = [add_player(club) for club in range(1, n_clubs + 1) for _ in range(pool_per_club)]
    low = min(2, len(candidates))
    in_ids_a = rng.sample(candidates, k=rng.randint(low, len(candidates)))
    in_ids_b = in_ids_a if same_position else rng.sample(candidates, k=rng.randint(low, len(candidates)))

    snapshot = BootstrapSnapshot(
        events=[],
        teams=[Club(id=club, name=f"Club {club}") for club in range(1, n_clubs + 1)],
        element_types=[],
        elements=players,
        game_settings=GameSettings(squad_team_limit=limit),
        raw={"game_config": {"scoring": {}}},
        fetched_at=datetime.now(UTC),
        season="test",
    )
    node = Node(
        parent=None,
        transfers=(),
        event=1,
        state=SquadState(holdings=holdings, bank=0, event=1, free_transfers=1),
        score=0.0,
        net=0.0,
        hit_points=0,
        xi=None,
        total_transfers=0,
        path_ids=(),
    )
    return snapshot, node, rules, out_a, out_b, in_ids_a, in_ids_b


def test_mask_k2_club_check_matches_tensor_reference_at_slot_boundaries() -> None:
    """Explicit construction hitting all four slots-free boundaries a
    `squad_team_limit` of 3 admits (0, 1, 2, 3), for both a same-club
    candidate pair and a cross-club pair, same-position and cross-position.
    """
    limit = 3
    # Held: club 1 full (3, so 0 free after out_a/out_b removed elsewhere),
    # club 2 has 2 (1 free), club 3 has 1 (2 free), club 4 has none held (3 free).
    players = [Player(id=pid, web_name=f"P{pid}", team=club, element_type=1, now_cost=0) for pid, club in enumerate(
        [1, 1, 1, 2, 2, 3], start=1
    )]
    # out_a/out_b: two more held players, from clubs 5 and 6, untouched by
    # the boundary clubs above.
    players.append(Player(id=7, web_name="Pout_a", team=5, element_type=1, now_cost=0))
    players.append(Player(id=8, web_name="Pout_b", team=6, element_type=2, now_cost=0))
    # Candidates spanning every boundary club, plus club 5/6 themselves (the
    # outgoing players' own clubs, whose free count rises by one on removal).
    for pid, club in zip(range(9, 15), [1, 2, 3, 4, 5, 6]):
        players.append(Player(id=pid, web_name=f"P{pid}", team=club, element_type=1, now_cost=0))

    holdings = {pid: Holding(player=pid, purchase_price=0, bought_event=0) for pid in range(1, 9)}
    snapshot = BootstrapSnapshot(
        events=[],
        teams=[Club(id=club, name=f"Club {club}") for club in range(1, 7)],
        element_types=[],
        elements=players,
        game_settings=GameSettings(squad_team_limit=limit),
        raw={"game_config": {"scoring": {}}},
        fetched_at=datetime.now(UTC),
        season="test",
    )
    rules = TransferRules(
        sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000
    )
    node = Node(
        parent=None,
        transfers=(),
        event=1,
        state=SquadState(holdings=holdings, bank=0, event=1, free_transfers=1),
        score=0.0,
        net=0.0,
        hit_points=0,
        xi=None,
        total_transfers=0,
        path_ids=(),
    )

    in_ids = list(range(9, 15))  # one candidate per club 1..6

    for label, out_a, out_b, in_ids_a, in_ids_b in [
        ("cross-position, distinct in-clubs", 7, 8, in_ids, in_ids),
        ("cross-position, same in-club pair", 7, 8, [9, 9], [9, 9]),
    ]:
        expected = _mask_k2_tensor_reference(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
        actual = _mask_k2(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
        np.testing.assert_array_equal(actual, expected, err_msg=label)


def test_mask_k2_club_check_matches_tensor_reference_randomised() -> None:
    rng = random.Random("fu-mask-k2-club-check")
    for trial in range(200):
        n_clubs = rng.randint(2, 6)
        limit = rng.choice([1, 2, 3])
        snapshot, node, rules, out_a, out_b, in_ids_a, in_ids_b = _club_mask_scenario(
            rng, n_clubs=n_clubs, limit=limit, pool_per_club=rng.randint(1, 3)
        )
        expected = _mask_k2_tensor_reference(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
        actual = _mask_k2(out_a, out_b, in_ids_a, in_ids_b, node, snapshot, rules)
        np.testing.assert_array_equal(
            actual, expected, err_msg=f"trial {trial}: n_clubs={n_clubs}, limit={limit}, out_a={out_a}, out_b={out_b}"
        )


# --- FU-37: the --max-cells guard (optimizer-search.md §7.3) ---------------


def test_search_too_expensive_raises_before_any_grid_is_built(
    bootstrap_snapshot: BootstrapSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """optimizer-search.md §7.3/§8: a configuration whose `projected_cells`
    exceeds `--max-cells` must raise before the first grid is built, and the
    message must name the flags that reduce it.
    """
    import fpl_cli.domain.optimizer as optimizer_module

    next_id = max(player.id for player in bootstrap_snapshot.elements) + 1
    # One free-club (6-9), unheld candidate per position, so at least one
    # combo is legal and `projected_cells` is not trivially 0 regardless of
    # `max_cells` — a 0-vs-0 comparison would guard nothing.
    extras = [
        Player(id=next_id + i, web_name=f"P{next_id + i}", team=6 + i, element_type=1 + i, now_cost=45)
        for i in range(4)
    ]
    add_players(bootstrap_snapshot, *extras)
    rules = TransferRules.from_snapshot(bootstrap_snapshot)

    held = list(range(1, 16))
    holdings = {pid: Holding(player=pid, purchase_price=50, bought_event=0) for pid in held}
    state = SquadState(holdings=holdings, bank=50, event=1, free_transfers=1)
    projections = {
        (pid, event): _projection(pid, event, 5.0) for pid in bootstrap_snapshot.players_by_id for event in (2, 3)
    }

    def _grid_should_not_be_built(*args, **kwargs):
        raise AssertionError("a grid was scored after the guard should have refused the run")

    monkeypatch.setattr(optimizer_module, "_expand_root", _grid_should_not_be_built)

    with pytest.raises(SearchTooExpensive) as excinfo:
        optimise(
            state, bootstrap_snapshot, projections, rules,
            from_event=2, horizon=2, beam=2, first_moves=5, max_hit=4, max_cells=0, now=NOW,
        )

    # Sizing check: the guard must actually have something to refuse, or a
    # `max_cells=0` pass proves nothing about the projection itself.
    assert excinfo.value.cost.projected_cells > 0

    message = str(excinfo.value)
    for flag in ("--horizon", "--beam", "--first-moves", "--max-cells"):
        assert flag in message, f"{flag} missing from refusal message: {message!r}"


def test_cells_per_node_matches_candidates_actually_scored(
    bootstrap_snapshot: BootstrapSnapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """optimizer-search.md §7.3/§8: `cells_per_node` must agree with the
    number of candidates the real expansion actually scores as finite
    (mask-passed) cells — "a projection that drifts from reality is a guard
    that fires on the wrong runs".

    `bootstrap_snapshot`'s held squad already has every club at
    `squad_team_limit` (5 clubs x 3 players = 15), so a pool candidate
    sharing a saturated club is legal only for the one out-slot whose own
    club it is: some out-combinations get partially masked cells and others
    none. A fixture where nothing is ever masked (or everything is) would
    make the two counts agree trivially, the same vacuous shape FU-36 found
    elsewhere in this file.
    """
    import fpl_cli.domain.optimizer as optimizer_module

    next_id = max(player.id for player in bootstrap_snapshot.elements) + 1
    extras = [
        # One always-legal, free-club (6) candidate per position.
        Player(id=next_id + 0, web_name="Pfree0", team=6, element_type=1, now_cost=45),
        Player(id=next_id + 1, web_name="Pfree1", team=6, element_type=2, now_cost=45),
        Player(id=next_id + 2, web_name="Pfree2", team=6, element_type=3, now_cost=45),
        Player(id=next_id + 3, web_name="Pfree3", team=6, element_type=4, now_cost=45),
        # A second MID candidate in club 1 — held MID P10's own club (P10:
        # id 10, `team = 10 % 5 + 1 == 1`) — so it is legal only for the
        # out=10 combo and club-blocked for every other MID out-slot.
        Player(id=next_id + 4, web_name="Psaturated", team=1, element_type=3, now_cost=45),
    ]
    add_players(bootstrap_snapshot, *extras)
    rules = TransferRules.from_snapshot(bootstrap_snapshot)
    assert bootstrap_snapshot.players_by_id[10].team == 1  # the shared-club premise above

    held = list(range(1, 16))
    holdings = {pid: Holding(player=pid, purchase_price=50, bought_event=0) for pid in held}
    state = SquadState(holdings=holdings, bank=50, event=1, free_transfers=1)
    projections = {
        (pid, event): _projection(pid, event, 5.0) for pid in bootstrap_snapshot.players_by_id for event in (2, 3)
    }

    scored = 0
    real_top_k = optimizer_module._top_k_indices

    def counting_top_k(values, k, chunk_cells=optimizer_module.GRID_CHUNK_CELLS):
        nonlocal scored
        scored += int(np.isfinite(values).sum())
        return real_top_k(values, k, chunk_cells)

    monkeypatch.setattr(optimizer_module, "_top_k_indices", counting_top_k)

    # horizon=1 so every `_top_k_indices` call comes from `_expand_root` —
    # `cells_per_node` is defined and verified against the root node only
    # (optimizer-search.md §7.3's own table), and a deeper beam level would
    # count candidates the projection was never claiming to cover.
    result = optimise(
        state, bootstrap_snapshot, projections, rules,
        from_event=2, horizon=1, beam=4, first_moves=50, max_hit=4, max_cells=10**9, now=NOW,
    )

    assert scored > 0, "no candidate was ever scored — this fixture proves nothing"
    assert scored == result.cost.cells_per_node

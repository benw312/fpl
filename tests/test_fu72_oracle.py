"""The FU-72 plan oracle (`tools/fu72_plan_oracle.py`) against brute force.

The oracle's MILP is a second formulation of the squad and transfer rules, which
is exactly the drift CLAUDE.md warns about. These tests pin it to the shipped
rules two ways: its optimum must equal an exhaustive search whose every plan is
scored through `apply_transfers`, and its scorer must equal `objective_points`.

The league is built so each rule binds. The squad was bought at £4.0m and is now
£5.0m, so it sells at £4.5m (`selling_price`'s 50% fee), not £5.0m. Every club
already holds three. The good MID costs £5.7m, £0.2m more than a sale plus the
£1.0m bank reaches, so it can never be bought. CheapDEF (£5.0m) and CheapFWD
(£4.9m) are affordable together, just: £1.0m + 2 × £4.5m − £9.9m = £0.1m. So a
second GW3 transfer is possible, and it gains exactly the 4 points a hit costs.

Every test names the mutation it must fail against. Each was run against that
mutation before being kept. Skipped without the `oracle` extra.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("scipy")

from conftest import _bootstrap_snapshot  # noqa: E402

from fpl_cli.api.models import Player  # noqa: E402
from fpl_cli.domain.squad import best_xi, objective_points  # noqa: E402
from fpl_cli.domain.transfers import Holding, SquadState, Transfer, TransferRules  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fu72_plan_oracle as oracle  # noqa: E402

CHEAP_FWD, DEAR_MID, CHEAP_DEF = 16, 17, 18


def _league():
    snapshot = _bootstrap_snapshot()
    extras = [
        Player(id=CHEAP_FWD, web_name="CheapFWD", team=1, element_type=4, now_cost=49),
        Player(id=DEAR_MID, web_name="DearMID", team=2, element_type=3, now_cost=57),
        Player(id=CHEAP_DEF, web_name="CheapDEF", team=3, element_type=2, now_cost=50),
    ]
    snapshot = snapshot.model_copy(
        update={"elements": [*snapshot.elements, *extras], "fetched_at": datetime(2025, 8, 28, tzinfo=UTC)}
    )
    for cached in ("players_by_id", "clubs", "positions"):
        snapshot.__dict__.pop(cached, None)
    state = SquadState(
        holdings={pid: Holding(player=pid, purchase_price=40, bought_event=1) for pid in range(1, 16)},
        bank=10,
        event=2,
        free_transfers=0,
    )
    return snapshot, state, TransferRules.from_snapshot(snapshot)


# Base players score 2 a week; the extras score well. GW4's numbers make selling
# again worth considering. The club limit binds on the best move: DEF 7 is the
# only defender in CheapDEF's club and scores 6, so buying CheapDEF legally means
# selling 7. Without the limit the same move would sell a 2-point defender from
# another club and keep 7. FWD 15 plays the same role for CheapFWD.
_POINTS = {
    3: {**{pid: 2 for pid in range(1, 16)}, 7: 6, 15: 5, CHEAP_FWD: 9, DEAR_MID: 15, CHEAP_DEF: 7},
    4: {**{pid: 2 for pid in range(1, 16)}, 4: 6, 7: 6, 15: 5, CHEAP_FWD: 1, DEAR_MID: 15, CHEAP_DEF: 8},
}


def _brute_force(snapshot, state, rules, events, per_event_cap):
    """Every plan of at most `per_event_cap` transfers per event, scored through
    the shipped validator; invalid plans are skipped, not scored."""
    forecast = oracle.perfect_forecast(snapshot, _POINTS, events)
    ids = [player.id for player in snapshot.elements]
    singles = [Transfer(out_id=out, in_id=in_) for out in ids for in_ in ids if out != in_]
    batches = [()]
    for size in range(1, per_event_cap + 1):
        batches += list(itertools.combinations(singles, size))
    best = None
    for combination in itertools.product(batches, repeat=len(events)):
        plan = dict(zip(events, combination, strict=True))
        try:
            total = oracle.realise(state, plan, events, snapshot, rules, forecast).total
        except ValueError:
            continue
        best = total if best is None else max(best, total)
    return best


def test_the_milp_optimum_equals_brute_force_over_two_events() -> None:
    """One transfer per event over GW3-GW4: selling price, bank, club limit and
    flow all bind.

    Mutations: selling at `now_cost` instead of `selling_price` (DearMID becomes
    affordable); dropping the club-limit row; flipping the sign of `q` in the
    flow row.
    """
    snapshot, state, rules = _league()
    events = [3, 4]
    solved = oracle.solve_optimum(state, snapshot, rules, _POINTS, events, max_transfers_per_event=1)
    assert solved.objective == _brute_force(snapshot, state, rules, events, per_event_cap=1)
    replayed = oracle.realise(state, solved.plan, events, snapshot, rules, oracle.perfect_forecast(snapshot, _POINTS, events))
    assert replayed.total == solved.objective
    assert all(t.in_id != DEAR_MID for moves in solved.plan.values() for t in moves)


def test_the_milp_charges_hits_beyond_the_free_transfer_as_the_rules_do() -> None:
    """Two transfers in GW3 with one free: the second costs 4, exactly as
    `_fold_event` charges it.

    Mutations: dropping `u <= f` (every transfer becomes free); setting the
    starting availability to the cap instead of `free_transfers + 1`.
    """
    snapshot, state, rules = _league()
    events = [3]
    solved = oracle.solve_optimum(state, snapshot, rules, _POINTS, events, max_transfers_per_event=2)
    assert solved.objective == _brute_force(snapshot, state, rules, events, per_event_cap=2)
    replayed = oracle.realise(state, solved.plan, events, snapshot, rules, oracle.perfect_forecast(snapshot, _POINTS, events))
    assert replayed.total == solved.objective
    assert sum(replayed.hits.values()) == 4 * max(0, len(solved.plan[3]) - 1)


def test_the_scorer_is_objective_points_and_refuses_an_invalid_plan() -> None:
    """`realise` must score with the shipped XI and captain rule and must not
    score a plan the validator rejects.

    Mutation: removing the `validation.valid` check in `realise`.
    """
    snapshot, state, rules = _league()
    forecast = oracle.perfect_forecast(snapshot, _POINTS, [3])
    held = {pid: forecast[(pid, 3)] for pid in state.player_ids}
    expected = objective_points(best_xi(state.player_ids, held, snapshot), held)
    assert oracle.realise(state, {}, [3], snapshot, rules, forecast).total == expected
    with pytest.raises(ValueError, match="validator rejects"):
        oracle.realise(state, {3: [Transfer(out_id=1, in_id=CHEAP_FWD)]}, [3], snapshot, rules, forecast)


def test_the_perfect_forecast_is_realised_points_and_zero_when_absent() -> None:
    """Mutation: defaulting an absent player to anything but 0."""
    snapshot, _, _ = _league()
    forecast = oracle.perfect_forecast(snapshot, {3: {CHEAP_FWD: 9}}, [3])
    assert forecast[(CHEAP_FWD, 3)].xp_total == 9.0
    assert forecast[(1, 3)].xp_total == 0.0


def test_the_milp_refuses_a_state_not_placed_before_the_window() -> None:
    """fu-72-plan-scoring.md §1: exactly one accrual precedes the window.

    Mutation: removing the `state.event` guard.
    """
    snapshot, state, rules = _league()
    with pytest.raises(ValueError, match="events\\[0\\] - 1"):
        oracle.solve_optimum(replace(state, event=1), snapshot, rules, _POINTS, [3], max_transfers_per_event=1)

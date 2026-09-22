"""Score the optimiser's plans against realised points and a MILP optimum (FU-72).

docs/plans/fu-72-plan-scoring.md is the plan; this is its harness. Over a settled
three-gameweek window it asks how many realised points each of these plans earns:

    HOLD   no transfers
    P0     the program as shipped: component/1.2 forecast, default search
    O1-O4  the same search under a *perfect* forecast (xP = realised points),
           relaxing one default at a time: objective alignment, hit cap, beam
    M2     the exact optimum of the planner's own move space (<= 2 transfers/GW)
    Minf   the exact optimum under the full transfer rules

Each difference isolates one cause from FU-72 §1. Chips are not modelled on
either side (FU-72 cause 2), nor are autosubs, the vice-captain or in-window
price changes.

**This is an oracle.** It has seen the results, so it lives in `tools/`, is never
importable by the package, and refuses any gameweek that is not settled
(`fu53_minutes_oracle.py`'s rule).

**The MILP is checked by shipped code, not trusted.** Its plan is replayed
through `apply_transfers`, the same validator manual planning uses (CLAUDE.md).
Every event must validate, and the replayed realised score must equal the
MILP's own objective. A mismatch fails the run.

Usage (needs the `oracle` extra: pip install -e ".[oracle]"):
    python tools/fu72_plan_oracle.py --window 2            # GW2-GW4
    python tools/fu72_plan_oracle.py --window 3 --wide     # add O4 (~81x cost)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain import variants
from fpl_cli.domain.evaluation import actuals_from_live_event
from fpl_cli.domain.optimizer import (
    DEFAULT_BEAM,
    DEFAULT_DECAY,
    DEFAULT_FIRST_MOVES,
    DEFAULT_FT_VALUE,
    DEFAULT_MAX_HIT,
    K_ENUM,
    _validator_usable,
    optimise,
)
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.squad import best_xi, objective_points
from fpl_cli.domain.transfers import (
    Ledger,
    SquadState,
    Transfer,
    TransferRules,
    apply_transfers,
    replay,
    selling_price,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_report import PINNED, load  # noqa: E402

SQUAD = Path(__file__).resolve().parents[1] / "squad.json"
HORIZON = 3
UNBOUNDED_HIT = 10**9
WIDE_BEAM = 50
WIDE_FIRST_MOVES = 400


# --- The perfect forecast and the realised scorer -------------------------------


def perfect_forecast(
    snapshot: BootstrapSnapshot, points: Mapping[int, Mapping[int, float]], events: Sequence[int]
) -> dict[tuple[int, int], Projection]:
    """xP = realised total points, for every player in the snapshot and every
    event; a player absent from an event's live payload scored 0."""
    return {
        (player.id, event): Projection(
            player=player.id,
            event=event,
            xp_total=float(points[event].get(player.id, 0)),
            xp_appearance=0.0,
            xp_attack=0.0,
            xp_clean_sheet=0.0,
            xp_conceded=0.0,
            xp_saves=0.0,
            xp_defcon=0.0,
            xp_bonus=0.0,
            xp_cards=0.0,
            p_start=0.0,
            xmins=0.0,
            fixtures=1,
            model_version="oracle/actuals",
        )
        for player in snapshot.elements
        for event in events
    }


@dataclass(frozen=True)
class Realised:
    total: float
    per_event: dict[int, float]
    hits: dict[int, int]
    final: SquadState


def realise(
    state: SquadState,
    plan: Mapping[int, Sequence[Transfer]],
    events: Sequence[int],
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    forecast: Mapping[tuple[int, int], Projection],
) -> Realised:
    """Walk `plan` through `apply_transfers` and score each event's best XI and
    captain under `forecast` (the actuals), minus that event's hits. Raises if
    the shipped validator rejects any event — a plan that cannot be made is not
    scored."""
    per_event: dict[int, float] = {}
    hits: dict[int, int] = {}
    for event in events:
        result = apply_transfers(
            state, list(plan.get(event, ())), event, snapshot, rules, now=snapshot.fetched_at
        )
        if not result.validation.valid:
            raise ValueError(f"GW{event}: the validator rejects the plan: {result.validation.errors}")
        state = result.state
        by_player = {player: forecast[(player, event)] for player in state.player_ids}
        per_event[event] = objective_points(best_xi(state.player_ids, by_player, snapshot), by_player)
        hits[event] = result.hit_points
    total = sum(per_event.values()) - sum(hits.values())
    return Realised(total=total, per_event=per_event, hits=hits, final=state)


def path_plan(path) -> dict[int, list[Transfer]]:
    return {node.event: list(node.transfers) for node in path.chain()}


# --- The MILP --------------------------------------------------------------------


@dataclass(frozen=True)
class MilpResult:
    objective: float
    plan: dict[int, list[Transfer]]
    seconds: float
    status: str


def solve_optimum(
    state: SquadState,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    points: Mapping[int, Mapping[int, float]],
    events: Sequence[int],
    *,
    max_transfers_per_event: int,
    time_limit: float = 3600.0,
) -> MilpResult:
    """The exact optimum of realised window points, per fu-72-plan-scoring.md §3.

    Free transfers follow `_fold_event`: available F[e] = min(R[e-1] + 1, cap),
    remaining R[e] = F[e] - used[e], hits = transfers - used. `state.event` must
    be `events[0] - 1`, so exactly one accrual precedes the window.
    """
    from scipy.optimize import Bounds, LinearConstraint, milp  # noqa: PLC0415 - optional extra
    from scipy.sparse import lil_matrix  # noqa: PLC0415

    if state.event != events[0] - 1:
        raise ValueError("place the state at events[0] - 1 (fu-72-plan-scoring.md §1)")
    players = list(snapshot.elements)
    ids = [player.id for player in players]
    held = set(state.holdings)
    n_p, n_e = len(players), len(events)
    positions = snapshot.positions
    settings = snapshot.game_settings

    # Variable layout: five binaries per (player, event), then per event
    # n (transfers), u (free used), f (free available), bank.
    blocks = ("x", "s", "c", "b", "q")
    per_pe = len(blocks) * n_p * n_e

    def var(block: str, p: int, e: int) -> int:
        return (blocks.index(block) * n_e + e) * n_p + p

    def evar(kind: str, e: int) -> int:
        return per_pe + ("n", "u", "f", "bank").index(kind) * n_e + e

    n_vars = per_pe + 4 * n_e
    lower = np.zeros(n_vars)
    upper = np.ones(n_vars)
    integrality = np.ones(n_vars)
    cap = rules.free_transfer_cap
    for e in range(n_e):
        upper[evar("n", e)] = max_transfers_per_event
        upper[evar("u", e)] = cap
        upper[evar("f", e)] = cap
        upper[evar("bank", e)] = np.inf
        integrality[evar("bank", e)] = 0

    buyable = [_validator_usable(player) and player.can_transact for player in players]
    sell_price = [
        selling_price(state.holdings[player.id].purchase_price, player.now_cost, rules)
        if player.id in held
        else player.now_cost
        for player in players
    ]
    for p, player in enumerate(players):
        for e in range(n_e):
            if not buyable[p]:
                upper[var("b", p, e)] = 0
            if not player.can_transact:
                upper[var("q", p, e)] = 0

    rows: list[tuple[dict[int, float], float, float]] = []

    def row(coefficients: dict[int, float], lo: float, hi: float) -> None:
        rows.append((coefficients, lo, hi))

    for e in range(n_e):
        for p, player in enumerate(players):
            before = {var("x", p, e - 1): -1.0} if e > 0 else {}
            start = 0.0 if e > 0 else (1.0 if player.id in held else 0.0)
            # x[e] - x[e-1] - b + q = start (flow)
            row({var("x", p, e): 1.0, **before, var("b", p, e): -1.0, var("q", p, e): 1.0}, start, start)
            row({var("s", p, e): 1.0, var("x", p, e): -1.0}, -np.inf, 0.0)  # starts only if held
            row({var("c", p, e): 1.0, var("s", p, e): -1.0}, -np.inf, 0.0)  # captain only if starting
            row({var("b", p, e): 1.0, var("q", p, e): 1.0}, -np.inf, 1.0)  # never both in one event
        for position_id, position in positions.items():
            members = [p for p, player in enumerate(players) if player.element_type == position_id]
            row({var("x", p, e): 1.0 for p in members}, position.squad_select, position.squad_select)
            row({var("s", p, e): 1.0 for p in members}, position.squad_min_play, position.squad_max_play)
        for club in snapshot.clubs:
            members = [p for p, player in enumerate(players) if player.team == club]
            if members:
                row({var("x", p, e): 1.0 for p in members}, -np.inf, settings.squad_team_limit)
        row({var("s", p, e): 1.0 for p in range(n_p)}, settings.squad_squadplay, settings.squad_squadplay)
        row({var("c", p, e): 1.0 for p in range(n_p)}, 1, 1)
        # n = sum of buys; buys = sells (a transfer is one of each)
        row({evar("n", e): 1.0, **{var("b", p, e): -1.0 for p in range(n_p)}}, 0, 0)
        row({**{var("b", p, e): 1.0 for p in range(n_p)}, **{var("q", p, e): -1.0 for p in range(n_p)}}, 0, 0)
        # bank[e] = bank[e-1] + sells - buys
        money = {evar("bank", e): 1.0}
        if e > 0:
            money[evar("bank", e - 1)] = -1.0
        for p, player in enumerate(players):
            money[var("b", p, e)] = money.get(var("b", p, e), 0.0) + player.now_cost
            money[var("q", p, e)] = money.get(var("q", p, e), 0.0) - sell_price[p]
        opening = float(state.bank) if e == 0 else 0.0
        row(money, opening, opening)
        # free transfers: u <= f, u <= n, f[e] <= f[e-1] - u[e-1] + 1, f[0] <= start + 1
        row({evar("u", e): 1.0, evar("f", e): -1.0}, -np.inf, 0)
        row({evar("u", e): 1.0, evar("n", e): -1.0}, -np.inf, 0)
        if e == 0:
            row({evar("f", 0): 1.0}, -np.inf, min(state.free_transfers + rules.free_transfers_per_event, cap))
        else:
            row(
                {evar("f", e): 1.0, evar("f", e - 1): -1.0, evar("u", e - 1): 1.0},
                -np.inf,
                rules.free_transfers_per_event,
            )

    matrix = lil_matrix((len(rows), n_vars))
    lo = np.empty(len(rows))
    hi = np.empty(len(rows))
    for index, (coefficients, low, high) in enumerate(rows):
        for column, value in coefficients.items():
            matrix[index, column] = value
        lo[index], hi[index] = low, high

    objective = np.zeros(n_vars)  # milp minimises
    for e, event in enumerate(events):
        for p, player_id in enumerate(ids):
            gained = float(points[event].get(player_id, 0))
            objective[var("s", p, e)] = -gained
            objective[var("c", p, e)] = -gained
        objective[evar("n", e)] = rules.points_per_extra_transfer
        objective[evar("u", e)] = -rules.points_per_extra_transfer

    started = time.monotonic()
    result = milp(
        objective,
        constraints=LinearConstraint(matrix.tocsr(), lo, hi),
        integrality=integrality,
        bounds=Bounds(lower, upper),
        options={"time_limit": time_limit, "mip_rel_gap": 0.0},
    )
    seconds = time.monotonic() - started
    if result.x is None:
        raise RuntimeError(f"MILP found no solution: {result.message}")
    if result.status != 0:
        raise RuntimeError(f"MILP not proven optimal ({result.message}); refusing to report it as the optimum.")

    solution = np.round(result.x).astype(int)
    plan: dict[int, list[Transfer]] = {}
    for e, event in enumerate(events):
        bought = sorted(ids[p] for p in range(n_p) if solution[var("b", p, e)])
        sold = sorted(ids[p] for p in range(n_p) if solution[var("q", p, e)])
        plan[event] = [Transfer(out_id=out, in_id=in_) for out, in_ in zip(sold, bought, strict=True)]
    return MilpResult(objective=-result.fun, plan=plan, seconds=seconds, status=result.message)


# --- The run -----------------------------------------------------------------------


def _describe(plan: Mapping[int, Sequence[Transfer]], names: Mapping[int, str]) -> str:
    parts = []
    for event in sorted(plan):
        moves = plan[event]
        if moves:
            parts.append(f"GW{event}: " + ", ".join(f"{names[t.out_id]}→{names[t.in_id]}" for t in moves))
    return "; ".join(parts) or "no transfers"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", type=int, required=True, help="first gameweek of the three-gameweek window")
    parser.add_argument("--pinned", default=str(PINNED))
    parser.add_argument("--wide", action="store_true", help=f"add O4: beam {WIDE_BEAM}, first moves {WIDE_FIRST_MOVES}")
    parser.add_argument("--skip-planner", action="store_true", help="MILP runs only")
    parser.add_argument(
        "--forecasts",
        nargs="+",
        default=None,
        help="instead of the full run: score the default search's plan under each named variant's forecast",
    )
    args = parser.parse_args(argv)

    pinned = Path(args.pinned).expanduser()
    events = [args.window + offset for offset in range(HORIZON)]
    snapshot, fixtures, _ = load(events[0], pinned)
    points: dict[int, dict[int, float]] = {}
    for event in events:
        _, _, live = load(event, pinned)  # refuses an unsettled gameweek
        points[event] = {player: actual.total_points for player, actual in actuals_from_live_event(live).items()}

    rules = TransferRules.from_snapshot(snapshot)
    start = replace(replay(Ledger.from_file(SQUAD, snapshot), snapshot), event=events[0] - 1, free_transfers=0)
    names = {player.id: player.web_name for player in snapshot.elements}
    oracle = perfect_forecast(snapshot, points, events)
    print(f"window GW{events[0]}-GW{events[-1]}; squad {SQUAD.name} at GW{start.event}, "
          f"{start.free_transfers} banked (1 free at GW{events[0]}), bank £{start.bank / 10:.1f}m")

    rows: list[tuple[str, Realised, str]] = []

    def record(label: str, plan: Mapping[int, Sequence[Transfer]], note: str = "") -> Realised:
        realised = realise(start, plan, events, snapshot, rules, oracle)
        rows.append((label, realised, note or _describe(plan, names)))
        print(f"  {label:5s} {realised.total:7.1f}  {note or _describe(plan, names)}", flush=True)
        return realised

    record("HOLD", {})

    if args.forecasts:
        # The points-based view of model quality (fu-72-results.md §3's gap):
        # the same default search, fed each forecast, scored on realised points.
        # A measurement, not a criterion — nothing here promotes a model.
        for name in args.forecasts:
            variant = variants.get(name)
            model = variants.build(variant, snapshot, fixtures)
            try:
                forecast = model.project([player.id for player in snapshot.elements], events)
            except ValueError as exc:
                print(f"  {name}: cannot project GW{events[0]}-GW{events[-1]} ({exc})", flush=True)
                continue
            result = optimise(start, snapshot, forecast, rules, from_event=events[0], horizon=HORIZON,
                              now=snapshot.fetched_at)
            record(f"P[{variant.version}]", path_plan(result.paths[0]))
        return 0

    if not args.skip_planner:
        model = variants.build(variants.get("component/1.2"), snapshot, fixtures)
        forecast = model.project([player.id for player in snapshot.elements], events)
        runs = [
            ("P0", forecast, {}),
            ("O1", oracle, {}),
            ("O2", oracle, {"decay": 1.0, "ft_value": 0.0}),
            ("O3", oracle, {"decay": 1.0, "ft_value": 0.0, "max_hit": UNBOUNDED_HIT}),
        ]
        if args.wide:
            runs.append(("O4", oracle, {"decay": 1.0, "ft_value": 0.0, "max_hit": UNBOUNDED_HIT,
                                        "beam": WIDE_BEAM, "first_moves": WIDE_FIRST_MOVES,
                                        "max_cells": 10**12}))
        for label, projections, settings in runs:
            began = time.monotonic()
            result = optimise(start, snapshot, projections, rules, from_event=events[0], horizon=HORIZON,
                              now=snapshot.fetched_at, **settings)
            best = result.paths[0]
            record(label, path_plan(best))
            print(f"        ({time.monotonic() - began:.0f}s; settings {settings or 'defaults'})", flush=True)

    for label, cap in (("M2", K_ENUM), ("Minf", rules.transfers_cap)):
        solved = solve_optimum(start, snapshot, rules, points, events, max_transfers_per_event=cap)
        realised = record(label, solved.plan)
        if abs(realised.total - solved.objective) > 1e-6:
            raise SystemExit(f"{label}: MILP objective {solved.objective} != replayed {realised.total}")
        print(f"        ({solved.seconds:.0f}s; replay through apply_transfers matches the MILP objective)",
              flush=True)

    print(f"\ndefaults: decay {DEFAULT_DECAY}, ft_value {DEFAULT_FT_VALUE}, max_hit {DEFAULT_MAX_HIT}, "
          f"beam {DEFAULT_BEAM}, first moves {DEFAULT_FIRST_MOVES}, k_enum {K_ENUM}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

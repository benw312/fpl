"""A points-based criterion: paired, multi-squad plan scoring. **AN ORACLE.**

docs/plans/points-criterion.md is the plan. For each settled three-gameweek window,
draw N legal starting squads by ownership-weighted sampling from the window's
pre-deadline capture. For each squad and each model, score the default search's
plan on realised points, exactly as FU-72 does (`fu72_plan_oracle.realise`). Models
are compared **paired**, on the same squads.

Reads settled results, so it lives in `tools/` and refuses unsettled gameweeks.

Usage:
    python tools/points_criterion.py --windows 2 3 --squads 40 \\
        --models naive/1.0 component/1.1-price component/1.2 --out results.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_report import PINNED, load  # noqa: E402
from fu72_plan_oracle import HORIZON, path_plan, perfect_forecast, realise  # noqa: E402

from fpl_cli.api.models import BootstrapSnapshot  # noqa: E402
from fpl_cli.domain import variants  # noqa: E402
from fpl_cli.domain.evaluation import actuals_from_live_event  # noqa: E402
from fpl_cli.domain.optimizer import _validator_usable, optimise  # noqa: E402
from fpl_cli.domain.rules import validate_squad_structure  # noqa: E402
from fpl_cli.domain.transfers import Holding, SquadState, TransferRules  # noqa: E402

DEFAULT_SEED = 20261001


# --- The squad sampler -------------------------------------------------------------


@dataclass(frozen=True)
class SampledSquad:
    player_ids: tuple[int, ...]
    bank: int


def _ownership(player) -> float:
    try:
        return max(float(player.selected_by_percent), 0.0)
    except (TypeError, ValueError):
        return 0.0


def sample_squad(snapshot: BootstrapSnapshot, rng: random.Random, *, max_attempts: int = 1000) -> SampledSquad:
    """One legal squad, players drawn with probability proportional to ownership.

    Slots are filled in a shuffled order so that no position always gets first
    claim on the budget. A candidate is admissible only if the club limit holds
    and the rest of the squad can still be filled at the cheapest eligible
    prices. A player with zero ownership can still be drawn, at a small floor
    weight, so a squad can always be completed.
    """
    budget = snapshot.game_settings.squad_total_spend
    limit = snapshot.game_settings.squad_team_limit
    eligible = [p for p in snapshot.elements if _validator_usable(p) and p.can_transact]
    by_position: dict[int, list] = {}
    for player in eligible:
        by_position.setdefault(player.element_type, []).append(player)
    for players in by_position.values():
        players.sort(key=lambda p: p.now_cost)

    for _ in range(max_attempts):
        slots = [pid for pid, pos in snapshot.positions.items() for _ in range(pos.squad_select)]
        rng.shuffle(slots)
        chosen: list = []
        clubs: dict[int, int] = {}
        spent = 0
        for index, position in enumerate(slots):
            rest = slots[index + 1 :]
            held = {p.id for p in chosen}

            def cheapest_fill(extra_ids: set[int]) -> int:
                # Club limits are ignored here; a squad that then cannot be
                # completed is rejected and redrawn (max_attempts).
                total = 0
                used = set(held) | extra_ids
                for slot in rest:
                    pick = next((p for p in by_position[slot] if p.id not in used), None)
                    if pick is None:
                        return 10**9
                    used.add(pick.id)
                    total += pick.now_cost
                return total

            options = [
                p
                for p in by_position[position]
                if p.id not in held
                and clubs.get(p.team, 0) < limit
                and spent + p.now_cost + cheapest_fill({p.id}) <= budget
            ]
            if not options:
                break
            weights = [_ownership(p) + 0.01 for p in options]
            pick = rng.choices(options, weights=weights, k=1)[0]
            chosen.append(pick)
            clubs[pick.team] = clubs.get(pick.team, 0) + 1
            spent += pick.now_cost
        else:
            ids = tuple(sorted(p.id for p in chosen))
            if validate_squad_structure(list(ids), snapshot).valid:
                return SampledSquad(player_ids=ids, bank=budget - spent)
    raise RuntimeError("could not sample a legal squad")


def sample_squads(snapshot: BootstrapSnapshot, n: int, seed: int) -> list[SampledSquad]:
    rng = random.Random(seed)
    return [sample_squad(snapshot, rng) for _ in range(n)]


def starting_state(squad: SampledSquad, snapshot: BootstrapSnapshot, window: int) -> SquadState:
    """Bought at the window's prices, placed so one free transfer is available
    at `window` (FU-72's state rule)."""
    prices = {p.id: p.now_cost for p in snapshot.elements}
    return SquadState(
        holdings={pid: Holding(player=pid, purchase_price=prices[pid], bought_event=window - 1) for pid in squad.player_ids},
        bank=squad.bank,
        event=window - 1,
        free_transfers=0,
    )


# --- The parallel runner -------------------------------------------------------------

_CACHE: dict = {}


def _window_context(window: int, pinned: str, models: tuple[str, ...]):
    key = (window, pinned, models)
    if key not in _CACHE:
        events = [window + offset for offset in range(HORIZON)]
        snapshot, fixtures, _ = load(events[0], Path(pinned))
        points = {}
        for event in events:
            _, _, live = load(event, Path(pinned))
            points[event] = {p: a.total_points for p, a in actuals_from_live_event(live).items()}
        ids = [p.id for p in snapshot.elements]
        forecasts = {
            name: variants.build(variants.get(name), snapshot, fixtures).project(ids, events) for name in models
        }
        _CACHE[key] = (
            snapshot,
            events,
            TransferRules.from_snapshot(snapshot),
            perfect_forecast(snapshot, points, events),
            forecasts,
        )
    return _CACHE[key]


def _score(task):
    window, pinned, models, squad = task
    snapshot, events, rules, oracle, forecasts = _window_context(window, pinned, models)
    state = starting_state(squad, snapshot, window)
    row = {"window": window, "squad": list(squad.player_ids), "bank": squad.bank}
    row["HOLD"] = realise(state, {}, events, snapshot, rules, oracle).total
    for name in models:
        result = optimise(state, snapshot, forecasts[name], rules, from_event=events[0], horizon=HORIZON,
                          now=snapshot.fetched_at)
        row[name] = realise(state, path_plan(result.paths[0]), events, snapshot, rules, oracle).total
    return row


# --- Statistics ---------------------------------------------------------------------


def paired(rows: list[dict], candidate: str, incumbent: str) -> dict:
    diffs = [row[candidate] - row[incumbent] for row in rows]
    n = len(diffs)
    mean = statistics.fmean(diffs)
    sd = statistics.stdev(diffs) if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "se": sd / math.sqrt(n) if n else 0.0,
        "positive": sum(d > 0 for d in diffs),
        "zero": sum(d == 0 for d in diffs),
        "negative": sum(d < 0 for d in diffs),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--windows", type=int, nargs="+", required=True)
    parser.add_argument("--squads", type=int, default=40)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--pinned", default=str(PINNED))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    pinned = str(Path(args.pinned).expanduser())
    models = tuple(args.models)
    tasks = []
    for window in args.windows:
        snapshot, *_ = load(window, Path(pinned))
        for squad in sample_squads(snapshot, args.squads, args.seed + window):
            tasks.append((window, pinned, models, squad))

    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_score, tasks, chunksize=1))
    print(f"{len(rows)} squad-windows in {time.monotonic() - started:.0f}s")

    for window in args.windows:
        subset = [row for row in rows if row["window"] == window]
        print(f"\nwindow GW{window}-GW{window + HORIZON - 1}, {len(subset)} squads")
        for name in models:
            gain = [row[name] - row["HOLD"] for row in subset]
            print(f"  {name:32s} vs HOLD: mean {statistics.fmean(gain):+7.2f}  sd {statistics.stdev(gain):6.2f}")
        for i, a in enumerate(models):
            for b in models[i + 1 :]:
                stats = paired(subset, b, a)
                print(f"  {b} − {a}: mean {stats['mean']:+6.2f}  sd {stats['sd']:5.2f}  se {stats['se']:5.2f}  "
                      f"(+{stats['positive']} ={stats['zero']} −{stats['negative']})")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

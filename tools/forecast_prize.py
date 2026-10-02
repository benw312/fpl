"""Bound the prize for each candidate forecast direction. **AN ORACLE.**

docs/plans/forecast-prize-bounds.md is the plan. Each candidate's best case is fed
to the shipped planner (`optimise`, default settings) and scored on realised points
exactly as FU-72 scores plans, alongside the evaluation harness's Spearman figures:

    A  will-he-play   component/1.1-price with realised minutes, rates untouched
    B  magnitudes     1.2's xP isotonically recalibrated to realised points, per
                      event, in-sample -- ranking unchanged by construction
    C  ep_next        FPL's own ep_next, replicated across the window (crude:
                      FPL publishes nothing further ahead)
    D  rates          1.2's own appearance term + realised NON-appearance points
                      (goals, assists, clean sheets, bonus, saves, cards...): the
                      model keeps its minutes uncertainty, and knows who hauls
    E  chance quality D, but goal and assist points replaced by realised xG and
                      xA valued at the position's scoring -- the chances each
                      player actually got, without the finishing luck
    F  defence luck   D, but clean-sheet and goals-conceded points replaced by
                      their expectation under Poisson(realised xGC while on the
                      pitch) -- the chances conceded, without the keeper's luck
    G  all chance quality  E and F together
    H  defence only   1.2 as shipped, but its clean-sheet and conceded terms
                      replaced by their expectation under realised xGC
    I  attack only    1.2 as shipped, but its attack term replaced by realised
                      xG/xA at their point values

A and B are ceilings and C is a proxy for a cheap real change. None of them is a
criterion, and nothing here changes a model.

Reuses `fu72_plan_oracle` for state, scoring and the settled-only rule, and
`fu53_minutes_oracle` for the minutes substitution, so there is no second
expression of the model.

Usage: python tools/forecast_prize.py --window 2
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fu53_minutes_oracle import component_oracle_projections, realised_from_live  # noqa: E402
from fu72_plan_oracle import HORIZON, SQUAD, path_plan, perfect_forecast, realise  # noqa: E402
from calibration_report import PINNED, load  # noqa: E402

from fpl_cli.domain import variants  # noqa: E402
from fpl_cli.domain.evaluation import actuals_from_live_event, evaluate_model  # noqa: E402
from fpl_cli.domain.optimizer import optimise  # noqa: E402
from fpl_cli.domain.projections import Projection  # noqa: E402
from fpl_cli.domain.transfers import Ledger, TransferRules, replay  # noqa: E402


def isotonic(predicted: Sequence[float], actual: Sequence[float]) -> list[float]:
    """Pool-adjacent-violators: the non-decreasing fit of `actual` on `predicted`,
    returned in input order. Tied predictions share one fitted value, so the
    order of the input is never reversed. A ceiling for recalibration, because it
    is fitted on the very outcomes it is then scored against."""
    order = sorted(range(len(predicted)), key=lambda i: predicted[i])
    # Merge exact ties first, so tied predictions cannot be split apart.
    blocks: list[list[float]] = []  # [sum, count, first_index_in_order, last]
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and predicted[order[end + 1]] == predicted[order[position]]:
            end += 1
        total = sum(actual[order[k]] for k in range(position, end + 1))
        blocks.append([total, end - position + 1, position, end])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            last = blocks.pop()
            blocks[-1][0] += last[0]
            blocks[-1][1] += last[1]
            blocks[-1][3] = last[3]
        position = end + 1
    fitted = [0.0] * len(predicted)
    for total, count, first, last in blocks:
        for k in range(int(first), int(last) + 1):
            fitted[order[k]] = total / count
    return fitted


def recalibrated(
    forecast: Mapping[tuple[int, int], Projection], points: Mapping[int, Mapping[int, float]], events: Sequence[int]
) -> dict[tuple[int, int], Projection]:
    result: dict[tuple[int, int], Projection] = {}
    for event in events:
        keys = [key for key in forecast if key[1] == event]
        fitted = isotonic([forecast[k].xp_total for k in keys], [float(points[event].get(k[0], 0)) for k in keys])
        for key, value in zip(keys, fitted, strict=True):
            result[key] = replace(forecast[key], xp_total=value)
    return result


def rates_oracle(
    forecast: Mapping[tuple[int, int], Projection], lives: Mapping[int, object], events: Sequence[int]
) -> dict[tuple[int, int], Projection]:
    """D: the modelled appearance points, plus everything else as realised. A
    player who did not play realised nothing beyond appearance, so his term is
    the model's alone -- the minutes uncertainty stays modelled."""
    result: dict[tuple[int, int], Projection] = {}
    for event in events:
        actual = actuals_from_live_event(lives[event])
        for key, projection in forecast.items():
            if key[1] != event:
                continue
            outcome = actual.get(key[0])
            rest = 0.0 if outcome is None else outcome.total_points - outcome.component_points.get("xp_appearance", 0.0)
            result[key] = replace(projection, xp_total=projection.xp_appearance + rest)
    return result


def chance_quality_oracle(
    forecast: Mapping[tuple[int, int], Projection],
    lives: Mapping[int, object],
    events: Sequence[int],
    snapshot,
) -> dict[tuple[int, int], Projection]:
    """E: D with the attack term (goals and assists, `xp_attack` in the
    evaluation's mapping) swapped for realised xG and xA at their point values."""
    scoring = snapshot.raw["game_config"]["scoring"]
    position_of = {p.id: snapshot.positions[p.element_type].singular_name_short for p in snapshot.elements}
    result: dict[tuple[int, int], Projection] = {}
    for event in events:
        actual = actuals_from_live_event(lives[event])
        stats = {element.id: element.stats for element in lives[event].elements}
        for key, projection in forecast.items():
            if key[1] != event:
                continue
            outcome = actual.get(key[0])
            if outcome is None:
                result[key] = replace(projection, xp_total=projection.xp_appearance)
                continue
            parts = outcome.component_points
            rest = outcome.total_points - parts.get("xp_appearance", 0.0) - parts.get("xp_attack", 0.0)
            s = stats[key[0]]
            expected_attack = (
                float(s.get("expected_goals") or 0) * scoring["goals_scored"][position_of[key[0]]]
                + float(s.get("expected_assists") or 0) * scoring["assists"]
            )
            result[key] = replace(projection, xp_total=projection.xp_appearance + rest + expected_attack)
    return result


def _poisson_floor_half(rate: float) -> float:
    """E[floor(k/2)] for k ~ Poisson(rate): FPL's goals-conceded penalty unit."""
    pmf, total = math.exp(-rate), 0.0
    for k in range(0, 25):
        if k:
            pmf *= rate / k
        total += pmf * (k // 2)
    return total


def defence_luck_removed(
    forecast: Mapping[tuple[int, int], Projection], lives: Mapping[int, object], events: Sequence[int], snapshot
) -> dict[tuple[int, int], Projection]:
    """F/G helper: swap each player's realised clean-sheet and conceded points
    for their expectation under his realised xGC. Applied to D's or E's
    forecast, whose xp_total already holds the realised components."""
    scoring = snapshot.raw["game_config"]["scoring"]
    position_of = {p.id: snapshot.positions[p.element_type].singular_name_short for p in snapshot.elements}
    result: dict[tuple[int, int], Projection] = {}
    for event in events:
        actual = actuals_from_live_event(lives[event])
        stats = {element.id: element.stats for element in lives[event].elements}
        for key, projection in forecast.items():
            if key[1] != event:
                continue
            outcome = actual.get(key[0])
            if outcome is None:
                result[key] = projection
                continue
            s, pos = stats[key[0]], position_of[key[0]]
            xgc = float(s.get("expected_goals_conceded") or 0)
            minutes = float(s.get("minutes") or 0)
            expected_cs = (math.exp(-xgc) if minutes >= 60 else 0.0) * scoring["clean_sheets"][pos]
            expected_gc = _poisson_floor_half(xgc) * scoring["goals_conceded"][pos] if minutes > 0 else 0.0
            realised = outcome.component_points.get("xp_clean_sheet", 0.0) + outcome.component_points.get("xp_conceded", 0.0)
            result[key] = replace(projection, xp_total=projection.xp_total - realised + expected_cs + expected_gc)
    return result


def model_terms_replaced(
    forecast: Mapping[tuple[int, int], Projection],
    lives: Mapping[int, object],
    events: Sequence[int],
    snapshot,
    *,
    defence: bool,
) -> dict[tuple[int, int], Projection]:
    """H (defence=True) or I (defence=False): one modelled half swapped for its
    chance-quality truth, everything else left as 1.2 modelled it."""
    scoring = snapshot.raw["game_config"]["scoring"]
    position_of = {p.id: snapshot.positions[p.element_type].singular_name_short for p in snapshot.elements}
    result: dict[tuple[int, int], Projection] = {}
    for event in events:
        stats = {element.id: element.stats for element in lives[event].elements}
        for key, projection in forecast.items():
            if key[1] != event:
                continue
            s, pos = stats.get(key[0]), position_of[key[0]]
            if s is None:
                result[key] = projection
                continue
            minutes = float(s.get("minutes") or 0)
            if defence:
                xgc = float(s.get("expected_goals_conceded") or 0)
                truth = (math.exp(-xgc) if minutes >= 60 else 0.0) * scoring["clean_sheets"][pos]
                truth += _poisson_floor_half(xgc) * scoring["goals_conceded"][pos] if minutes > 0 else 0.0
                modelled = projection.xp_clean_sheet + projection.xp_conceded
            else:
                truth = (float(s.get("expected_goals") or 0) * scoring["goals_scored"][pos]
                         + float(s.get("expected_assists") or 0) * scoring["assists"])
                modelled = projection.xp_attack
            result[key] = replace(projection, xp_total=projection.xp_total - modelled + truth)
    return result


def ep_next_forecast(snapshot, events: Sequence[int]) -> dict[tuple[int, int], Projection]:
    ep = {player.id: float(player.ep_next or 0.0) for player in snapshot.elements}
    return perfect_forecast(snapshot, {event: ep for event in events}, events)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--window", type=int, required=True)
    parser.add_argument("--pinned", default=str(PINNED))
    args = parser.parse_args(argv)
    pinned = Path(args.pinned).expanduser()
    events = [args.window + offset for offset in range(HORIZON)]

    snapshot, fixtures, _ = load(events[0], pinned)
    lives = {event: load(event, pinned)[2] for event in events}  # refuses an unsettled gameweek
    points = {e: {p: a.total_points for p, a in actuals_from_live_event(lives[e]).items()} for e in events}
    actuals_first = actuals_from_live_event(lives[events[0]])
    rules = TransferRules.from_snapshot(snapshot)
    start = replace(replay(Ledger.from_file(SQUAD, snapshot), snapshot), event=events[0] - 1, free_transfers=0)
    oracle = perfect_forecast(snapshot, points, events)
    ids = [player.id for player in snapshot.elements]

    shipped = variants.build(variants.get("component/1.2"), snapshot, fixtures).project(ids, events)
    price = variants.build(variants.get("component/1.1-price"), snapshot, fixtures)
    minutes_oracle: dict[tuple[int, int], Projection] = {}
    for event in events:
        realised = realised_from_live(lives[event])
        for pid, projection in component_oracle_projections(price, ids, event, realised, "full").items():
            minutes_oracle[(pid, event)] = projection

    runs = {
        "P0  1.2 as shipped": shipped,
        "A   minutes oracle (1.1-price rates)": minutes_oracle,
        "B   1.2 recalibrated (isotonic)": recalibrated(shipped, points, events),
        "C   ep_next across window": ep_next_forecast(snapshot, events),
        "D   rates oracle (1.2 appearance kept)": rates_oracle(shipped, lives, events),
        "E   chance quality (D, xG/xA for goals)": chance_quality_oracle(shipped, lives, events, snapshot),
        "F   defence luck removed (D, xGC for CS)": defence_luck_removed(
            rates_oracle(shipped, lives, events), lives, events, snapshot),
        "G   all chance quality (E + F)": defence_luck_removed(
            chance_quality_oracle(shipped, lives, events, snapshot), lives, events, snapshot),
        "H   defence chance quality only": model_terms_replaced(shipped, lives, events, snapshot, defence=True),
        "I   attack chance quality only": model_terms_replaced(shipped, lives, events, snapshot, defence=False),
        "O1  perfect forecast": oracle,
    }
    hold = realise(start, {}, events, snapshot, rules, oracle).total
    print(f"window GW{events[0]}-GW{events[-1]}; HOLD {hold:.0f}")
    print(f"  {'forecast':40s} {'points':>6} {'vs P0':>6}  {'sp_played':>9} {'sp_all':>7}")
    baseline = None
    for label, forecast in runs.items():
        result = optimise(start, snapshot, forecast, rules, from_event=events[0], horizon=HORIZON,
                          now=snapshot.fetched_at)
        total = realise(start, path_plan(result.paths[0]), events, snapshot, rules, oracle).total
        baseline = total if baseline is None else baseline
        first = {pid: p for (pid, ev), p in forecast.items() if ev == events[0]}
        scored = evaluate_model(first, actuals_first, model_name=label)
        print(f"  {label:40s} {total:6.0f} {total - baseline:+6.0f}  {scored.spearman_played:9.4f} "
              f"{scored.spearman_all:7.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

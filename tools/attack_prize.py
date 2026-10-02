"""Measure three candidate improvements to the attacking rate half, in plan points.

Development measurement on GW2-GW5. It reads settled results, so it lives in
`tools/`. **Prototypes, not variants**: nothing here is registered or a candidate.
FU-75's criterion and a fresh pre-registration govern any real change.

Each prototype changes only the raw per-90 xG and xA, and the exposure in minutes,
fed into `component/1.2`'s own `shrink_rate`, with its own priors and prior
minutes. 1.2's attack term is then rescaled by the ratio of new to old expected
attacking points. Everything else in 1.2 is untouched, so each difference from 1.2
is that idea alone:

    A  last-season prior  this season's xG/xA pooled with 2025-26's for the same
                          player (by FPL `code`), last season weighted w = 1
    B  penalty takers     first-choice taker (`penalties_order == 1`) gets
                          +P_PEN * XG_PEN xG per 90, on top of the observed rate
    C  recency            per-gameweek xG/xA/minutes from this season's settled
                          live payloads (GW1..W-1), weighted 0.5 ** (age / 2)

Scored as FU-75 scores (`points_criterion`'s squad sampler and state, FU-72's
realised scorer), paired against 1.2 on the same squads.

Usage: python tools/attack_prize.py --windows 2 3 --squads 40
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_report import PINNED, load  # noqa: E402
from fu72_plan_oracle import HORIZON, path_plan, perfect_forecast, realise  # noqa: E402
from points_criterion import DEFAULT_SEED, sample_squads, starting_state  # noqa: E402

from fpl_cli.api.models import LiveEvent  # noqa: E402
from fpl_cli.domain import variants  # noqa: E402
from fpl_cli.domain.evaluation import actuals_from_live_event, evaluate_model  # noqa: E402
from fpl_cli.domain.optimizer import optimise  # noqa: E402
from fpl_cli.domain.projections import shrink_rate, shrunk_rates  # noqa: E402
from fpl_cli.domain.transfers import TransferRules  # noqa: E402

LAST_SEASON = PINNED / "2025-26-players_raw.csv"
LAST_SEASON_SHA256 = "412ce0172016f8f98f25177dc6de9f3cd2a8ec7a6135f9aa638d7fdee784d67b"
EVENT_CACHE = Path.home() / ".fpl-cli" / "events"
LAST_SEASON_WEIGHT = 1.0  # [prototype choice, not tuned]
P_PEN = 0.15  # [assumption: ~0.3 penalties a match, so ~0.15 per team-match; not measured here]
XG_PEN = 0.76  # [the conventional xG of a penalty]
HALF_LIFE = 2.0  # [prototype choice, gameweeks; not tuned]
IDEAS = ("A last-season prior", "B penalty takers", "C recency")
# --oracles: the attack/defence split of forecast_prize.py's H and I, over many squads.
ORACLES = ("H defence chance quality", "I attack chance quality")


def _last_season() -> dict[int, tuple[float, float, float]]:
    import hashlib  # noqa: PLC0415

    digest = hashlib.sha256(LAST_SEASON.read_bytes()).hexdigest()
    if digest != LAST_SEASON_SHA256:
        raise SystemExit(f"{LAST_SEASON.name}: sha256 {digest} is not the pinned {LAST_SEASON_SHA256}")
    return {
        int(row["code"]): (float(row["expected_goals"]), float(row["expected_assists"]), float(row["minutes"]))
        for row in csv.DictReader(LAST_SEASON.open())
    }


def _history(window: int) -> list[tuple[int, dict]]:
    """Per-gameweek stats for GW1..window-1, from the settled cache only."""
    rows = []
    for event in range(1, window):
        payload = json.loads((EVENT_CACHE / f"{event}-live.json").read_text())
        if not (payload["finished"] and payload["data_checked"]):
            raise SystemExit(f"GW{event} cache is not settled")
        live = LiveEvent(**payload["live"])
        rows.append((event, {e.id: e.stats for e in live.elements}))
    return rows


def raw_inputs(snapshot, window: int, idea: str) -> dict[int, tuple[float, float, float]]:
    """(raw xG per 90, raw xA per 90, exposure minutes) per player, for one idea."""
    out = {}
    # `Player` does not parse `code` or `penalties_order`; a measurement reads
    # them from the raw payload rather than widening the shipped model.
    raw = {e["id"]: e for e in snapshot.raw["elements"]}
    if idea.startswith("A"):
        last = _last_season()
        for p in snapshot.elements:
            xg, xa, mins = float(p.expected_goals or 0), float(p.expected_assists or 0), float(p.minutes)
            code = raw[p.id].get("code")
            if code in last and last[code][2] > 0:
                lxg, lxa, lmin = last[code]
                xg, xa, mins = xg + LAST_SEASON_WEIGHT * lxg, xa + LAST_SEASON_WEIGHT * lxa, mins + LAST_SEASON_WEIGHT * lmin
            out[p.id] = (xg / mins * 90 if mins else 0.0, xa / mins * 90 if mins else 0.0, mins)
    elif idea.startswith("B"):
        for p in snapshot.elements:
            bonus = P_PEN * XG_PEN if raw[p.id].get("penalties_order") == 1 else 0.0
            out[p.id] = (float(p.expected_goals_per_90) + bonus, float(p.expected_assists_per_90), float(p.minutes))
    elif idea.startswith("C"):
        totals: dict[int, list[float]] = {}
        for event, stats in _history(window):
            weight = 0.5 ** ((window - 1 - event) / HALF_LIFE)
            for pid, s in stats.items():
                t = totals.setdefault(pid, [0.0, 0.0, 0.0])
                t[0] += weight * float(s.get("expected_goals") or 0)
                t[1] += weight * float(s.get("expected_assists") or 0)
                t[2] += weight * float(s.get("minutes") or 0)
        for p in snapshot.elements:
            xg, xa, mins = totals.get(p.id, [0.0, 0.0, 0.0])
            out[p.id] = (xg / mins * 90 if mins else 0.0, xa / mins * 90 if mins else 0.0, mins)
    return out


def prototype(model, base, snapshot, window: int, idea: str):
    """1.2's projections with the attack term rescaled for `idea`."""
    scoring = snapshot.raw["game_config"]["scoring"]
    inputs = raw_inputs(snapshot, window, idea)
    factor: dict[int, float] = {}
    for p in snapshot.elements:
        position = snapshot.positions[p.element_type].singular_name_short
        old = shrunk_rates(p, position, model._rate_priors, model._rate_config)
        settings = model._rate_config.rates
        prior_xg = model._rate_priors.prior_for("xg", position, p.now_cost, settings["xg"].prior_source)
        prior_xa = model._rate_priors.prior_for("xa", position, p.now_cost, settings["xa"].prior_source)
        raw_xg, raw_xa, mins = inputs[p.id]
        new_xg = shrink_rate(raw_xg, mins, prior_xg, settings["xg"].prior_minutes)
        new_xa = shrink_rate(raw_xa, mins, prior_xa, settings["xa"].prior_minutes)
        goal = scoring["goals_scored"][position]
        before = old.xg * goal + old.xa * scoring["assists"]
        after = new_xg * goal + new_xa * scoring["assists"]
        factor[p.id] = after / before if before > 0 else 1.0
    return {
        key: replace(proj, xp_total=proj.xp_total + proj.xp_attack * (factor[key[0]] - 1.0),
                     xp_attack=proj.xp_attack * factor[key[0]])
        for key, proj in base.items()
    }


_CACHE: dict = {}


def _context(window: int, oracles: bool = False):
    if window not in _CACHE:
        events = [window + k for k in range(HORIZON)]
        snapshot, fixtures, _ = load(window, PINNED)
        lives = {e: load(e, PINNED)[2] for e in events}
        points = {e: {p: a.total_points for p, a in actuals_from_live_event(lives[e]).items()} for e in events}
        model = variants.build(variants.get("component/1.2"), snapshot, fixtures)
        base = model.project([p.id for p in snapshot.elements], events)
        forecasts = {"1.2": base}
        if oracles:
            from forecast_prize import model_terms_replaced  # noqa: PLC0415
            forecasts[ORACLES[0]] = model_terms_replaced(base, lives, events, snapshot, defence=True)
            forecasts[ORACLES[1]] = model_terms_replaced(base, lives, events, snapshot, defence=False)
        else:
            for idea in IDEAS:
                forecasts[idea] = prototype(model, base, snapshot, window, idea)
        _CACHE[window] = (snapshot, events, TransferRules.from_snapshot(snapshot),
                          perfect_forecast(snapshot, points, events), forecasts, lives[events[0]])
    return _CACHE[window]


def _score(task):
    window, squad, oracles = task
    snapshot, events, rules, oracle, forecasts, _ = _context(window, oracles)
    state = starting_state(squad, snapshot, window)
    row = {"window": window, "HOLD": realise(state, {}, events, snapshot, rules, oracle).total}
    for name, forecast in forecasts.items():
        result = optimise(state, snapshot, forecast, rules, from_event=events[0], horizon=HORIZON,
                          now=snapshot.fetched_at)
        row[name] = realise(state, path_plan(result.paths[0]), events, snapshot, rules, oracle).total
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--windows", type=int, nargs="+", required=True)
    parser.add_argument("--squads", type=int, default=40)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", default=None)
    parser.add_argument("--oracles", action="store_true", help="score H and I (oracles) instead of A-C")
    args = parser.parse_args(argv)

    for window in args.windows:
        snapshot, events, _, _, forecasts, live = _context(window, args.oracles)
        actual = actuals_from_live_event(live)
        print(f"GW{window} Spearman (played / all) at the window's first gameweek:")
        for name, forecast in forecasts.items():
            first = {pid: p for (pid, ev), p in forecast.items() if ev == events[0]}
            r = evaluate_model(first, actual, model_name=name)
            print(f"  {name:22s} {r.spearman_played:.4f} / {r.spearman_all:.4f}")

    tasks = [(w, s, args.oracles) for w in args.windows for s in sample_squads(load(w, PINNED)[0], args.squads, DEFAULT_SEED + w)]
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(_score, tasks, chunksize=1))
    print(f"\n{len(rows)} squad-windows in {time.monotonic() - started:.0f}s")
    for window in args.windows:
        sub = [r for r in rows if r["window"] == window]
        print(f"\nwindow GW{window}-GW{window + HORIZON - 1}, {len(sub)} squads; 1.2 − HOLD "
              f"{statistics.fmean(r['1.2'] - r['HOLD'] for r in sub):+.2f}")
        for idea in (ORACLES if args.oracles else IDEAS):
            d = [r[idea] - r["1.2"] for r in sub]
            sd = statistics.stdev(d)
            print(f"  {idea:22s} − 1.2: mean {statistics.fmean(d):+6.2f}  se {sd / math.sqrt(len(d)):5.2f}  "
                  f"(+{sum(x > 0 for x in d)} ={sum(x == 0 for x in d)} −{sum(x < 0 for x in d)})")
    if args.out:
        Path(args.out).write_text(json.dumps(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())

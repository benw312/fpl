"""Route (a): check a projection against the six-season outcome distribution.

vaastav-survey.md §6(a) — take the archive's distribution as a published target
and sanity-check our own output against it, with **no runtime dependency**. The
constants below are measured once and baked in; nothing here reads the archive.

**Why this is not "one more evaluation table".** Every metric in `plan evaluate`
scores a projection against *the gameweek that just happened*. Two settled
gameweeks is a thin reference, and FU-63's -13.6% aggregate bias was measured
against exactly that. This scores against **six seasons**, so a season that is
itself unusual cannot be mistaken for a model defect. Measured on the pinned
captures: 1.2's bias against this season's realised totals is -13.5% and -13.6%,
but against the six-season norm for the same round number it is **-10% and -6%** —
a third of what we attributed to the model is this season scoring above average.

**What may and may not be compared.**

*Valid — additive.* Expectations add, so `sum(xp_total)` is an estimate of the
total points the population will score, and the historical mean total for the same
round number is the right reference. Likewise each position's *share* of projected
points, which is population-size invariant.

*Not valid as a defect measure — dispersion.* The count of players projected above
5 is **not** comparable with the count who score above 5. `Var(E[Y|X]) <= Var(Y)`,
so a perfectly calibrated model necessarily puts fewer predictions above a high
threshold than there are outcomes above it. §3 reports it anyway because the *size*
of the gap is FU-62's compression made legible — but it is a dispersion diagnostic,
never evidence of bias, and the output says so.

Norms are **measured, not chosen.** They come from 226 gameweeks across six
seasons (2020-21 to 2025-26) and are not model parameters, so FU-50 §3's
prohibition on tuning does not reach them. Re-derive with the EDA in
vaastav-survey.md if the archive is refreshed.

Usage
-----
    python tools/distribution_check.py --event 3
    python tools/distribution_check.py --event 3 --model component/1.1-price
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.domain import variants
from fpl_cli.domain.evaluation import actuals_from_live_event

PINNED = Path.home() / "fpl-pinned"

# Pinned trio per settled gameweek, as tools/calibration_report.py.
RUNS: dict[int, tuple[str, str, str | None, datetime]] = {
    2: ("gw2-pre-deadline.json", "gw2-fixtures.json", "gw2-live.json",
        datetime(2026, 8, 28, 0, 32, 59, tzinfo=UTC)),
    3: ("gw3-pre-deadline.json", "gw3-fixtures.json", "gw3-live.json",
        datetime(2026, 9, 4, 0, 1, 59, tzinfo=UTC)),
}

# --- The measured norms (vaastav-survey.md §3, §4) ---------------------------
#
# Keyed by ROUND NUMBER, not averaged over the season: the FPL element set grows
# from ~586 in round 1 to ~780 by the end, so a season-average per-population
# figure would be compared against the wrong denominator early on. Each entry is
# (mean points per PLAYED player, mean points per POPULATION player, seasons
# contributing).

ROUND_NORMS: dict[int, tuple[float, float, int]] = {
    1: (2.898, 1.406, 6),
    2: (2.868, 1.385, 6),
    3: (2.793, 1.289, 6),
    4: (2.931, 1.342, 6),
    5: (2.782, 1.244, 6),
    6: (2.751, 1.222, 6),
    7: (2.825, 1.236, 5),
    8: (2.899, 1.267, 6),
    9: (2.839, 1.258, 6),
    10: (2.817, 1.232, 6),
    11: (2.878, 1.244, 6),
    12: (2.934, 1.259, 6),
    13: (2.828, 1.213, 6),
    14: (2.910, 1.239, 6),
    15: (2.858, 1.213, 6),
    16: (2.916, 1.225, 6),
    17: (2.987, 1.250, 6),
    18: (2.877, 1.175, 6),
    19: (2.954, 1.225, 6),
    20: (2.859, 1.162, 6),
    21: (2.988, 1.180, 6),
    22: (2.853, 1.130, 6),
    23: (2.909, 1.133, 6),
    24: (2.962, 1.158, 6),
    25: (2.948, 1.137, 6),
    26: (3.029, 1.164, 6),
    27: (3.031, 1.164, 6),
    28: (2.873, 1.087, 6),
    29: (2.876, 1.098, 6),
    30: (2.856, 1.089, 6),
    31: (2.950, 1.122, 6),
    32: (2.936, 1.117, 6),
    33: (2.938, 1.115, 6),
    34: (2.987, 1.125, 6),
    35: (2.878, 1.081, 6),
    36: (3.078, 1.139, 6),
    37: (2.791, 1.044, 6),
    38: (2.905, 1.095, 6),
}

POSITION_SHARE_OF_POINTS: dict[str, float] = {
    "GKP": 0.083,
    "DEF": 0.318,
    "MID": 0.455,
    "FWD": 0.135,
}

# Fraction of players who APPEARED scoring at least N. Dispersion reference
# for §3 only — see the docstring on why this is not a bias measure.
PLAYED_ABOVE: dict[int, float] = {
    2: 0.5781,
    3: 0.3189,
    4: 0.2456,
    5: 0.2199,
    6: 0.1838,
    8: 0.0869,
    10: 0.0416,
    13: 0.0160,
}


# --- The rule change, and why the pooled figures above are the wrong reference
# for two of the four positions ---------------------------------------------
#
# Defensive-contribution points arrived in 2025-26. Measured on the archive, the
# defenders' share of all points moved from a five-season pre-rule mean of 31.5%
# to 35.0% in 2025-26 — a 3.5-point step, nearly as large as the 4.3-point
# gameweek-to-gameweek standard deviation. Pooling across that change therefore
# understates DEF and overstates MID for any season played under the new rules,
# and `POSITION_SHARE_OF_POINTS` above must NOT be used as the reference for one.
#
# It moved the level too: total points per played player ran 2.864 in 2024-25
# against 2.994 in 2025-26.
#
# So the post-rule figures below are the correct reference and the pooled ones
# above are kept only for contrast. The cost is real and is stated rather than
# hidden: **this is one season**, so a round-level entry here is a single
# observation where the pooled table averages six. Read the level from it with
# that in mind; the season-long position shares are the part that is tight.
POSTRULE_ROUND_NORMS: dict[int, tuple[float, float]] = {
    1: (3.210, 1.392),
    2: (2.895, 1.283),
    3: (3.076, 1.307),
    4: (3.190, 1.313),
    5: (2.731, 1.123),
    6: (2.688, 1.125),
    7: (2.891, 1.208),
    8: (3.062, 1.260),
    9: (2.908, 1.226),
    10: (2.927, 1.187),
    11: (3.168, 1.277),
    12: (2.987, 1.199),
    13: (2.855, 1.150),
    14: (3.141, 1.264),
    15: (2.981, 1.217),
    16: (3.070, 1.216),
    17: (3.023, 1.186),
    18: (3.058, 1.156),
    19: (3.293, 1.241),
    20: (3.027, 1.142),
    21: (3.034, 1.126),
    22: (3.131, 1.140),
    23: (2.941, 1.110),
    24: (2.954, 1.100),
    25: (2.858, 1.060),
    26: (2.866, 1.049),
    27: (3.071, 1.115),
    28: (2.804, 1.031),
    29: (2.951, 1.101),
    30: (3.230, 1.163),
    31: (3.041, 1.113),
    32: (2.983, 1.094),
    33: (3.112, 1.133),
    34: (3.049, 1.074),
    35: (2.856, 1.047),
    36: (3.040, 1.071),
    37: (2.853, 1.039),
    38: (2.817, 1.045),
}

POSTRULE_POSITION_SHARE: dict[str, float] = {
    "GKP": 0.075,
    "DEF": 0.350,
    "MID": 0.453,
    "FWD": 0.123,
}

POSTRULE_PLAYED_ABOVE: dict[int, float] = {
    2: 0.5863,
    3: 0.3678,
    4: 0.2804,
    5: 0.2200,
    6: 0.1799,
    8: 0.0933,
    10: 0.0446,
    13: 0.0156,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(value: float) -> str:
    return f"{value:+.1%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", type=int, required=True)
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--pinned", default=str(PINNED))
    args = parser.parse_args(argv)

    pinned = Path(args.pinned)
    try:
        bootstrap, fixtures_file, live_file, captured = RUNS[args.event]
    except KeyError:
        raise SystemExit(f"No pinned trio for GW{args.event}. Known: {sorted(RUNS)}.") from None
    if args.event not in ROUND_NORMS:
        raise SystemExit(f"No historical norm for round {args.event}.")

    snapshot = BootstrapSnapshot.from_payload(
        json.loads((pinned / bootstrap).read_text(encoding="utf-8")), fetched_at=captured
    )
    fixtures = [Fixture(**row) for row in json.loads((pinned / fixtures_file).read_text(encoding="utf-8"))]
    actuals = None
    if live_file and (pinned / live_file).is_file():
        payload = json.loads((pinned / live_file).read_text(encoding="utf-8"))
        if payload.get("finished") and payload.get("data_checked"):
            actuals = actuals_from_live_event(LiveEvent(**payload["live"]))

    per_played, per_pop, seasons = ROUND_NORMS[args.event]
    post_played, post_pop = POSTRULE_ROUND_NORMS.get(args.event, (per_played, per_pop))
    ids = [player.id for player in snapshot.elements]
    positions = {p.id: snapshot.positions[p.element_type].singular_name_short for p in snapshot.elements}
    models = tuple(args.model) if args.model else ("component/1.1-price", "component/1.2")

    print(f"GW{args.event}  capture {sha256(pinned / bootstrap)[:12]}…  "
          f"fixtures {sha256(pinned / fixtures_file)[:12]}…")
    print(f"round {args.event} norms — pooled 2020-26: {per_played:.3f} per played, {per_pop:.3f} per pop "
          f"({seasons} seasons);  2025-26 post-rule: {post_played:.3f} / {post_pop:.3f} (1 season)")
    print(f"population projected: {len(ids)}")

    realised_total = realised_played = None
    if actuals is not None:
        scored = [pid for pid in ids if pid in actuals]
        realised_total = sum(actuals[pid].total_points for pid in scored)
        realised_played = sum(1 for pid in scored if actuals[pid].played)
        print(f"this season realised: {realised_total} pts over {len(scored)} projected, "
              f"{realised_played} played → {realised_total / realised_played:.3f} per played, "
              f"{realised_total / len(scored):.3f} per population "
              f"({pct(realised_total / len(scored) / per_pop - 1)} vs pooled, "
              f"{pct(realised_total / len(scored) / post_pop - 1)} vs post-rule)")

    print("\n=== §1 TOTAL POINTS (valid: expectations are additive) ===")
    print(f"{'model':<28} {'sum xP':>9} {'per pop':>9} {'vs pooled':>10} {'vs postrule':>12} {'vs realised':>12}")
    projections = {}
    for name in models:
        model = variants.build(variants.get(name), snapshot, fixtures)
        rows = {pid: p for (pid, _), p in model.project(ids, [args.event]).items()}
        projections[name] = rows
        total = sum(p.xp_total for p in rows.values())
        against_realised = pct(total / realised_total - 1) if realised_total else "    n/a"
        print(f"{model.name:<28} {total:>9.0f} {total / len(ids):>9.3f} "
              f"{pct(total / len(ids) / per_pop - 1):>10} "
              f"{pct(total / len(ids) / post_pop - 1):>12} {against_realised:>12}")

    print("\n=== §2 SHARE OF PROJECTED POINTS BY POSITION (valid: population-invariant) ===")
    header = f"{'model':<28} " + " ".join(f"{p:>9}" for p in ("GKP", "DEF", "MID", "FWD"))
    print(header)
    print(f"{'2025-26 (post-rule) share':<28} " + " ".join(
        f"{POSTRULE_POSITION_SHARE[p]:>9.1%}" for p in ("GKP", "DEF", "MID", "FWD"))
        + "   <- the reference")
    print(f"{'2020-26 pooled (pre-rule mix)':<28} " + " ".join(
        f"{POSITION_SHARE_OF_POINTS[p]:>9.1%}" for p in ("GKP", "DEF", "MID", "FWD"))
        + "   (contrast only — spans the defcon change)")
    for name, rows in projections.items():
        by_position = collections.Counter()
        for pid, projection in rows.items():
            by_position[positions[pid]] += projection.xp_total
        total = sum(by_position.values()) or 1.0
        print(f"{name:<28} " + " ".join(f"{by_position[p] / total:>9.1%}" for p in ("GKP", "DEF", "MID", "FWD")))

    print("\n=== §3 DISPERSION — NOT a bias measure (see module docstring) ===")
    print("A calibrated model MUST put fewer predictions above a high threshold than")
    print("there are outcomes above it. The gap sizes FU-62's compression; it is not evidence of bias.")
    print(f"\n{'threshold':>10} {'historical % of played':>23} " +
          " ".join(f"{n.split('/')[-1][:14]:>15}" for n in models))
    for threshold, share in PLAYED_ABOVE.items():
        cells = []
        for name in models:
            rows = projections[name]
            above = sum(1 for p in rows.values() if p.xp_total >= threshold)
            cells.append(f"{above:>6} ({above / (realised_played or len(ids)):>5.1%})")
        print(f"{'>= ' + str(threshold):>10} {share:>22.1%} " + " ".join(f"{c:>15}" for c in cells))
    print("\n(model columns count PROJECTED players above the threshold, as a share of those")
    print(" who actually played, so the two columns are on the same denominator.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

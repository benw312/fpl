"""The minutes-term diagnostics FU-60 §5 requires every gameweek. **Not an oracle.**

Reads no outcome into any projection. It scores finished `p_start` values
against finished `starts` stats, which is the same relationship `plan evaluate`
has to `xp_total` — the model is built from the pre-deadline capture and never
sees the result.

**Why this exists.** FU-60 §5 fixes, in advance, how a `spearman_played` win
that comes with a log loss loss is to be read: `spearman_played` decides, and
the log loss delta is *recorded each gameweek as the tracked size of FU-57's
residual*. It is a measurement, not a gate. That measurement was made by hand at
GW2 and again at GW3, and a figure recomputed by hand each time is a figure
nobody can reproduce — FU-40's argument, applied to a measurement rather than to
a number. Two of the three are already quoted in gw3-evaluation.md §3 and in
FU-60 §5 itself.

It also produces FU-60 §4.2's count, which asks for the mechanism behind FU-57
to be measured rather than inferred: players who have started every finished
gameweek and are still rated at or below 0.5.

**`p_start` only means a start rate under `component`.** `naive/1.0` puts the
raw availability scalar there and `official-ep/1.0` hardcodes 0.0 — the same
reason `cli.py`'s `_START_NOTES` keys off the model name (FU-45). Only
`component` variants are scored here, and asking for another is refused rather
than silently reported as a probability.

**Verified against GW3 before being used on GW4**, which is the whole reason it
is worth having rather than a fresh script. Run at `--event 3` it reproduces
every figure gw3-evaluation.md §3 and §4 published on 2026-09-11, each of which
was computed by hand in a different session: Brier 0.1314 / 0.1003 / 0.1291,
log loss 0.4042 / 0.3194 / 0.3977, Σ`p_start` 277.5 / 192.0 / 274.4 against 220
actual starters, the 59-of-183 suppression count with 48 of them starting, and
the +0.0848 tracked residual quoted in FU-60 §6.3. A diagnostic that cannot
reproduce the number already in the record is not measuring the same thing.

Lives in `tools/` for `calibration_report.py`'s reason: `pyproject.toml`
packages `src/fpl_cli` only, so nothing shipped can import a diagnostic. Like
its siblings it carries no tests — `tools/` is diagnostics, and the check that
matters for one is the reproduction above.

Usage
-----
    python tools/minutes_diagnostics.py --event 4
    python tools/minutes_diagnostics.py --event 3 --model component/1.2
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from fpl_cli.domain.evaluation import actuals_from_live_event  # noqa: F401  (parity with sibling tools)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_report import RUNS, load, project, sha256  # noqa: E402

DEFAULT_MODELS = ("component/1.1-price", "component/1.2", "component/1.2-availability")

# Clamp before the log. A model may legitimately emit exactly 0.0 or 1.0 —
# `_as_probability` clamps to [0, 1] (FU-56) — and log loss is infinite there.
# 1e-15 is far below any difference between the variants being compared and is
# applied identically to all of them, so it cannot move a comparison; it only
# stops one confident miss returning inf and destroying the whole figure.
EPSILON = 1e-15


def started(live, player_id: int) -> bool | None:
    """Did the player start? `None` if the payload does not say.

    The `starts` stat is published per element and is the API's own statement,
    rather than an inference from minutes — a 60-minute substitute and a
    60-minute starter are indistinguishable by minutes alone.
    """
    for element in live.elements:
        if element.id == player_id:
            value = element.stats.get("starts")
            return None if value is None else bool(value)
    return None


def brier_and_log_loss(pairs: list[tuple[float, bool]]) -> tuple[float, float]:
    brier = sum((p - float(y)) ** 2 for p, y in pairs) / len(pairs)
    log_loss = -sum(
        math.log(max(p, EPSILON)) if y else math.log(max(1.0 - p, EPSILON)) for p, y in pairs
    ) / len(pairs)
    return brier, log_loss


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", type=int, required=True, help=f"settled gameweek; known {sorted(RUNS)}")
    parser.add_argument("--model", action="append", help="repeatable; component variants only")
    parser.add_argument("--pinned", default=str(Path.home() / "fpl-pinned"))
    args = parser.parse_args()

    models = tuple(args.model) if args.model else DEFAULT_MODELS
    bad = [name for name in models if not name.startswith("component/")]
    if bad:
        raise SystemExit(
            f"{bad} do not model a start rate. naive/1.0 puts the availability scalar in "
            "`p_start` and official-ep/1.0 hardcodes 0.0, so a Brier score over either "
            "would be a number about nothing (FU-45)."
        )

    snapshot, fixtures, live = load(args.event, Path(args.pinned))
    ids = [player.id for player in snapshot.elements]
    truth = {pid: started(live, pid) for pid in ids}
    scored = [pid for pid in ids if truth[pid] is not None]
    actual_starters = sum(1 for pid in scored if truth[pid])
    print(f"population: {len(ids)} projected, {len(scored)} with a `starts` stat, "
          f"{actual_starters} started")

    # FU-60 §4.2: players who started every finished gameweek so far.
    appearances = max((player.starts for player in snapshot.elements), default=0)
    ever_present = [p.id for p in snapshot.elements if p.starts == appearances and appearances > 0]
    print(f"appearances a = {appearances}; {len(ever_present)} players have starts = {appearances}, "
          f"{sum(1 for pid in ever_present if truth.get(pid))} of them started GW{args.event}\n")

    print(f"{'variant':<34} {'Brier':>8} {'log loss':>10} {'sum p_start':>12} {'rated<=0.5':>11} {'of which started':>17}")
    results = {}
    for name in models:
        projections = project(name, snapshot, fixtures, args.event)
        pairs = [(projections[pid].p_start, truth[pid]) for pid in scored if pid in projections]
        brier, log_loss = brier_and_log_loss(pairs)
        total_p = sum(projections[pid].p_start for pid in scored if pid in projections)
        suppressed = [pid for pid in ever_present if pid in projections and projections[pid].p_start <= 0.5]
        results[name] = (brier, log_loss)
        print(f"{name:<34} {brier:>8.4f} {log_loss:>10.4f} {total_p:>12.1f} {len(suppressed):>11} "
              f"{sum(1 for pid in suppressed if truth.get(pid)):>17}")

    if "component/1.2" in results and "component/1.1-price" in results:
        delta = results["component/1.1-price"][1] - results["component/1.2"][1]
        print(f"\nFU-60 §5 tracked residual — log loss delta (1.1-price minus 1.2): {delta:+.4f}")
        print("  positive favours 1.2. Recorded as a measurement; §5 forbids it becoming a gate.")


if __name__ == "__main__":
    main()

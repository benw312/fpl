"""Calibration diagnostics for a settled gameweek. **Not an oracle.**

Unlike `fu53_minutes_oracle.py` this reads no outcome into any projection — it
only scores finished projections against finished results, which is what
`plan evaluate` already does. It is here because it produces two tables that
`plan evaluate` does not, and that are named as work to repeat:

  §1  component error within one return-category bucket
      (haulers-decomposition.md §1)
  §2  calibration by PREDICTED bin, which unlike the category table does not
      select on the outcome (haulers-decomposition.md §3)

**rank-calibration.md §6 step 2 requires both to be re-run against the post-FU-57
model**, and compared against today's figures. A re-implementation from the prose
would produce numbers that are not comparable with them — FU-40's argument applied
to a measurement rather than a figure, the same reason `fu53_minutes_oracle.py` is
committed.

Lives in `tools/` for the reason that file gives: `pyproject.toml` packages
`src/fpl_cli` only, so nothing shipped can import a diagnostic, and it may reach
for private names without that coupling leaking into the package.

Usage
-----
    python tools/calibration_report.py --event 3
    python tools/calibration_report.py --event 2 --category Blanks
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.domain import variants
from fpl_cli.domain.evaluation import COMPONENTS, _category, actuals_from_live_event

PINNED = Path.home() / "fpl-pinned"

# The pinned trio per settled gameweek, with the capture time each bootstrap was
# fetched at. `fetched_at` reaches no projected number, but the pinned copies'
# mtimes were rewritten by copying, so it is passed explicitly.
RUNS: dict[int, tuple[str, str, str, datetime]] = {
    2: ("gw2-pre-deadline.json", "gw2-fixtures.json", "gw2-live.json",
        datetime(2026, 8, 28, 0, 32, 59, tzinfo=UTC)),
    3: ("gw3-pre-deadline.json", "gw3-fixtures.json", "gw3-live.json",
        datetime(2026, 9, 4, 0, 1, 59, tzinfo=UTC)),
    4: ("gw4-pre-deadline.json", "gw4-fixtures.json", "gw4-live.json",
        datetime(2026, 9, 12, 0, 3, 59, tzinfo=UTC)),
}

DEFAULT_MODELS = ("component/1.1-price", "component/1.2", "component/1.2-availability", "naive/1.0")

# Equal-width in predicted xP. Deliberately not quantile bins: haulers-
# decomposition.md's gap records that quantile binning would read differently,
# and changing the binning between runs would break the comparison §6 step 2
# exists to make.
BIN_EDGES = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 99.0)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(event: int, pinned: Path):
    try:
        bootstrap, fixtures, live, captured = RUNS[event]
    except KeyError:
        raise SystemExit(
            f"No pinned trio for GW{event}. Known: {sorted(RUNS)}. Pin the capture, "
            "fixtures and settled live payload into ~/fpl-pinned first."
        ) from None
    payload = json.loads((pinned / live).read_text(encoding="utf-8"))
    if not (payload.get("finished") and payload.get("data_checked")):
        raise SystemExit(
            f"GW{event} is not settled (finished={payload.get('finished')}, "
            f"data_checked={payload.get('data_checked')}). Bonus and stat corrections "
            "land after the whistle; scoring against provisional results measures noise."
        )
    snapshot = BootstrapSnapshot.from_payload(
        json.loads((pinned / bootstrap).read_text(encoding="utf-8")), fetched_at=captured
    )
    schedule = [Fixture(**row) for row in json.loads((pinned / fixtures).read_text(encoding="utf-8"))]
    print(f"GW{event}  bootstrap {sha256(pinned / bootstrap)[:12]}…  "
          f"fixtures {sha256(pinned / fixtures)[:12]}…  live {sha256(pinned / live)[:12]}…  "
          f"(settled, captured {captured.isoformat()})")
    return snapshot, schedule, LiveEvent(**payload["live"])


def project(name: str, snapshot, fixtures, event: int) -> dict[int, object]:
    model = variants.build(variants.get(name), snapshot, fixtures)
    ids = [player.id for player in snapshot.elements]
    return {pid: p for (pid, ev), p in model.project(ids, [event]).items()}


def component_table(models, projections, actuals, category: str) -> None:
    """§1: where one category bucket's error sits, by component.

    **Read with FU-61 in hand.** The bucket selects on the realised total, so for
    `Haulers` the signed error is dominated by that selection and is not a model
    property. The split *between* components is still informative; the magnitude
    is not.
    """
    members = [pid for pid in actuals if _category(actuals[pid].total_points) == category]
    print(f"\n=== §1 component error within '{category}' (n={len(members)}) ===")
    if not members:
        print("   (empty bucket)")
        return
    for name in models:
        rows = projections[name]
        common = [pid for pid in members if pid in rows]
        total = statistics.mean(rows[pid].xp_total - actuals[pid].total_points for pid in common)
        print(f"\n-- {name}   mean total error {total:+.3f}")
        print(f"   {'component':<14} {'pred':>8} {'actual':>8} {'error':>8} {'share':>8}")
        summed = 0.0
        measured = []
        for component in COMPONENTS:
            predicted = statistics.mean(getattr(rows[pid], component) for pid in common)
            realised = statistics.mean(actuals[pid].component_points[component] for pid in common)
            measured.append((component, predicted, realised, predicted - realised))
            summed += predicted - realised
        for component, predicted, realised, error in sorted(measured, key=lambda r: r[3]):
            share = f"{error / total * 100:>7.0f}%" if total else "      -"
            print(f"   {component.removeprefix('xp_'):<14} {predicted:>8.3f} {realised:>8.3f} "
                  f"{error:>+8.3f} {share}")
        residual = total - summed
        print(f"   {'[unmapped]':<14} {'':>8} {'':>8} {residual:>+8.3f}"
              f"   own goals, pens saved/missed — no component")


def calibration_table(models, projections, actuals) -> None:
    """§2: calibration by predicted bin — the diagnostic that does not select on
    the outcome, and the one rank-calibration.md would be fitted against."""
    print("\n=== §2 calibration by PREDICTED xP bin (whole projected population) ===")
    for name in models:
        rows = projections[name]
        common = sorted(set(rows) & set(actuals))
        print(f"\n-- {name}")
        print(f"   {'predicted xP':<14} {'n':>5} {'mean pred':>10} {'mean actual':>12} "
              f"{'bias':>8} {'P(haul)':>9}")
        for low, high in zip(BIN_EDGES, BIN_EDGES[1:]):
            group = [pid for pid in common if low <= rows[pid].xp_total < high]
            if len(group) < 5:
                continue
            predicted = statistics.mean(rows[pid].xp_total for pid in group)
            realised = statistics.mean(actuals[pid].total_points for pid in group)
            hauled = sum(1 for pid in group if actuals[pid].total_points >= 5) / len(group)
            label = f"{low:.0f}-{high:.0f}" if high < 90 else f"{low:.0f}+"
            print(f"   {label:<14} {len(group):>5} {predicted:>10.2f} {realised:>12.2f} "
                  f"{predicted - realised:>+8.2f} {hauled:>8.0%}")
        predicted_total = sum(rows[pid].xp_total for pid in common)
        realised_total = sum(actuals[pid].total_points for pid in common)
        bias = predicted_total / realised_total - 1 if realised_total else float("nan")
        spread = statistics.pstdev([rows[pid].xp_total for pid in common])
        print(f"   {'ALL':<14} {len(common):>5} {predicted_total / len(common):>10.2f} "
              f"{realised_total / len(common):>12.2f} "
              f"{(predicted_total - realised_total) / len(common):>+8.2f}")
        print(f"   total predicted {predicted_total:.0f} vs actual {realised_total:.0f} "
              f"({bias:+.1%})   predicted SD {spread:.2f}, max {max(rows[pid].xp_total for pid in common):.2f}")
    actual_values = [actuals[pid].total_points for pid in sorted(actuals)]
    print(f"\n   realised SD {statistics.pstdev(actual_values):.2f}, "
          f"max {max(actual_values)}, n>=10: {sum(1 for a in actual_values if a >= 10)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", type=int, required=True, help=f"settled gameweek; known {sorted(RUNS)}")
    parser.add_argument("--category", default="Haulers", help="return-category bucket for §1")
    parser.add_argument("--model", action="append", default=None, help="repeatable; defaults to four")
    parser.add_argument("--pinned", default=str(PINNED))
    args = parser.parse_args(argv)

    snapshot, fixtures, live = load(args.event, Path(args.pinned))
    actuals = actuals_from_live_event(live)
    models = tuple(args.model) if args.model else DEFAULT_MODELS
    digests = {name: variants.get(name).digest for name in models}
    print("models: " + ", ".join(f"{n} {d}" for n, d in digests.items()))
    projections = {name: project(name, snapshot, fixtures, args.event) for name in models}

    # Bucketed over the intersection the tables actually score, not over every
    # live element: the element set grows mid-season, so `actuals` carries
    # players this capture never projected and counting them here would print a
    # denominator no table below uses.
    scored = sorted(set(next(iter(projections.values()))) & set(actuals))
    counts = collections.Counter(_category(actuals[pid].total_points) for pid in scored)
    print(f"population: {len(snapshot.elements)} projected, {len(actuals)} live, "
          f"{len(scored)} scored; buckets {dict(counts)}")

    component_table(models, projections, actuals, args.category)
    calibration_table(models, projections, actuals)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Does a uniform xP scale change what the optimiser recommends? (FU-63, FU-64)

The objective is

    score(alpha) = alpha * XP - hit_points + terminal_value

which is **linear in alpha**, so one `optimise` run at alpha = 1 determines every
path's score at every alpha exactly. This probe reads the flip points off rather
than re-running the search per alpha — the first attempt swept six alphas and took
four minutes to learn nothing, which fu-63-optimiser-sensitivity.md §1 records.

Two traps it exists to stop anyone re-hitting:

1. **A full free-transfer bank makes the probe vacuous.** With enough banked
   transfers `hit_points` is 0 on every path and `alpha` has no channel to act
   through. `--free-transfers 0 --at-event N` places the state so exactly one free
   transfer is available at `--from-event`.
2. **Free transfers accrue per intervening event.** Setting `free_transfers` on a
   ledger sitting at event 1 still yields a full bank by GW4, because
   `apply_transfers` adds one per event stepped. The *state's event* must move too.

FU-64's first step — establish whether `terminal_value` is ever non-zero, by
sweeping squads, horizons and bank depths — is what this is the seed for. It
reports the terminal free-transfer count precisely so that sweep is a loop around
this.

Usage
-----
    python tools/optimiser_scale_probe.py --from-event 4 --horizon 3 \
        --at-event 3 --free-transfers 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.domain import variants
from fpl_cli.domain.optimizer import DEFAULT_DECAY, DEFAULT_FT_VALUE, optimise
from fpl_cli.domain.transfers import Ledger, TransferRules, replay

DEFAULT_CAPTURE = Path.home() / ".fpl-cli" / "archive"
DEFAULT_SQUAD = Path(__file__).resolve().parents[1] / "squad.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def score_at(path, alpha: float) -> float:
    """`path`'s score under an xP scale of `alpha`, from its alpha = 1 figures."""
    projected = path.score + path.hit_points - path.terminal_value
    return alpha * projected - path.hit_points + path.terminal_value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", default=None, help="capture directory; default: newest in the archive")
    parser.add_argument("--squad", default=str(DEFAULT_SQUAD))
    parser.add_argument("--model", default="component/1.2")
    parser.add_argument("--from-event", type=int, required=True)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--at-event", type=int, default=None,
                        help="place the ledger state at this event before optimising (see trap 2)")
    parser.add_argument("--free-transfers", type=int, default=None,
                        help="override the banked free transfers (see trap 1)")
    parser.add_argument("--alpha-min", type=float, default=0.30)
    parser.add_argument("--alpha-max", type=float, default=3.00)
    args = parser.parse_args(argv)

    capture = Path(args.capture) if args.capture else max(
        (d for d in DEFAULT_CAPTURE.iterdir() if (d / "bootstrap-static.json").is_file()),
        key=lambda d: d.name,
    )
    squad = Path(args.squad)
    snapshot = BootstrapSnapshot.from_payload(
        json.loads((capture / "bootstrap-static.json").read_text(encoding="utf-8")),
        fetched_at=datetime.now(UTC),
    )
    fixtures = [Fixture(**row) for row in json.loads((capture / "fixtures.json").read_text(encoding="utf-8"))]
    print(f"capture {capture.name}  bootstrap {sha256(capture / 'bootstrap-static.json')[:12]}…  "
          f"fixtures {sha256(capture / 'fixtures.json')[:12]}…  squad {sha256(squad)[:12]}…")

    rules = TransferRules.from_snapshot(snapshot)
    state = replay(Ledger.from_file(squad, snapshot), snapshot)
    if args.at_event is not None:
        state = replace(state, event=args.at_event)
    if args.free_transfers is not None:
        state = replace(state, free_transfers=args.free_transfers)
    available = min(
        state.free_transfers + rules.free_transfers_per_event * (args.from_event - state.event),
        rules.free_transfer_cap,
    )
    print(f"state at event {state.event}, {state.free_transfers} banked → ~{available} free at "
          f"GW{args.from_event}; {rules.points_per_extra_transfer} pts per extra transfer")
    if available >= 3:
        print("  ! a deep bank makes this probe vacuous — hits never bind (trap 1). "
              "Use --at-event/--free-transfers.")

    variant = variants.get(args.model)
    model = variants.build(variant, snapshot, fixtures)
    ids = [player.id for player in snapshot.elements]
    events = [args.from_event + offset for offset in range(args.horizon)]
    result = optimise(state, snapshot, model.project(ids, events), rules,
                      from_event=args.from_event, horizon=args.horizon, decay=DEFAULT_DECAY,
                      ft_value=DEFAULT_FT_VALUE, max_hit=10**9, now=datetime.now(UTC))
    names = {player.id: player.web_name for player in snapshot.elements}

    def describe(path) -> str:
        if not path.first_move:
            return "HOLD (empty FIRST MOVE — the path may still transfer later)"
        return " + ".join(f"{names.get(t.out_id, t.out_id)}→{names.get(t.in_id, t.in_id)}"
                          for t in path.first_move)

    print(f"\n{variant.version} digest {variant.digest}; {len(result.paths)} paths, "
          f"GW{events[0]}-GW{events[-1]}\n")
    best_by_k: dict[int, object] = {}
    for path in result.paths:
        k = len(path.first_move)
        if k not in best_by_k or path.score > best_by_k[k].score:
            best_by_k[k] = path
    print(f"{'k':>2} {'hit':>4} {'termFT':>7} {'termV':>8} {'XP':>9} {'score@1':>9}  first move")
    for k in sorted(best_by_k):
        p = best_by_k[k]
        print(f"{k:>2} {p.hit_points:>4} {p.node.state.free_transfers:>7} {p.terminal_value:>8.3f} "
              f"{p.score + p.hit_points - p.terminal_value:>9.3f} {p.score:>9.3f}  {describe(p)[:46]}")

    # FU-64: terminal value is inert if no path ever banks a transfer.
    terminal = {p.node.state.free_transfers for p in result.paths}
    print(f"\nterminal free-transfer counts across all paths: {sorted(terminal)}")
    if max(p.terminal_value for p in result.paths) == 0.0:
        print(f"  ! every path spends its bank, so terminal_value is identically 0 and "
              f"ft_value ({DEFAULT_FT_VALUE}) cannot affect the ranking — FU-64.")

    print("\nrecommendation as a function of the xP scale (score is linear in alpha):")
    previous = None
    steps = int(round((args.alpha_max - args.alpha_min) * 100)) + 1
    for step in range(steps):
        alpha = round(args.alpha_min + step * 0.01, 2)
        best = max(result.paths, key=lambda p: score_at(p, alpha))
        current = describe(best)
        if current != previous:
            print(f"   alpha ≥ {alpha:>5.2f} (implied xP bias {1 / alpha - 1:>+7.1%}): "
                  f"k={len(best.first_move)} hit={best.hit_points}  {current[:46]}")
            previous = current
    return 0


if __name__ == "__main__":
    sys.exit(main())

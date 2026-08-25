# Plan: `fpl plan simulate` CLI command (FU-7)

## Context

`domain/transfers.py` (`da4f6d6`) implements deterministic transfer
simulation — ledger replay, transfer application, rollover, hits, selling
prices — but has no CLI entry point. FU-7 in `docs/plans/follow-ups.md` and
the README Agent Plan both name `fpl plan simulate` as the command that
exposes it; `cli.py` was deliberately left untouched by the transfers task to
keep it scoped to the domain layer. This also gives `Ledger.legacy` (set when
a squad file is upgraded from the bare `players: [int]` format) somewhere to
surface its warning — currently nothing reads that flag.

Goal: a `fpl plan simulate` command that takes a squad ledger JSON file and a
transfer instructions file, replays the ledger to the current state, applies
the requested transfers gameweek by gameweek via `domain.transfers.simulate`,
and reports the resulting squad, bank, free transfers remaining, and any
points hits — using the existing `SnapshotService` / Typer / Rich patterns
from `players list` and `squad validate`.

No code written yet — this plan is for the next task.

---

## Decision 1 — transfers are specified in a plan file, not on the command line

**File**, not `--transfer OUT:IN` flags repeated per gameweek.

Reasons:

1. **Shape mismatch.** `simulate()` already takes
   `transfers_by_event: dict[int, list[Transfer]]` — an explicitly
   multi-gameweek, multi-transfer-per-gameweek structure. Expressing that on
   a command line means either repeating `--gw 4 --out 351 --in 233` flags
   and inferring grouping from adjacency (fragile, unusual for Typer), or
   inventing a mini string DSL (`4:351>233,4:100>200`) — that's reimplementing
   JSON with worse ergonomics and no reuse of `json.loads`.
2. **House pattern.** Every structured input in this CLI is already a JSON
   file loaded via `.from_file(path)`: `Ledger.from_file`,
   `SquadPlan.from_file`. `squad validate squad.json` takes a path, not
   inline flags. A transfers plan is the same kind of object.
2. **Reproducibility.** A multi-gameweek "what if" plan is something a user
   edits and re-runs, not a one-off. A file is diffable and reusable; a long
   flag-laden invocation is not.

A single-transfer, single-gameweek CLI convenience flag was considered and
rejected: it would be a second, parallel input path for the same data,
doubling the parsing logic for a case the file format already covers in one
line.

### Transfers plan schema

New format, separate from the ledger (the ledger records what *happened*;
this file records what's *proposed*):

```json
[
  {"event": 4, "transfers": [{"out": 351, "in": 233}]},
  {"event": 5, "transfers": [{"out": 100, "in": 200}, {"out": 101, "in": 201}]}
]
```

- Array, one object per gameweek, `event` matching `events[].id`.
- `transfers` is a list of `{"out": <player_id>, "in": <player_id>}`,
  directly constructing `Transfer(out_id, in_id)`.
- A duplicate `event` across two entries is a load-time error (ambiguous —
  which entry wins is not something to guess at).

Add `parse_transfers_plan(path: Path) -> dict[int, list[Transfer]]` to
`domain/transfers.py`, alongside `Ledger.from_file` and in the same style
(plain function, not a wrapper dataclass — the return type already is the
exact shape `simulate()` wants, so a class would only add indirection).

---

## Decision 2 — a gameweek that fails validation is reported, not silently dropped or fatal

`apply_transfers` already defines this behaviour: on failure it returns
`TransferResult(state=state, ...)` — the **unchanged** input state — with a
non-empty `validation.errors`. `simulate()` folds over that, so a rejected
gameweek's transfers are skipped and every later gameweek in the same run is
evaluated from the last *valid* state, not from the rejected one. The domain
layer already made this choice; the CLI's job is to render it faithfully, not
to add a second policy on top (e.g. aborting the whole run on first failure).

So the command:

1. Runs `simulate()` once for the whole plan file — it never stops early.
2. Prints one summary row per gameweek (event, transfers made, hit points,
   bank, free transfers, ✓/✗).
3. Under any ✗ row, prints its `validation.errors` in red and
   `validation.warnings` in yellow — same style as `squad validate`
   (`cli.py:89-92`).
4. Prints the **final** squad/bank/free-transfers from the last result (which,
   if the last gameweek failed, is the last successfully-applied state — not
   a half-applied one, since `TransferResult.state` on failure is the prior
   state unchanged).
5. Exits `1` if any gameweek failed, `0` otherwise — mirroring
   `squad validate`'s `raise typer.Exit(1)` on invalid (still subject to the
   pre-existing FU-3 bug: `typer.Exit` there is passed a code, this is
   consistent with the *fixed* pattern once FU-3 lands, and with today's
   accidental-but-harmless behaviour either way since `1` is a valid code).

This was chosen over aborting on first failure because a manager planning
several gameweeks ahead wants to see *where* a plan breaks and what the squad
looked like afterwards, not just the first error — consistent with
`domain/transfers.py` already being designed this way rather than raising.

One case is a hard error, not a validation failure, and is treated
differently: `apply_transfers` raises `ValueError` (not a `ValidationResult`)
if a plan entry's `event` is `<= state.event` at the time it's reached
(transfers targeting an already-replayed or duplicate gameweek). This is a
malformed plan file, not a rejected transfer, so the CLI catches `ValueError`
around the `simulate()` call and exits via the existing `load_snapshot`-style
`except ... raise typer.Exit(...)` pattern, printing the message and stopping
— nothing downstream of a malformed plan can be trusted enough to render.

---

## Command surface

```
fpl plan simulate SQUAD_LEDGER TRANSFERS_PLAN
```

- `SQUAD_LEDGER`: path to a squad JSON file — the existing `Ledger.from_file`
  format (or legacy `players: [int]`).
- `TRANSFERS_PLAN`: path to the new transfers-plan JSON above.

`cli.py` additions:

```python
plan_app = typer.Typer(help="Simulate and optimise transfer plans.")
app.add_typer(plan_app, name="plan")

@plan_app.command("simulate")
def simulate_plan(squad_path: Path, transfers_path: Path) -> None:
    snapshot = load_snapshot()

    try:
        ledger = Ledger.from_file(squad_path, snapshot)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise typer.Exit(f"Could not read squad ledger: {exc}") from exc
    if ledger.legacy:
        print("[yellow]Legacy squad file: selling prices are estimated from "
              "current prices, not real purchase history.[/yellow]")

    try:
        transfers_by_event = parse_transfers_plan(transfers_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise typer.Exit(f"Could not read transfers plan: {exc}") from exc

    rules = TransferRules.from_snapshot(snapshot)
    state = replay(ledger, snapshot)
    try:
        results = simulate(state, transfers_by_event, snapshot, rules)
    except ValueError as exc:
        raise typer.Exit(f"Invalid transfers plan: {exc}") from exc

    console.print(simulation_table(transfers_by_event, results))
    for event, result in zip(sorted(transfers_by_event), results):
        for error in result.validation.errors:
            print(f"[red]✗ GW{event}: {error}[/red]")
        for warning in result.validation.warnings:
            print(f"[yellow]! GW{event}: {warning}[/yellow]")

    final_state = results[-1].state if results else state
    console.print(squad_state_table(final_state, snapshot))
    print(f"Bank: £{final_state.bank / 10:.1f}m  |  Free transfers: {final_state.free_transfers}")
    print(f"Total hit points: {sum(result.hit_points for result in results)}")

    if any(not result.validation.valid for result in results):
        raise typer.Exit(1)
```

(Uses the pre-existing `typer.Exit(str)` idiom already in `cli.py` — not
fixed here; that's FU-3's scope, not this task's.)

`presentation.py` additions, matching `player_table`'s shape:

- `simulation_table(transfers_by_event, results) -> Table`: one row per
  gameweek — Event, Transfers, Hit, Bank, Free Transfers, Valid (✓/✗).
- `squad_state_table(state, snapshot) -> Table`: one row per held player —
  ID, Player, Club, Pos, Purchase price, Now cost — reusing
  `snapshot.players_by_id`, `snapshot.clubs`, `snapshot.positions` the same
  way `player_table` does.

---

## Files touched

- `src/fpl_cli/domain/transfers.py` — add `parse_transfers_plan`.
- `src/fpl_cli/cli.py` — add `plan_app` Typer sub-app and `simulate` command,
  import `Ledger`, `Transfer`, `TransferRules`, `parse_transfers_plan`,
  `replay`, `simulate` from `domain.transfers`.
- `src/fpl_cli/presentation.py` — add `simulation_table`, `squad_state_table`.
- `tests/test_transfers.py` or a new `tests/test_cli_simulate.py` — cover
  `parse_transfers_plan` (valid file, duplicate event, malformed JSON) and,
  using Typer's `CliRunner` against the synthetic snapshot fixture pattern
  already in `tests/conftest.py`, a passing simulate run, a run with a
  rejected gameweek (exit code 1, error text present), and a legacy-ledger
  warning.

Not touched: `domain/optimizer.py` (still unwritten), `storage/cache.py`,
`api/*`.

---

## Verification

- `pytest -q` — new tests above green, existing suite unaffected (no
  existing function signatures change).
- Manual smoke test against the real cached snapshot: a small squad ledger
  with a genesis buy log, a transfers-plan file with one valid gameweek and
  one deliberately invalid gameweek (e.g. a 4th player from one club), run
  `fpl plan simulate squad.json transfers.json`, confirm:
  - the valid gameweek's row shows ✓ with correct bank/hit arithmetic,
  - the invalid gameweek's row shows ✗ with its structural error printed,
  - the final squad table reflects state *after* the valid gameweek only,
  - exit code is `1`.
- A second manual run with an all-valid multi-gameweek plan, confirming exit
  code `0` and that free-transfer rollover/hits match hand calculation.

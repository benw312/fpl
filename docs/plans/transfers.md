# Plan: `domain/transfers.py` — deterministic transfer simulation

## Context

The README Agent Plan names manual transfer simulation as "the optimizer's
correctness baseline" — `domain/optimizer.py` cannot be trusted until a
deterministic, rule-derived simulator exists to check its recommendations
against. `domain/transfers.py` is the last unwritten domain module before that
work can start.

Today the project can validate a *static* squad (`domain/rules.py`,
`domain/squad.py`) but has no concept of a squad **changing over time**: no
purchase prices, no bank, no free transfers, no gameweek boundaries. This plan
adds that.

Scope of this task: applying transfers gameweek by gameweek, free-transfer
rollover and its cap, points hits for excess transfers, selling prices, and
official UTC deadlines. **Chips (wildcard, free hit, bench boost, triple
captain) are deferred** — see [Chips: deferred, with schema reserved](#chips-deferred-with-schema-reserved).

No code written yet.

---

## What the API actually provides

Verified against a live cached snapshot (`~/.fpl-cli/bootstrap-static.json`,
2026-08-24), not assumed:

| Rule | Source | Value |
|---|---|---|
| Sell-on fee | `game_settings.transfers_sell_on_fee` | `0.5` |
| Max extra free transfers | `game_settings.max_extra_free_transfers` | `4` |
| Transfers per gameweek cap | `game_settings.transfers_cap` | `20` |
| Sell at purchase price | `game_settings.element_sell_at_purchase_price` | `false` |
| Squad budget | `game_settings.squad_total_spend` | `1000` |
| Deadlines | `events[].deadline_time` | ISO-8601 `Z` |
| Timezone | `game_settings.timezone` | `"UTC"` |
| Buy/sell eligibility | `elements[].can_transact` | per player |

Two values are **not** in the payload and are flagged as assumptions in code:

- **The −4 points hit.** Absent from `game_settings` *and* from
  `game_config.scoring`. Genuinely underivable.
- **The base rate of 1 free transfer per gameweek.** Inferred from the field
  name `max_extra_free_transfers` — "extra" relative to an unstated base of 1,
  giving a cap of 5. The base itself is never stated.

`game_settings` is mirrored at `game_config.rules` with identical values; the
existing `GameSettings` model reads the former, and this plan does not change
that.

---

## Decision 1 — the ledger is an append-only log; state is derived by replay

The squad JSON stores an append-only log of buy/sell events. Holdings, purchase
prices, bank and free transfers are all **computed by replaying it from
genesis** on every load. There is exactly one stored representation, so nothing
can drift out of sync, and the whole ledger is auditable by reading the file.

**Genesis is the £100m window.** First run is assumed to be an initial squad
build: 15 buys, `bank = squad_total_spend − Σ purchase prices`. A manager
joining mid-season backdates buy events with their real purchase prices — the
format supports it, so this assumption is a default, not a constraint.

Purchase price stops being separate state: it is the price recorded in a
player's most recent `buy` entry. That matters because purchase price is
**manager-private** — the API only ever exposes `now_cost`, so no snapshot can
supply it. It has to be persisted by us, and the log is where it already lives.

Replay cost is nil: a full season is a few hundred entries.

### Schema

```json
{
  "version": 1,
  "genesis_event": 1,
  "log": [
    {"event": 1, "type": "buy",  "player": 427, "price": 145},
    {"event": 1, "type": "buy",  "player": 351, "price": 80},
    {"event": 4, "type": "sell", "player": 351, "price": 82},
    {"event": 4, "type": "buy",  "player": 233, "price": 90}
  ],
  "chips_played": [],
  "starters": [],
  "captain": null,
  "vice_captain": null
}
```

- `price` is the price **at the time of the transaction**, in integer tenths.
  For a sell it is the computed selling price, frozen at sale — never
  recomputed on replay.
- `event` is the gameweek id the transaction belongs to (matches `events[].id`).
- `starters` / `captain` / `vice_captain` are unchanged from today's format and
  orthogonal to the ledger. *[They are logically per-gameweek and currently
  aren't — out of scope; filed as FU-6.]*

**Backward compatibility:** a file with a bare `players: [int]` array and no
`log` is the legacy format. The loader accepts it, synthesises a genesis log at
current `now_cost`, and warns that selling prices will be optimistic. Existing
`squad.json` files and `tests/test_rules.py` keep working.

---

## Decision 2 — `apply_transfers` returns a new state; it never mutates

Transfer application is a pure function: `(state, transfers) → new state`.

1. **The optimiser demands it.** Beam search branches one state into many
   candidates. With mutation every branch needs a defensive deep copy, and a
   missed copy is an aliasing bug that silently corrupts the search.
2. **Failure atomicity.** A rejected transfer must not leave a half-applied
   squad with 14 players. Returning a new state makes the failure case
   structurally impossible rather than something to remember to unwind.
3. **Replay is already a fold.** `replay()` folds the log into successive
   states; `apply_transfers` is the same operation on a projected future. One
   shape, not two.
4. **House style.** `ValidationResult`, `SquadPlan` and `SnapshotResult` are all
   `@dataclass(frozen=True)`.

Cost, stated: each application allocates a new holdings dict. At 15 players and
a horizon of a handful of gameweeks this is irrelevant; if the optimiser ever
makes it matter, that's a measured optimisation inside the optimiser, not a
reason to make the domain mutable now.

---

## Decision 3 — split the structural checks out of `validate_squad`

**The problem.** `rules.py:42-44` enforces `Σ now_cost ≤ squad_total_spend`.
That rule is correct at genesis and wrong from then on: after price rises a
perfectly legal squad routinely exceeds £100m. The real post-genesis constraint
is that **the bank never goes negative**, which is ledger arithmetic, not a sum
over current prices. Running today's validator on a mid-season state produces a
false budget error.

**The fix.** Extract the structural half:

```python
# domain/rules.py
def validate_squad_structure(player_ids, snapshot) -> ValidationResult:
    ...   # size, duplicates, unknown ids, positions, club limit, selectability

def validate_squad(player_ids, snapshot) -> ValidationResult:
    result = validate_squad_structure(player_ids, snapshot)
    ...   # + Σ now_cost ≤ squad_total_spend
```

`validate_squad`'s signature and behaviour are **unchanged** — genesis builds,
`domain/squad.validate_plan`, `cli.py` and `tests/test_rules.py` are all
untouched. `transfers.py` calls `validate_squad_structure` plus its own
`bank >= 0` ledger invariant.

This satisfies the `CLAUDE.md` requirement literally: every state a transfer
produces passes the *same* structural validator used for manual planning —
identical code, not a parallel reimplementation. The budget rule is genuinely a
different rule in the two contexts, and separating it is honest where
parameterising it would produce one function with two incompatible meanings of
"budget" inside it.

Rejected alternative: filtering the budget error string out post-hoc. That means
matching on user-facing prose and suppressing a real failure class.

---

## Decision 4 — `TransferRules` lives in the domain, not in `api/models.py`

```python
@dataclass(frozen=True)
class TransferRules:
    sell_on_fee: float              # transfers_sell_on_fee
    max_extra_free_transfers: int   # max_extra_free_transfers
    transfers_cap: int              # transfers_cap
    sell_at_purchase_price: bool    # element_sell_at_purchase_price
    squad_total_spend: int          # squad_total_spend
    # [assumption: absent from bootstrap-static — see "What the API provides"]
    points_per_extra_transfer: int = 4
    # [inference: implied by max_extra_free_transfers naming, never stated]
    free_transfers_per_event: int = 1

    @classmethod
    def from_snapshot(cls, snapshot: BootstrapSnapshot) -> TransferRules: ...
```

The two undeliverable values are overridable per call and carry their bracketed
justification at the definition site.

They are deliberately **not** added to `GameSettings`. That model claims to
mirror the payload; a field the API never sends would leave a later reader
unable to tell which defaults are real. `api/models.py` stays an honest mirror.

`GameSettings` does gain the two real fields it is currently missing:
`transfers_cap: int = 20` and `element_sell_at_purchase_price: bool = False`.

---

## Decision 5 — selling price, derived from the fee setting

```python
def selling_price(purchase_price: int, now_cost: int, rules: TransferRules) -> int:
    if rules.sell_at_purchase_price:
        return purchase_price
    profit = now_cost - purchase_price
    if profit <= 0:
        return now_cost            # losses are borne in full
    kept = math.floor(profit * (1 - rules.sell_on_fee))
    return purchase_price + kept
```

Integer tenths throughout; no float ever reaches stored state. The fee comes
from the snapshot, so `// 2` is never hardcoded.

*[Precision caveat: `profit * (1 - fee)` is exact for the only value the API has
ever sent (0.5) and for any small integer profit. An exotic future fee like 0.3
could floor a hair wrong. Not worth `Fraction` today; noted at the call site.]*

---

## Decision 6 — gameweek boundaries and free-transfer rollover

```
cap = free_transfers_per_event + max_extra_free_transfers     # 1 + 4 = 5

at each gameweek boundary:
    free_transfers = min(free_transfers + free_transfers_per_event, cap)

within a gameweek:
    paid = max(0, transfers_made - free_transfers)
    hit  = paid * points_per_extra_transfer
    free_transfers = max(0, free_transfers - transfers_made)
```

- **Before the GW1 deadline, transfers are unlimited and free.** Consistent with
  `chips[].start_event == 2` for wildcard: the game itself treats GW1 as already
  unlimited, so no chip is offered for it.
- `transfers_cap` (20) is a hard per-gameweek ceiling — exceeding it is an
  error, not a hit.
- Validation runs **once per gameweek batch, on the resulting state** — never
  per individual transfer. A 2-transfer gameweek passes through a 13-player
  intermediate that is legitimately invalid; validating it would be a false
  failure.

### Deadlines

`Gameweek.deadline_time` already parses to a timezone-aware `datetime` (the API
sends `...Z`) and `game_settings.timezone` is `"UTC"`, so no conversion is
needed — only a guard that all comparisons are aware, never naive. Transfers
targeting a gameweek whose deadline has passed are rejected.

`Gameweek` gains `finished: bool = False` and `is_previous: bool = False`;
`deadline_time` stays `datetime | None` and the `None` case is handled
explicitly (an unreleased gameweek cannot be transferred into).

---

## Decision 7 — `can_transact` is a transfer-time rule, not a squad-legality rule

`Player.can_transact` already exists on the model and is currently unused.
A player with `can_transact=False` cannot be bought or sold, but a squad that
already holds one is not illegal. So the check belongs in `transfers.py`, not in
`validate_squad_structure` — adding it to the shared validator would
retroactively invalidate legitimately-held squads.

---

## Chips: deferred, with schema reserved

Wildcard, free hit, bench boost and triple captain are **out of scope**. The log
format is fixed by this task, so the question is what it must carry now to avoid
a breaking migration later.

**Free hit does not need event semantics in the log.** It reverts both squad and
bank at the next deadline, so by construction it is a no-op on the ledger —
recording its transfers would mean writing entries whose only purpose is to be
skipped on replay. The log records what *happened*; the simulator projects what
*might*. A free-hit squad is a projection, like any other simulated future
gameweek, and never becomes history.

**Wildcard needs nothing either.** Its transfers are permanent and real; they
land in the log as ordinary buys and sells. Its only effects — no points hit,
unlimited count — are computed at simulation time, not stored.

**One chip fact is load-bearing and is reserved now.** On a wildcard or free-hit
gameweek, banked free transfers are preserved. Because wildcard transfers *are*
in the log as ordinary entries, a naive replay would decrement free transfers
for them, which is wrong. Free-transfer arithmetic therefore has to know which
gameweeks had a chip. That is a **per-gameweek** fact, not a per-transaction
one — and bench boost and triple captain move no money at all, so they have no
transactions to attach to. Hence a sibling array, not a tag on log entries:

```json
"chips_played": []          // later: [{"chip": "wildcard", "event": 9}]
```

Three things go in the format now:

1. **`"version": 1`** — the genuinely load-bearing one. Without it, no later
   format change is distinguishable or migratable.
2. **`"chips_played": []`** — empty and unread by this task; the array
   free-transfer arithmetic will need.
3. **Log entries as objects, never tuples** — keeps every future per-entry field
   purely additive.

**Explicitly not added: a per-entry `chip` tag.** It is unnecessary by the
argument above, and an unused field invites incorrect use. The cost of omitting
it, stated plainly: a past free-hit squad cannot be viewed retrospectively,
because it was never recorded. That is recoverable whenever it's actually
wanted — `version` plus object entries make adding an optional field
non-breaking. Chip *names, windows and counts* need no reservation at all: the
API supplies them in full via `chips[]` (`name`, `number`, `start_event`,
`stop_event`, `chip_type`, `overrides`), so `api/models.py` gains no `Chip`
model in this task.

---

## Module layout

New: `src/fpl_cli/domain/transfers.py`

```python
TransferRules       # frozen; .from_snapshot(snapshot)          [Decision 4]
Transaction         # frozen; event, type, player, price
Ledger              # version, genesis_event, log, chips_played
                    #   .from_file(path) — accepts legacy `players: [int]`
Holding             # frozen; player, purchase_price, bought_event
SquadState          # frozen; holdings, bank, event, free_transfers
                    #   .player_ids -> list[int]   (feeds the validator as-is)
Transfer            # frozen; out_id, in_id
TransferResult      # frozen; state, validation, transfers_made,
                    #   hit_points, free_transfers_remaining

replay(ledger, snapshot, *, as_of_event=None) -> SquadState
selling_price(purchase_price, now_cost, rules) -> int            [Decision 5]
apply_transfers(state, transfers, event, snapshot, rules) -> TransferResult
simulate(state, transfers_by_event, snapshot, rules) -> list[TransferResult]
```

`SquadState.player_ids` is what reaches `validate_squad_structure(...)` — the
existing validator takes `list[int]` and needs no adaptation.

Modified:

- `src/fpl_cli/domain/rules.py` — extract `validate_squad_structure`;
  `validate_squad` unchanged externally. *[Decision 3]*
- `src/fpl_cli/api/models.py` — `GameSettings` gains `transfers_cap` and
  `element_sell_at_purchase_price`; `Gameweek` gains `finished` and
  `is_previous`. *[Decisions 4, 6]*
- `tests/conftest.py` — the `bootstrap_snapshot` fixture currently has
  `events=[]`; add synthetic gameweeks with UTC deadlines. Existing tests are
  unaffected.

Not touched in this task: `cli.py` (no `fpl plan simulate` command yet — filed
as FU-7), `domain/optimizer.py`, `presentation.py`, `storage/cache.py`.

---

## Implementation steps

1. `api/models.py` — add the four missing fields. Smallest change, unblocks
   everything else.
2. `domain/rules.py` — extract `validate_squad_structure`. Run `pytest -q`
   here: `test_rules.py` must stay green with zero edits, proving the
   refactor is behaviour-preserving.
3. `domain/transfers.py` — `TransferRules`, `Transaction`, `Ledger`, `Holding`,
   `SquadState`, `selling_price`, `replay`.
4. `domain/transfers.py` — `apply_transfers`, `simulate`.
5. `tests/conftest.py` — add gameweek fixtures.
6. `tests/test_transfers.py` — new.

Branch: `task/transfers` off `main`, per `CLAUDE.md`.

---

## Verification

`pytest -q`. New coverage in `tests/test_transfers.py`, all against the
synthetic dataset with no live API:

**Selling price** — price rise with odd profit rounds the kept half *down*
(purchase 80, now 83 → sell 81); price rise with even profit (80 → 84 → 82);
price fall sells at `now_cost`, full loss borne; price unchanged sells at
purchase; `element_sell_at_purchase_price=True` returns purchase price
regardless; a non-0.5 fee derives correctly from the setting rather than
halving.

**Replay** — genesis of 15 buys yields `bank == squad_total_spend − Σ prices`;
a buy/sell pair updates bank and holdings; purchase price tracks the *most
recent* buy after a player is sold and re-bought at a different price;
`as_of_event` truncates correctly; legacy `players: [int]` file loads and warns.

**Free transfers** — accrue 1 per gameweek; cap at
`1 + max_extra_free_transfers` (5) and do not exceed it across many idle
gameweeks; spending resets accrual correctly; GW1 is unlimited and free.

**Hits** — 1 transfer on 1 FT costs 0; 2 on 1 costs 4; 3 on 1 costs 8; 2 on 2
costs 0; exceeding `transfers_cap` (20) is an error, not a hit.

**Validation** — a transfer producing a 4th player from one club fails on the
*same* structural validator used by manual planning; a transfer leaving the bank
negative fails on the ledger invariant; a mid-season squad whose `Σ now_cost`
exceeds £100m **passes** (the regression Decision 3 exists to prevent); a
2-transfer gameweek is not falsely failed on its 13-player intermediate; a
player with `can_transact=False` cannot be transferred in or out.

**Deadlines** — a transfer into a gameweek whose deadline has passed is
rejected; a gameweek with `deadline_time=None` is rejected; all comparisons are
timezone-aware.

**Immutability** — `apply_transfers` leaves the input `SquadState` unchanged
(assert the original's holdings and bank after the call); a rejected batch
returns the input state untouched rather than a partially-applied one.

Then a manual smoke check on the real cached snapshot: replay a genesis ledger,
apply a transfer, confirm bank arithmetic and selling price against the FPL web
UI for the same player.

---

## Follow-ups to file in [follow-ups.md](follow-ups.md)

- **FU-5 — chips.** Wildcard, free hit, bench boost, triple captain. Schema
  reserved by this task (`version`, `chips_played`, object entries); the
  free-transfer preservation rule is the first thing that needs it.
- **FU-6 — `starters`/`captain` are per-gameweek, stored as if global.** The
  ledger is now gameweek-aware and the lineup fields are not.
- **FU-7 — `fpl plan simulate` CLI command.** `transfers.py` ships with no
  user-facing entry point; the README Agent Plan names the command.

---

## Scope boundary

In scope: `domain/transfers.py` (new), `domain/rules.py` (structural split),
`api/models.py` (four fields), `tests/conftest.py` (gameweek fixtures),
`tests/test_transfers.py` (new).

Out of scope, left filed: chips (FU-5), per-gameweek lineups (FU-6), CLI command
(FU-7), and the pre-existing FU-3 (`typer.Exit` misuse) and FU-4 (SQLite).

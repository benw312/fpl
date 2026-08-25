# Plan: `fpl squad create` — interactive squad builder

## Context

The README Agent Plan names `fpl squad create` as a target command and calls
for an interactive squad builder ("search players by name; filter by position,
club, price, points, form, availability; show remaining budget and club counts;
warn about injuries; save named local squads; import/export plans as JSON").
Nothing in the repo implements it. Today the only way to produce a squad is to
hand-author JSON and run `fpl squad validate` against it.

There is a second, sharper reason to build it now. `domain/transfers.py`
(`da4f6d6`) computes selling prices from `Holding.purchase_price`, and
`Ledger.from_file` falls back to a **legacy** path when a squad file is a bare
`players: [int]` array — synthesising a genesis log at current `now_cost` and
setting `Ledger.legacy = True`, which `cli.py:111` surfaces as "selling prices
are estimated from current prices, not real purchase history". Every
hand-authored squad file today hits that path. A builder that emits a proper
ledger — one `buy` transaction per player, carrying the price paid and the
gameweek it was bought in — is what makes transfer simulation trustworthy from
the first gameweek rather than approximately right.

Goal: `fpl squad create` renders a Rich pitch-style grid of 15 numbered
position slots with running cost and per-club counts, takes a slot number then
a player (prompt_toolkit fuzzy autocomplete on surname), and writes a ledger
JSON file directly consumable by `Ledger.from_file` / `replay`.

No code written yet — this plan is for the next task.

---

## Decision 1 — Rich renders; prompt_toolkit owns only the input line

Confirmed workable, and the redraw behaviour is measured rather than assumed.
Running `PromptSession.prompt()` against a `Vt100_Output` over a `StringIO`
(prompt_toolkit 3.0.52):

| Setting | Emitted |
|---|---|
| default | `?1049h` absent, `[2J` absent — **no alternate screen, no clear** |
| default (`reserve_space_for_menu=8`) | **7 newlines before the prompt line** |
| `reserve_space_for_menu=0` | 1 newline |
| `erase_when_done=True` | accepted input line removed from scrollback |

So prompt_toolkit renders inline at the cursor and never takes the screen.
Rich prints above it are untouched *by prompt_toolkit's renderer* — but the
reserve-space newlines **scroll the terminal** when the cursor is near the
bottom, pushing the pitch up by up to 7 lines. A pitch pinned in place without
redrawing is therefore not achievable, whatever the two libraries do.

**Approach: clear and redraw in place each iteration.**

```
console.clear()          # \x1b[2J\x1b[H — visible screen only; no [3J,
console.print(pitch)     #   so terminal scrollback is preserved
session.prompt("slot> ")
```

Because the screen is rebuilt from the top on every pick, the reserve-space
scroll is invisible; the pitch sits at a fixed screen position, which is the
entire point of a pitch layout.

Consequences to honour in the implementation:

- **The render must fit the terminal.** Clear-then-print scrolls and truncates
  the top if the pitch exceeds the height. Budget ~24 rows: 3-line header
  panel + 4 position rows + spacing + a 2-line hint footer, leaving room for
  the 8 reserved menu lines. Check `console.size.height` at startup and refuse
  with a clear message below a floor (~20 rows).
- **`erase_when_done=True`** on the `PromptSession` — a redrawn screen should
  not carry the previous prompt's accepted text. Note this is a **constructor**
  kwarg only; `completer`, `bottom_toolbar`, `validator`,
  `reserve_space_for_menu`, `complete_style` and `placeholder` *are* per-call
  overrides on `.prompt()`, so one session serves both prompts.
- **The final ledger summary is printed after the loop exits**, with a plain
  `console.print` and no clear, so the result survives in scrollback.
- **No `rich.live.Live`.** Live's refresh thread and prompt_toolkit's renderer
  both drive the cursor and will fight. Not used anywhere in the repo today;
  keep it that way.

Two prompts per pick, both plain input lines on one long-lived `PromptSession`:

```
slot>    ← number 1–15 | <Enter> next empty slot | d N clear slot | done | quit
player>  ← fuzzy autocomplete, Esc cancels back to the slot prompt
```

---

## Decision 2 — live *prevention*, one authoritative validation at the end

Live, as preferred — but the naive reading (call `validate_squad_structure`
after each pick and print its errors) is wrong and should not be implemented.
`validate_squad_structure` (`domain/rules.py:20`) validates a **complete**
squad: at 3 players picked it emits "The squad must contain exactly 15
players; found 3", "GKP requires 2 players; found 1", and so on. Those are
guaranteed failures on every partial squad — pure noise that trains the user to
ignore the error region.

Two layers instead:

**Live, per pick — the completer only ever offers legal candidates.** Feedback
is a filter over the candidate list, not an error report, so it cannot produce
false failures. A candidate is excluded when it is:

- not of the slot's `element_type`;
- already picked;
- from a club already at `settings.squad_team_limit`;
- not selectable (`not can_select` or `removed`);
- unaffordable — see the budget reserve below.

Alongside it, the header panel carries the running state (spent, remaining,
per-club counts, slots filled) and each candidate's `display_meta` carries
club / position / price / an availability marker. After a pick that lands an
injured or doubtful player (`status != "a"` or
`chance_of_playing_next_round == 0`), print one yellow warning line — the same
condition `validate_squad_structure` warns on, surfaced when it is actionable
rather than 12 picks later.

**Budget reserve.** Plain `price <= bank` permits a dead end: overspend early
and slots 13–15 become unfillable, recoverable only by undoing picks. Cap each
pick at

```
bank - Σ (cheapest eligible price for each still-empty slot)
```

where "eligible" reuses the same exclusion set. ~10 lines, and it makes the
dead end unreachable rather than merely diagnosable.

**On completion (15/15) — one `validate_squad(player_ids, snapshot)` call**,
the exact function `fpl squad validate` uses (`domain/rules.py:65`), rendered
with the existing red-✗ / yellow-! idiom from `cli.py:92-95`. The builder must
not become a second, parallel implementation of the rules; CLAUDE.md's "every
optimiser recommendation must pass the same validator used for manual squad
planning" applies with equal force here. `validate_squad` (not
`validate_squad_structure`) is correct at genesis: it adds the
`squad_total_spend` budget check, which holds against `now_cost` precisely
because this *is* the genesis squad — see the docstring at
`domain/rules.py:22-27`.

The candidate filter derives its limits from the same snapshot fields the
validator reads (`settings.squad_team_limit`, `settings.squad_total_spend`,
`position.squad_select`, `settings.squad_squadsize`) — never hardcoded.

---

## Decision 3 — all 15 slots, positional grid; no XI/bench split

**All 15, in four position rows.** Captaincy and lineup selection being out of
scope does force this, for three reasons:

1. **An XI+bench layout *is* a formation.** Placing a player on the grass
   rather than the bench is a lineup decision. If the builder isn't making
   lineup decisions it cannot make that placement, and inventing one would be
   asserting a choice it has no basis for.
2. **Formation validity is a separate, currently-unsolved problem.**
   `Position.squad_min_play` / `squad_max_play` exist on the model
   (`api/models.py:51-52`) and are read by **nothing**. `validate_plan`
   (`domain/squad.py:33`) checks only that `starters` numbers 11 and is a
   subset of the squad — it never checks the formation is legal. An XI/bench
   view would need that validator to exist first.
3. **The output has nowhere to put it.** The ledger schema is a `log` of buy
   transactions; it has no `starters`, `captain` or `vice_captain` field. An
   XI/bench distinction made in the UI would be discarded on write.

The grid is therefore positional, not tactical — pitch-*like* without claiming
a formation:

```
┌─ Squad 8/15 · £62.5m spent · £37.5m left ─────────────────────┐
│ ARS 2   LIV 2   MCI 1   NEW 1   BHA 1   CHE 1                 │
└───────────────────────────────────────────────────────────────┘

    GK    1 Raya      ARS  5.5     2 ──────────
   DEF    3 Gabriel   ARS  6.0     4 Gvardiol  MCI  6.0    5 ──────────  ...
   MID    8 Salah     LIV 14.5     9 Saka      ARS 10.0   10 ──────────  ...
   FWD   13 Haaland   MCI 15.0    14 ──────────           15 ──────────

  slot number · <Enter> next empty · d N clear · done · quit
```

Slots number 1–15 in reading order, sized from `position.squad_select` per
`snapshot.element_types` — so 2/5/5/3 is derived, not written down.

Two gaps this surfaces are filed as follow-ups rather than fixed here (one
concern per branch): FU-8 (formation validation) and FU-9 (XI, captain and
vice-captain selection).

---

## Decision 4 — one index, one completer instance, state read per call

**Built once**, both the snapshot-derived index and the `Completer` object.

The measurement that settles it: with `complete_while_typing=True`,
prompt_toolkit calls `get_completions` on **every keystroke**. So per-keystroke
work must be small. Per-*prompt* rebuilding would also be cheap in absolute
terms (15 rebuilds), but it does not actually help — the filter depends on
state that changes *within* a single prompt-free interval (picked ids, bank,
club counts), and the completer is bound at `PromptSession` construction. The
completer must read live state at call time regardless, and once it does,
rebuilding it buys nothing.

At session start, build once:

```python
@dataclass(frozen=True)
class Candidate:
    id: int
    name: str          # web_name — the surname the user types
    key: str           # name.casefold() — the match key
    club: int
    price: int
    meta: str          # "ARS · MID · £10.0m · doubtful" — display_meta
```

`by_position: dict[int, list[Candidate]]`, each list sorted by `total_points`
descending so the first menu entry is the obvious one when the user types
"sal". ~700 objects total, built once from `snapshot.elements`.

Per keystroke, over the ~250 candidates of one position only: a compiled
subsequence regex against `key`, plus set-membership exclusions, capped at ~40
yielded completions.

### Own `Completer` subclass, not `FuzzyCompleter`

Verified against 3.0.52: `FuzzyCompleter` **overwrites `Completion.display`**
with its own highlighted copy of `Completion.text` and discards ours
(`display_meta` does survive). So with `FuzzyCompleter` the visible menu text
is `Completion.text` verbatim — meaning the disambiguating id has to leak into
it ("Salah #328") or be dropped entirely. It also calls the inner completer
with an empty-word document on every keystroke, re-materialising all ~700
candidates before filtering.

A ~20-line subsequence match inside our own `Completer` keeps `display` and
`display_meta` under our control, ranks by total points rather than
FuzzyCompleter's match-start heuristic, and folds the slot/club/budget filters
into the same pass:

```python
class SlotCompleter(Completer):
    def get_completions(self, document, complete_event):
        typed = document.text_before_cursor.casefold()
        pattern = re.compile(".*?".join(map(re.escape, typed)))
        for candidate in self.eligible():          # reads live builder state
            if pattern.search(candidate.key):
                yield Completion(
                    candidate.name,
                    start_position=-len(document.text_before_cursor),
                    display=candidate.name,
                    display_meta=candidate.meta,
                )
```

**Identity on accept.** `Completion.text` is the bare surname, and FPL has
duplicate surnames. Resolve the accepted string against the *eligible*
candidate list for the active slot: exactly one match → take it; several →
reprint those few as a numbered Rich table and prompt for the number; none →
red message, reprompt. The disambiguation list is short because it is already
filtered by position and by everything else the slot excludes.

`complete_while_typing=True`, `complete_style=CompleteStyle.MULTI_COLUMN`.

---

## Output — a ledger, not an id list

Written to `--output` (default `squad.json`), in exactly the shape
`Ledger.from_file` parses at `domain/transfers.py:63-78`:

```json
{
  "version": 1,
  "genesis_event": 3,
  "log": [
    {"event": 3, "type": "buy", "player": 328, "price": 145},
    {"event": 3, "type": "buy", "player": 15,  "price": 55}
  ],
  "chips_played": []
}
```

- `"log"` present ⇒ `Ledger.legacy` stays `False` ⇒ no estimated-selling-price
  warning at `cli.py:111`. That is the point of the whole exercise.
- `price` is `player.now_cost` at build time — for a genesis squad that *is*
  the purchase price, no estimation involved.
- **On `bought_event`:** `Holding.bought_event` (`domain/transfers.py:124`) is
  an *in-memory* field that `_fold_event` derives from each transaction's
  `event` (`domain/transfers.py:187`). The file schema carries `event` per
  transaction; a `bought_event` key would be silently ignored by
  `Ledger.from_file`. Every buy carrying its own `event` is what produces
  correct `bought_event` on replay.
- `genesis_event` comes from `_current_event_id(snapshot)`
  (`domain/transfers.py:110`) — falls back `is_current` → `is_next` → `1`.
  **Rename it to `current_event_id`** (public) rather than importing an
  underscore-prefixed name across modules; it has one existing call site
  (`domain/transfers.py:84`).
- Deliberately **not** also emitting a `players: [int]` array.
  `Ledger.from_file` tests `"log" in payload` first, so it would be dead weight
  there; and `SquadPlan.from_file` would read it only for `validate_plan` to
  then fail on the absent `starters`/`captain`. It buys nothing today.

That last point is a real interop gap: **`fpl squad validate` cannot read the
file `fpl squad create` writes** (`SquadPlan.from_file` expects
`players`/`starters`/`captain`). Filed as FU-10; not fixed here.

Refuse to overwrite an existing output path unless `--force`; check before
writing, not after building.

---

## Files touched

- **`pyproject.toml`** — add `"prompt-toolkit>=3.0,<4"` to `[project]
  dependencies`. Present globally (3.0.52) but **absent from `.venv`**, so
  `pip install -e ".[dev]"` must be re-run.
- **`src/fpl_cli/domain/squad.py`** — the pure, terminal-free core, so the
  rules are testable without driving a prompt:
  - `SquadSlots` — slot layout derived from `snapshot.element_types`
    (`position.squad_select`), holding `slot → player_id | None`.
  - `eligible_players(slots, slot_index, snapshot) -> list[Player]` — the
    Decision 2 exclusion set including the budget reserve.
  - `to_ledger_payload(slots, snapshot) -> dict` — the JSON above.
- **`src/fpl_cli/domain/transfers.py`** — rename `_current_event_id` →
  `current_event_id`; update its one call site.
- **`src/fpl_cli/presentation.py`** — `squad_grid(slots, snapshot) -> Group`
  (header `Panel` + the four position rows), reusing `snapshot.clubs` /
  `snapshot.positions` / `snapshot.players_by_id` exactly as `player_table` and
  `squad_state_table` already do. Rendering only; no rule logic.
- **`src/fpl_cli/builder.py`** *(new)* — `SlotCompleter`, the `Candidate`
  index, and the prompt loop. Kept out of `cli.py` so the Typer layer stays a
  thin adapter, and out of `domain/` because it imports prompt_toolkit.
  Constructor takes `input`/`output` (defaulting to `None`, i.e.
  prompt_toolkit's real terminal) so tests can inject a pipe.
- **`src/fpl_cli/cli.py`** — `@squad_app.command("create")`, taking
  `--output PATH` and `--force`. Uses the existing `load_snapshot()` helper.
  Guard `sys.stdin.isatty()` and refuse cleanly when not a TTY. Catch
  `KeyboardInterrupt` / `EOFError` from the loop → "Cancelled; nothing
  written." Use `console.print(...)` + `raise typer.Exit(1)` for errors — the
  correct idiom, not the `typer.Exit(str)` bug at `cli.py:29/47/90`, which is
  FU-3's scope and stays untouched.
- **`tests/conftest.py`** — add a `builder_snapshot` fixture (see
  Verification); leave `bootstrap_snapshot` untouched.
- **`tests/test_squad_builder.py`** *(new)*.

Not touched: `api/*`, `storage/cache.py`, `domain/rules.py`,
`domain/optimizer.py` (still unwritten).

---

## Verification

**A larger fixture is needed first.** `bootstrap_snapshot` in
`tests/conftest.py` holds exactly 15 players — 2/5/5/3, all priced `50`,
distributed `team=(id % 5) + 1` so every club has exactly 3, which is
`squad_team_limit`. It is precisely one valid squad and no alternatives: there
is no 4th player at any club to exclude, no second candidate for any slot, and
no price variation. Nothing about *filtering* can be tested against it. Add a
`builder_snapshot` fixture alongside it — same shape, ~60 players, several per
club including at least one club with 4+, and varied `now_cost` — and leave the
existing fixture untouched so the current suite is unaffected.

**Unit — the domain core, no terminal (the bulk of the coverage).** Against
`builder_snapshot`:

- `eligible_players` excludes wrong position, already-picked, a club already at
  `squad_team_limit` (pick 3 from the 4+-player club, assert the 4th is gone),
  `can_select=False`, and `removed=True`.
- Budget reserve: with `bank` low enough that a candidate's price would leave
  the remaining slots unfillable, that candidate is excluded — and *not*
  excluded once one more cheap slot is filled.
- `to_ledger_payload` → `Ledger.from_file` round-trip (either fixture):
  `legacy is False`, `genesis_event == current_event_id(snapshot)`, 15 buys.
- `replay(ledger, snapshot)` on that payload: 15 holdings, every
  `Holding.bought_event == genesis_event`,
  `bank == squad_total_spend - Σ now_cost`, and
  `validate_squad(state.player_ids, snapshot).valid is True`.

**Completer — no terminal.** Instantiate `SlotCompleter` directly and call
`get_completions(Document("sal", 3), CompleteEvent())`, asserting the yielded
ids, their order (points-descending), and that `display_meta` carries club /
position / price. This is the check that catches a regression to
`FuzzyCompleter`'s display-overwriting behaviour.

**End-to-end — driven terminal.** Verified working during planning:

```python
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

with create_pipe_input() as pipe:
    pipe.send_text("1\nP1\n2\nP2\n...\ndone\n")
    builder = SquadBuilder(snapshot, input=pipe, output=DummyOutput())
```

One full 15-pick run writing to `tmp_path`, asserting the file parses via
`Ledger.from_file` and validates. Plus a rejection path: send a slot number
that is already filled, and an unresolvable player name, and assert the loop
reprompts rather than exiting.

**Manual smoke, real terminal** (the parts no test covers):

1. `fpl sync`, then `fpl squad create --output /tmp/squad.json`.
2. Confirm the pitch holds a fixed screen position across all 15 picks and does
   not creep upward — this is the Decision 1 reserve-space behaviour.
3. Confirm the completion menu shows surname + club/position/price meta, that
   typing a duplicated surname triggers the numbered disambiguation, and that a
   club's 4th player never appears.
4. Confirm the final `validate_squad` output and the ledger summary survive on
   screen after the loop (no clear after exit).
5. `fpl plan simulate /tmp/squad.json transfers.json` — confirm **no** yellow
   "Legacy squad file" warning, and that a sale's price reflects
   `selling_price(purchase_price, now_cost, rules)` rather than bare
   `now_cost`.
6. Resize the terminal below the height floor and confirm the refusal message.
7. `fpl squad create < /dev/null` — confirm the non-TTY refusal, not a hang.
8. `pytest -q` — full suite green.

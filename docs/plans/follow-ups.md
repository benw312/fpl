# Follow-ups

Work deliberately deferred out of other tasks. Each entry records what, why it was
deferred, and what it unblocks.

---

## FU-1 — Extract the stale-cache decision into a `SnapshotService`

**Deferred from:** [transport.md](transport.md), Step 3.

`cli.load_snapshot` (`cli.py:21-33`) mixes three concerns: choosing between live and
cached data, printing a staleness warning via `rich.print`, and exiting the process.
The caching decision cannot be tested without reaching into the CLI module.

**Proposal:** move it to `api/snapshots.py` as a `SnapshotService` taking an API and
a cache, returning `SnapshotResult(snapshot, stale, reason)`. `cli.py` decides how to
render staleness; the service decides what to load.

**Unblocks:** `tests/test_stale_cache.py` currently monkeypatches
`fpl_cli.cli.OfficialFplApi` and `fpl_cli.cli.SnapshotCache` because `load_snapshot`
constructs both internally. That patching goes away.

**Also fixes:** the same code path is duplicated in `sync` (`cli.py:39-46`), which
constructs its own API and cache.

---

## FU-2 — `load_snapshot` never writes the cache on a successful fetch

**Deferred from:** [transport.md](transport.md), Step 3.

`cli.py:26` fetches a fresh snapshot and returns it without saving. Only `fpl sync`
(`cli.py:42`) populates the cache. A user who runs `fpl players list` without ever
running `fpl sync` therefore has no cached snapshot to fall back on — which defeats
the stale-cache guarantee in `CLAUDE.md` ("Cached snapshots must keep the app usable
during failures") for the most likely first-run path.

**Severity:** this is a real user-visible gap, not cosmetic. Worth doing soon,
ideally together with FU-1 since the fix lands in the same function.

**Fix:** save after every successful fetch.

**Test to add with the fix:** live fetch succeeds → the cache file exists afterwards
and round-trips. Deliberately omitted from `tests/test_stale_cache.py` rather than
committed as a known-failing test.

---

## FU-3 — `typer.Exit` is passed a message where it expects an exit code

**Deferred from:** [transport.md](transport.md), Step 3.

`typer.Exit.__init__` is `(self, code: int = 0)`. Three call sites pass a string:
`cli.py:31`, `cli.py:44`, `cli.py:87`. The message reaches the user only by accident
of `SystemExit` semantics — `sys.exit(str)` prints to stderr and exits 1 — so the
intended exit code is silently discarded and every failure exits 1.

**Fix:** print to stderr explicitly, then `raise typer.Exit(1)`.

**Blocks:** `tests/test_stale_cache.py` can assert only the exception type, not the
message, until this is fixed.

---

## FU-4 — SQLite cache backend

**Deferred from:** [transport.md](transport.md), Assumptions.

`CLAUDE.md` and the README Agent Plan both specify "SQLite plus raw JSON snapshots"
for caching. `storage/cache.py` implements raw JSON only. Nothing needs SQLite yet —
it becomes relevant once per-player `element-summary/{id}` responses and historical
gameweek data are cached, where a single JSON blob stops being a sensible shape.

**Not urgent.** Revisit when the second and third endpoints land.

---

## FU-5 — Chips (wildcard, free hit, bench boost, triple captain)

**Deferred from:** [transfers.md](transfers.md), "Chips: deferred, with schema
reserved".

`domain/transfers.py` implements ordinary transfer application, rollover, hits
and selling prices only. Chip behaviour — no hit for wildcard, full squad+bank
revert for free hit, no transfer effect for bench boost/triple captain — is not
implemented.

The ledger schema was fixed with chips in mind so this doesn't require a
breaking migration: `Ledger.version`, `Ledger.chips_played` (empty, unread by
the current code), and object-shaped `Transaction` log entries. The first thing
that will need `chips_played`: on a wildcard or free-hit gameweek, banked free
transfers must be preserved rather than decremented by `_fold_event` — today
every non-genesis event decrements free transfers by however many buys it
contains, which is wrong for a chip-played gameweek once chips exist.

**Unblocks:** the README Agent Plan's "Model wildcard and free-hit behaviour
separately" requirement.

---

## FU-6 — `starters`/`captain`/`vice_captain` are per-gameweek, stored as global

**Deferred from:** [transfers.md](transfers.md), Decision 1.

The squad JSON's `starters`, `captain` and `vice_captain` fields are unchanged
from before the transfer ledger existed — one value each, for the whole file.
But a lineup is logically a per-gameweek choice: a manager sets a different
starting XI and captain most weeks. The ledger (`Ledger.log`) is now
gameweek-aware; these three fields are not, so a squad file can't currently
record "who was captain in gameweek 4" once gameweek 5 has been played.

**Not urgent** on its own — `domain/squad.SquadPlan` still works for
single-snapshot validation. Revisit if/when the CLI needs to answer
"what was my lineup in a past gameweek", or when the optimiser needs to assign
a captain per simulated gameweek.

---

## FU-7 — `fpl plan simulate` CLI command

**Deferred from:** [transfers.md](transfers.md), Module layout.

`domain/transfers.py` has no CLI entry point. The README Agent Plan names
`fpl plan simulate` and `fpl plan optimize` as target commands; only the
domain logic for the former now exists. `cli.py` was deliberately left
untouched by that task to keep it scoped to the domain layer.

**Unblocks:** exercising transfer simulation from the command line at all,
and gives `Ledger.legacy` (set when a squad file is upgraded from the bare
`players: [int]` format) somewhere to surface its warning — currently nothing
reads that flag.

---

## FU-8 — Formation validity is never checked

**Deferred from:** [squad-builder.md](squad-builder.md), Decision 3.

`Position.squad_min_play` and `squad_max_play` (`api/models.py:51-52`) are
parsed from the snapshot and read by **nothing**. `validate_plan`
(`domain/squad.py:33-40`) checks only that `starters` numbers
`squad_squadplay` and is a subset of `players` — so a starting XI of 1 GK and
10 forwards validates clean today.

**Fix:** count starters by `element_type` and check each against its position's
`squad_min_play`/`squad_max_play`, in `validate_plan` alongside the existing
starter checks. Rules come from the snapshot, so nothing is hardcoded.

**Blocks:** any XI/bench UI. `fpl squad create` deliberately renders a flat
15-slot positional grid rather than a pitch-with-bench precisely because
placing a player in the XI is a formation decision that no validator currently
backs — see FU-9.

---

## FU-9 — Starting XI, captain and vice-captain selection

**Deferred from:** [squad-builder.md](squad-builder.md), Decision 3.

`fpl squad create` picks a 15-player squad and nothing else. Choosing the XI,
captain and vice-captain is a separate interaction, and the ledger format it
writes (`log` of buy transactions) has no field to record any of them.

Needs FU-8 first (an XI can't be offered before an illegal formation can be
rejected) and overlaps FU-6, which already notes that `starters`/`captain`/
`vice_captain` are logically per-gameweek but stored as one global value each.
Doing this properly probably means resolving FU-6's schema question at the same
time rather than bolting a global XI onto a gameweek-aware ledger.

---

## FU-10 — `fpl squad validate` silently misparses the ledger file `fpl squad create` writes

**Deferred from:** [squad-builder.md](squad-builder.md), Output.
**Sharpened from user testing (2026-08-25):** this is not a load failure —
it's a silent misreport.

`fpl squad create` emits a transfer ledger (`version`/`genesis_event`/`log`),
which is what `domain/transfers.py` consumes and what keeps `Ledger.legacy`
false. But `fpl squad validate` goes through `SquadPlan.from_file`
(`domain/squad.py:20-27`), which reads `payload.get("players", [])` — a
ledger has no `players` key, so this returns `[]` with **no error at all**.
`validate_plan` then reports "The squad must contain exactly 15 players;
found 0 players" as if the user had built an empty squad, when the file on
disk is a fully valid, non-empty 15-player ledger. Confirmed directly:

```python
>>> SquadPlan.from_file(Path("ledger.json"))
SquadPlan(players=[], starters=[], captain=None, vice_captain=None)
```

Any other unrecognised JSON shape hits the same silent path — `.get(...,
[])` never raises, so a typo'd key or a completely unrelated JSON file also
reports "found 0 players" instead of "this file isn't a squad plan or
ledger."

**Fix — three shapes, not two:**
1. `"log" in payload` → a ledger. Run `replay(ledger, snapshot)` then
   `validate_squad(state.player_ids, snapshot)`, skipping the
   starters/captain checks a ledger has no data for.
2. `"players" in payload` → the existing `SquadPlan` shape, unchanged.
3. Neither key present → raise clearly (e.g. `ValueError`, caught by
   `cli.py`'s existing `except (OSError, ValueError, TypeError) as exc:
   raise typer.Exit(f"Could not read squad plan: {exc}")` at
   `cli.py:131-132` — no new error handling needed there, just something to
   raise). Do not fall through to an empty squad.

**Not fixed here:** changes an existing command's input handling, a separate
concern from the squad-builder branch that surfaced it.

---

## FU-11 — `p1`'s substitute term isn't gated by availability

**Deferred from:** [projections-v1.md](projections-v1.md) Decision 4, step 3
(`task/projections-v1`).

`domain/projections.py::_minutes_probabilities` implements the plan's formula
literally: `p1 = p_start + (1 - p_start) * p_sub_appearance`. For a player
with `status` in `{i, s, u}` (unavailable), `_availability` correctly drives
`p_start` to 0 — but `p_sub_appearance` (default 0.35) is a flat constant
applied regardless of availability, so `p1` still comes out to `0.35` rather
than `0.0`. This also inflates `xmins` by `(1 - p_start) * p_sub_appearance *
mins_per_sub` for a long-term injury.

`xp_appearance` and `xp_attack` etc. are gated through `xmins`/`p1`/`p60`, so
a genuinely unavailable player gets a small non-zero score instead of the
expected exact zero. Not fixed here — the plan's Decision 4 text specifies
this formula precisely and doesn't gate the substitute term, so this may be
intentional (or an oversight in the plan itself); needs a decision, not a
silent patch. Candidate fix: multiply the substitute term by `availability`
too, i.e. `p1 = p_start + (1 - p_start) * p_sub_appearance * availability`.

**Escalated to a blocker (2026-08-25, [optimizer-ux.md](optimizer-ux.md) §8).**
Must be decided before `fpl plan optimise` ships.

**Diagnosis, traced against the live snapshot.** The availability signal is
neither missing nor overridden. `_availability` (`projections.py:59-66`) maps
`status ∈ {i, s, u}` to `0.0` correctly — all 97 such players in the current
snapshot return exactly `0.0` — and that reaches `p1` through `p_start`, which
correctly becomes `0.0`. The defect is that `p1`'s *second* term is
unconditional, so when `p_start = 0` it becomes the whole value. There is no
floor or clamp construct overriding anything. **The fix is therefore not
removing a floor, and not wiring up an unconnected signal: it is extending an
already-correct signal into the second term.**

`xmins` (`projections.py:98`) has the same structure and the same defect. The
candidate fix must be applied to **both** lines, not just `p1` as the snippet
above shows:

```python
p1    = p_start + (1 - p_start) * p_sub_appearance * availability
xmins = p_start * e_mins_start + (1 - p_start) * p_sub_appearance * mins_per_sub * availability
```

`p60` is unaffected — `p_start * p60_given_start` is correctly `0.0`.

**Corrected severity.** An earlier draft of optimizer-ux.md claimed injured
cheap players could outscore fit ones at the same price. Measured, that is false
at present: over 5 gameweeks the best unavailable player projects 1.75 xP while
the worst fit player at £4.0m projects 5.91, and the injured player outscores
0 of 56 fit players at that price. At `appearances = 1` the shrinkage collapses
to the position prior, which gives fit players a `p_start` an injured player
cannot approach.

The real defect is **convergence, not inversion**. For a player with
`starts = 0`, `p_start` decays as `appearances` grows, so a fit-but-fringe
player falls toward the same unconditional 0.35 an injured player is pinned at —
`xmins` gap 35.4 at GW1, 12.6 by GW10, 4.2 by GW38. The model progressively
loses the ability to distinguish "fringe squad player" from "ruled out injured",
which is exactly the discrimination an optimiser needs when picking a cheap
enabler. Least visible in pre-season, most damaging late.

---

## FU-12 — `rich.print` and `console.print` are mixed arbitrarily

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8 (CLI audit).

`cli.py:9` does `from rich import print`, shadowing the builtin, *and* `cli.py:31-39`
imports `console` from `presentation`. Both are used, seemingly at random, within
the same function. `fpl squad create` uses `console.print` for its own messages
(`cli.py:121, 124, 132, 135, 144, 149`) but bare `print` for validation errors and
warnings (`cli.py:140, 142`). `fpl plan simulate` uses `console.print` for tables
(`cli.py:197, 205`) but bare `print` for the legacy warning, the per-gameweek
diagnostics and the two summary lines (`cli.py:180, 200, 202, 206, 207`).
`builder.py` uses `console` exclusively.

Two output channels means width detection, output capture and `NO_COLOR`/
`--no-color` handling differ between lines of the same command's output.

**Fix:** drop the `from rich import print` import; route everything through the
`presentation.console` singleton.

**Unblocks:** any future `--json` or `--quiet` flag (FU-13), which needs a single
place to suppress or redirect output.

---

## FU-13 — No machine-readable output on any command

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

Every command prints a Rich table or styled text and nothing else. There is no
`--json` anywhere, so no command's output can be consumed by a script or diffed
programmatically.

This matters most for the optimiser: [optimizer-ux.md](optimizer-ux.md) §1 makes
`fpl plan optimise --output` → `fpl plan simulate` the mechanism that satisfies
CLAUDE.md's *"Every optimiser recommendation must pass the same validator used
for manual squad planning"*. Asserting that the two agree is currently a
by-eye comparison of two Rich tables.

**Needs FU-12 first** — a single output channel, before there is anything to
switch.

---

## FU-14 — `fpl players show` and `fpl squad import` / `export` are unimplemented

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

The README Agent Plan names nine commands. Six exist (`sync`, `players list`,
`squad create`, `squad validate`, `plan simulate`, `plan evaluate`). Missing:
`fpl players show`, `fpl squad show`, `fpl squad import`/`export`, and
`fpl plan optimize`.

`fpl squad show` and `fpl players show` are **not** filed here — both are
load-bearing for the optimiser workflow and are specified in
[optimizer-ux.md](optimizer-ux.md) §8.1 and §8.2. `fpl plan optimise` is the
subject of that document. This entry covers only `squad import`/`export`, which
nothing currently needs: `squad create --output` writes JSON and
`squad validate` reads it, so import/export would today be a rename of files
that are already plain JSON on disk. Revisit if a non-JSON interchange format
or a named-squad store ever appears.

---

## FU-15 — The README "Commands" section is stale

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

`README.md:25-33` lists three commands (`sync`, `players list`,
`squad validate`), omitting `squad create`, `plan simulate` and `plan evaluate`.
Worse, `README.md:33` describes a squad plan as *"a JSON object containing a
`players` array of player IDs"* — the **legacy** format. `fpl squad create` now
writes a transfer ledger (`version`/`genesis_event`/`log`), and the legacy shape
survives only as `Ledger.from_file`'s fallback, which sets `legacy=True` and
produces optimistic selling prices.

A user following the README today builds the one squad format the app warns
about.

**Also stale:** `README.md:5-12` ("The first slice supports…") predates the
squad builder, transfer simulation and projections.

---

## FU-16 — FU-3 is still live, at eight call sites

**Re-affirmed from:** [optimizer-ux.md](optimizer-ux.md), §8. Original: FU-3.

FU-3 recorded three `typer.Exit(str)` call sites. There are now eight:
`cli.py:56, 76, 159, 178, 188, 195, 231, 238`. `typer.Exit.__init__` is
`(self, code: int = 0)`, so every one of these discards its intended exit code
and reaches the user only via `sys.exit(str)` semantics — print to stderr,
exit 1.

Filed separately from FU-3 rather than editing it, because the count growing
from three to eight while the entry sat open is itself the finding: the idiom is
being copied. `plan-simulate.md:176-177` copied it knowingly.

**Fix (unchanged from FU-3):** print to stderr explicitly, then
`raise typer.Exit(1)`.

---

## FU-17 — `players list --club` fails silently on an unknown club

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

`cli.py:104`:

```python
players = [player for player in players if player.team == club_id] if club_id else []
```

An unrecognised `--club` yields `club_id is None` and therefore an empty result
with no message — indistinguishable from a club that genuinely has no matching
players. Two lines above, `--position` raises
`typer.BadParameter("Use GKP, DEF, MID, or FWD.")` for the same class of error
(`cli.py:99-100`).

**Fix:** raise `typer.BadParameter` naming the unknown club, matching
`--position`. Club names come from the snapshot, so the valid set is known at
the point of failure.

---

## FU-18 — `presentation.py` is a flat module; the Agent Plan specifies a package

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

The README Agent Plan's file list names `src/fpl_cli/presentation/` — a package.
The repo has `src/fpl_cli/presentation.py`, a flat module, now at 185 lines with
seven renderers. `CLAUDE.md` documents the flat module deliberately
(*"`presentation.py` (flat module)"*), so the two are in direct conflict.

[optimizer-ux.md](optimizer-ux.md) adds at least four more renderers (a
projection table, a paths table, a "why" table, a provenance panel). Decide
before that lands, rather than drifting: either split into a package and update
`CLAUDE.md`'s Structure section, or amend the README's file list. Either is
fine; the conflict is not.

---

## FU-19 — `CLAUDE.md`'s "not yet written" line is stale

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

`CLAUDE.md` states *"Not yet written: domain/optimizer.py, interactive squad
builder."* The interactive squad builder exists as `src/fpl_cli/builder.py`
(238 lines) and ships as `fpl squad create`.

Minor, but `CLAUDE.md` is loaded into context every session and instructs agents
that the repo is the source of truth — a stale line there is worse than a stale
line in the README.

---

## FU-20 — `_build_schedule` is private, and it is the only blanks/doubles logic

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.7.

`projections.py:216-233` maps `event -> team -> list[_FixtureLeg]`, skipping
fixtures with `event is None`. It is the **only** machinery in the repo that
knows about blank and double gameweeks, and it is private to `projections.py`.

[optimizer-ux.md](optimizer-ux.md) §5 annotates a projection of `0.0` with
"GW8: Bournemouth blank (0 fixtures)", which requires the fixture count for a
team in a gameweek. `Projection.fixtures` carries that number per player, so the
optimiser can get it indirectly — but any command that wants to *show the
schedule* (a fixture-difficulty view, `players show`, a blanks/doubles warning
in `plan optimise`'s header) needs the mapping itself.

**Fix:** promote to `build_schedule` with a public `FixtureLeg`, or expose a
narrower `fixture_count(team, event)` helper. Prefer the narrower one until a
second caller genuinely needs the legs.

---

## FU-21 — `chance_of_playing_this_round` is never parsed

**Deferred from:** [optimizer-ux.md](optimizer-ux.md) §8, while diagnosing FU-11.

`api/models.py` parses `status`, `news` and `chance_of_playing_next_round`
(`models.py:21, 22, 26`) but not `chance_of_playing_this_round`, which the API
also publishes. `_availability` (`projections.py:59-66`) therefore has one
numeric availability signal where the API offers two.

The two differ in a way that matters mid-gameweek: `..._this_round` reflects the
gameweek in progress, `..._next_round` the one after. A player injured during a
gameweek has these disagree, and the model currently cannot see it.

**Not urgent, and not part of FU-11.** FU-11 is a formula defect — the
availability signal that *is* parsed reaches `p_start` correctly and is simply
absent from `p1`'s second term. Adding a second signal fixes nothing there, and
doing both at once would confuse a fix with an enhancement.

**Relevant when:** projections are computed for an in-progress gameweek, or the
horizon starts at the current event rather than the next one.
`fpl plan optimise` plans from the next open deadline
([optimizer-ux.md](optimizer-ux.md) §2), so it is unaffected as designed.

---

## FU-22 — `best_xi` has no vice-captain rule

**Deferred from:** `task/best-xi`.

`best_xi` (`domain/squad.py`) returns a `BestXI(starters, captain)` — no
vice-captain. `validate_plan` (`domain/squad.py:55-60`) requires one: it must
be one of the starters and must differ from the captain.

**Not needed yet** — nothing currently calls `best_xi` to produce a plan file.
It becomes load-bearing once `fpl plan optimise --output` (or whatever writes
a `SquadPlan`/ledger from optimiser output) exists: that round-trip needs a
complete, `validate_plan`-passing file, so the write path can't omit
`vice_captain`.

**Candidate fix:** second-highest-`xp_total` starter, by the same
`(-xp_total, player_id)` ordering `best_xi` already uses to pick the captain —
i.e. the next entry after `captain` in that ordering, restricted to starters.

**Unblocks:** the `optimise --output` → `simulate` round-trip
([optimizer-ux.md](optimizer-ux.md)).

---

## FU-23 — `BootstrapSnapshot`'s lookup properties rebuild their dicts on every access

**Deferred from:** [optimizer-search.md](optimizer-search.md) §2.

`players_by_id`, `clubs` and `positions` (`api/models.py:165-175`) are plain
`@property` methods that build a fresh dict on every call — 612 entries for
`players_by_id`, measured at **63 µs per access**. `apply_transfers` reaches
`players_by_id` twice per call (`transfers.py:242`, and again inside
`validate_squad_structure`), so a large fraction of its cost is rebuilding a
dict that never changes for the lifetime of a snapshot.

Measured: `apply_transfers` for a single transfer drops from **197 µs to 69 µs
(2.9×)** with `players_by_id` memoised. Every existing command benefits;
`fpl plan optimise` depends on it, since the search validates every node it
retains.

**Fix:** memoise. `BootstrapSnapshot` is a Pydantic model, so
`functools.cached_property` needs `model_config` to permit it — the simpler
route is to build the three mappings once in `from_payload` and store them as
private attributes. Either is fine; the property names must not change.

**Prerequisite for:** [optimizer-search.md](optimizer-search.md) §7's cost
budget. Separate concern from the optimiser — its own branch, before
`domain/optimizer.py`.

---

## FU-24 — `best_xi` materialises a sorted tuple per candidate formation

**Deferred from:** [optimizer-search.md](optimizer-search.md) §2, §6.2.

`best_xi` (`domain/squad.py:140-149`) builds a fully sorted 11-element starters
tuple inside the formation loop, once for each of the 8 legal formations, when
only the winner's tuple is ever used. The prefix sums it already computes are
enough to rank formations; the tuple is needed once, at the end.

Measured: `best_xi` + `objective_points` costs **136 µs**; the same computation
returning only the value costs **15.6 µs — 8.7×**. It is a refactor of existing
code rather than new work.

It is no longer the largest speedup in the optimiser design — **FU-26**, which
vectorises this function's hot half, is — but it is the one FU-26 depends on:
splitting value from witness is what creates a `xi_value` seam to vectorise, and
the property test below is what keeps the vectorised kernel tied to the rule
`validate_plan` uses. Land this first.

**Fix:** split value from witness, both in `domain/squad.py` so that manual
planning and the optimiser keep selecting an XI through one rule (CLAUDE.md):

- `xi_value(player_ids, projections, snapshot) -> float` — the hot path.
  Formation ranking from prefix sums plus the captain term; no tuples.
- `best_xi(...) -> BestXI` — unchanged signature, materialises starters,
  captain and (FU-22) vice-captain.

Both must share one formation enumeration, so the fast path cannot drift from
the XI `validate_plan` checks. Extract it as
`legal_formations(snapshot) -> list[tuple[int, ...]]`, computed once — the set is
a snapshot-level constant (8 combinations on the live snapshot) and two call
sites iterating the same `product(...)` would be two things to keep in step.
Guard with a property test asserting
`xi_value(...) == objective_points(best_xi(...), ...)` on random squads.

**Prerequisite for:** [optimizer-search.md](optimizer-search.md) §7's cost
budget, and for **FU-26**. Its own branch, before `domain/optimizer.py`.

---

## FU-25 — Two-pass self-consistent estimate of `ft_value`

**Deferred from:** [optimizer-search.md](optimizer-search.md) §6.1.

The terminal value of a free transfer banked at the horizon edge is
`ft_value` points, shipped as a constant defaulting to 1.5. That number is
**unsourced in this repo**: `docs/research/projections-survey.md` records
sertalpbilal's `decay_base = 0.84` but not an `ft_value`, so unlike the decay
factor it has no provenance here at all.

A run-time estimator taken from the *current* squad was measured and rejected:
the best free single transfer from `squad.json` gains **9.96 points** at the
root event, because the estimate tracks squad quality rather than the marginal
worth of a transfer. Using it would make the search hoard transfers.

**Candidate fix:** estimate it self-consistently instead. Search with
`ft_value = 0`; take the winning path's squad at the horizon edge; compute the
best free single-transfer gain at event H *from that squad*; re-run with it.
Costs 2× the runtime (≈24 s at [optimizer-search.md](optimizer-search.md) §7's
budget) and needs an argument that the second pass does not oscillate.

**Not urgent.** The `‡` marker (optimizer-ux.md §5.3) excludes the final
gameweek's move from the recommendation text regardless, and the output already
reports whether the recommendation changes at `ft_value ∈ {0, 2 × default}` —
so a wrong constant degrades visibly rather than silently.

---

## FU-26 — Vectorise `xi_value` and score a node's children as one batch

**Deferred from:** [optimizer-search.md](optimizer-search.md) §2, §6.2, §7.

**This is a prerequisite of the optimiser's cost budget, not an optimisation of
it.** [optimizer-search.md](optimizer-search.md) §5.3 fixes the enumeration cap at
**k ≤ 2 at every beam level**, not just the root, because
`hold · hold · (A→B, C→D)` — bank a free transfer, then spend two — is standard
FPL play and a search that cannot represent it has a blind spot nothing in its
output would reveal. That decision multiplies the branching factor per node by
~290 (559 → 162,792 children) and puts the run at ~10⁸ scored candidates. Pure
Python cannot pay for it.

Measured on the live snapshot, per scored child:

| | Cost | vs FU-24 |
|---|---:|---:|
| FU-24's `xi_value`, called per child | 15.6 µs | — |
| node-amortised incremental, pure Python | 4.44 µs | 3.5× |
| **vectorised with numpy** | **357 ns** | **44×** |

Per node-event, over the root's full 162,793-child k ≤ 2 expansion: **722 ms pure
Python, 58 ms vectorised — 12.4×**, both timed in one process on one machine. End
to end at horizon 5, `--beam 4`: **≈ 8 minutes against 39 s**.

**The mechanism.** Per `(node, event)`, sort each position's xP descending and
build prefix sums `B_p[k]`. For a child inserting incoming values into a position
after removing the outgoing, the new prefix sums follow from *the best k either
contains the new player or it does not*:

```
one incoming x:    S'[k] = max( B[k],  x + B[k-1] )
two incoming x,y:  S'[k] = max( B[k],  max(x,y) + B[k-1],  (x+y) + B[k-2] )
```

The child's value is `max over the 8 legal formations f of Σ_p S'_p[f_p]`, plus a
captain term of `max(others_max, incoming…)`. Every term broadcasts over the
candidate axis, so all ~140 candidates for one slot are scored by ~5 array
operations and a k = 2 out-pair becomes an `[m_a, 1] + [1, m_b]` outer sum
evaluated 8 times. Feasibility — joint budget, club limit, already-held,
same-position de-duplication — is a boolean mask over the same grid.

**Two constraints on the implementation, both load-bearing:**

- **The cached structure is valid only for the `(node, event)` pair it was built
  for.** The xP ranking within a position changes every gameweek. Build it inside
  the per-event expansion and never let it outlive one. This is the most dangerous
  bug available in this design.
- **Never materialise a level's children.** Reduce each out-combination's grid to
  its top-`w` immediately and release it. Accumulating them first is what
  exhausted a 12 GB machine during the measurement of
  [optimizer-search.md](optimizer-search.md) §7 — 32.6 M child tuples ≈ 13 GB at
  horizon 5, `--beam 4`. Both designs produce identical output and identical
  asymptotic runtime, so only a memory test distinguishes them; §8 specifies one.

**Adds numpy as a straight runtime dependency** — no optional extra, no
pure-Python fallback. A second implementation of the hot kernel would be a second
place for the objective to drift.

**Prerequisite:** FU-24, which creates the `xi_value` seam this vectorises and
whose property test keeps it honest. Its own branch, after FU-24 and before
`domain/optimizer.py`.

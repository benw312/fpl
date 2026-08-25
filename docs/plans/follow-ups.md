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
This was filed as a scoring inaccuracy affecting players already held. It is
worse than that: the optimiser ranks *every* player as a transfer target by
`xp_total`, so an unavailable cheap player scores positively and is affordable
in states where fit alternatives are not. Nothing else in the objective knows he
is out — `can_transact` gates transacting, not projecting. The search can
therefore recommend **buying** a visibly injured player, inverting the README
Agent Plan's "Penalize unavailable or risky players". The decision this entry
asks for must be made before `fpl plan optimise` ships.

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

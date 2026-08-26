# Follow-ups

Work deliberately deferred out of other tasks. Each entry records what, why it was
deferred, and what it unblocks.

Closed entries stay in place — the numbering is referenced from commit messages and
from the plans in this directory, so it must not shift. A closed entry carries a
**Status: closed** line naming the commit that closed it and what was checked in the
code, not just what the commit claimed. Its body is left as written, so where the
fix diverged from the entry the Status line says how.

**Last reconciled against `main`:** 2026-08-26 (`387ff0c`).

---

## FU-1 — Extract the stale-cache decision into a `SnapshotService`

**Status: closed** — `7642b44` *Extract SnapshotService, fix cache write on successful
fetch (FU-1, FU-2)* (2026-08-24). Verified: `api/snapshots.py` defines
`SnapshotService` and a frozen `SnapshotResult(snapshot, stale, reason)`;
`cli.load_snapshot` (`cli.py:50-63`) constructs the service, renders the staleness
warning itself and returns `result.snapshot`. `sync` (`cli.py:67-81`) goes through the
same service via `refresh()`, so the duplicated path under **Also fixes** is gone.

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

**Status: closed** — `7642b44` *Extract SnapshotService, fix cache write on successful
fetch (FU-1, FU-2)* (2026-08-24). Verified: `SnapshotService.load` calls
`self._cache.save(snapshot)` on the success path before returning
`SnapshotResult(stale=False)` (`api/snapshots.py`), so a bare `fpl players list`
populates the cache. `refresh()` saves too. The same shape was applied to fixtures
(`load_fixtures`/`refresh_fixtures`) when that endpoint landed.

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

**Status: closed** — `33cd761` *Give typer.Exit an exit code, not a message (FU-3,
FU-16); fix CLAUDE.md Structure (FU-19)* (2026-08-26). Closes **FU-16** with it.
Verified: no `typer.Exit` in `src/` receives a non-integer argument. All nine sites
print through the new `presentation.error_console` and then `raise typer.Exit(1)`,
the eight inside `except` blocks keeping their `from exc`.

**The channel is not `console`.** `error_console` is a separate `Console(stderr=True,
markup=False, highlight=False, style="red")`. stderr because that is where
`sys.exit(str)` already put these messages — sending them through the existing
stdout `console` would have been a silent regression, letting
`fpl squad validate x.json > out.txt` swallow the error. Markup off because every
message on this channel interpolates exception text, and an exception carrying
`['foo']` would otherwise be read as a Rich tag. This does not pre-empt **FU-12**;
it gives it one named channel to consolidate onto.

**What stops it coming back.** `tests/test_cli_exit_codes.py` asserts exit code 1 and
message-on-stderr-not-stdout across all nine paths, and adds an AST scan over `src/`
that fails on any `typer.Exit` given a non-integer first argument, reporting it by
`file:line`. Both the scan and a behaviour test were confirmed to fail against the old
idiom before being kept. The growth from three sites to nine happened one copied line
at a time with nothing to catch it; that is now caught at the moment of writing rather
than at the next audit.

**FU-16 was merged in here on 2026-08-26** — it was a re-filing of this same defect
with a higher count, and carrying a follow-up about a follow-up meant two entries to
keep in step for one fix. Its body is below, kept as the record of why the count
mattered.

`typer.Exit.__init__` is `(self, code: int = 0)`. Call sites pass a string instead. The
message reaches the user only by accident of `SystemExit` semantics — `sys.exit(str)`
prints to stderr and exits 1 — so the intended exit code is silently discarded and
every failure exits 1.

**The count is itself the finding.** Three at filing; eight when re-filed as FU-16
against [optimizer-ux.md](optimizer-ux.md) §8; **nine on `main` at 2026-08-26** —
`cli.py:56, 76, 159, 186, 196, 203, 209, 256, 263`. The idiom is being copied while the
entry sits open, and `plan-simulate.md:176-177` copied it knowingly. Re-check the count
when next touching this rather than trusting the line numbers above.

**Fix:** print to stderr explicitly, then `raise typer.Exit(1)`. Mechanical, and cheaper
the sooner it happens — every new command adds sites. `cli.py` already has the
correct idiom in place at nine other sites (`raise typer.Exit(1)` after a
`console.print`), so the two forms sit side by side in the same file.

**Blocks:** ~~`tests/test_stale_cache.py` can assert only the exception type, not the
message, until this is fixed.~~ Unblocked by the fix —
`tests/test_cli_exit_codes.py` now asserts both the code and the message text.

**Do with FU-12** if convenient — that entry routes all output through
`presentation.console`, and the stderr half of this fix is the same decision about
which channel a failure message goes to. Neither depends on the other.

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

**Status: closed** — `50ae917` *Add fpl plan simulate CLI command (FU-7)* (2026-08-25).
Verified: `@plan_app.command("simulate")` exists at `cli.py:178`, taking a squad path
and a transfers path, and renders through `presentation.simulation_table` /
`squad_state_table`. `Ledger.legacy` now has a reader — the command surfaces its
warning.

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

**Status: closed** — `0d4dc85` *Wire squad_min_play/squad_max_play into starting XI
validation (FU-8)* (2026-08-25). Verified: `validate_plan` (`domain/squad.py:52-56`)
counts starters by `element_type` and checks each count against that position's
`squad_min_play`/`squad_max_play`, reading both from the snapshot — nothing hardcoded.
A 1-GK/10-FWD XI no longer validates clean. This clears the blocker FU-9 was waiting
on.

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

~~Needs FU-8 first~~ — **FU-8 closed `0d4dc85`, so this is unblocked**
(an XI can't be offered before an illegal formation can be rejected; it now can be).
Still overlaps FU-6, which already notes that `starters`/`captain`/
`vice_captain` are logically per-gameweek but stored as one global value each.
Doing this properly probably means resolving FU-6's schema question at the same
time rather than bolting a global XI onto a gameweek-aware ledger.

---

## FU-10 — `fpl squad validate` silently misparses the ledger file `fpl squad create` writes

**Status: closed** — `0c6ea1c` *Implement FU-10: squad validate accepts both ledger and
plan formats* (2026-08-25). Verified: `validate_squad_file` (`domain/squad.py:68-85`)
implements all three shapes as specified — `"log" in payload` replays the ledger and
runs `validate_squad` on the resulting player IDs, `"players" in payload` keeps the
existing `SquadPlan` path, and anything else raises `ValueError` naming the path and
the two keys it looked for. No fall-through to an empty squad remains.

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

**Status: closed** — `a7b86d3` *Gate p1/xmins's substitute term by availability (FU-11)*
(2026-08-25). Verified: `projections.py:100-101` reads

```python
p1    = p_start + (1 - p_start) * config.p_sub_appearance * availability
xmins = p_start * e_mins_start + (1 - p_start) * config.p_sub_appearance * config.mins_per_sub * availability
```

— **both** lines gated, and `p60` untouched, exactly as the *Diagnosis, traced against
the live snapshot* section below specifies.

**Read the entry from that section down, not from the top.** The opening paragraphs are
the filing-time draft and are superseded twice over: their candidate fix gates `p1`
alone, which would have left `xmins` wrong, and their framing ("this may be intentional
… needs a decision, not a silent patch") was the open question, since answered. The
severity was also restated — the defect that justified fixing this is the
**convergence** one under *Corrected severity*, not the inversion an earlier draft of
optimizer-ux.md claimed. Both drafts are kept because the correction is the useful
record. FU-21 was deliberately **not** bundled into the fix and remains open.

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

## FU-16 — *merged into FU-3*

**Status: closed** — merged into **FU-3** on 2026-08-26 and closed with it the same
day by `33cd761`. See FU-3 for what was verified.

FU-16 re-filed FU-3 after the `typer.Exit(str)` count grew from three call sites to
eight, deliberately as a new entry so that the growth was visible rather than edited
away. That worked as a signal and has been folded into FU-3, which now carries the
count and its history. The number is kept here because the plans reference it; the
content is not duplicated.

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
**Status: open, narrowed** (2026-08-26, `33cd761`). The documentation half is settled:
`CLAUDE.md`'s Structure block now states the flat module *and* names the conflict with
the README Agent Plan, so the two no longer disagree silently. What remains is the
decision this entry was actually filed for — split into a package and update
`CLAUDE.md`, or amend the README's file list. Note the entry's line count is stale:
`presentation.py` is 200 lines now, still with seven renderers — the growth is the
`error_console` singleton added by FU-3, not another renderer.

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
**Status: closed** — `33cd761` *Give typer.Exit an exit code, not a message (FU-3,
FU-16); fix CLAUDE.md Structure (FU-19)* (2026-08-26). Verified against the tree:
`transport.py` is listed at top level where it actually lives, `domain/` now lists
`evaluation.py`, `projections.py` and `strength.py`, `builder.py` is listed, paths are
stated as relative to `src/fpl_cli/`, and *"Not yet written"* is down to
`domain/optimizer.py` alone.

**FU-18 is not closed by this.** The `presentation.py` entry regained the note that
the README Agent Plan specifies a `presentation/` package — restoring what the
`b522572` rewrite dropped — but that records the conflict rather than deciding it.
FU-18's remaining half is the decision itself.

**How the line got there matters.** `git log -- CLAUDE.md` shows two commits, and the
later one is `b522572` *Add interactive squad builder* — the commit that **added
`builder.py`** rewrote `Current state` into `Structure` and wrote *"Not yet written:
… interactive squad builder"* in the same diff. This was never accurate for a single
commit; it is not documentation that drifted, it is documentation that was wrong on
arrival, which is why no later commit would have caught it.

That same rewrite silently dropped the line *"Note: plan specifies a `presentation/`
package; currently a flat module"* — the exact conflict re-filed months later as
**FU-18**. Two of this file's entries trace to one careless section rewrite.

**Wider than filed.** The `Structure` block has drifted further since: `domain/` lists
`rules.py, squad.py, transfers.py` but the package also holds `evaluation.py`,
`projections.py` and `strength.py`; `api/` lists `transport.py`, which actually sits
at `src/fpl_cli/transport.py`. Fix all four in one pass, and settle FU-18 with them
since it is the same block.

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

**Status: closed** — `387ff0c` *Memoise BootstrapSnapshot's lookup mappings (FU-23)*
(2026-08-26). Verified: `players_by_id`, `clubs` and `positions` (`api/models.py:173-183`)
are `functools.cached_property`, not plain `@property` — the entry's second candidate
route (build in `from_payload`) was not the one taken, but the constraint that mattered
holds: the three property names are unchanged, so no call site moved. A comment at
`api/models.py:168-171` records that a mutating caller must `del` the memo.

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

**Status: closed** — `5afd728` *Split best_xi into xi_value and best_xi (FU-24)*
(2026-08-26). Verified: `xi_value` and `best_xi` both enumerate through
`legal_formations(snapshot)`, and `tests/test_xi_value.py` carries §8's property
test. The witness tuple is now built only for formations tied for the win — one in
the common case, against eight before — which preserves the documented tie-break
without putting a tuple on the hot path.

Two deviations from the entry, both deliberate. `legal_formations` returns a
**tuple**, not the `list` §6.2 named: the value is cached and shared between
callers, so it must not be mutable. And the per-squad feasibility guard moved into
the shared structure builder rather than staying textually inside `best_xi`, so
`xi_value` applies it too — a value half that silently scored an infeasible squad
would be worse than one that raised. §6.2's point that the check belongs to the
squad and not the formation set still holds; only its position in the file changed.

**The measured speedup is 1.64×, not 8.7× — resolved 2026-08-26 against the live
cached snapshot.** Both of the entry's figures were reproduced, and neither is wrong
on its own terms; they were measured under different conditions, and the ratio
between them never meant anything:

- **136 µs is a pre-FU-23 number.** Dropping the `players_by_id` memo before each
  call reproduces it at **136.9 µs**; with FU-23 in place the same call is
  **71.7 µs**. The missing 65 µs is the dict rebuild FU-23 removed, not `best_xi`'s
  own cost.
- **15.6 µs excludes the structure build.** Timing only the scoring step, with the
  per-position sorts and prefix sums hoisted out, gives **12.4 µs**; timing the whole
  function gives **43.8 µs**. `_xi_structure` is the 33 µs difference, and 75% of
  `xi_value`.

Like for like — whole call, FU-23 in place, live snapshot, real squad and real
projection table — FU-24 is **71.7 → 43.8 µs (1.64×)**, and `best_xi` itself
**71.7 → 54.5 µs (1.32×)**.

**Neither of the other two candidate explanations holds.** Squad composition: the
live squad and the synthetic fixture are both 2/5/5/3 and differ by 1.2% on identical
xP (43.8 vs 43.3 µs), so the synthetic fixture is a valid stand-in here.
Projection-table lookup: reading all 15 `xp_total` values costs **0.78 µs**, and
post-FU-23 `players_by_id` access costs **0.09 µs**. Neither is material.

[optimizer-search.md](optimizer-search.md) §6.2's table and §7.1's budget were both
corrected for this. **§7's runtime table was not affected** — it was measured end to
end against a numpy prototype rather than derived from any per-child figure — but its
pure-Python fallback was, and badly: see FU-26.

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

**Status: closed** — `8dc390b` (2026-08-26). `domain/squad.NodeScorer` scores a whole
`(node, event)` expansion as batched numpy; `numpy>=1.26,<3` is a straight runtime
dependency in `pyproject.toml`, no optional extra and no pure-Python fallback.
`XiStructure`/`xi_structure` were promoted from private as this entry anticipated,
so the kernel scores against the same ranking `best_xi` uses.

**Measured, replacing the projections** (live snapshot, real `squad.json` squad, real
projections, root k ≤ 2 expansion of 158,650 children; timing and memory in separate
passes because `tracemalloc` inflated a shared loop by 5.5×):

| | Projected | Measured |
|---|---:|---:|
| Per scored child | 357 ns | **105 ns** |
| Per node-event | 58 ms | **16.6 ms** |
| Speedup over the pure-Python reference | 12.4× | **362×** |

**The 105 ns is only meaningful with its grid size attached.** Per-out-combination
overhead dominates — 120 `score_children` calls at ~130 µs each — so the expansion
costs ~15 ms almost regardless of pool width, and per-child cost falls from 461 ns at
a pool of 20 to 38 ns at a pool of 90. Widening the pool improves the per-child
figure while making the run slower. [optimizer-search.md](optimizer-search.md) §7.1a
carries the sweep.

**§8's property test holds against the kernel.** `tests/test_node_scorer.py` asserts
`score_children(...)[i] == xi_value(child) == objective_points(best_xi(child))` for
k = 1, k = 2 cross-position and k = 2 same-position, over four xP distributions, to
1e-9. `xi_value` is the reference implementation, not a fallback: nothing in the
runtime chooses between them. Four mutations were confirmed to fail it before the
tests were kept — dropping the two-incoming term, dropping incoming players from the
captain term, removing the right-hand `-inf` pad, and an off-by-one in the prefix
index.

**What is still not measured, and why it matters.** §7.1's Runtime/Peak RSS/Best
score columns came from an uncommitted prototype and **remain unreproducible**. This
entry measures only the kernel's share. §7.1a re-derives a runtime *floor* per row
from measured throughput × structural expansion counts — 10.9 s at the default
horizon 5 `--beam 4`, 20.9 s at horizon 8 — but candidate generation, dominance
pruning, feasibility masking, `apply_transfers` and beam bucketing are all excluded.
**k ≤ 2 at every beam level and horizon 8 hold on the kernel, measured; whether they
hold for the whole search needs `domain/optimizer.py`.**

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

**The 44× above is against the wrong baseline (corrected 2026-08-26).** It divides
the numpy kernel's amortised 357 ns by the 15.6 µs row, which was timed with the
structure build hoisted out and is not amortised. The like-for-like comparison is
against the node-amortised pure-Python figure, 4.44 µs — **12.4×**, which is what
§7 already uses and what the table's own last two rows say. Read 12.4×, not 44×.

**This entry is now more load-bearing, not less.** §7's runtime table was measured
end to end against a numpy prototype, so it stands as written — but its pure-Python
fallback does not. The "≈ 8 min at horizon 5" it quoted is the 4.44 µs
node-amortised variant, which **does not exist in the repo**; the only pure-Python
scorer that does is `xi_value` as landed, non-amortised at 43.8 µs, which puts the
default horizon-5 `--beam 4` run at **~1.7 hours** rather than 8 minutes. The gap
this entry closes on that row is ~157×, not 12.4×. **k ≤ 2 at every beam level and
horizon 8 hold only if this lands.**

**Prerequisite:** ~~FU-24~~ — **closed `5afd728`**, so this is unblocked. The
`xi_value` seam and §8's property test both exist; `domain/squad._XiStructure` holds
the per-position prefix sums to vectorise, and is private pending this entry
promoting it. Its own branch, before `domain/optimizer.py`.

**Re-record §7's measured column as part of this work.** Those figures were taken
against a prototype of `domain/optimizer.py` and this kernel, neither of which is in
the repo, so nothing in it can confirm them today.

---

## FU-27 — `xi_value` builds the witness half of its structure and then discards it

**Deferred from:** FU-24's re-measurement (2026-08-26, `task/optimizer-cost-budget`).

`_xi_structure` (`domain/squad.py`) builds one structure serving both halves of the
FU-24 split, so `xi_value` pays for two things it never reads: the per-position
`ranked` tuples, which only the witness materialises from, and the frozen
`_XiStructure` dataclass wrapping seven fields. It also calls `legal_formations`
(2.3 µs, mostly the `spec` tuple build and cache-key hash) and resolves every
`xp_total` through a closure over the Pydantic model on each of ~34 accesses.

Measured on the live snapshot: `xi_value` is **43.8 µs**, of which `_xi_structure`
is **33 µs**. A variant hoisting `xp_total` into a plain dict once, taking the
formation list as a parameter, and skipping the witness-only tuples ran at
**24.9 µs** — a **1.76×** saving, verified to return the identical value.

**Not done with FU-24**, which was scoped to the split itself; this is an
optimisation of one side of it and wants its own before/after.

**Superseded in practice by FU-26 (`8dc390b`), but not closed.** `NodeScorer` amortises
the structure build across a node's children, so `xi_value` is no longer on any hot
path — it is the reference implementation `tests/test_node_scorer.py` checks the
kernel against, called once per child in tests and never in a search. At that duty
cycle a 1.76× saving buys nothing, and the witness-only fields this would strip are
what make `xi_value` readable as the definition of the objective.

**Recommend closing as won't-do** unless a pure-Python scoring path reappears. Left
open only because that is a judgement call rather than a fact.

The property test in `tests/test_xi_value.py` is what makes it safe to try: any
divergence between a faster `xi_value` and `best_xi` fails there.

---

## FU-28 — Dominance pruning is not exact for a same-bucket k = 2 double-pick

**Deferred from:** §8's dominance property test (`tests/test_optimizer.py`,
2026-08-26, `task/optimizer`).

optimizer-search.md §5.2 claims exact `(position, club)` dominance: a dominated
player can always be swapped for its dominator at no cost in legality or value. The
property test's random search found a counterexample — recorded in full, with the
concrete numbers, in optimizer-search.md §5.2's "Correction" — where a bucket has
`id6` dominating `id8` at equal cost, and the true best *same-club* two-defender pick
at a given budget is `id6 + id8`. Since `id8` is stripped from the pool before the
search runs, and `_mask_k2` allows both in-slots of a same-position k = 2 move to
land in the same club, the search can only reach `id6` + the next survivor, a 4.8
point loss on that seed with no floor under how much larger the gap could be on a
different bucket.

The argument in §5.2 ("interchangeable under every constraint") only proves 1-for-1
substitution; it was never checked against a squad wanting two players from one
bucket simultaneously, which is exactly the same-position, same-club shape
`_mask_k2`'s `i < j` dedup was built to support.

**Options, none implemented:**
- Restrict `_mask_k2` so a same-position k = 2 pair can never share a club — cheap,
  restores exactness, but silently drops a real move shape (stacking one club's
  defence for a fixture swing) instead of reporting it per §5.3's own standard for
  unenumerated shapes.
- Widen the pool per bucket to the top `m` Pareto layers, `m = min(squad_team_limit,
  position.squad_select)` — exact for every k ≤ 2 shape, bounded pool growth (`m` is
  2–3 on the live snapshot), more construction than a one-line fix.
- Leave the pruning as is, but name the gap in the output the way `k_rules >
  k_enum` is named in §5.3, rather than continuing to claim an exactness the
  algorithm does not have.

**Unblocks:** nothing currently blocks on this — `tests/test_optimizer.py`'s
dominance test is scoped to k = 1 (provably exact) and documents the k = 2 gap in its
own docstring rather than asserting a property that doesn't hold.


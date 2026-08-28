# Follow-ups

Work deliberately deferred out of other tasks. Each entry records what, why it was
deferred, and what it unblocks.

Closed entries stay in place — the numbering is referenced from commit messages and
from the plans in this directory, so it must not shift. A closed entry carries a
**Status: closed** line naming the commit that closed it and what was checked in the
code, not just what the commit claimed. Its body is left as written, so where the
fix diverged from the entry the Status line says how.

**Last reconciled against `main`:** 2026-08-27 (`76809ae`). FU-28 is marked closed
against `task/fu-28-dominance`, which is not on `main` yet; its Status line says so.

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

**Status: closed** — `e69bb3d` *Make dominance pruning exact: exclude only at m usable
dominators (FU-28)* and `b9706c6` *Raise the --max-cells default from 400M to 800M
(FU-28)* (2026-08-27, `task/fu-28-dominance`). Verified in the code, not taken from
the commit message: `_dominance_pool` (`optimizer.py`) collects dominators into a list
and excludes only at `len(dominators) >= max_from_bucket`, with
`max_from_bucket = min(limit, position.squad_select)` derived per bucket; the inner
loop skips `not _validator_usable(other)`, and `_validator_usable` is
`can_select and not removed`. Pool admission is still `can_transact and not removed`,
unchanged. `DEFAULT_MAX_CELLS` is `800_000_000`. The `dominance_unsound` parameter is
gone from `presentation.optimise_header` and the `dominance_pruning_unsound` key from
`cli.py`'s `--json` payload; `tests/test_cli_optimise.py` asserts the absence of both.
Three end-to-end regressions in `tests/test_optimizer.py`
(`..._never_excludes_against_a_held_dominator`, `..._survives_a_same_bucket_double_buy`,
`..._counts_only_dominators_the_validator_would_accept`), each demonstrated failing on
`76809ae` first, plus a property test raised from a single pick to a joint pick of up
to `m`. **Diverged from the entry below in two ways**, both recorded there: the defect
was not limited to k = 2, and the "restrict `_mask_k2`" option does not restore
exactness. Designed in `docs/plans/fu-28-dominance.md`; landed behaviour documented in
optimizer-search.md §5.2, §6.3 and §7.1g. **Not yet on `main`** at the time of writing.

**Deferred from:** §8's dominance property test (`tests/test_optimizer.py`,
2026-08-26, `task/optimizer`).

**The fix: exclude a player only once `m = min(squad_team_limit,
position.squad_select)` *selectable* dominators exist**, rather than on the first
dominator found. `m` is the most a legal squad can hold from one `(position, club)`
bucket at once, so an optimum containing an excluded player always leaves one
dominator free to substitute. Exact for every k, so FU-29's `--schedule` at k = 3
inherits it. Measured on the live snapshot at GW2: pool 189 → 374, exclusions 425 →
240, **best score unchanged at 70.066**, runtime 62.3 s → 90.8 s.

**Two things the entry below got wrong, both corrected before closing:**

1. **The title's "k = 2" is too narrow.** The same defect fires on a *single*
   transfer, when the excluded player's dominator is already in the squad —
   `_candidates_for` filters the dominator out as unbuyable while dominance has
   already removed the dominated player. It fired 14 times on the live snapshot.
2. **"Restrict `_mask_k2`" does not restore exactness.** It was recorded as "cheap,
   restores exactness". Measured, it does neither useful thing: it cannot reach the
   k = 1 shape, and on the k = 2 counterexample it makes the answer *worse*.

**Scope deliberately left alone:** pool *admission* still runs on `can_transact and
not removed`, so FU-35 is untouched and still open. Only the *dominance* predicate
gained `can_select` — the exchange argument needs a substitute the validator will
accept, and counting one it would reject reproduces the same defect one level up. The
two predicates now differ inside `_dominance_pool` on purpose, with a comment saying
so; do not reconcile them except through FU-35.

The original entry follows, for the record.

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
- ~~Restrict `_mask_k2` so a same-position k = 2 pair can never share a club — cheap,
  restores exactness~~ — **it does not restore exactness; measured, see
  `fu-28-dominance.md` §3.1.** It cannot touch the k = 1 shape below, and on the k = 2
  counterexample it makes the answer *worse* (gap 1.0 → 6.0), because removing a move
  shape does not recover the value the pruning discarded. Also
  silently drops a real move shape (stacking one club's
  defence for a fixture swing) instead of reporting it per §5.3's own standard for
  unenumerated shapes.
- Widen the pool per bucket to the top `m` Pareto layers, `m = min(squad_team_limit,
  position.squad_select)` — exact for every k ≤ 2 shape, bounded pool growth (`m` is
  2–3 on the live snapshot), more construction than a one-line fix.
- Leave the pruning as is, but name the gap in the output the way `k_rules >
  k_enum` is named in §5.3, rather than continuing to claim an exactness the
  algorithm does not have.

**A fourth option, found while measuring the three above, and the one implemented:**
exclude a player only once **`m` distinct players dominate them**, rather than on the
first dominator found. Exact for every k by the same exchange argument as the
Pareto-layer option, prunes strictly harder (374 vs 408 survivors on the live snapshot
once the selectability qualifier is applied), 8 s cheaper, and a smaller diff.
`fu-28-dominance.md` §3.4 and §4.

**~~Unblocks:~~ nothing currently blocks on this — `tests/test_optimizer.py`'s
dominance test is scoped to k = 1 (provably exact)** — **also wrong.** k = 1 is exact
only in the bucket-in-isolation setting that test constructs, where the squad holds
nothing. In the search, an excluded player whose dominator is **already held** is
unreachable on a *single* transfer: `_dominance_pool` never consults the node's
holdings, and `_candidates_for` then filters the dominator out as already held. That
shape is reproduced in `fu-28-dominance.md` §2.2 and fires 14 times on the live
snapshot at GW2. The property test documented the k = 2 gap in its own docstring but
asserted a k = 1 property that does not hold in the search; it now asserts exactness
for a joint pick of up to `m`, which is the property that does.

---

## FU-29 — `--schedule` (optimizer-search.md §5.7) is not implemented

**Deferred from:** `task/optimise-cli`, while wiring `fpl plan optimise`.

`optimizer-search.md` §5.7 specifies `--schedule` — a per-gameweek transfer count
fixed by the user (e.g. `--schedule 0,0,3`), searched by complete enumeration over
players at each scheduled count rather than the free `k_enum = 2` beam search.
`domain/optimizer.py`'s own module docstring already scopes it out: *"`--schedule`
(§5.7), `--max-transfers-per-gw 3` at the root (§5.4) and the decision-margin
threshold (§6.4) are out of scope for this branch."* `optimizer-ux.md` §2's CLI
command surface doesn't list it at all — it belongs to the search plan, not the UX
plan `fpl plan optimise` was built against.

**Not a CLI-wiring task.** It needs real search-algorithm work: `NodeScorer.
score_children` hard-raises above 2 incoming players per position, so a scheduled
count of 3 needs new masking and scoring, not just a new flag; the schedule also
fixes the horizon (`--schedule 0,0,3` implies `--horizon 3`) and moves the DP-prune
bucket key to the first gameweek with a non-zero scheduled count (§5.7's own text).

**Worth doing.** §5.7 measured `--schedule 0,0,3,0,0` at **3.2 s** against an
estimated ~35 minutes for the equivalent shape under the free k ≤ 2 search — it is
the only way to plan "bank two transfers, then take a hit for a specific fixture
swing," which free k ≤ 2 cannot represent at all past k = 2. It is the feature that
makes that standard piece of FPL play plannable, not a nice-to-have.

**Rejected for this branch:** a stub flag that only raises "not implemented" was
considered and declined — it would advertise a capability in `--help` that doesn't
exist, and stub flags tend to outlive the reason they were added.

---

## FU-30 — `plan simulate` hardcodes `ComponentProjection`, so the `optimise --output` round-trip only verifies points under `--model component`

**Deferred from:** `task/optimise-cli`, while verifying the `optimise --output` →
`simulate` round-trip live.

`simulate_plan` (`cli.py:244`) builds `model = ComponentProjection(...)` unconditionally
— there is no way to tell it which model to project with. `fpl plan optimise` (this
branch) takes `--model component | naive | official-ep`. Run it with anything but the
default and pipe `--output` into `plan simulate`: the transfers apply and the squad
structure round-trips (legality is checked inside `apply_transfers`, which doesn't
touch projections at all), but the printed Points column is `ComponentProjection`'s
number for a plan that was scored and ranked under a different model. Confirmed live:
a `--model naive` plan showing 44.0 projected GW points reads back through `simulate`
as 0.0, because every synthetic player in that check had zero component inputs.

**This silently breaks the guarantee `optimizer-ux.md` §1 and CLAUDE.md state.** §1:
*"The two commands must print identical per-gameweek numbers for the same path; if
they diverge, one of them is wrong, and the divergence is the test."* That test is
only meaningful if both sides used the same model — under any other `--model`, a
divergence means nothing (of course they differ, they scored different things), so
the check silently stops testing what it claims to. §8.5 named this as the mechanism
that satisfies CLAUDE.md's *"Every optimiser recommendation must pass the same
validator used for manual squad planning"* — that guarantee is aspirational for any
`optimise` run that isn't `--model component` (the default, so easy to miss).

**Fix: give `plan simulate` a `--model` flag, default `component`.** Not: record the
producing model in the transfers-plan file. Reasons, in order of weight:

1. **The plan file schema is a bare list**, precisely (`optimizer-ux.md` §8.6:
   `[{"event": 4, "transfers": [...]}, ...]`), already documented, already the
   round-trip contract `parse_transfers_plan`/`write_transfers_plan` and their tests
   assert against. Adding a "which model" field means wrapping the list in an object —
   a breaking schema change to a format that's meant to be hand-authored too, for a
   field a hand-written plan has no honest value to put there.
2. **A model tag on the file goes stale.** Nothing re-checks it if the file is hand-
   edited after generation, or if the same plan is re-scored to compare models — which
   is a real, useful thing to do with `simulate` (see next point) and is exactly what a
   baked-in tag would prevent.
3. **`--model` matches `optimise`'s own surface** and lets `simulate` do something a
   file-embedded tag can't: show one plan's points under a *different* model than
   produced it, on request. That's a legitimate diagnostic (comparing a plan's real
   payoff across models is what `--robustness` already reasons about internally, §6).
4. Independence of the round-trip check doesn't depend on which option is chosen —
   `simulate` recomputes `best_xi`/`objective_points` from scratch either way; the
   check verifies that code path against the search's own, not that the model choice
   was rediscovered.

**Not fixed here.** `optimise --output` already round-trips correctly for the default
model, which is what today's tests (`tests/test_transfers.py`,
`tests/test_cli_optimise.py`) cover; a separate branch for `plan simulate` is one
concern, this one was CLI wiring for `optimise`.

**Unblocks:** the `optimise --output` → `simulate` round-trip actually testing what
`optimizer-ux.md` §1 and CLAUDE.md claim it tests, for any `--model` choice.

---

## FU-31 — `fpl plan optimise` doesn't expose `--beam`, `--first-moves` or `--max-cells`

**Deferred from:** `task/beam-width`, while re-measuring optimizer-search.md §5.5 and
§7.1 against the live snapshot.

`domain.optimizer.optimise()` takes `beam`, `first_moves` and `max_cells` keyword
arguments (`optimizer.py:785-787`, defaults `DEFAULT_BEAM = 4`, `DEFAULT_FIRST_MOVES
= 50`, `DEFAULT_MAX_CELLS = 400_000_000`), but `optimise_plan` (`cli.py:454-465`)
does not thread any of them through — there is no way to run `fpl plan optimise` at a
non-default beam width, or to raise the cost ceiling, from the command line at all.

**Found while measuring, not while building.** optimizer-search.md §5.5 documents
`--beam 2, 4, 8` as if it were a CLI flag; it never was one. Re-measuring §5.5 and
§7.1's Runtime/Peak RSS columns against the live snapshot for real (rather than
against the never-committed prototype) required calling `domain.optimizer.optimise()`
directly, with the CLI's own setup copied by hand into a benchmark script, because
there was no flag to reach `--beam 8` or `16`, or to get past the default
`--max-cells` guard, any other way.

**Worth doing independently of the measurement.** Anyone who hits the
`SearchTooExpensive` refusal §7.3 designed — "Reduce `--horizon`, `--beam` or
`--first-moves`, or raise `--max-cells`" — cannot act on that message today; the
flags it names don't exist on the command they're printed from. That is a
correctness gap in the UX, not just a benchmarking inconvenience.

**Not fixed here.** This is a CLI-wiring task once someone picks the flag names and
defaults-display convention the rest of `optimise_plan`'s options use; it does not
touch the search itself. One concern, deferred rather than folded into a measurement
branch.

**Unblocks:** a user (or a future re-measurement) reproducing §5.5's and §7.1c's
tables through `fpl plan optimise` itself, and reacting to a `SearchTooExpensive`
refusal without editing source.

---

## FU-32 — `_materialize` computes `best_xi` for every candidate; it is read ~15 times

**Status: closed** — `c4a2f5b` (2026-08-27). `_materialize` (`optimizer.py`) no
longer calls `best_xi`; every `Node` it builds carries `xi=None`, and `cli.py`'s
`_path_row` — `node.xi`'s one reader — reproduces the XI at display time from
`node.state.player_ids` and the event's projection table, per the `Node` docstring.
Verified exact: `fpl plan optimise squad.json` run before/after in plain, `--explain`
and `--json` form — `--json` byte-identical, the other two differing only in the
cache-mtime-derived fetched-at header — plus `pytest -q` (231 passed). Measured
**71.9 s against the pre-change 92.5 s baseline (§7.1c)**, a 20.6 s saving against
§7.1d's ~19 s prediction; full re-measurement in optimizer-search.md §7.1e.

**Deferred from:** `task/perf-findings`, profiling the non-scoring path after §7.1c
found scoring to be only 13.8% of the default run.

`_materialize` (`optimizer.py:449`) calls `best_xi` for every child it builds. On the
default configuration (horizon 5, `--beam 4`, root GW2) that is **318,619 calls
costing ~19 s — 20.6% of the 92.5 s run**, measured at 65.7 µs each (§7.1d).

**`node.xi` has exactly one reader in the repository:** `cli.py:423`, inside
`_path_row`, at display time. It is read for the nodes on displayed paths only —
roughly 15 of them (`--paths 3` × horizon 5), plus the hold row. Everything else the
search does reads `state`, `score`, `net`, `hit_points`, `total_transfers` and
`path_ids`; `_beats`, `_dp_prune`, `sort_key` and `NodeScorer` never touch `xi`.

**The design already licenses this.** `Node`'s own docstring: *"`xi`/`captain` are a
cache of a deterministic argmax (§6.2), reproducible from `state.player_ids` and the
projection table — never a source of truth."* Populating that cache eagerly for
318,619 candidates to serve ~15 reads is the defect; the docstring describes the fix.

**Exact — no output changes.** `best_xi` is a deterministic argmax over
`state.player_ids` and the event's projections, both of which survive on the Node.
Computing it lazily at display time, or eagerly for survivors only, produces
identical values. No approximation, no ordering change, no effect on which path wins.

**Not fixed here.** This branch filed findings; implementation is a separate concern.
Independent of FU-33 and FU-34 — it can land on its own.

**Unblocks:** ~19 s (20.6%) off the default run for no behavioural change. See
optimizer-search.md §7.1d for the phase table this came from.

---

## FU-33 — `_mask_k2` builds a 3-D club tensor 20× the size of the mask it produces

**Status: closed** — `e14fa42` (2026-08-27). `_mask_k2` (`optimizer.py`) no longer
builds the `(len_a, len_b, n_clubs)` tensor; `free_a`/`free_b` (two 1-D slots-free
vectors) plus one equality outer product (`club_a[:, None] == club_b[None, :]`) decide
the same predicate this entry specifies below. `_mask_k1` was left as filed — it was
already O(a), not a tensor, so the "same treatment" note below did not apply. Verified
exact: a dedicated test (`tests/test_optimizer.py::test_mask_k2_club_check_matches_tensor_reference_*`)
keeps the old tensor code as the reference and checks equality across an explicit
slots-free-boundary case (0/1/2/3 free) and 200 randomised trials; a deliberate `>= 1` →
`>= 0` mutation was confirmed to fail both. Also verified end-to-end: `fpl plan optimise`
run before/after in plain, `--explain` and `--json` form — `--json` byte-identical, the
other two differing only in the cache-mtime header — plus `pytest -q` (233 passed).
Measured **63.1 s with FU-32 also landed, against 71.9 s with FU-32 alone** — an ~8.8 s
saving, short of this entry's ~14 s estimate; full re-measurement and the gap's
discussion in optimizer-search.md §7.1e.

**Deferred from:** `task/perf-findings`, same profile as FU-32.

`_mask_k2` (`optimizer.py:321-327`) enforces the club limit by materialising

```
totals = base[None, None, :] + add_a[:, None, :] + add_b[None, :, :]
club_ok = (totals <= limit).all(axis=2)
```

— an `(len_a, len_b, n_clubs)` int8 tensor, then reducing it along the club axis. At
the measured pool (189 survivors; 41/49/57/42 per position) a representative
out-combination has slots of 48 and 48 against 20 clubs: **46,080 int8 cells built to
produce a 2,304-cell boolean mask, a 20× blow-up.**

Measured on the default configuration: `_mask_k2` is **18.0% of runtime (~16.7 s)**,
of which the club tensor is **83% — ~15% of the whole run, ~14 s** (the affordability
half is 24.0 µs against the tensor's 181.7 µs). At **262 µs per call the mask costs
more than the `NodeScorer.score_children` call it masks (175 µs)**, which is the
clearest single sign that the non-scoring path, not the kernel, is where the run went.

**It reduces to O(a + b + a·b) with no tensor.** `squad_team_limit` is 3 and at most
two players come in, so a pair `(x, y)` is club-infeasible iff:

- `count[club(x)] + 1 > limit`, or
- `count[club(y)] + 1 > limit`, or
- `club(x) == club(y)` and `count[club(x)] + 2 > limit`.

That is two 1-D boolean vectors over the candidate lists plus one equality outer
product — no club axis, no 3-D array, no `.all()` reduction. **Exact**, not an
approximation: it is the same predicate, evaluated without enumerating clubs that
cannot be violated (most clubs sit at 0–1 against a limit of 3 and can never break
by adding ≤ 2).

**Check `_mask_k1` at the same time.** It is only 0.4% of runtime so it is not worth a
branch of its own, but it builds `club_ok` by the same per-candidate list
comprehension and should get the same treatment while the file is open.

**Not fixed here.** Findings-only branch. Independent of FU-32 and FU-34.

**Unblocks:** ~14 s (15%) off the default run for no behavioural change.

---

## FU-34 — `_expand_node` materialises 390 candidates for every 1 that survives

**Status: decided, not implemented** — resolved 2026-08-27 on `task/fu-34-resolution`;
full evidence in optimizer-search.md §7.1f. **The restructure is approved, and the
second reading below is the correct one** — but see the priority note at the end of
this entry, which puts FU-28 ahead of it.

The `[gap]` this entry left open is closed by measurement, not by argument:

- **The dominance test needs three things the generator does not already hold**, and
  none of them is state arithmetic it does not already do. `bank` after the buy is the
  masks' own `bank_after − cost` — the value they compute and discard as a boolean.
  Post-move `free_transfers` is `max(0, free_available − k)`, constant per
  out-combination, extending a block already headed *"mirroring `transfers.py`'s
  `_fold_event`"*. The holdings key is a set operation. `score`, `total_transfers` and
  `path_ids` are already derived without `apply_transfers` today. **0 mismatches in
  318,568 accepted children** on all five derived quantities, and 0 in 122,580 more at
  horizon 3 with hits actually charged (k ∈ {0,1,2}, hit ∈ {0,4}, five distinct
  free-transfer transitions).
- **It relocates an existing check rather than adding duplication.** Affordability and
  the club limit are expressed twice today, in the masks and again in
  `validate_squad_structure` / the `bank < 0` check, and both expressions run on all
  318,903 candidates. After the change the same two expressions sit in the same two
  places; only the execution count falls, by 390×.
- **The CLAUDE.md guarantee holds literally.** Recommendations are nodes on returned
  paths, every one a materialised survivor, and every survivor still passes
  `apply_transfers` → `validate_squad_structure`.
- **The validator's *other*, unstated role — filtering candidates before they can
  influence pruning — is replaceable exactly.** All 335 rejections per default run have
  one cause: `"<player> is not selectable"`, from four pool members that are
  `can_transact=True, removed=False, can_select=False` (FU-35). Every other error path
  in `apply_transfers` is either structurally impossible for a candidate that passed
  `_candidates_for` and the masks, or candidate-*independent* (deadline,
  `transfers_cap` — one check per level).

**Implementation shape, when it is done.** `_expand_node` returns tuples; `_expand_level`
dp-prunes, sorts, slices to `beam`, materialises only those. Apply selectability to the
**retained tuples, after the per-combination top-k — not inside the mask**: masking those
four players out would free the top-k slots they currently occupy and waste, changing
which candidates reach `_dp_prune`. Filtering after top-k reproduces today's candidate
set exactly, which is what makes the change byte-exact rather than merely equivalent in
spirit. Keep `_materialize`'s `return None` as a backstop, backfill from the next-ranked
survivor if it fires, and make it loud in tests.

**Re-measured cost, on current code** (§7.1d's phase table predates FU-32 and §7.1e
recorded its FU-33 attribution missing by ~5 s): `_materialize` from `_expand_node` is
**29.6 s of 65.1 s instrumented — 45.5%**. On 816 survivors that becomes ~0.08 s, against
~0.5 s of replacement per-candidate work. **Net ~29 s: 63.1 s → ~34 s**, band mid-30s to
low-40s.

**The top-N approximation recorded below as a fallback is rejected, not deferred** — the
exact route is measured and costs nothing extra. (`_dp_prune` removes only 9.4% of
children, 288,775 of 318,568, so the approximation's margin would in fact be generous;
there is simply no reason to take it.)

**Priority: FU-28 first.** This entry buys ~29 s on a run that already completes. FU-28
is *unsound pruning*: a dominated player is stripped from the pool before the search
starts, and §5.2's recorded counterexample shows the true optimum can need it — a 4.8
point loss on that seed, **with no floor established under how much larger the gap could
be on a different bucket**. An accuracy defect with unbounded error outranks a
performance defect with a measured 29 s ceiling. The 120 s cap in optimizer-search.md
§7.1c/d is a budget this project set for itself, not an external requirement, and horizon
8 fitting inside it is not a reason to reorder these.

**Deferred from:** `task/perf-findings`, same profile as FU-32. **This is the largest
single finding and the only one of the three that needs a design decision.**

`_expand_node` retains `local_retain=beam` candidates *per out-combination* and
materialises all of them (`optimizer.py:636-644`); `_expand_level` then dp-prunes the
lot and keeps `beam` **in total** (`optimizer.py:700-702`). With ~120 out-combinations
per node that is ~480 materialisations per node expansion to retain 4.

Measured on the default configuration (horizon 5, `--beam 4`, root GW2):

| | Measured |
|---|---:|
| Children materialised | **318,568** |
| Children surviving `_dp_prune` + `[:beam]` | **816** |
| Discard ratio | **390 : 1** |
| `_materialize` share of runtime | **53.0% (~49 s of 92.5 s)** |
| — `apply_transfers` | 26.8% (~25 s), 85.7 µs × 318,954 |
| — `best_xi` (FU-32) | 20.6% (~19 s), 65.7 µs × 318,619 |
| Candidates rejected by `apply_transfers` | 335 (**0.105%**) |

**This is the term that scales with `--beam`**, which is what §7.1c observed from the
outside without being able to name. Holding horizon at 3 and varying width: at
`--beam 1` `_materialize` is 25.8% of runtime, at `--beam 4` it is 53.0% — while
`_mask_k2` *falls* from 30.7% to 18.1% and the kernel from 23.6% to 13.8%, because
those track node count and only `_materialize` tracks width.

**`_expand_root` already does it the right way.** It accumulates cheap
`(ranking_score, out_ids, in_ids, root_event_delta)` tuples across every
out-combination (`optimizer.py:531-534`), sorts globally, selects `first_moves`, and
**only then** materialises (`optimizer.py:552-568`). That is why the widest
enumeration in the whole search costs **0.2% of runtime**. `_expand_node` performs the
same computation in the opposite order. The fix is to apply the pattern already in the
file, not to invent one.

**The open question, which is why this is filed rather than fixed.** Deferring
materialisation means `_dp_prune` needs `bank`, `free_transfers` and the holdings set
for candidates that have not been through `apply_transfers`. Two readings, and the
choice belongs to whoever owns the design:

- **It adds duplication.** Deriving bank/free-transfers/holdings outside
  `apply_transfers` puts squad-state arithmetic in a second place. optimizer-search.md
  §5.3 is explicit that *"the generator does arithmetic; `apply_transfers` is the
  authority"*, and §6.2 records that a second expression of the objective is exactly
  the drift risk the design works to avoid. The same argument applies to state.
- **It only moves where the single authoritative check happens.** `_mask_k1`/`_mask_k2`
  already enforce affordability and the club limit *before* scoring — that is their
  entire purpose — and `apply_transfers` then spends roughly half its time in
  `validate_squad_structure` re-checking those same two constraints per candidate
  (cProfile: 27.3 s of `apply_transfers`'s 57.0 s cumulative at horizon 3, `--beam 4`).
  The measured rejection rate is **0.105%**, i.e. the mask is already almost exactly
  right. On this reading the authoritative check does not disappear, it runs on the 816
  survivors instead of the 318,568 candidates — and CLAUDE.md's requirement is that
  *every optimiser recommendation* pass the same validator, which survivors do.

`[gap: not resolved by this measurement. It needs a decision on whether
`apply_transfers` is the authority on *candidate generation* or on *recommendations*.
The profile can say what it costs; it cannot say what the contract should be.]`

**A cheaper partial variant exists and is also not free.** Materialising the top
`N = beam × small factor` by score before pruning would cut most of the cost without
touching the state-arithmetic boundary — but it is an **approximation**: a node
outside the top N by score can still enter the final beam if enough higher-scored
nodes are removed as dominated. Small risk at a generous margin, but it changes the
answer in principle, where the two readings above do not. Record it as a fallback,
not as the default plan.

**Not fixed here.** Findings-only branch, and this one should not be implemented
before the question above is answered.

**Unblocks:** the largest share of the default run — ~49 s, of which FU-32 already
claims ~19 s independently. With FU-32 and FU-33 landed and this one restructured,
optimizer-search.md §7.1d projects the default run at **~35 s against today's 92.5 s**,
and horizon 8 at `--beam 4` back inside the 120 s budget.

---

## FU-35 — `_dominance_pool` and `validate_squad_structure` disagree on which players are usable

**Deferred from:** `task/fu-34-resolution` (optimizer-search.md §7.1f), where it turned
up as the cause of every rejection FU-34 measured.

`_dominance_pool` (`optimizer.py:184`) admits a player on `can_transact and not
removed`. `validate_squad_structure` (`rules.py:57`) rejects a squad containing one that
is `not can_select or removed`. `can_select` is not checked anywhere between the two, so
a player with `can_transact=True, can_select=False, removed=False` enters the pool, is
enumerated, masked, scored and materialised at every node of the search — and is then
thrown away by the validator, along with the retained top-k slot it occupied.

Measured on the live snapshot (default config, horizon 5, `--beam 4`, root GW2): **four
such players in the 189-member pool** — 197 Bassette, 225 Uche, 298 Destan, 530
Patterson, all `status='u'` — accounting for **all 335 of the run's `apply_transfers`
rejections** (75/75 at horizon 3). Snapshot-wide, 42 of 614 players carry the same
flag combination.

**The second-order effect is the one that matters.** Those four are not merely wasted
work: they compete in `_dominance_pool` and can exclude *usable* players from the pool
entirely. On this snapshot exactly one player is excluded by an unselectable dominator
(299 Burstow, dominated by 298 Destan) and Burstow is himself unselectable, so nothing
legitimate is lost **today** — but nothing prevents it. A cheap, unusable player is
exactly the shape that dominates on cost.

**Not a free fix, and deliberately not bundled into FU-34.** Filtering the pool on
`can_select` takes it from 189 to 185 and frees the top-k slots those four currently
consume, so more legitimate candidates reach `_dp_prune`. That is a strictly better
search, but it **changes the output** — which is why it cannot ride along with FU-34, a
change whose whole claim is byte-exactness. It needs its own before/after and its own
justification.

**Also decide which flag is authoritative.** `can_transact` and `can_select` are
separate API fields; §5.2's pool and §5.3's validator currently encode different
answers to "is this player usable". One of them is wrong, and the plan does not say
which.

**Unblocks:** removes 335 wasted materialisations per default run (a rounding error next
to FU-34), and closes the false-exclusion path above, which is the real reason to do it.

---

## FU-36 — §8 tests that pass because the fixture cannot produce the condition they guard

**Status: closed** — `120eda3` *Fix two vacuous §8 guard tests and add the missing
--max-cells tests (FU-36, FU-37)* (2026-08-27, `task/fu-36-37`, merged as `8ba4ccf`).
Verified in the code: both instances this entry names now assert their own
reachability. `test_generator_children_are_all_accepted_by_apply_transfers`
(`tests/test_optimizer.py:252`) ends with `assert rejections` — "the can_select guard
was never exercised … so the loop above proves nothing" — so the rejection path this
entry measured at **0** occurrences must now actually run; it also asserts the
property that is true (a rejected candidate never reaches the output) rather than the
false one (no candidate is ever rejected).
`test_known_outcome_matches_brute_force_enumeration` (`:191`) prices player 10 beyond
any reachable bank and asserts it, so the affordability mask binds; the club half was
already declared and justified in its docstring and this entry accepted that.

The general point — each property test asserting that the condition it guards was
reachable — is now the house pattern rather than a one-off: FU-28's four new tests
(`e69bb3d`) each carry sizing checks naming what would make them vacuous.

**Deferred from:** `task/fu-34-resolution`, from an audit asked for after FU-34's
measurement showed the generator rejecting 335 children per run while the test asserting
it never rejects any was green.

`test_generator_children_are_all_accepted_by_apply_transfers` (`tests/test_optimizer.py:237`)
asserts §8's *"the generator is a filter, not a bypass"*: every child the search
materialises is accepted by `apply_transfers`, and a rejection fails the test.
**On live data that property is false** — it fires 335 times per default run (FU-35).
The test is green because `bootstrap_snapshot` (`tests/conftest.py:50-69`) builds every
player on `Player`'s defaults, so no `can_select=False`, `removed=True` or
`can_transact=False` player exists and the rejection branch is unreachable.

Measured across the whole suite by wrapping `_materialize`, `_mask_k1` and `_mask_k2`
for one `pytest -q` run (233 passed):

| Guard | Times exercised in the entire suite |
|---|---:|
| `_materialize` returning `None` (the property this test asserts) | **0** |
| affordability mask blocking a cell | 10,861 |
| club-limit mask blocking a cell | 68,604 |

The mask half is genuinely covered; the **authority** half is a tautology. The property
test alone makes 8,712 `_materialize` calls in which `assert result.validation.valid`
cannot fail.

**A second, milder instance in the same shape.**
`test_known_outcome_matches_brute_force_enumeration` (`tests/test_optimizer.py:183`) is
the one test that checks the search against an independent brute-force oracle, and its
fixture blocks **0** cells on both masks: `_tiny_snapshot` gives every player a distinct
club and an identical price. The club half is declared in the docstring (*"all distinct
clubs so the team limit (3) never binds"*) and justified — it keeps the oracle a clean
read on xP. The affordability half is not declared anywhere. To its credit this test
does guard its *own* stated condition: lines 224-228 assert the fixture is big enough
that `first_moves`/`beam` genuinely truncate. That assertion is the pattern the other
tests need.

**Fix, roughly.** Give the optimiser fixture at least one player per adverse flag and a
budget tight enough to bind, and — the general point — have each property test assert
that the condition it guards was reachable, the way the known-outcome test asserts its
own sizing. A property test that cannot fail is worse than no test: it reads as
coverage.

**Note for FU-34.** The restructure moves selectability into the generator's pre-filter,
which makes this test's property *true* rather than vacuous. It should be fixed first,
so it is a real guard on the change rather than a green light that means nothing.

**Unblocks:** nothing blocks on it, but FU-34 and FU-35 both rely on this test meaning
what it says.

---

## FU-37 — §8's two `--max-cells` guard tests do not exist

**Status: closed** — `120eda3` *Fix two vacuous §8 guard tests and add the missing
--max-cells tests (FU-36, FU-37)* (2026-08-27, `task/fu-36-37`, merged as `8ba4ccf`).
Verified in the code: both tests §8 specifies now exist in `tests/test_optimizer.py`.
`test_search_too_expensive_raises_before_any_grid_is_built` (`:1153`) monkeypatches
`_expand_root` to an `AssertionError`, so the refusal is proved to happen *before* the
first grid, asserts `cost.projected_cells > 0` so `max_cells=0` is not refusing an
empty search, and checks all four flag names appear in the message.
`test_cells_per_node_matches_candidates_actually_scored` (`:1200`) counts finite cells
through a wrapped `_top_k_indices` and asserts equality with `cost.cells_per_node` —
the drift check this entry called "the one worth writing".

Measured while closing this, since the second test's value depends entirely on its
fixture masking something: of the 205 grid cells that fixture offers, **86 (42%) are
masked out**, and the surviving 119 match `cells_per_node` exactly. So the agreement
is a real check today, not the trivial one this entry's sibling FU-36 warns about.

`[gap: that 42% is a property of the fixture, not an assertion. The docstring names
the vacuous case ("a fixture where nothing is ever masked … would make the two counts
agree trivially") but nothing asserts against it, so a later change to
`bootstrap_snapshot` or to the extras could drop it to 0% silently and the test would
still pass. One line — assert some cell was masked — would close it. Left rather than
fixed: this branch is FU-28's, and the test is sound as it stands.]`

**Deferred from:** `task/fu-34-resolution`, found during FU-36's audit.

optimizer-search.md §8 specifies two tests for the pre-flight guard: that a
configuration whose `projected_cells` exceeds `--max-cells` **raises before the first
grid is built** and names the flags that reduce it, and — separately — that
`cells_per_node` **agrees with the number of candidates actually scored**, "since a
projection that drifts from reality is a guard that fires on the wrong runs".

Neither exists. `SearchTooExpensive`, `projected_cells` and `cells_per_node` appear
nowhere under `tests/`; the only mention of `max_cells` is `max_cells=10**9` in four
optimizer tests, i.e. every test that touches the search **disables** the guard.

The second one is the one worth writing. `_cells_for_node` (`optimizer.py:352`) re-runs
`_mask_k1`/`_mask_k2` and sums the masks, so it is a second expression of the candidate
count — the same drift risk §6.2 names for the objective, in a component whose only job
is to refuse work. Nothing currently ties it to what the search actually scores.

**Unblocks:** nothing, but `SearchTooExpensive` is the only thing standing between a
mistyped `--horizon` and a machine (§7.2's defect cost one), and it is untested.


---

## FU-39 — `DEFAULT_MAX_CELLS` has no test at either value, and the next change to it is already scheduled

**Deferred from:** `task/fu-28-dominance` (`b9706c6`), which raised it from 400M to
800M because exact dominance took the default configuration's `projected_cells` to
~513M and the guard refused the run.

FU-37 added the two `--max-cells` guard tests optimizer-search.md §8 specifies, and
they are good tests — but they pass `max_cells` explicitly (`0` and `10**9`), as does
every other `optimise()` call in the suite. **Nothing reads `DEFAULT_MAX_CELLS`.**
`grep` finds it in exactly two places, both in `optimizer.py`: its definition and the
parameter default. So the number that actually stands between a default `fpl plan
optimise` and a refusal is unasserted, and was equally unasserted at 400M — this
entry records a pre-existing gap that FU-28 made load-bearing, not one it introduced.
Before FU-28 the default had ~3.5× headroom; now it has ~1.6×.

**Why it is awkward to close, which is why it is filed rather than fixed.** A test
that exercises the threshold needs a fixture whose `projected_cells` lands between the
admitted and refused sides of 800M. The synthetic snapshots are orders of magnitude
short of that (`_tiny_snapshot` is a 6-a-side squad), and building one that isn't
would mean a fixture large enough to be slow — which is the thing §8's other tests
carefully avoid. Options, none costed:

- Assert only that omitting `max_cells` is *bounded* rather than unbounded —
  `inspect.signature(optimise).parameters["max_cells"].default == DEFAULT_MAX_CELLS`.
  Cheap, non-vacuous, and catches the plausible regression (someone defaulting it to
  `None` or `10**12`). Does not test the value.
- Assert the value against a recorded projection for the live default configuration,
  as a golden number with a comment. Tests the thing that matters, but pins a test to
  a cached snapshot, which no other test in this suite does.
- Leave it, and treat §7.1g's measurement as the check. Honest, but the check then
  only happens when someone remembers to re-measure.

**The headroom, measured, because the value matters and not only the missing test.**
Default configuration (horizon 5, `--beam 4`, `--first-moves 50`), cached snapshot
2026-08-27T22:18Z, 616 players, root GW2, `squad.json`:

| | `projected_cells` | Ceiling | Headroom | Ratio |
|---|---:|---:|---:|---:|
| before FU-28 | 112,969,160 | 400,000,000 | 287,030,840 | **3.54×** |
| after FU-28 | **515,771,890** | 800,000,000 | **284,228,110** | **1.55×** |

`--max-hit` makes no difference to this: at GW2 one free transfer accrues to two, so
`k_max` is 2 whether the flag is set to 4 or left uncapped, and the CLI default
projects the same 515,771,890. The absolute headroom is almost unchanged (287.0M →
284.2M) while the *ratio* has more than halved. A ceiling with 1.55× headroom is a
different kind of object from one with 3.5×: it will be reached by ordinary drift, not
only by a mistyped flag. §5.2 predicts the pool grows as players differentiate through
the season, and each pool player costs roughly quadratically at k = 2.

**Do it before FU-29, and expect to move the number again.** `--schedule` at k = 3
enumerates a third incoming slot, and the pool the third slot draws from is the one
FU-28 doubled. Measured on the same snapshot, counting the same `i < j < k` dedup the
generator uses but **without** the budget and club masks — so a strict upper bound on
what the guard would count:

| k | unmasked cells per node |
|---:|---:|
| 1 | 1,525 |
| 2 | 914,566 |
| 3 | **286,265,852** |

**One k = 3 node expansion is 36% of the entire 800M ceiling**, against 0.11% for
k = 2. §7.3 says the guard "also bounds `--schedule`" and that this is why §5.7 can
state its ceiling of 3 as a consequence rather than a rule — that reasoning still
holds, but the margin it holds by is now much thinner, and `--schedule 0,0,3` will
have to be costed against this ceiling rather than assumed to clear it. Deciding how
the ceiling is tested is better done before it moves again than during.

**Reproducibility note.** §7.1g and FU-28's commit messages cite a 2026-08-27T13:33Z
capture with 614 players; the figures above are from a 22:18Z capture with 616. The
difference is two players, both excluded under either rule (exclusions 425 → 427 under
the old rule, 240 → 241 under the new one), and it is snapshot drift, not a rule
difference — confirmed by running both rules against the same capture. The 13:33Z
capture no longer exists: `SnapshotService.load()` saves on every successful live
fetch, so the verification runs for this branch overwrote it, and `~/.fpl-cli/archive`
holds nothing between 2026-08-27T00:30 and now. `[gap: any measurement in these plans
taken against "the cached snapshot" is reproducible only until the next `fpl` command
runs. Nothing pins a capture for measurement purposes. Not this entry's concern, but
it is the reason two figures that should match do not.]`

**Also unresolved, from the same measurement (§7.1g):** the ceiling is expressed in
cells but justified in seconds, and the conversion between them is not a constant.
Measured throughput was 1.81 M projected cells/s at a 189-player pool and 5.66 M/s at
374, because per-node fixed costs amortise over larger grids. §7.3's "≈ 115 s at the
measured 3.5 M/s" gloss has been struck, but nothing replaces it. `[gap: two points do
not fit a per-node-plus-per-cell model with any confidence; that needs a sweep this
branch did not run.]`

---

## FU-40 — A measurement quoted in a plan or a commit message must name both captures it came from

**Standing requirement, not deferred work.** `--snapshot` and the `provenance` block
exist as of `task/snapshot-pinning`; what remains is the discipline of using them,
which no test can enforce.

**The rule.** Any figure quoted in `docs/plans/` or in a commit message must name
**both** captures it was measured against: the pinned bootstrap-static capture, and the
fixtures cache. Path and `captured_at` for each. "Measured against the cached snapshot"
names a file, not a version of it, and both files are rewritten in ordinary use.

```bash
fpl plan optimise squad.json --snapshot ~/fpl-pinned/gw2-pre-deadline.json --json
```

The payload's whole `provenance` block is the citation — both lines of it — and copying
only `provenance.snapshot` is the failure this entry exists to prevent:

```
snapshot ~/fpl-pinned/gw2-pre-deadline.json  (captured 2026-08-28T07:26:38Z)
fixtures ~/.fpl-cli/fixtures.json            (captured 2026-08-28T00:32:59Z)
```

`provenance.snapshot.source` reading `cache` or `live` is the signal that a figure is
**not** citable and the measurement should be re-taken pinned.

**Why the fixtures line is not optional.** `--snapshot` pins bootstrap-static and
nothing else. Fixtures come from `~/.fpl-cli/fixtures.json`, which
`SnapshotService.load_fixtures` rewrites on every successful live fetch
(`api/snapshots.py:155`) and `sync` rewrites outright (`:161`) — so any non-pinned
`plan simulate`, `plan optimise` or `plan evaluate` moves it, exactly as unpinned runs
used to move the bootstrap cache. **A figure measured against a pinned capture can
therefore still drift, and two pinned runs against the same capture on different days
need not agree.** The pin makes that drift visible rather than impossible:
`provenance.fixtures.captured_at` is the fixtures cache's mtime, so a re-measurement
that disagrees can be attributed instead of argued about.

The exposure is not confined to blanks and doubles. `_build_schedule`
(`domain/projections.py:218`) turns the fixtures list into opponent *and venue* per team
per event, and `ComponentProjection` feeds both into `rates(team, opponent, home)` for
every projected cell — so a changed fixtures file moves every component of every
projection, not only the fixture counts.

**Why, in this file's own history.** FU-39's reproducibility note records the failure:
§7.1g and three of FU-28's commit messages cite a 2026-08-27T13:33Z capture with 614
players, against figures re-measured from a 22:18Z capture with 616. The difference
was two players and no rule change — but establishing that took a separate run against
both rules, because neither figure said which capture produced it, and the 13:33Z
capture no longer existed to check. Its `[gap: nothing pins a capture for measurement
purposes]` is what `--snapshot` closes; this entry is the other half, which tooling
cannot close.

**What is still not pinned.** The capture format is bootstrap-static only. A pinned run
reads fixtures and event-live from their ordinary caches, read-only, and `provenance`
reports them as `cache` with each file's mtime — which is why the rule above requires
the fixtures line rather than treating it as a detail. `plan evaluate` inherits the same
exposure through `~/.fpl-cli/events/{gw}-live.json`; it has no `--json` output, so a
figure taken from it has to carry that path and mtime by hand.

`[gap: pinning fixtures and event-live wants either a bundle capture format or a second
flag; snapshot-pinning.md §5 records the choice as open, and neither was in scope for
`task/snapshot-pinning`. Until one lands, this entry's rule is the only thing standing
between a fixtures rewrite and a silently invalidated figure — and unlike the
bootstrap-static half, no tooling enforces it.]`

---

## FU-41 — A capture is a directory, not a file

**Status: landed** — `task/fu-41-capture-directories`. `fpl sync` writes
`~/.fpl-cli/archive/YYYY-MM-DD/` holding `bootstrap-static.json`, `fixtures.json` and
`manifest.json`; `--snapshot` accepts that directory or a bare bootstrap-static file.
Manifest version 2 adds `role` and `next_event`.

**Deferred from:** [snapshot-pinning.md](snapshot-pinning.md) §5, which recorded the
gap and proposed "either a bundle format or a second flag". A directory is the bundle,
and needs no second flag.

**Why this was urgent rather than tidy.** FU-40 established that `_build_schedule`
(`domain/projections.py:218`) turns the fixtures list into opponent *and venue* per team
per event, and that `ComponentProjection` feeds both into `rates(team, opponent, home)`
for **every projected cell**. `--snapshot` pinned bootstrap-static alone, and
`~/.fpl-cli/fixtures.json` is rewritten by every successful live fetch — so a
`plan evaluate` run for GW2 against a rewritten fixtures file **is not measuring what it
reports**, and says nothing to indicate it. That is not a reproducibility inconvenience;
it is a wrong number presented as a backtest. Pinning bootstrap-static and leaving
fixtures loose closed the half of the hole that was easier to see.

**What the manifest records, and why the deadline field is the point of it.**

```json
{
  "version": 1,
  "captured_at": "2026-08-28T09:01:35.768027+00:00",
  "current_event": {"id": 1, "deadline_time": "2026-08-21T17:30:00+00:00", "deadline_passed": true},
  "files": {"bootstrap-static.json": {"sha256": "..."}, "fixtures.json": {"sha256": "..."}}
}
```

`fpl-sync.timer` is `Persistent=true`, so a missed firing runs on catch-up rather
than being skipped. The four pre-FU-41 archives show what that does to a filename:
`bootstrap-2026-08-25.json` was written at **15:12** and `bootstrap-2026-08-26.json` at
**22:32**, against 00:30 and 00:32 for the other two. **A capture's name says nothing
about whether it precedes the deadline it appears to**, and a leak-free evaluation
depends on exactly that. It is now recorded at capture time, from the fetch, so a
backtest can check rather than assume.

Both gameweeks are recorded, because one field cannot answer both questions.
`current_event` is the `is_current` gameweek, whose deadline has almost always passed —
that is what makes it current — and it is the right field for the leak check
`select_archived_snapshot` performs. `next_event` is the gameweek a capture is a
*candidate* for: `gw2-pre-deadline.json` is named for GW2 while its `is_current` is GW1,
whose deadline passed a week earlier. Each is phrased as the fact its own consumer
needs — `deadline_passed` for the leak check, `captured_before_deadline` for the
candidate check — so neither question requires opening `bootstrap-static.json`.

**Roles: one canonical slot per UK date.** The first valid capture of a day claims the
slot; anything later that day is written ad-hoc under a path keyed by the instant, and
`role` records which it is. Nothing inspects timer state, which is what makes the
offline case come out right by itself: a sync that finds the slot empty claims it,
whether that is the timer at 01:00 or someone at their desk at noon.

**A capture claims a slot only when the slot is empty, and an existing capture is never
deleted or overwritten for any reason.** The first cut of this got it wrong in a way
worth recording, because it was nearly invisible: `is_valid_capture` treated an
unrecognised manifest version as invalid, and the refuse-to-replace guard protected only
*valid* captures — so an older build reading a newer capture would conclude it was
rubbish and clear it. That is not a two-concurrent-builds problem. `git bisect` reaches
it inside this branch's own history: at `256e7af` the manifest version was 1, an
unrecognised version raised, and `write_capture` did `mkdir(exist_ok=True)` and wrote
straight into the slot — it did not even need the delete. A day's snapshot cannot be
fetched again, and "this build cannot read it" is indistinguishable from inside from
"this is rubbish".

So occupancy blocks the claim, not validity. Anything unusable found in a slot is
*renamed aside* to `YYYY-MM-DD.unreadable-<timestamp>/`, with every byte preserved, and
the incoming capture files ad-hoc anyway — promoting yourself into a slot you have just
vacated is how nobody ever looks at what was in it. `sync` names both paths and
distinguishes the two cases, because they call for opposite reactions: an unrecognised
manifest version probably means a *newer* build wrote it and the operator should check
what they are running, whereas a capture that fails its own digests is rubbish. Both are
kept either way.

Captures are staged in a sibling `.incoming-*` directory and `os.replace`d into place, so
a crashed write leaves staging rubbish rather than a partial capture squatting on a slot.
Quarantine and ad-hoc paths both key on a timestamp truncated to the second and both
de-duplicate with a `-2` suffix — a collision at either would destroy the thing being
preserved, or crash the sync that was trying to preserve it.

Legacy bare files compete on equal terms and are neither migrated nor deleted, which is
also why a manifest with **no** `role` reads as ad-hoc: a version 1 capture was never
asked to claim a slot and must not claim one retrospectively. Confirmed on the real
archive: `bootstrap-2026-08-28.json` (00:32) holds today, the v1 directory written at
09:01 and the ad-hoc capture at 09:19 both read as ad-hoc, and
`select_archived_snapshot` picks the bare file.

`plan evaluate`'s scan considers canonical captures only. Ad-hoc captures stay on disk
and readable through `--snapshot`; they are simply not something automatic selection
should silently prefer over the day's canonical one.

**Slots are keyed by UK date, not UTC.** The first implementation used
`captured_at.date()`, which is the UTC date. A 23:30 UTC capture in summer is 00:30 the
next day in London, so it was filed under the slot the *following* night's capture is
entitled to. `captured_at` itself stays UTC.

**The timer fires at 01:00 UK, not 00:00 UTC.** FPL moved the daily price change to
00:00 UK for 2026/27, from 01:30 GMT / 02:30 BST. `OnCalendar=daily` with
`RandomizedDelaySec=1h` on a UTC host means 00:00–01:00 UTC: safely 01:00–02:00 UK under
BST, but 00:00–01:00 UK once the clocks go back on 2026-10-25 — straddling the
price-change boundary and silently mixing pre- and post-change captures in the price
history. Now `OnCalendar=*-*-* 01:00:00 Europe/London` with `RandomizedDelaySec=5m`,
which tracks the change instead of drifting across it: `systemd-analyze` confirms
00:00 UTC while BST is in force and 01:00 UTC from 2026-10-26. Timezone suffixes in
calendar specs need systemd ≥ 250; this host runs 255.

`captured_at` is the fetch time rather than the clock at write time, and rather than a
file mtime — `cp -r` resets mtimes, and mtime is what `select_archived_snapshot` had to
date archives by because it was all they recorded. Capture directories are now dated by
their manifest; the four bare files are still dated by mtime, because that remains all
they have.

**The sha256s make the capture falsifiable rather than merely labelled.** A file that
does not match its recorded digest is a hard error naming the file, not a warning: a
capture exists to be trusted, and a measurement taken from a modified one is not
reproducible whatever the manifest claims. Verification happens per file on read, so the
error names the file the run actually depended on and a command that never reads
fixtures is not failed by a fixtures file it never touches.

**What is still not pinned.** `[gap: event-live. `plan evaluate` reads
`~/.fpl-cli/events/{gw}-live.json` through the cache even under a pinned run; the
manifest does not cover it and `plan evaluate` has no `--json` through which to report
its provenance. A third file in the capture and an `--json` on `plan evaluate` would
close it. Neither was needed for `--snapshot`, so neither was built — but note that the
argument above, that an evaluation against loose inputs is a wrong number rather than an
irreproducible one, applies to event-live exactly as it applied to fixtures.]`

**Partly addressed by FU-43**, which is not the same as closed. `task/event-live-gate`
stopped a provisional event-live payload being scored as final, and gave it a
settled-ness provenance reported on the console. It did **not** put event-live in the
capture: a pinned run still reads `~/.fpl-cli/events/{gw}-live.json`, the manifest still
does not cover it, and `plan evaluate` still has no `--json`. The gap above stands as
written.

`[gap: `fpl-sync.service` and `fpl-sync.timer` live in `~/.config/systemd/user/` and
are not in version control, so the reasoning above is the only record of why the
calendar spec is what it is. A `deploy/` directory holding both units would make the
change reviewable and reproducible; this branch documented it instead, which is weaker.]`

`[gap: an ad-hoc capture is never promoted. If a day's canonical capture is later found
to be corrupt, the ad-hoc captures from the same day are on disk and pinnable but will
not be selected automatically, and nothing offers to repair the slot. Deliberate — a
repair path that rewrites history silently is worse than one that makes you look.]`

`[gap: quarantined captures accumulate. Nothing prunes `*.unreadable-*` and nothing
offers to restore one to its slot once the operator has decided it is fine — the restore
is a `mv`, deliberately, because a tool that puts captures back is a tool that can put
the wrong one back.]`

**Three gaps recorded here are now closed.** The third was the destructive one: `next_event` records the deadline a capture is
a candidate for, and `plan evaluate` dates its projection snapshot from the manifest
rather than the archived file's mtime — the case ad-hoc and copied captures make
reachable rather than theoretical. And an unreadable capture is now moved aside intact
instead of being cleared, which is the difference between an operator finding a
confusing directory and an operator finding nothing at all.

---

## FU-42 — `--archive-dir` isolates the capture, not the caches

**Status: open.** Filed from `task/archive-dir`, which added
`fpl sync --archive-dir PATH` and removed a dead `FPL_CACHE_DIR` export from
`.envrc`.

**What prompted it.** Verification syncs were filing into the production
archive: on 2026-08-28 three captures landed in `~/.fpl-cli/archive/` from test
runs alone (`2026-08-28/`, and ad-hoc `2026-08-28T091907Z/` and
`2026-08-28T094050Z/`). A canonical slot is claimed once and never overwritten
(FU-41), so a test run that claims one costs that day's real capture — the
irreplaceable thing, since a day's snapshot cannot be fetched again.

**What was established about `FPL_CACHE_DIR`, because the premise was wrong.**
It was believed the caches honoured `FPL_CACHE_DIR` while the archive alone did
not. They do not. **Nothing in the codebase has ever read it.** Every path is
hardcoded under `~/.fpl-cli`: `storage/cache.py` (`bootstrap-static.json`),
`api/snapshots.py` (`fixtures.json`, `events/`, `archive/`). The only
environment variable the CLI consults is `FPL_SNAPSHOT`, in `cli.py`. The
export entered in `3fde912` *Add direnv config for venv activation* set to
`$HOME/.fpl-cli` — the same value as the hardcoded default — so it never had an
observable effect, which is why the discrepancy went unnoticed for as long as
it did.

Checked before deleting it: the only file under `~` that mentions
`FPL_CACHE_DIR` is `projects/fpl/.envrc` itself. `~/.bashrc` and `~/.profile`
have no FPL references, there is no `~/.bash_profile`, `~/.zshrc` or
`~/.bash_aliases`, and the user crontab has no active entries.
`~/.config/systemd/user/fpl-sync.service` sets no `Environment=` and its
`ExecStart` is a bare `fpl sync`, so the timer never saw the variable in any
case — direnv does not apply to systemd.

**Why the variable was removed rather than wired up.** Half-wiring it — the
archive following it while the caches did not — produces partial isolation that
looks total, which is worse than none: a user pointing it at a scratch location
would get a scratch archive and production caches, and nothing would say so.
Wiring up the whole cache root was the coherent alternative and was declined for
this branch as a separate question (below). What remains is one explicit flag,
and a test that fails if the variable is ever half-wired.

**The gap.** `[gap: --archive-dir protects the capture and nothing else. A sync
with the flag still refetches and rewrites `~/.fpl-cli/bootstrap-static.json`
and `~/.fpl-cli/fixtures.json` in place. Per FU-40, `_build_schedule`
(`domain/projections.py`) turns the fixtures list into opponent *and* venue for
every projected cell, so a rewritten fixtures file moves every cell of an
in-flight measurement. A test sync with `--archive-dir` is therefore safe for
the archive — the irreplaceable part — and still disruptive to a measurement in
progress.

Whether dev runs want a full scratch cache root (a `FPL_CACHE_DIR` that
genuinely resolves all four paths, or a `--cache-dir` alongside `--archive-dir`)
is a separate question and is deliberately not answered here. Note only that it
is the same trade-off in a larger frame: whatever is chosen must move all four
paths together or none, because the failure mode being avoided is a partial
guarantee nobody can see.]`

---

## FU-43 — An event-live payload must say whether the gameweek had settled

**Status: landed** — `task/event-live-gate`. The event-live cache is now an envelope
recording the gameweek's `finished` and `data_checked` at the moment of the fetch;
neither service serves an unsettled or unrecorded payload silently.

**Deferred from:** [snapshot-pinning.md](snapshot-pinning.md) §5, whose second gap this
closes. §5's *first* gap — event-live is not in the capture — is untouched and stays
open, as does the FU-41 note above.

**The defect.** `SnapshotService.load_event_live` gated on `finished and data_checked`
before preferring a cached payload; `PinnedSnapshotService.load_event_live` bypassed the
gate entirely, by a documented decision that turned out to be wrong. FPL awards bonus
points and applies stat corrections after the final whistle, so a payload fetched at full
time is materially wrong rather than merely early — and it is wrong in a biased
direction, since bonus falls on the highest scorers, who are exactly the players a
projection model is judged by. `plan evaluate` scoring against one produces a figure that
looks valid and is not.

**Why the obvious fix was the wrong one.** Giving the pinned path
`SnapshotService`'s gate would have made it worse, not better. That gate reads finality
out of the snapshot in hand, and under pinning the snapshot in hand is a *pre-deadline*
capture — it reports the gameweek unfinished because it was taken before the gameweek was
played. Gating on it refuses every correct backtest there is. Projection inputs and
outcome data come from opposite sides of the deadline by design; that is the point of a
backtest, not a flaw in one. Only the outcome payload can speak for the outcome payload,
and until this branch the payload said nothing.

**The envelope.** `{version, event, fetched_at, finished, data_checked, live}`. The
reader checks what the file records rather than trusting that the writer was gated
correctly — a file written by an older build, copied from another machine mid-gameweek,
or edited by hand is indistinguishable otherwise, and the gameweek's finality *today*
says nothing about the state the bytes were captured in. A payload with no `version` is
the pre-envelope shape and classifies as `unknown`, distinct from `unsettled`: the file
genuinely does not say, and reporting "written before it settled" would be inventing a
finding. Settled-ness is never inferred from the contents — "some players have bonus, so
bonus must have been applied" is a heuristic that would be wrong for exactly the gameweek
where it mattered.

**Refuse, warn or refetch — the call, and why it differs by service.** The two services
have different options, so one policy for both would be wrong for one of them.

- `SnapshotService` can reach the API, so an unsettled or unrecorded cache is
  **refetched**, and the file rewritten in the recording format. This is a repair, not an
  avoidance: the legacy file that forced the refetch is replaced by one a pinned run can
  use. Refusing here would be a hard failure with a live fix sitting available.
- `PinnedSnapshotService` cannot fetch, so it **refuses**, naming the file, the flags and
  the remedy. Refusing was chosen over warning because a pinned run exists to produce a
  citable measurement — the whole reason to reach for `--snapshot` — and a warned-past
  wrong number still gets quoted. The counter-argument, that a hard failure mid-run may
  be worse than a loud warning, does not apply here: the only caller loads event-live
  before any projection runs, so nothing has been computed or printed and the run costs a
  re-invocation. It is also the consistent choice — that service already refuses a
  *missing* cache with the same shape of message, and refusing an absent payload while
  serving an unusable one would be the incoherence.
- A **live fetch of an in-flight gameweek is served**, marked unsettled. It is the
  freshest data in existence, there is nothing better to fall back to and nothing to wait
  for, so refusing would deny the only answer available rather than protect anyone from a
  worse one. What must not happen is serving it *silently*.

**Provenance on the console, not in `--json`.** FU-40's rule applied to the third input.
`plan evaluate` has no `--json` (FU-41's gap), so `evaluate_plan` prints the settled-ness
above the tables. The settled case is printed too, not just the unsettled one: "no
warning appeared" is indistinguishable from "the check was skipped", and the point of
recording finality is that a reader can tell which.

**State on this machine when the branch landed.** `~/.fpl-cli/events/1-live.json`,
written 2026-08-25, is the pre-envelope shape and classifies as `unknown`. GW1 currently
reports `finished=true, data_checked=true`, so under the old code it would have been
served as final on the strength of the gameweek's state alone, with nothing in the file
to support that. It now refetches on the next unpinned `plan evaluate --event 1`, which
rewrites it in the recording format; a pinned run refuses until that has happened.

`[gap: `plan evaluate` still has no `--json`, so a figure taken from it cannot be quoted
with machine-readable provenance the way `plan optimise` can (FU-40). The settled-ness is
on the console only. Adding `--json` to `plan evaluate` was deliberately kept off this
branch — it is a command-surface change, not a correctness fix, and bundling it would
have made the gate harder to review. It is wanted: FU-40's argument for carrying
provenance into a quotable payload applies to `plan evaluate` at least as strongly as to
`plan optimise`, since evaluate is the command whose numbers end up in commit messages.]`

`[gap: the write gate is unchanged and still the pre-existing one — an unsettled payload
is never persisted, so in normal operation the reader's `unsettled` branch is unreachable
from this build's own writes. It is reachable from an older build, a copied cache, a
hand-edited file, or any future relaxation of the write gate, which is why the reader
checks rather than assumes. Tests construct the state directly.]`

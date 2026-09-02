# Follow-ups

Work deliberately deferred out of other tasks. Each entry records what, why it was
deferred, and what it unblocks.

Closed entries stay in place — the numbering is referenced from commit messages and
from the plans in this directory, so it must not shift. A closed entry carries a
**Status: closed** line naming the commit that closed it and what was checked in the
code, not just what the commit claimed. Its body is left as written, so where the
fix diverged from the entry the Status line says how.

**Last reconciled against `main`:** 2026-08-28 (`99e5afb`). Every entry below was
checked against the source at that commit, not against the commit log.

Five merges landed since the previous reconciliation at `76809ae`, not four:
`30fc761` (FU-28), `8bcfda8` (`task/snapshot-pinning`, which filed FU-40),
`670859c` (FU-41), `c44ce00` (`task/archive-dir`, FU-42) and `99e5afb`
(`task/event-live-gate`, FU-43) — plus `a828b5a`, a direct commit that closed
FU-28, FU-36 and FU-37 in this file. `task/snapshot-pinning` is the one usually
forgotten, and it is the merge that moved the most entries: FU-40 was filed by it
and FU-13's premise was falsified by it.

**Findings of this pass, in the order they matter:**

- **FU-19 has regressed** and is the one to act on. *[Acted on: closed by
  `task/fu-19-18-13`, which added the check. FU-18 and FU-13 were decided on the same
  branch — FU-18 closed, FU-13 narrowed. The three rows in the table below are updated;
  the bullets in this list are left as the pass found them.]* It was closed on the strength
  of `CLAUDE.md`'s *"Not yet written"* line being reduced to `domain/optimizer.py`
  alone. `domain/optimizer.py` is now 960 lines, so that line is false again — the
  same defect the entry was filed for, in the same field. Reopened below.
- **FU-13 is partially closed** by `task/snapshot-pinning`: `--json` exists, on
  `plan optimise` only.
- **FU-43 is partially closed**, and its Status line has been changed from
  *landed* to say which half.
- **No entry was found closed in code but unmarked**, the failure this pass exists
  to catch. FU-13 is the near miss: its headline claim was false and its Status
  line absent.
- Thirteen open entries cite line numbers or symbols that have moved. Bodies
  corrected in place; the corrections are marked so the original claim is still
  legible.
- **There is no FU-38.** It appears nowhere in this file, in `docs/`, in `src/`, in
  `tests/`, or in any commit message on any branch. Most likely a number claimed and
  abandoned before the entry was written. Recorded rather than reused: the header's
  own rule is that numbering must not shift, and silently filling the hole would make
  a future reader think an entry was deleted.

**Closed entries were spot-checked too, where a commit claimed the close.** FU-28's
Status line is accurate in every particular: exclusion is at
`len(dominators) >= max_from_bucket` with `max_from_bucket = min(limit,
position.squad_select)` (`optimizer.py:247, 269`), the inner loop skips
`not _validator_usable(other)` (`:258`), admission is unchanged, `DEFAULT_MAX_CELLS` is
`800_000_000`, and `dominance_pruning_unsound` is absent from the payload with
`tests/test_cli_optimise.py:226` asserting it. FU-36 and FU-37's three named tests exist
at the exact lines cited (`tests/test_optimizer.py:252, 1153, 1200`), and FU-36's
`assert rejections` reachability check is present. FU-41's claims hold:
`MANIFEST_VERSION = 2`, `ROLE_CANONICAL`/`ROLE_ADHOC`, and `write_capture` staging into
place. No closed entry was found to overstate its close.

**Every open entry, and what this pass concluded.** *Still open* means checked against
the source and the defect is still there.

| Entry | Outcome | Basis |
|---|---|---|
| FU-4 | Still open, body accurate | No `sqlite` anywhere in `src/`; `storage/cache.py` is JSON only |
| FU-5 | Still open, body accurate | `chips_played` is written (`squad.py:455`) and parsed (`transfers.py:83`), read by nothing |
| FU-6 | Still open, body accurate | `SquadPlan.starters/captain/vice_captain` still one value each (`squad.py:23-25`) |
| FU-9 | Still open, body accurate | `to_ledger_payload` emits `log` and `chips_played` only — no XI, captain or vice-captain |
| FU-12 | Still open, **lines corrected** | `from rich import print` at `cli.py:12`, still mixed with `console.print` |
| FU-13 | Open, **narrowed** by `task/fu-19-18-13` | Retitled and scoped to `plan evaluate` and `plan simulate`; explicitly not wanted on four others |
| FU-14 | Still open, **body corrected** | `plan optimise` landed; `squad import`/`export`, `players show`, `squad show` still absent |
| FU-15 | Still open, **lines corrected** | README Commands block still lists three commands, still documents the legacy squad shape |
| FU-17 | Still open, **lines corrected** | `cli.py:307` unchanged; no `BadParameter` for an unknown club |
| FU-18 | **Closed** by `task/fu-19-18-13` | Stays one file; section comments added and a 600-line split threshold recorded |
| FU-19 | **Closed** by `task/fu-19-18-13` | Block corrected, and `tests/test_claude_md_structure.py` now fails when block and tree disagree |
| FU-20 | Still open, **lines corrected** | `_build_schedule` still private (`projections.py:219`); no `fixture_count` |
| FU-21 | Still open, **lines corrected** | `chance_of_playing_this_round` still parsed nowhere |
| FU-22 | Still open, **body corrected** | `--output` exists but writes a transfers plan, not a `SquadPlan` — trigger unmet |
| FU-25 | Still open, body accurate | `DEFAULT_FT_VALUE = 1.5` still a constant (`optimizer.py:48`); no estimator |
| FU-27 | Still open (won't-do), **symbols corrected** | `_xi_structure`/`_XiStructure` renamed public by FU-26; `ranked` tuples still built |
| FU-29 | Still open, body accurate | No `"--schedule"` string in `cli.py` |
| FU-30 | Still open, **lines corrected** | `simulate_plan` still takes no `--model` (`cli.py:384`) |
| FU-31 | Still open, **body corrected** | No `--beam`/`--first-moves`/`--max-cells`; default is now 800M, not 400M |
| FU-34 | Decided, not implemented — unchanged | No re-check needed; the entry records a decision, not a code claim |
| FU-35 | **Still open, and confirmed so by FU-28's own source comment** | `optimizer.py:219-223` names FU-35 as the owner of the admission line; `:231` unchanged |
| FU-39 | Still open, body accurate | `DEFAULT_MAX_CELLS` still appears in exactly two places, both `optimizer.py` (`:60`, `:851`) |
| FU-40 | Open permanently; **two passages superseded** | Standing rule, not closable; FU-41 landed the bundle format it assumed absent |
| FU-42 | Still open, body accurate | `--archive-dir` at `cli.py:248`; all four cache paths still hardcoded; `FPL_SNAPSHOT` still the only env var read |
| FU-43 | **Partially closed** | Gate landed; `capture.py` still writes two files, so event-live is not pinned |

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

`cli.py:12` does `from rich import print`, shadowing the builtin, *and* `cli.py:64`
imports `console` from `presentation`. Both are used, seemingly at random, within
the same function. `fpl squad create` uses `console.print` for its own messages
(`cli.py:325, 328, 336, 339, 348, 353`) but bare `print` for validation errors and
warnings (`cli.py:344, 346`). `fpl plan simulate` uses `console.print` for its table
(`cli.py:440`) but bare `print` for the legacy warning (`cli.py:395`).
`builder.py` uses `console` exclusively.

*[Line numbers re-checked 2026-08-28 against `99e5afb`; the originals were `cli.py:9`,
`31-39`, `121, 124, 132, 135, 144, 149`, `140, 142`, `197, 205` and
`180, 200, 202, 206, 207`. The defect is unchanged — the mix is still there, in the
same two commands. One thing did move on its own: `plan simulate`'s error paths now go
through `error_console` (`cli.py:392, 403, 411, 418`), added by FU-3's exit-code work,
so that command is now three channels rather than two.]*

Two output channels means width detection, output capture and `NO_COLOR`/
`--no-color` handling differ between lines of the same command's output.

**Fix:** drop the `from rich import print` import; route everything through the
`presentation.console` singleton.

**Unblocks:** any future `--json` or `--quiet` flag (FU-13), which needs a single
place to suppress or redirect output.

---

## FU-13 — `--json` on `plan evaluate` and `plan simulate`, and nowhere else

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

**Status: open, narrowed to two commands** (2026-08-28, `task/fu-19-18-13`). Retitled:
the original was *"No machine-readable output on any command"*, which stopped being
true when `task/snapshot-pinning` put `--json` on `plan optimise` (`cli.py:649`, still
the only `"--json"` string in the module). The entry is narrowed rather than closed,
because the remaining want is specific and the remaining not-want is equally specific.

**Wanted: `plan evaluate`.** The strongest case of the three, and it is FU-40's
argument rather than a convenience one. `plan evaluate`'s figures are the ones that end
up in commit messages and in `docs/plans/`, and FU-40 requires a quoted figure to name
the captures it came from. `plan optimise` can satisfy that — its payload carries the
`provenance` block. `plan evaluate` cannot: FU-43 had to report event-live settled-ness
on the **console** for want of a payload to put it in, which tells a reader whether the
actuals were final but not which file they came from or when it was written. So the one
command whose numbers most need machine-readable provenance is the one that has none.

**Wanted: `plan simulate`.** Because it is a verification path, not an output path.
[optimizer-ux.md](optimizer-ux.md) §1 makes `plan optimise --output` → `plan simulate`
the mechanism that satisfies CLAUDE.md's *"Every optimiser recommendation must pass the
same validator used for manual squad planning"*, and §1's test is that the two print
identical per-gameweek numbers. Asserting that today is a by-eye comparison of two Rich
tables — one side of which already emits JSON. Giving `simulate` a payload makes the
comparison a diff. (FU-30 is the other half of making that comparison mean anything:
`simulate` hardcodes `ComponentProjection`, so the two sides can still be scored under
different models. Both are needed; neither is sufficient.)

**Not wanted: `players list`, `squad create`, `squad validate`, `sync`.** No consumer
exists for any of them, and a second output format is a permanent maintenance cost, not
a one-off: every future field has to be added twice, kept consistent twice, and tested
twice, for output nothing reads. `players list` is the tempting one — it looks like the
natural thing to pipe — but a script wanting player data has the snapshot cache and the
capture directory, both already JSON on disk and both richer than any table. Adding
`--json` there would be building an export for data that is already exported.

**FU-12 remains a prerequisite for doing this well, and did not turn out to be one for
doing it at all.** The entry originally said *"Needs FU-12 first — a single output
channel, before there is anything to switch"*. That was wrong as stated: `--json`
landed on `plan optimise` with FU-12 untouched, and `cli.py:12` still does
`from rich import print` alongside the `presentation.console` import. It worked because
`optimise --json` writes the payload to stdout directly and its surrounding notices
were moved to stderr **by hand** — the pinned-snapshot notice and the stale-cache
notice both went to `error_console` specifically so the payload would stay parseable.
That is a per-command fix, not a structural one. Each further `--json` has to repeat
that discipline by hand and will break silently if a single `print` is left on stdout,
which is precisely what FU-12 describes. So: FU-12 is not blocking, and doing these two
without it means doing the stderr audit twice more.

**Not implemented on this branch.** `task/fu-19-18-13` scoped the decision only.

---

## FU-14 — `fpl players show` and `fpl squad import` / `export` are unimplemented

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

The README Agent Plan names nine commands. Seven exist (`sync`, `players list`,
`squad create`, `squad validate`, `plan simulate`, `plan optimise`, `plan evaluate`).
Missing: `fpl players show`, `fpl squad show`, and `fpl squad import`/`export`.

*[Corrected 2026-08-28 against `99e5afb`: the original listed six commands and named
`fpl plan optimize` among the missing. It landed on `task/optimise-cli` —
`cli.py:637` registers `plan optimise`, with `plan optimize` kept as a hidden alias at
`cli.py:1018`. The entry's own scope is unaffected: it covers `squad import`/`export`
only, and those are still absent.]*

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

`README.md:40-45` lists three commands (`sync`, `players list`,
`squad validate`), omitting `squad create`, `plan simulate`, `plan optimise` and
`plan evaluate`. Worse, `README.md:48` describes a squad plan as *"a JSON object
containing a `players` array of player IDs"* — the **legacy** format. `fpl squad create`
now writes a transfer ledger (`version`/`genesis_event`/`log`), and the legacy shape
survives only as `Ledger.from_file`'s fallback, which sets `legacy=True` and
produces optimistic selling prices.

A user following the README today builds the one squad format the app warns
about.

**Also stale:** `README.md:7-12` ("The first slice supports…") predates the
squad builder, transfer simulation and projections.

*[Line numbers re-checked 2026-08-28 against `99e5afb`; originally `25-33`, `33` and
`5-12`. The drift is `task/snapshot-pinning`, `task/archive-dir` and
`task/event-live-gate`, each of which added a section **above** Commands. Note what
that means: three consecutive branches updated the README and none of them touched the
Commands block, so it has now been stale across four merges. The omission is wider than
when this was filed — `plan optimise` has been added to the missing list.]*

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

`cli.py:307`:

```python
players = [player for player in players if player.team == club_id] if club_id else []
```

An unrecognised `--club` yields `club_id is None` and therefore an empty result
with no message — indistinguishable from a club that genuinely has no matching
players. Four lines above, `--position` raises
`typer.BadParameter("Use GKP, DEF, MID, or FWD.")` for the same class of error
(`cli.py:303`).

*[Line numbers re-checked 2026-08-28 against `99e5afb`; originally `cli.py:104` and
`99-100`. The code itself is byte-identical — only its position moved.]*

**Fix:** raise `typer.BadParameter` naming the unknown club, matching
`--position`. Club names come from the snapshot, so the valid set is known at
the point of failure.

---

## FU-18 — `presentation.py` is a flat module; the Agent Plan specifies a package

**Deferred from:** [optimizer-ux.md](optimizer-ux.md), §8.

**Status: closed — decided, stays one file** — `task/fu-19-18-13` (2026-08-28).
`presentation.py` remains a flat module. The README Agent Plan's file list is the
document that is wrong, and `CLAUDE.md` now says so positively — *"one file by
decision, not by drift"* — rather than recording an unresolved conflict.

**The reasoning, since the entry exists to have this argued rather than defaulted.**
At 393 lines the sharing between renderers outweighs the cost of one file. Colour
thresholds, price formatting (integer units to `£x.xm`) and xP formatting run through
every table, and they are conventions rather than helpers — the kind of thing that
stays consistent because it is visible on one screen, and drifts once it has to be
imported. A package split by command would cut across that sharing rather than along
it: `plan optimise`'s four renderers use the same price and xP conventions as
`players list`'s one, so the seam between the two is not where the coupling is.

**And a threshold, because that is what stops this recurring.** The entry has been
re-litigated twice, both times as a judgement call about whether the file had got too
big, and both times the answer moved because the number had. **Split into a package
when `presentation.py` exceeds 600 lines.** Not a suggestion to review at 600 — the
decision is taken now, and 600 is when it takes effect. The figure is chosen as roughly
the point at which the shared conventions above stop being visible on one screen while
navigating, which is the only property the sharing argument depends on. Until then this
entry is closed and reopening it needs a new argument, not a new line count.

**What was done in the closing commit.** Section comments per command group
(`presentation.py:31, 56, 108, 166, 221`), so the file is navigable by the command
whose output each renderer produces — the thing a package would have given, at the cost
of nothing. `squad_state_table` sits under `plan simulate` rather than under a squad
group because that is the command that prints it. The `plan optimise` marker carries
the note on why the split would cut across the sharing, so the next person to weigh it
finds the argument next to the code rather than only here.

*[gap: the README Agent Plan's file list still names `src/fpl_cli/presentation/`. It
is not amended here — the Agent Plan is a historical statement of intent rather than a
live specification, and editing it would make it a worse record of what was planned.
`CLAUDE.md` is the live document and it is now unambiguous. If the Agent Plan is ever
reworked into a live spec, this is one of the lines to reconcile.]*

**Superseded Status line, left as written** — *open, narrowed* (2026-08-26, `33cd761`):
the documentation half was settled there, in that `CLAUDE.md`'s Structure block stated
the flat module and named the conflict, so the two no longer disagreed silently. What
remained was the decision this entry was filed for, which is the one taken above.

*[Re-checked 2026-08-28 against `99e5afb`. The line count in this Status note was
already a correction of the body's; both are now stale again, and in the direction that
matters. `presentation.py` is **376 lines with eleven renderers** — it was 185 in the
body, 200 in this note. More to the point, the four renderers this entry named as the
reason to decide *before* they landed have landed: `optimise_paths_table:302`,
`optimise_why_table:346`, `optimise_recommendation:325` and `optimise_header:223`, which
is the provenance panel. **The deadline this entry set for itself has passed and the
decision was not taken.** That is the finding, not the line count — the file doubled
under an open question about whether it should be a file at all. **This is what
prompted the close above**, and it is why that close carries a threshold: a deadline
expressed as "before those renderers land" was one nobody could see passing, whereas a
line count is checkable at a glance.]*

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

**Scope grew, 2026-08-30 (`task/fu-19-readme`): the guard now covers two
documents.** This entry was filed about `CLAUDE.md` and closed by a check over
it. The README's Architecture table — written on `task/readme` on 2026-08-28 —
went stale on 2026-08-29, when the `task/model-versioning` merge added
`domain/variants.py` without updating it. **Same mechanism, second document,
third instance overall.** The gap block below already anticipated this: it
recorded that the guard covered `src/fpl_cli/` only and that *"FU-15 records the
README's equivalent staleness, which nothing checks either."* It went stale
before anything acted on that.

`tests/test_claude_md_structure.py` now checks both. The comparison is one
function — `structure_drift`, unchanged in what it decides — taking the reader as
an argument; each document gets a small parser producing the same
`{group: {modules}}` mapping. **A single parser was considered and rejected**:
`CLAUDE.md` groups modules under a package heading and wraps across lines, the
README gives one fully-qualified path per table row, and a reader accepting both
shapes would accept either shape in either document — a weaker guarantee than the
one being bought. Aligning the formats instead would mean losing the README's
per-module description column or expanding `CLAUDE.md`'s eight lines to seventeen
table rows in a file loaded into context every session; neither is worth one
parser. The reasoning is at the top of the test.

Every failure message now names the document as well as the module, because a
module can be missing from two places and *"`domain/`: variants.py exists but is
not listed"* would send the reader to the wrong file.

The README's *"This table is not checked against anything"* line was true when
written and is now false; it is replaced by a description of what does check it.

*[One asymmetry between the two, pinned by a test rather than smoothed over:
`CLAUDE.md` names a package in a heading, so a package survives its last module
being dropped from the list and the drift reads "module missing". The README
derives groups from the paths, so dropping the last `domain/` row removes the
package from the document and the drift reads "package missing". Both name the
fault; the messages differ because the documents do.]*

**Extended again the same day to the README's Commands table** — the fourth
instance, and the first caught before it broke rather than after. The gap block
this replaces said the table "has not gone stale yet, which is exactly what was
true of the Architecture table on 2026-08-28"; acting on that rather than filing
it is the whole difference between three corrections and a check.

**This one compares a document to the thing it documents, not to another list.**
`app_commands` reads `registered_commands` and `registered_groups` off the Typer
app at import — no invocation, no `CliRunner`, no argument parsing — so there is
no second hand-maintained inventory that could itself drift. That makes it a
stronger guard than either module check, which compare a document to a directory
listing. Groups are walked recursively (nothing nests today; the recursion costs
two lines and closes the hole), an unnamed command falls back to its function
name the way Typer derives it, and hidden commands are returned separately: `plan
optimize` is a deliberate alias documented inside `plan optimise`'s row, so it
must not be required — but a row promoting it is told it is a hidden alias rather
than that it does not exist, which would be untrue.

The prose count in the same paragraph — *"Eight commands."* — is checked too. It
is the same hand-maintained number, one line above the table, that would go stale
by the same mechanism.

`structure_drift` is **not** reused for this one, and the reasoning is in the
test: it compares `{group: {member}}` mappings and phrases findings in terms of
packages and `src/fpl_cli/`. A command set is a flat set of paths, and forcing it
through that shape would give accurate comparisons with wrong nouns. The
comparison is a six-line set difference — a different check, not a second copy of
the module checker.

`[gap: `--help` text itself is still unchecked. The table's *descriptions* are
prose and can say anything, including something a command no longer does; only
the command's existence is guarded. Comparing descriptions to docstrings was
considered and not attempted — they are deliberately written differently, the
table being one line and the docstring several.]`

**Status: closed — by a check, not a correction** — `task/fu-19-18-13` (2026-08-28).
`tests/test_claude_md_structure.py` parses `CLAUDE.md`'s Structure block, walks
`src/fpl_cli/`, and fails naming every disagreement: a module that exists and is not
listed, a module listed that does not exist, a package no group mentions, and a
*"Not yet written"* entry naming something that exists. Verified in the intended order
— the guard was written first and **failed against the block as it stood**, reporting
both faults by name (`domain/optimizer.py` missing from the `domain/` group, and the
*"Not yet written"* line naming a module that exists) — and the block was corrected
afterwards, in the same commit. `optimizer.py` is now listed and the *"Not yet written"*
line is gone, there being nothing left in it.

The check is deliberately a check rather than a third correction. Two regressions by the
same mechanism is a missing guard; a third hand-fix would have restored the same
condition that produced the first two. Following FU-3's AST scan, it reports drift by
name so the failure says what to change, and it reports **all** drift rather than the
first — the block is edited by hand, and being sent back once per module is how it stops
being edited. `CLAUDE.md` now points at the test, so the obligation is visible from the
thing being maintained.

`[gap: the guard covers `src/fpl_cli/` only, which is what the block claims to
describe. It does not check the `docs/plans/` pointer, the Commands block, or the Stack
list, all of which are hand-maintained in the same way and none of which has regressed
yet. FU-15 records the README's equivalent staleness, which nothing checks either.]`

**The regression this closed** (2026-08-28 reconciliation, checked against `99e5afb`).
`CLAUDE.md`'s Structure block still read *"Not yet written: domain/optimizer.py."*
`src/fpl_cli/domain/optimizer.py` is 960 lines and has been on `main` since
`task/optimise-cli`; `domain/` in that same block does not list it either. The close
below was correct when written — the line was reduced to `optimizer.py` alone, and
`optimizer.py` genuinely did not exist — but the entry is *"the 'not yet written' line
is stale"*, and it is stale again in the same field.

This is the same failure mode the original close diagnosed, and it recurred the same
way: the commit that **added** the module did not update the block naming it as
missing. The first time it was `b522572` adding `builder.py`; this time it is the
`plan optimise` work adding `optimizer.py`. That is twice, which makes it a property of
the block rather than an accident — `CLAUDE.md`'s Structure section is a hand-maintained
list of files that nothing checks against the tree, so it is wrong by default whenever a
module lands and right only when someone remembers.

**Fix:** delete the *"Not yet written"* line — there is nothing left in it — and add
`optimizer.py` to the `domain/` list. **Not done here:** this branch reconciles
`follow-ups.md` and changes nothing else. *[Both done in `task/fu-19-18-13`.]*

`[gap: a test asserting `CLAUDE.md`'s Structure block against the actual tree would
close this permanently and is the only thing that would. Not filed as its own entry
because the reconciliation pass has no mandate to invent work; noted here so the option
is on the record next time this regresses.]` *[Closed in `task/fu-19-18-13` — this is
the test that was written, and the reason the entry above closes as a check rather than
a correction.]*

**Original close, left as written** — `33cd761` *Give typer.Exit an exit code, not a
message (FU-3, FU-16); fix CLAUDE.md Structure (FU-19)* (2026-08-26). Verified against
the tree at the time:
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

`projections.py:219-236` maps `event -> team -> list[_FixtureLeg]`, skipping
fixtures with `event is None`. It is the **only** machinery in the repo that
knows about blank and double gameweeks, and it is private to `projections.py`.

*[Line numbers re-checked 2026-08-28 against `99e5afb`; originally `216-233`.
`_build_schedule` is still private and there is still no `fixture_count` helper. It now
has three call sites inside the module (`projections.py:257, 334, 376`), one per
projection model — so the "second caller" test this entry proposes for promoting it is
already met internally, though not yet by anything outside the module.]*

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
(`models.py:22, 23, 27`) but not `chance_of_playing_this_round`, which the API
also publishes. `_availability` (`projections.py:59-66`) therefore has one
numeric availability signal where the API offers two.

*[Line numbers re-checked 2026-08-28 against `99e5afb`; the model fields were cited as
`21, 22, 26`. `_availability`'s range is unchanged at `59-66`, and its body is
unchanged: `chance_of_playing_next_round` first, then `status` in {"d", "a"}.
`chance_of_playing_this_round` still appears nowhere in `src/`.]*

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

`best_xi` (`domain/squad.py:279`, returning `BestXI` at `:92`) returns
`(starters, captain)` — no vice-captain. `validate_plan` (`domain/squad.py:64-66`)
requires one: it must be one of the starters and must differ from the captain.

**Not needed yet** — nothing currently calls `best_xi` to produce a plan file.
It becomes load-bearing once `fpl plan optimise --output` (or whatever writes
a `SquadPlan`/ledger from optimiser output) exists: that round-trip needs a
complete, `validate_plan`-passing file, so the write path can't omit
`vice_captain`.

*[Re-checked 2026-08-28 against `99e5afb`; `validate_plan`'s vice-captain checks were
cited at `55-60`. **`fpl plan optimise --output` now exists** (`cli.py:648`) — but the
trigger this entry names is still unmet, and the distinction is the whole point of the
entry. `--output` writes a **transfers plan** through
`transfers.write_transfers_plan` (`domain/transfers.py:116`), a mapping of event to
transfers; it does not write a `SquadPlan` or a ledger, so `validate_plan` is not on
that path and no `vice_captain` field is emitted or required. The entry stays open and
still-not-urgent, but its "once `--output` exists" wording now reads as satisfied when
it is not — the condition is a writer of `SquadPlan`, not the flag.]*

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

`xi_structure` (`domain/squad.py:161`) builds one structure serving both halves of the
FU-24 split, so `xi_value` (`:257`) pays for two things it never reads: the per-position
`ranked` tuples, which only the witness materialises from (built at `:176`, filled at
`:191`), and the `XiStructure` container. It also calls `legal_formations`
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

*[Re-checked 2026-08-28 against `99e5afb`. Two symbols this entry names were renamed by
FU-26's `NodeScorer` work and no longer exist under the cited names: `_xi_structure` is
now the **public** `xi_structure` (`squad.py:161`) and `_XiStructure` is now
`XiStructure` — the kernel needed the structure across the module boundary. Body
updated. The measurements (43.8 µs / 33 µs / 24.9 µs, 1.76×) are **not** re-verified:
they were taken on a live snapshot with a benchmark that is not in the repo, and
re-taking them needs a pinned capture under FU-40's rule. Treat them as indicative of
the shape, not as current figures. The substance is unchanged — the witness-only
`ranked` tuples are still built for both callers, and the won't-do recommendation still
stands.]*

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

`simulate_plan` (`cli.py:384`) builds `model = ComponentProjection(...)` unconditionally
— there is no way to tell it which model to project with. `fpl plan optimise`
(`cli.py:637`) takes `--model component | naive | official-ep`.

*[Line numbers re-checked 2026-08-28 against `99e5afb`; originally `cli.py:244`.
The defect is unchanged: `simulate_plan`'s signature is
`(squad_path, transfers_path, snapshot_path)` — no `--model`. Both commands did gain
`--snapshot` from `task/snapshot-pinning`, which narrows the *other* half of the
round-trip's exposure (both sides can now be pinned to one capture) without touching
this one. If anything that sharpens the entry: the round-trip is now reproducible and
still not comparable.]* Run it with anything but the
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
arguments (`optimizer.py:849-851`, defaults `DEFAULT_BEAM = 4`, `DEFAULT_FIRST_MOVES
= 50`, `DEFAULT_MAX_CELLS = 800_000_000`), but `optimise_plan` (`cli.py:638-651`)
does not thread any of them through — there is no way to run `fpl plan optimise` at a
non-default beam width, or to raise the cost ceiling, from the command line at all.

*[Re-checked 2026-08-28 against `99e5afb`; originally `optimizer.py:785-787` and
`cli.py:454-465`, with `DEFAULT_MAX_CELLS = 400_000_000`. The default was raised to
800M by FU-28 (`b9706c6`) — see FU-39, which exists because of that raise. The three
flags are still absent: grepping `"--beam"`, `"--first-moves"` and `"--max-cells"` in
`cli.py` returns nothing, while `optimise_plan` has since gained `--decay`,
`--robustness`, `--explain`, `--output`, `--json` and `--snapshot`. Six flags were added
to this command without these three, which is worth weighing when the entry is
picked up: the omission is now a deliberate-looking gap rather than an oversight.]*

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

`_dominance_pool` (`optimizer.py:191`) admits a player on `can_transact and not
removed` (`optimizer.py:231`). `validate_squad_structure` (`rules.py:57`) rejects a
squad containing one that is `not can_select or removed`. `can_select` is not checked
between the two on the admission path, so
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

*[Re-checked 2026-08-28 against `99e5afb`. **This entry is confirmed still open, and
FU-28 explicitly left it so.** `optimizer.py:219-223` carries the note in the source:
*"Admission — `can_transact and not removed`. Unchanged. … **FU-35 owns this line, not
FU-28.**"* The admission list at `optimizer.py:231` is unchanged, as that note says.

What FU-28 *did* change is narrower and answers half of the authoritative-flag question
above: dominance **counting** now additionally requires `_validator_usable`
(`optimizer.py:180-188`), which mirrors `rules.py:57`. So for "may this player be
counted as a dominator", the validator's `can_select` is now authoritative — FU-28's
exchange argument needs a dominator that can legally replace the excluded player. For
"may this player enter the pool at all", nothing has changed and the two predicates
still disagree. When this entry is picked up, the question is narrower than as written:
not "which flag is authoritative" in general, but "should admission follow counting",
where counting has already been settled.

Line numbers corrected above (`optimizer.py:184` → the function at `:191`, the admission
list at `:231`); `rules.py:57` is unchanged. The measurements — 189→185 pool, four
players, 335 rejections, 42 of 614 snapshot-wide — are **not** re-verified: they were
taken against a live snapshot that no longer exists, and re-taking them needs a pinned
capture under FU-40's rule.]*

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

## FU-40 — A measurement quoted in a plan or a commit message must name the captures **and the model version** it came from

**Standing requirement, not deferred work.** `--snapshot` and the `provenance` block
exist as of `task/snapshot-pinning`; what remains is the discipline of using them,
which no test can enforce.

**Status: open — and open permanently, by construction.** Not closable: a rule about
what a human writes in a commit message has no code to check. Re-read 2026-08-28
against `99e5afb`. The rule stands as written; **two passages of the reasoning below
are now out of date**, both because FU-41 landed the bundle format this entry assumed
would not exist. They are marked inline rather than rewritten, because the argument for
the rule is the part worth preserving and it is unaffected.

**The rule.** Any figure quoted in `docs/plans/` or in a commit message must name
**all three** things it was measured against: the pinned bootstrap-static capture, the
fixtures cache, and **the model version that produced it**. Path and `captured_at` for
the two captures; the registered variant name for the model. "Measured against the
cached snapshot" names a file, not a version of it, and both files are rewritten in
ordinary use.

*[**Extended to the model version, 2026-08-29 (`task/model-versioning`).** The
original rule covered the two inputs and said nothing about the code that consumed
them, which was defensible only while there was exactly one configuration of each
model. FU-47 introduces several — rate-shrinkage.md §7 enumerates sixteen constants
across seven rates — and they are compared against the same actuals in one run, so a
figure naming only its captures no longer identifies what produced it.*

*The same argument as the original, one level up: `component/1.0+banded` named a file
of code, not a version of it. Measured on `task/model-versioning`, four materially
different models all reported that string, projecting Haaland at GW3 as 3.430, 2.993,
17.243 and 5.081 — `minutes_config` and `defcon_thresholds` appeared in the version
string nowhere at all. A figure citing both captures and `component/1.0+banded` was
therefore **not** reproducible, and nothing said so.*

*`domain/variants.py` closes the code half the way `--snapshot` closed the input half:
the version string is a property of a registered variant, and
`tests/test_variants.py` pins a digest over every constant each variant holds, so a
constant cannot move while the name stays put. What that buys is that citing the
version name is now sufficient — before, it would have been citing a label.*

***What to quote.*** *The registered variant name, exactly as it appears in
`Projection.model_version` and in `plan evaluate`'s table — e.g.
`component/1.0+banded`, not "the component model". For a run comparing variants, name
each. `plan optimise --json` already carries it as `model`.*

***What is enforced, and what is not.*** *A digest test stops a registered variant
drifting. Two further holes were found while reviewing this, and only one of them
could be closed:*

- ***Closed.*** *An unregistered `ModelVariant` could take a registered name, hold
  different constants and emit the same version string — worse than the old literal,
  because the registry blesses that string, so the digest test would pass while the
  figure came from something else. Measured: an impostor `component/1.0` projected
  Haaland at GW3 as 2.993 against the registered 3.430, both stamped
  `component/1.0+banded`. `variants.build` now refuses a variant whose name is
  registered but which is not the registered instance. Unregistered names stay free.*
- ***Open, and unenforceable.*** *Constructing `ComponentProjection(...)` directly
  with a hand-made `minutes_config` bypasses the registry entirely and reports the
  fallback literal from `projections.py`, as drift-prone as it ever was. Nothing can
  catch that without removing the fallback, which every test constructing a model
  directly depends on. Figures must come from a registered variant, and that — like
  the rest of this entry — is a discipline with no test behind it.]*

```bash
fpl plan optimise squad.json --snapshot ~/fpl-pinned/gw2-pre-deadline.json --json
```

The payload's whole `provenance` block is the citation — both lines of it — and copying
only `provenance.snapshot` is the failure this entry exists to prevent:

```
snapshot ~/fpl-pinned/gw2-pre-deadline.json  (captured 2026-08-28T07:26:38Z)
fixtures ~/.fpl-cli/fixtures.json            (captured 2026-08-28T00:32:59Z)
model    component/1.0+banded
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

*[**Superseded for directory captures, 2026-08-28 (`670859c`, FU-41).** The paragraph
above is true only of a **bare-file** pin now. A capture is a directory holding
`bootstrap-static.json` and `fixtures.json` together with a manifest recording a sha256
for each (`storage/capture.py:28-29, 273-285`); `PinnedSnapshotService.load_fixtures`
reads the capture's own fixtures and verifies them, reporting
`provenance.fixtures.source` as `pinned` rather than `cache`. So for a directory
capture the drift described above cannot happen, and two pinned runs on different days
**do** agree on fixtures.

The rule is unchanged and the fixtures line is still not optional — it is now the thing
that tells a reader *which* of the two situations produced the figure. Read
`provenance.fixtures.source`: `pinned` means the fixtures came from the capture and the
citation is complete; `cache` means a bare-file pin fell back to
`~/.fpl-cli/fixtures.json` and every word of the paragraph above applies. The four
pre-FU-41 archives are bare files, and one of them is the only pre-deadline capture for
GW2, so `cache` remains reachable and is not a legacy case yet.

Line numbers also drift: `load_fixtures`'s write is `api/snapshots.py:364` and
`refresh_fixtures`'s is `:370` (originally `:155` and `:161`).]*

The exposure is not confined to blanks and doubles. `_build_schedule`
(`domain/projections.py:219`) turns the fixtures list into opponent *and venue* per team
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

*[**Half closed, 2026-08-28.** The gap above had two halves and they have diverged:*

- ***Fixtures: closed*** *by FU-41 (`670859c`). The bundle format landed; a directory
  capture pins fixtures alongside bootstrap-static, digest-verified.*
- ***Event-live: open***, *and the paragraph above still describes it exactly.
  `storage/capture.py` writes and verifies two files and there is no third
  (`capture.py:171, 273-285`), so a pinned run still reads
  `~/.fpl-cli/events/{gw}-live.json` through the ordinary cache. FU-43 (`99e5afb`)
  narrowed the damage without closing this: an event-live payload now records whether
  the gameweek had settled, and a pinned run refuses one that cannot prove it was
  final — so a provisional payload can no longer be scored as final. A settled payload
  is still not pinned, and if it is later corrected the figure moves without the capture
  moving.*
- ***`plan evaluate` still has no `--json`***, *so the sentence above stands: a figure
  from it carries its event-live provenance by hand. What FU-43 added is a console line
  stating finality (`cli.py:1021`), which is a partial substitute — it tells a reader
  whether the actuals were final, but not which file they came from or when it was
  written. FU-43's own gap block asks for the flag; FU-13 tracks the wider surface.]*

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

**Status: partially closed** — `99e5afb` *Merge task/event-live-gate* (2026-08-28).
Checked in the source, not taken from the commit message.

**The half that is closed — the gate.** `api/snapshots.py:117` defines
`LIVE_CACHE_VERSION`, and `_parse_live_event_cache` classifies a cached payload
`settled` / `unsettled` / `unknown` from the `finished` and `data_checked` it records.
`SnapshotService.load_event_live` requires `cached.state == LIVE_SETTLED` before a cache
hit and otherwise refetches; `PinnedSnapshotService.load_event_live` raises
`PinnedSnapshotError` for either non-settled state and no longer consults the pinned
snapshot at all. `evaluate_plan` calls `_report_live_provenance` (`cli.py:1021`), which
prints finality in both directions.

**The half that is not — event-live is still not in the capture.** `storage/capture.py`
writes and verifies exactly two files: `BOOTSTRAP_FILENAME` and `FIXTURES_FILENAME`
(`capture.py:28-29`, `171`, `273-285`). There is no third. So a pinned run still reads
`~/.fpl-cli/events/{gw}-live.json` through the ordinary cache, the manifest still does
not cover it, and two pinned runs of the same capture can still read different actuals
if the payload is corrected between them. The gate stops a *provisional* payload being
scored as final; it does not make a *settled* one reproducible.

This is snapshot-pinning.md §5's first gap and the FU-41 note above, both of which stand
unchanged. Do not read this entry as closing them.

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

---

## FU-45 — `Projection` cannot say which of its fields a model does not model

**Deferred from:** `task/fu-44-project` ([players-project.md](players-project.md) §1.1).

`Projection` carries `p_start`, `xmins` and the eight components as plain floats, so
a model that does not model a field has no way to say so — it must put *something*
there. All three current models do, and they mean three different things:
`ComponentProjection` sets `p_start` to the minutes model's real start probability;
`NaiveProjection` sets it to the availability scalar, which is not a start rate;
`OfficialEpProjection` sets it to `0.0` and records the fact only in prose, in its
own `assumptions` tuple (*"p_start and xmins are not modelled"*).

A consumer therefore cannot distinguish "this player has a 0% chance of starting"
from "this model does not compute that" without knowing which model produced the
row. `fpl players project` special-cases it by matching the `--model` string
(`cli.py`, `_START_NOTES` and the `start_pct=None if model == "official-ep"` line),
which works and is honest — the column renders an em dash rather than a fabricated
`0%` — but it is a string comparison in the CLI standing in for a property of the
model.

**Why it is not urgent.** One consumer, one field, one model. The failure is
contained and visible.

**Why it will not stay that way.** `plan optimise --explain` already renders the
eight components, and `NaiveProjection` puts its entire `xp_total` into
`xp_appearance` with the other seven at `0.0` — the same ambiguity, on eight fields
rather than one, already shipped. Any second consumer of a component field repeats
the string comparison.

**Candidate fix:** a `modelled: frozenset[str]` on `Projection`, or `None` as the
sentinel for an unmodelled float. The sentinel is smaller but widens every field's
type; the set is explicit and costs one line per model. Prefer the set. Either way
the `assumptions` prose stays — it explains, where this would only mark.

---

## FU-46 — the horizon fixture total is never checked against real blank or double data

**Deferred from:** `task/fu-44-project` ([players-project.md](players-project.md) §4).

`fpl players project`'s "Next N" column shows the total fixtures across the horizon
in brackets, which is what makes the per-gameweek mean beside it interpretable — a
`(4)` over a horizon of 5 is a blank, a `(6)` is a double. The arithmetic is covered
by `tests/test_players_project.py::test_fixture_count_and_mean_span_a_blank_and_a_double`
against **constructed** fixtures.

It has never been exercised against real data, and currently cannot be: in the
cached fixtures list all 20 clubs play exactly once in each of GW2–GW6, and no
fixture has a null `event`. Every real row reads `(5)`. A verification run therefore
cannot distinguish a correct total from one that echoes the horizon length — that
mutation is caught by the synthetic test and by nothing else.

**Not a defect in the command.** It is a property of the fixture list this early in
a season; blanks and doubles arrive with cup competitions and postponements.

**What to do, when there is data:** re-run `fpl players project` against a capture
whose horizon contains a real blank or double and confirm the bracketed total
against `fixtures.json` by hand. Worth doing once, and worth doing on the first
capture that has one, since the same fixture list feeds every projected cell.
The same gap applies to `Projection.fixtures` generally, not only to this column —
`_build_schedule` is the only blanks-and-doubles machinery in the repo (FU-20) and
none of its real-data behaviour has been observed.

---

## FU-47 — per-90 rates are consumed raw, so one good match dominates the ranking

**Status: the principle is fixed; the parameters are not.** `08f6e54`
(`task/fu-47-shrinkage`, 2026-08-30), designed in
[rate-shrinkage.md](rate-shrinkage.md). Read the two halves separately — they are
different kinds of claim and the entry is not closed in the ordinary sense.

**What landed — the half that is settled.** `shrink_rate(raw, minutes, prior,
prior_minutes)` generalises the shrinkage `xp_bonus` already had, and all seven
rate knobs now go through it: the four `*_per_90` API inputs, yellow and red, and
bonus. They are computed once per player into a frozen `_ShrunkRates` and passed
to `_component_points_for_fixture`, which **no longer receives a `Player` at
all** — there is nothing left for an unshrunk rate to arrive on.
`tests/test_rate_shrinkage.py` scans that function's AST for the two shapes the
defect took and reports every site; run against the pre-fix code it finds all
eight. Priors are pooled from the snapshot by exposure, so the fix removes
hand-set constants rather than adding twenty-eight.

**Scope was six rates, not the four this entry names.** The entry's body below is
correct about the four `*_per_90` fields and misses two, both found while
designing the fix: `xp_cards` built its own per-90 inline and so would have
survived a fix scoped to `*_per_90` fields, and `xp_bonus` had the right algebra
with its prior pinned to zero rather than the league rate. rate-shrinkage.md §1.3
records both. That a fifth instance already existed is the argument for the guard
— it is a regression test, not a precaution.

**What is *not* settled — the parameters.** Every `M` is chosen, not measured,
and the plan says so at length: §9.2 files them all under "chosen because it
looked best, and must be measured", §5 calls 270/90/270 "demonstration
parameters, not proposed values", and §4.3 *measures* that they cannot be
estimated from one gameweek — Gamma-Poisson empirical Bayes returns negative
excess variance for xG, xA and saves in every position. There was therefore no
recommended parameterisation to register, and the values in
`domain/variants.py` are §5's demonstration figures plus mid-range picks from
§7's table for the three rates §5 does not name.

**The price-versus-position question is open, deliberately.** `component/1.1-price`
and `component/1.1-position` are registered as a **pair** rather than one being
chosen: they differ in exactly one thing — whether xG and xA shrink toward a
price-conditioned prior or a position-only one — and a test asserts that is the
only difference, so any gap between them is attributable to price conditioning
and nothing else. The evidence for price is Spearman 0.458 (MID xG90) from a
single gameweek, thinner than the plan's other measurements. This is what the
registry was built for; settle it by evaluation, not argument.

*[Still open after GW2, and after 1.1-price became the default on 2026-09-01.
The GW2 gap is 0.005 on Spearman(all) and 0.012 on Spearman(played), both inside
the 0.02 threshold, so the evaluation did not settle it and the pair is still a
pair. 1.1-price was made default over 1.0, not over 1.1-position. FU-50 fixes the
criteria for the next attempt.]*

*[Superseded 2026-09-01 by `task/default-1.1-and-preregistration`. Left as
written; the correction follows it.]*

**`component/1.0` is unchanged and remains the default.** Projections are
byte-identical to pre-branch `main` across all 3080 rows —
sha256 `c3812c8cae30c609b41243f3a26dcc49450c8b03993604ffb6129470037a7412`,
pinned to `~/fpl-pinned/gw2-pre-deadline.json` and `~/fpl-pinned/gw2-fixtures.json`
(captured 2026-08-28T07:26:38Z). 1.1 becomes the default only if a leak-free
evaluation supports it, and a test fails if the `component` alias or
`plan evaluate`'s default set starts pointing at it.

**The default is now `component/1.1-price`.** The `component` alias and
`_DEFAULT_EVALUATE_MODELS` both point at it; the test quoted above was inverted
rather than deleted, and now asserts the new pairing plus that `component/1.0`
stays *registered*. It does: every figure in this file measured against 1.0 is
still reproducible by naming it in full.

**The reason is the correctness argument, not the evaluation.** 1.0 consumes the
API's per-90 rates as published, so one minute played can yield 270 defensive
contributions per 90 — this entry's own headline defect. rate-shrinkage.md makes
that case without reference to any gameweek and it would stand if GW2 had gone
the other way, which is exactly why the switch is not conditional on the
scoreboard. What GW2 supplies is the removal of a contradiction: against 1.0,
1.1-price wins Spearman(all) 0.551 vs 0.536, Spearman(played) 0.359 vs 0.269 and
RMSE(played) 3.036 vs 3.148, and loses RMSE(all) 2.411 vs 2.405 — by 0.006.
Pinned to `~/fpl-pinned/gw2-pre-deadline.json` (sha256 `593f60c2e356…`),
`gw2-fixtures.json` (`fbd4457e5c81…`) and `gw2-live.json` (`afdaf81a6fcd…`),
model versions `component/1.0+banded` `fb431918c08c` and
`component/1.1-price+banded` `24c305e2025c`, per FU-40.

**What the switch does not establish, stated so it is not read as more than it
is.** The parameters are still **chosen, not measured** — the paragraph above on
§9.2, §5 and §4.3 is unaffected by this branch and nothing in GW2 fits any `M`.
Price versus position is still **unresolved**: the Spearman(played) gap is 0.012
against the 0.02 threshold that was fixed in advance, on one gameweek, with no
error bars. Making 1.1-price the default is not a finding that price
conditioning beats position conditioning; it is a choice of one of the two
shrunken variants over the unshrunken one, and the pair remains a pair. **FU-50**
fixes the criteria for settling it before the GW4/GW5 data exists.

`[gap: the only evaluation available is GW1, which leaks — the flat baseline
scores a perfect 0.000 because points_per_game after one gameweek *is* that
gameweek's score. Under it 1.1 scores worse than 1.0 (RMSE 2.457/2.472 against
2.241; Spearman 0.652/0.658 against 0.707), and price and position disagree by
about 0.006 in opposite directions on the two metrics. **None of that is
evidence either way.** The first honest comparison is the first gameweek whose
deadline post-dates a capture, and until then neither 1.1 variant should be
quoted as better or worse than 1.0.]`

*[Closed 2026-09-01: that comparison is GW2, run against a capture taken 16h57m
before the deadline. It reverses the GW1 ordering — 1.1-price now beats 1.0 on
three of the four metrics — which is what the gap predicted would happen once the
leak was removed, and is the reason the GW1 figures above must not be cited. The
successor caveat is not that the comparison is missing but that there is exactly
one of it, on one gameweek, with no error bars.]*

`[gap: rate-shrinkage.md §9.3 is the standing caveat and survives this commit —
the change is more internally consistent but not measurably better, and must not
be presented as an improvement to accuracy.]`

**The original entry follows, for the record.**

**Deferred from:** `task/fu-44-project` — found by the first run of
`fpl players project` against `~/fpl-pinned/gw2-pre-deadline.json`, 2026-08-29.

**This is a projections defect, found by the diagnostic that was built to find
exactly this.** It is filed rather than fixed because it changes the model, not the
command that revealed it.

`ComponentProjection` shrinks three inputs toward priors — the start rate, minutes
per start, and bonus per 90 (`projections.py`, Decision 4 and the `xp_bonus` term) —
and consumes four others **exactly as the API publishes them**:
`expected_goals_per_90`, `expected_assists_per_90`, `defensive_contribution_per_90`
and `saves_per_90`. After one played gameweek those are per-90 extrapolations from a
single match, and for a substitute from a few minutes.

Measured on that capture, projecting GW3:

| Player | Rate as published | Effect |
|---|---|---|
| De Cuyper (BHA, DEF) | `xG90 = 1.72` from 77 minutes | `xp_attack = 7.96` of a 10.28 total — top of the table, ahead of every forward |
| Alcaraz (EVE, MID) | `dc/90 = 270.0` from **1 minute** | `xp_defcon` saturates at its 2.00 cap |
| Haaland (MCI, FWD) | `xG90 = 0.74` from a full 90 | 3.43 total, 26th |

A left-back projecting 10.3 in a gameweek, and a forward with the best underlying
numbers in the league sitting 26th, are both wrong in the direction the shrinkage
elsewhere in the model exists to prevent. The minutes model is not at fault here:
`p_start` reads 72% and 44% respectively, which is reasonable. It is the rate terms
those probabilities multiply.

**Why it matters beyond the table.** `plan optimise` ranks on `xp_total`, so this
feeds the search directly, and it is worst early in the season — exactly when
transfer planning is most active and when the model has least data to correct
itself.

**Candidate fix:** shrink the four rates toward a positional prior on minutes
played, in the shape `xp_bonus` already uses
(`raw * minutes / (minutes + shrinkage_minutes)`), which is already in the file and
already has a constant chosen for it. That gives one mechanism for all rate terms
rather than a second invented one. The prior per position is a new
`[assumption: no empirical basis]`, and should be flagged as such alongside the
existing seven.

**Do not fix without the harness.** `fpl plan evaluate` is the only thing that can
say whether shrinkage helps, and its first leak-free run is still pending (README,
Known limitations). Shrinking the rates would be principled and unmeasured, which
is the state the whole model is already in — but a change made in that state should
at least be recorded as such, not presented as an improvement.

*[The leak-free run happened on 2026-09-01, against GW2. It says shrinkage helps
on three of four metrics and costs 0.006 of RMSE(all). That is one gameweek, so
the sentence above still governs: the change was made on the correctness
argument and is recorded as such, not presented as a measured improvement.]*

---

## FU-48 — `doubtful_chance` is unreachable: every non-`a` status publishes a percentage

**Deferred from:** `task/model-versioning`, while choosing the parameter for its test
fixture variant. Filed here rather than left as a gap comment in
`domain/variants.py`, because it is a projections question adjacent to FU-47, not a
registry one.

`MinutesModelConfig.doubtful_chance` (`DEFAULT_DOUBTFUL_CHANCE = 0.75`,
`projections.py`) is one of the seven constants the minutes-model block carries under
`[assumption: no empirical basis for any constant in this block]`. It is also
**dead on every capture this repo has ever held.**

`_availability` tests the published percentage first:

```python
if player.chance_of_playing_next_round is not None:
    return player.chance_of_playing_next_round / 100
if player.status == "d":
    return config.doubtful_chance          # <- only reachable when the above is None
```

So `doubtful_chance` is reached only for a player who is doubtful **and** carries no
published chance. Measured across every bootstrap-static payload on this machine —
the pinned `~/fpl-pinned/gw2-pre-deadline.json`, the four bare archives, five capture
directories, and the live cache; 11 captures spanning 2026-08-25 to 2026-08-30:

| | |
|---|---|
| `status="d"` observations | **203** |
| ...with `chance_of_playing_next_round` null | **0** |
| distinct players ever seen `"d"` | 34 |

**The pattern looks structural rather than incidental.** On the current snapshot the
null rate is 90% for `status="a"` (444 of 494) and **0% for every other status** —
`d` 0/18, `i` 0/58, `s` 0/2, `u` 0/51. The API appears to publish a percentage
whenever it publishes anything but "available", which is exactly the case the
`status == "d"` branch was written to cover.

**Why it matters more since `task/model-versioning`.** `doubtful_chance` is now a
registered-variant knob covered by the digest. A variant setting it gets a distinct
digest and a distinct version string, and would produce **identical projections** —
two names for one model, which is the failure FU-40's extension exists to prevent,
arriving from the opposite direction. This was found the practical way: it was the
first choice for that branch's fixture variant and was rejected on measurement,
because a fixture that provably moves no number cannot demonstrate that the
comparison path works.

**Not urgent.** Nothing is wrong with the output; a constant simply has no effect.

**Options, none chosen:**

- **Delete the constant and the branch.** Smallest tree, and honest about what the
  data shows. Costs the fallback if FPL ever does publish a bare `"d"`, in which case
  availability would drop to the `return 0.0` at the end of the function — treating a
  doubtful player as ruled out, which is worse than 0.75 and would be silent.
- **Keep it, and say what it is.** A defensive default for a case the API has not
  produced in 203 observations. Cheapest, and leaves a constant that no evaluation can
  ever move — which is misleading in a block whose other six constants are live.
- **Give it something to do.** `chance_of_playing_this_round` is published and parsed
  nowhere (FU-21); a doubtful player mid-gameweek can have the two disagree. That is
  the one route by which this branch could become reachable, and it argues for
  resolving FU-21 first.

`[gap: "structural" is inferred from 11 captures over six days in one season, all
pre-season or early. Nothing in the API documents the invariant — it is undocumented
throughout — so a mid-season or transfer-deadline payload could break it without
warning. The claim here is "not observed", not "cannot happen".]`

---

### The `i`/`s`/`u` half: measured, and it is not a defect

This entry originally carried a second gap, guessing that `i`, `s` and `u` mapping to
`0.0` regardless of a published percentage would treat a 75%-chance player as certain
to miss — a live error on real data, and the half that would have mattered. **Measured
across the same 11 captures, that does not happen.** The gap is left in place below,
struck, because the guess was reasonable and its falsification is the useful part.

| status | observations | publishing a percentage | values seen |
|---|---|---|---|
| `i` | 650 | 650 (100%) | **0% only** |
| `s` | 14 | 14 (100%) | **0% only** |
| `u` | 497 | 497 (100%) | **0% only** |

All 1,161 observations publish a percentage, and **every one of them publishes 0**.
So `_availability` returns `0/100 = 0.0` from its *first* branch, which is exactly
what the status mapping would have returned. The count of published values that
disagree with the mapping is **zero**. The hypothetical player — `status="i"` with
`chance_of_playing_next_round = 75` — does not exist in any capture held here.

**So the two halves are not symmetric, and not in the direction the gap implied.** The
first half is a real, if harmless, finding: a named constant with no effect. The
second half is a hypothesis this measurement falsifies. Ranked, they are one finding
and one non-finding, and the entry should be read that way.

### The finding that subsumes both: two of four branches are dead

Over **6,788 player-observations** across the 11 captures:

| `_availability` branch | taken | share |
|---|---|---|
| published percentage | 1,850 | 27.25% |
| `status == "a"` → `1.0` | 4,938 | 72.75% |
| `status == "d"` → `doubtful_chance` | **0** | never |
| fallback → `0.0` | **0** | never |

The API publishes a percentage for *every* non-`a` status, so the whole status table
below the first branch is decoration: the function is, in practice, "use the published
percentage, else if `a` return 1.0". Both remaining branches are unreachable, not just
the doubtful one.

**And `0.75` is well chosen, which the first half of this entry should not be read as
disputing.** Of the 203 `status="d"` observations, **179 (88%) publish exactly 75%**,
with 50% (17) and 25% (7) as the tail. The constant is dead *and* correct — it matches
the modal published value precisely. That strengthens the "keep it, and say what it is"
option above and weakens "delete it": the fallback, if ever reached, would be right.

*[Superseded gap, left as written:]* `[gap: the same question is unasked for the other
statuses. `i`, `s` and `u` all map to 0.0 regardless of any published percentage, so a
player with `status="i"` and `chance_of_playing_next_round = 75` is treated as
unavailable while the API says otherwise — the inverse asymmetry, and not measured
here.]`

`[gap: the branch counts above are reachability over captures, not a coverage run —
they say the branch was never *taken on this data*, not that it is unreachable in
principle. The same six-day, one-season caveat as the paragraph above applies to all
of it.]`

---

## FU-49 — `plan evaluate` warns that the actuals are provisional and scores them anyway

**Deferred from:** the GW2 evaluation of 2026-09-01, which stopped at its own pre-flight
check. Filed rather than fixed because that session was a measurement task and this is a
command-surface decision with three defensible answers, none of them obviously right.

**The defect.** `evaluate_plan` calls `_report_live_provenance(live_result)`
(`cli.py:1300`) and then, on the next executable line, `actuals_from_live_event`
(`cli.py:1303`) and the full scoring run. Nothing between them consults
`live_result.provenance`. `_report_live_provenance` (`cli.py:1209-1241`) is exactly what
its name says — a reporter. It prints, in yellow, that the actuals are not final and
"do not quote it as one", and returns `None` in both branches. The command then produces
every table it would have produced for a settled gameweek.

So the write path is gated and the read path is not. `SnapshotService.load_event_live`
(`snapshots.py:373`) persists a payload only when `finished and data_checked` — Decision 6,
unchanged since it was written — and the third bullet of FU-43's refuse/warn/refetch
section deliberately *serves* a live fetch of an in-flight gameweek, marked unsettled,
on the grounds that it is the freshest data in existence and there is nothing to fall
back to. That reasoning is still right for the **service**. What was never decided is
what the **caller** should do with a payload it has just been told is provisional, and
the answer it currently implements is "everything, in full, under a warning".

**Why it went unnoticed, which is the interesting half.** FU-43 closed the pinned
service's half of this: `PinnedSnapshotService.load_event_live` (`snapshots.py:662`)
refuses an unsettled or unrecorded payload outright, with a message naming the file, the
flags and the remedy. That entry's second gap states plainly that "in normal operation
the reader's `unsettled` branch is unreachable from this build's own writes" — and read
it as justification for the reader checking rather than assuming. It is also, read the
other way, the reason nobody looked at the unpinned caller: the write gate means no
unsettled payload is ever *cached*, so the only way to reach an unsettled
`LiveEventResult` on the unpinned path is a **live fetch during an in-flight gameweek**.
Every test constructs the state directly. Every ordinary run either has a settled
gameweek or has no payload at all.

That is a narrow window, and it is the worst possible one: an in-flight gameweek is
precisely when an impatient operator runs `plan evaluate` to see how the models did. The
hole is unreachable except by the person most motivated to reach it.

**The evidence, from 2026-09-01.** GW2's ten fixtures all report `finished: true` as of
`2026-08-31T19:00:00Z`, the last kickoff. The event does not: `finished=false,
data_checked=false`, `is_current=true`, still true in a live sync at
`2026-09-01T10:23:54Z` (archived `2026-09-01T102354Z`, adhoc). The gameweek is played and
unsettled, which is the exact state this entry is about.

It is not merely an unflipped flag. `average_entry_score` for GW2 across the archives:

| capture | GW2 `average_entry_score` |
|---|---|
| `archive/2026-08-29/` | 18 |
| `archive/2026-08-30/` | 29 |
| `archive/2026-08-31/` | 66 |
| `archive/2026-09-01/` | 79 |
| `archive/2026-09-01T102354Z/` | **81** |

The last two are ten hours apart with **zero fixtures outstanding** — +2 points of
league-average score after every match had finished. Bonus and stat corrections were
landing throughout, and they fall disproportionately on high scorers, who are exactly the
players a projection model is judged by. A run at any point in that table would have
produced six complete model tables — Spearman, RMSE, error-by-category, error-by-component
— under a yellow warning, against actuals that were still moving underneath it.

**The options, not chosen.**

1. **Hard refusal**, matching `PinnedSnapshotService`. Consistent with the pinned half and
   with FU-43's argument that a warned-past wrong number still gets quoted. The refusal
   costs nothing structurally — event-live is loaded before any projection runs
   (`cli.py:1273`), so nothing has been computed or printed and the remedy is waiting.
   Against it: FU-43's third bullet argued the unpinned service should serve in-flight
   data because it is the only answer available, and a caller that refuses to do anything
   with it makes that decision moot. It also removes a genuinely useful capability — a
   mid-gameweek indication is worth having, as long as nobody mistakes it for a result.
2. **`--allow-provisional` opt-in.** Refuse by default, with the flag naming what it
   permits. The operator who wants an in-flight indication types the word "provisional",
   which is hard to forget having typed, and the flag appears in shell history and in any
   command pasted into a plan or a commit message — so under FU-40 the provenance travels
   with the invocation rather than only with the console output. Against it: another flag
   on a command that FU-13 already wants `--json` on, and it does not stop the *output*
   being quoted once produced.
3. **Leave it as a warning.** Zero change, and the warning is already well written.

**A warning above a full table is the weakest of the three, and that should be recorded
even though the choice is open.** The number is what gets copied — into a plan, a commit
message, an entry in this file — and the warning does not travel with it. This is the same
argument FU-43 used to make `PinnedSnapshotService` refuse rather than warn ("a warned-past
wrong number still gets quoted"), and FU-41 used about fixtures. The asymmetry is that the
argument was accepted for the pinned path and never applied to the unpinned one, which is
the substance of this entry. Recording that is not the same as choosing option 1: options 1
and 2 both act on it, and the case for 3 is that an in-flight indication has real value and
the operator asking for it is not the same person who will quote it six weeks later. Ben
decides.

**Related, not blocking.** FU-13 wants `--json` on `plan evaluate`. If it lands first, the
provenance belongs in that payload under FU-40 whichever option is chosen here, and option
3 becomes materially more defensible — machine-readable provenance *does* travel with the
number in a way a console warning does not.

### `data_checked` is a lagging indicator of finality, not the definition of it

Everything above treats `finished and data_checked` as *the* boundary between provisional
and final. That is the wrong mechanism, and the entry should not be read as asserting it.
The flag is FPL's sign-off that the scores are final; it is not what *makes* them final,
and it does not arrive at the moment they become so.

**The published rule.** For 2026/27, FPL states that a gameweek's points are subject to
change until **09:00 UK on the day after the gameweek's final match**, after which no
further adjustments are made. This is new this season — it was previously one hour after
the final whistle, extended so that post-match Opta review can feed into BPS and DefCon.
So finality is defined by a clock, and `data_checked` is an operator action taken at some
point after that clock strikes.

**The lag is visible in this gameweek's own data.** GW2's last match kicked off
`2026-08-31T19:00:00Z`, so lockdown was 2026-09-01 09:00 UK = **08:00Z**. The live sync at
`2026-09-01T10:23:54Z` — two hours and twenty-three minutes past lockdown — still read
`finished=false, data_checked=false`, with `average_entry_score` at 81. By FPL's own
published rule those scores were final and immutable. The API was still reporting them
provisional, and `_report_live_provenance` would still have printed the yellow warning.

**So there are two errors, in opposite directions, and both belong on record.**

| window | actual state | tool reports | consequence |
|---|---|---|---|
| final whistle → 09:00 UK next day | genuinely provisional | provisional, and **scores anyway** | the defect this entry is filed for — a wrong number that looks valid |
| 09:00 UK next day → flag flip | **genuinely final** | provisional | a correct number disclaimed as provisional, or refused outright under options 1 and 2 |

The second is the milder failure — a false negative costs a delayed measurement, a false
positive costs a wrong one that gets quoted — but it is not nothing. Under **option 1** a
run in that window is refused outright despite the data being final by rule, and under
**option 2** it demands `--allow-provisional` for actuals that are not provisional, which
makes the flag's name a lie in exactly the case an operator would most reasonably reach for
it. Whoever implements either should know the window exists rather than discovering it as a
bug report.

**The recommendation does not change: `data_checked` stays the gate.** A clock-based rule
would have to derive "the gameweek's final match" from the fixtures list and then reason
about BST/GMT boundaries, rearranged fixtures, and postponements that move a gameweek's
last match days after its nominal end — each a way to compute a lockdown time that is
confidently wrong, and wrong in the *permissive* direction, which is the one that produces
a quoted bad number. `data_checked` is FPL's own sign-off, and being late is the safe way
for it to be inaccurate. It is the right gate. It is simply not the definition of finality,
and this entry described the mechanism wrongly by treating it as one.

**How to measure the lag, unblocked and cheap.** The systemd daily capture runs at 01:00 UK
(`archive/2026-09-01/` was written 00:01Z), so consecutive canonical captures bracket the
09:00 UK lockdown by roughly 23 hours — nowhere near fine enough to time the flip. Two
**ad-hoc** syncs on the day after a gameweek's last match, either side of 09:00 UK, would
bracket it: one at ~08:30 UK and one at ~09:30 UK, repeated across a few gameweeks, gives
the distribution of the lag rather than one observation of it. `fpl sync --archive-dir`
keeps these out of the canonical slot, which matters because a claimed slot is never
overwritten (FU-41) and a test capture costs that day's real one. **Note FU-42's gap
applies:** `--archive-dir` protects the archive and nothing else — both syncs still rewrite
`~/.fpl-cli/bootstrap-static.json` and `~/.fpl-cli/fixtures.json` in place, which moves
every cell of any measurement in flight. Do this on a day with no evaluation running, not
alongside one.

`[gap: the fixture schema in this dataset carries eight keys — `event`, `finished`, `id`,
`kickoff_time`, `team_a`, `team_a_score`, `team_h`, `team_h_score`. There is no
`finished_provisional`, no `minutes` and no `started`, so fixture-level provisionality is
not readable here even if a finer-grained gate were wanted. Whether those fields are
absent from the upstream API or dropped by `Fixture` on parse is not established — this
was read off the cached payloads, not off a live response body. Any option above must gate
on the *event* flags, which is what all three assume.]`

`[gap: the `average_entry_score` figures above are the league average, not a model error
measurement. They establish that scores were still moving, which is all this entry claims
of them. What is *not* measured is how much the model rankings themselves would have
shifted between a provisional run and a settled one — that would need both runs, and the
settled one does not exist yet. The bonus-falls-on-high-scorers argument for why the shift
would be biased rather than merely noisy is inherited from FU-43, where it is also
asserted rather than measured.]`

`[gap: "unreachable except by a live fetch during an in-flight gameweek" is reasoning over
the two services' code paths, not a coverage run. A cache written by an older build, copied
from another machine, or hand-edited reaches the same branch — the cases FU-43's envelope
exists for — and the unpinned caller treats those identically, since it reads
`provenance.state` not at all.]`

`[gap: the 09:00 UK rule is stated here on Ben's authority, from FPL's published rules for
2026/27. It is not derivable from anything in `bootstrap-static` or `fixtures` — no field
in either payload carries a lockdown time — so it cannot be checked by this repo's own
data, and under CLAUDE.md's "derive FPL rules from the live API snapshot" it could not be
hardcoded even if a clock-based gate were wanted. That is a third argument for keeping
`data_checked` as the gate, independent of the DST and postponement reasoning above: the
flag is *in* the snapshot and the deadline rule is not.]`

`[gap: this section's own evidence does not time the lag, it only bounds it — the flip had
not happened by 10:23Z, so the lag was **at least 2h23m**. No upper bound: the flip may
have occurred at any point after, and nothing was capturing. The GW1 transition cannot
supply a comparison either, since the only captures spanning it are the 01:00 UK dailies.
One observation, one gameweek, and the bracketing measurement described above is what would
replace it.]`

`[gap: the +2 in the evidence table above (79 at 00:01Z → 81 at 10:23Z) is bracketed by
captures that **straddle** the 08:00Z lockdown, so it does not establish movement *after*
lockdown and must not be read as doing so. Under the published rule it necessarily occurred
before 08:00Z. The table's original claim is unaffected — it was that scores moved after
every match had finished, and the last whistle was ~20:50Z the previous evening, so both
readings sit in the post-whistle, pre-lockdown window where movement is expected. The
figures are left as written; this is a tightening of what they prove, not a correction of
them.]`

---

## FU-50 — Pre-registration for the GW4/GW5 model decisions

**This entry is a written commitment, not a feature.** Nothing here is to be built.
There is no rule engine, no criteria file, no `--criteria` flag, and no code change
of any kind implied by this entry. It is a decision rule written down before the data
exists, so that the decision can be made against it afterwards rather than around it.
The only artefact is this text.

**Filed from:** `task/default-1.1-and-preregistration`, 2026-09-01, alongside the
switch of the default to `component/1.1-price`.

### Why this exists: the GW2 rule was underspecified, and it showed

The rule fixed in advance for GW2 was *"1.1 replaces 1.0 only if it wins on both
Spearman and RMSE"*. When it was written there was one Spearman column and one RMSE
pair. By the time it was applied there were two of each, because `spearman_played`
was added on `task/spearman-played` after the rule was set and RMSE had always been
reported over two populations without the rule saying which it meant. The result was
a rule that returned different answers depending on a reading nobody had fixed:

| criterion | winner | margin |
|---|---|---|
| Spearman (all) | 1.1-price | 0.015 |
| Spearman (played) | 1.1-price | 0.090 |
| RMSE (all) | **1.0** | 0.006 |
| RMSE (played) | 1.1-price | 0.112 |

Three of four favoured 1.1-price and the fourth favoured 1.0 by 0.006. Under one
reading the rule said "split, 1.0 stays"; under another it said "1.1 wins outright".
**A pre-registered rule that can be read two ways is not pre-registered**, because
the choice of reading is made after the result is visible, which is the exact
failure the pre-registration was meant to prevent. The default did in the end move,
but on the correctness argument in FU-47 and rate-shrinkage.md rather than on the
metrics — which is the only reason the ambiguity did not decide anything.

Everything below therefore names the metric, the population and the margin.

### 1. Price versus position

**Criterion.** `component/1.1-price` replaces `component/1.1-position` as the
registered default, or vice versa, only if **Spearman restricted to players who
appeared (`spearman_played`)** differs by **more than 0.02** in the same direction
**in each of two separately-evaluated gameweeks**. Otherwise the pair stays a pair
and 1.1-price remains default by incumbency, not by evidence.

**Why `spearman_played` and not the others.** The two variants differ in exactly one
thing — whether xG and xA shrink toward a price-conditioned or a position-only prior
— and a test in `tests/test_variants.py` asserts that is the only difference. That
difference acts on attacking returns among players who feature. `spearman_all` is
dominated by the played/didn't-play split, which neither variant addresses and which
is identical between them; including it would dilute the signal with a population
where the two are near-identical by construction. RMSE is a magnitude metric and
these variants are being asked to rank, which is what the optimiser consumes.

**Why 0.02.** It is the threshold that was already fixed for GW2 and it should not
move now that a figure exists — 0.012 was observed, and revising the threshold after
seeing it would be the precise vice this entry exists to prevent. It is a chosen
number with no error-bar justification, and it stays chosen.

**One population, not both.** `spearman_all` is to be reported as it always is, and
is explicitly **not** a criterion here. Recording both and deciding on one is the
point: the discarded column stays visible so a later reader can see it was discarded
deliberately rather than never computed.

### 2. One gameweek or two: two, and this is the most important clause

**No criterion in this entry may be satisfied by a single gameweek.** Each requires
the same direction and the same margin in **two gameweeks evaluated independently**
— GW4 and GW5, or any later pair. A result in one and a reversal in the other is a
null result, not a tie-break to be resolved by picking the larger margin.

The argument is that every measurement this project has produced so far carries the
same caveat, and it has never once been discharged. GW1 was a leak. GW2 is one
observation with no error bars, and the gaps carrying its conclusions were 0.015,
0.012, 0.005 and 0.006 — all of them small enough that a single gameweek's noise is
a live explanation, and none of them accompanied by any estimate of what that noise
is. The GW2 evaluation reversed the GW1 ordering of 1.0 and 1.1 completely; a third
gameweek reversing GW2 would be entirely unsurprising, and nothing in the record
would distinguish that from signal.

Two is chosen over three or five because it is the weakest requirement that can
detect a reversal at all, and a requirement nobody meets is not a standard but an
excuse to decide informally. Two consecutive agreeing gameweeks is not statistical
power — it is a coin flip's worth of confirmation — and it is stated here as a floor,
not as sufficiency.

**Blanks and doubles disqualify a gameweek from the pair.** GW2 had ten fixtures and
every team playing once, so nothing in it tested the fixture-count term. A gameweek
with a blank or a double confounds the rate comparison with a fixture-count effect
neither variant is being judged on. Check the fixture list before counting a
gameweek toward a pair; if GW4 or GW5 has one, use the next clean gameweek and say
so.

### 3. Tuning the `M` parameters

**Criterion: do not tune them, on any evidence available at GW4 or GW5.** The `M`
constants stay at their present chosen values, and no branch should propose fitting
them on this timescale.

rate-shrinkage.md §4.3 does not report that the parameters are hard to estimate; it
reports that they are **unidentifiable on this data**. Gamma-Poisson method of
moments returns *negative* excess variance for xG in all three outfield positions,
for xA in midfield, and for saves — observed between-player spread is smaller than
Poisson sampling noise alone predicts, so the estimator returns "shrink infinitely",
which would flatten every forward to the same 0.469 xG90. The single plausible cell
(dc DEF, M ≈ 131) sits beside dc MID at M ≈ 2, an artefact of one outlier inflating
a variance to 536. Two more gameweeks change the exposure per player from roughly
one match to roughly three. That does not fix a negative variance estimate; it
scales it.

**What would make them fittable, stated so the condition is checkable rather than
vague.** All three of:

1. **Exposure.** Six to eight gameweeks of accumulated minutes, which is
   rate-shrinkage.md's own figure in its closing gap and is not second-guessed here.
   The quantity that matters is minutes per player, not gameweeks elapsed — a
   rotation-heavy squad accumulates far less. State the median minutes per player in
   the eligible population when the estimate is attempted.
2. **A positive excess-variance estimate.** The estimator must return finite,
   positive `beta` for **at least xG and xA in every outfield position**, not one
   cell in isolation. A single identifiable cell beside an unidentifiable one is the
   dc DEF/dc MID artefact again, and is to be read as failure, not partial success.
3. **Outlier resistance.** The dc MID cell was destroyed by one player. Re-run the
   estimate with the single largest contributor to each cell's variance removed; if
   `beta` moves by more than a factor of two, the cell is not estimated, it is
   fitted to an individual. Report both figures.

Until all three hold, the constants remain `[assumption: no empirical basis]` and
are to be described that way in every quotation of any figure derived from them.
Meeting them replaces chosen constants with measured ones and removes most of
rate-shrinkage.md §9.2 — which is the prize, and the reason to state the condition
rather than drift toward tuning by feel.

### 4. Does the component model earn its complexity? — the control clause

**Criterion.** If the **best** component variant fails to beat `naive/1.0` on
**`spearman_played`** across **two clean gameweeks**, the component model is not
earning its complexity, and **`naive/1.0` becomes the default** until it does.

"Best" means best on `spearman_played` in that gameweek, chosen per gameweek rather
than fixed in advance — the component family gets its strongest showing on each
occasion, so a loss under this clause cannot be blamed on having backed the wrong
variant. "Beat" means strictly greater, with no margin: unlike the price-versus-
position clause this is not asking whether two close things differ, it is asking
whether the complicated thing clears the simple thing at all, and a tie does not
clear it. "Clean" carries §2's meaning — no blanks, no doubles.

**Naive and baseline are one result, not two.** `naive/1.0` and
`baseline/flat-ppg` are near-identical predictors: at GW2 they scored
`spearman_played` 0.330 and 0.331, `spearman_all` 0.619 and 0.613, and identical
0.260 on the restricted p_start population, with identical error-by-component rows
for all seven terms neither decomposes. Treating "component lost to both" as two
independent confirmations would be double-counting one fact. The clause is written
against `naive/1.0` alone for that reason, and `baseline/flat-ppg` continues to be
reported as the floor rather than used as a second test.

**This is a live possibility, not a formality, and the GW2 numbers say so.**
`component/1.0` — the default until 2026-09-01 — lost to persistence on **every
population tested**: `spearman_all` 0.536 against naive's 0.619, `spearman_played`
0.269 against 0.330, `p_start>0.5` 0.406 against 0.547, and `p_start>0.5 & played`
0.231 against 0.260. It was last or near-last on all four. Only shrinkage reversed
it, and only on one of the four: `component/1.1-price` takes `spearman_played` to
0.359 against naive's 0.330 while still losing `spearman_all` 0.551 to 0.619. So
the component family's entire claim to beat its own control currently rests on **one
metric, in one gameweek, by 0.029**, having been comprehensively behind a fortnight
earlier. A repeat that goes the other way is an ordinary outcome, not a surprise.

**Why `spearman_played` and not `spearman_all` or RMSE.** `spearman_all` is
dominated by the played/didn't-play split, which persistence gets close to free —
that is the confound `task/spearman-played` was written to expose, measured at
0.282–0.289 for naive and baseline against 0.192–0.199 for the 1.1 variants.
Judging the component model on a metric it loses mostly for reasons of population
composition would be as unfair as judging it on one it wins for the same reason.
RMSE is excluded because component wins it decisively and always has — it is the
better-calibrated model and the worse-ordering one, and a criterion built from the
metric it already wins would be a formality.

**The honest weakness in this criterion, stated rather than buried.** The optimiser
does not consume a ranking of players; it sums projected points over a squad and a
horizon and ranks *paths*. `spearman_played` is a proxy for that objective, not the
objective. A model that orders players worse but calibrates magnitudes far better
could in principle produce better transfer plans while failing this clause — and
component is exactly that shape of model. The counter is that nothing in this repo
measures plan quality end to end, and choosing a criterion we cannot compute over
one we can is how a decision gets deferred indefinitely. **The proxy is accepted
knowingly.** If someone builds a plan-quality measurement before GW4, that is a
better criterion and §5's revision route is open to it — before the gameweek, not
after.

**What "naive becomes the default" means operationally.** The `component` alias and
`_DEFAULT_EVALUATE_MODELS` point at `naive/1.0`; every component variant stays
registered and re-measurable; `plan optimise`'s robustness line still compares
three models, so the component variants keep dissenting visibly rather than
disappearing. It is a demotion, not a deletion, and it reverses the moment the
clause is met in the other direction across two clean gameweeks.

### 5. These are not to be re-read against a result

**The criteria above are fixed — §§1–3 as of 2026-09-01, §4 as of 2026-09-02 — and
are not to be reinterpreted, narrowed, widened, or have their metric or population
swapped once a GW4 or GW5 figure is visible.** This clause governs §4 exactly as it
governs the others: the control clause was written before the GW4/GW5 answer was
known, and "component lost but only just" is not a reading it admits. If a result lands at 0.019 on `spearman_played`, the answer is
"no change", not a discussion of whether 0.02 was ever the right threshold. If
`spearman_all` disagrees with `spearman_played`, the answer is `spearman_played`,
because that is what this entry says, and the disagreement is to be reported rather
than used.

The criteria **may** be changed, but only in a commit that lands **before** the
gameweek it would apply to is settled, and that says what it is changing and why in
terms that do not reference any figure from that gameweek. A change made after the
data exists is not a revision of the rule; it is the result choosing the rule.

If a criterion turns out to be badly specified — as GW2's was — the correct response
is to record that it was badly specified, decline to decide on it, and pre-register a
better one for the following gameweek. **Deciding anyway, on a rule discovered to be
ambiguous, is the failure mode.** GW2 escaped it only because an independent
correctness argument carried the decision; that will not always be true.

*[Closed 2026-09-02 by §4 above, on the same branch as the minutes-model plan. The
gap is left as written because its last sentence is the point: the clause was
deliberately not smuggled into the original entry, and was then written as its own
commit while the GW4/GW5 answer is still unknown — which is the only condition under
which it could be written honestly. The original text follows.]*

`[gap: this entry pre-registers criteria for two decisions — price versus position,
and whether to tune `M`. It does **not** pre-register a criterion for the comparison
that matters most, which is whether any component variant beats `naive/1.0` and the
flat baseline. At GW2 naive beat `component/1.0` on Spearman(all) 0.619 vs 0.536 and
on Spearman(played) 0.330 vs 0.269, and `component/1.1-price` beat naive on
Spearman(played) 0.359 vs 0.330 while losing Spearman(all) 0.551 vs 0.619. What
should follow from a repeat of that at GW4 and GW5 is not written down anywhere,
and writing it would mean pre-committing to what happens if the model loses —
including the possibility that the honest answer is to stop projecting and ship the
control. That is a harder commitment than the two above and is deliberately not
smuggled in here as a third clause.]`

`[gap: §4 judges the component family on `spearman_played` alone, and a model that
loses it while winning RMSE decisively — which is component's exact shape — is
demoted under this clause despite being the better-calibrated projector. That is a
deliberate choice with a real cost, argued in §4, and it is recorded here as a gap
rather than only as a justification because the argument could be wrong.]`

`[gap: "two gameweeks evaluated independently" is not defined operationally beyond
"run the evaluation twice against two settled gameweeks". Whether the two runs must
use different pre-deadline captures (they will, in practice) and whether a
re-evaluation of the same gameweek after a stat correction counts as a second
observation (it must not) are unaddressed. Neither is likely to bite before GW5.]`

`[gap: no criterion here has an error-bar justification. 0.02, "two gameweeks", "six
to eight gameweeks" and "a factor of two" are all chosen numbers, in a project whose
standing complaint is that its constants are chosen numbers. The defence is only
that choosing them *before* the data is a different act from choosing them after,
and that is the whole and only claim this entry makes for them.]`

---

## FU-51 — a return date says a player is available, not that he plays ninety minutes

**Deferred from:** [minutes-model.md](minutes-model.md) §6.1, item S3, which proposes
parsing `Expected back <date>` out of `news` and lifting availability from 0.0 at
that date. Filed rather than folded into S3 because it is a second, separable claim:
S3 fixes *when* a player becomes available, and this fixes *what availability means*
in the gameweek he returns.

**The defect S3 would introduce if filed alone.** `_availability` returns a scalar
that multiplies `p_start`, and `p_start` then drives `p60`, `p1` and `xmins`. So
lifting a returning player from 0.0 to 1.0 does not merely mark him selectable — it
asserts he is as likely to start, and to play as many minutes, as a player who has
been fit throughout. On the pinned capture that would promote Doku from 0.0 across
GW3–GW7 to a full projection from GW4, which is wrong in the opposite direction to
today's error and wrong about a player expensive enough to matter.

Returning players are eased back: a bench role, a half, a substitute appearance with
the start the following week. The projection should reflect that the club has told
us *when he is available*, which is all a return date is, and not read it as a claim
about minutes.

**The value chosen, and it is chosen.** For the **first gameweek on or after the
return date**, expected minutes are capped at **45**, with availability at 1.0 and
normal behaviour from the following gameweek. Forty-five is a half: unambiguous,
conservative, and deliberately clear of the 60-minute appearance-point threshold, so
the cap does not sit on a knife-edge where a rounding difference flips two points.
One gameweek of ramp, not two, because a longer ramp is a stronger claim about
recovery than the data supports.

**This number is not tuned and must not be.** It is a `[assumption: no empirical
basis]` constant of exactly the kind FU-50 §3 and minutes-model.md §6.2 forbid
fitting on the data now available, and it belongs in minutes-model.md §7's
enumeration as a registered knob — `return_ramp_minutes` (float, minutes, 20–90) and
`return_ramp_events` (int, 0–3, where 0 reproduces S3 without this entry) — so that
a variant can hold it and a later evaluation can compare against it rather than
argue about it.

**Scope.** Seven players carry a parseable return date on the pinned capture, six of
them returning inside a five-gameweek horizon. This entry therefore governs a handful
of players per gameweek — but they are the expensive injured ones a transfer plan is
about, which is the same argument minutes-model.md §3.3 makes for S3 itself.

`[gap: whether minutes on return are predictable from the length of the absence — a
three-week hamstring against a three-month knee — is the question this entry
sidesteps with a flat 45. It is plausible that they are, and it would replace the
constant with a function. Establishing it needs historical injury spells joined to
subsequent per-gameweek minutes, across many players and several seasons. **This
project holds no such data and cannot obtain it from the FPL API**: `news` is
overwritten in place, so an absence's length is only recoverable from a dense capture
archive, and this machine's archive begins 2026-08-25. FU-52's `element-summary`
history does not carry it either — it records minutes played, not why they were
missed. Recorded as an open question with no route to answering it from current
sources, not as deferred work.]`

`[gap: the cap is specified as expected minutes, but the minutes model's output is a
distribution over start/sub/no-appearance, not a single figure. Whether 45 is imposed
by capping `xmins`, by forcing the substitute path, or by scaling `p_start` changes
which components move — a capped `xmins` with an uncapped `p_start` still awards a
full clean-sheet probability, which would be incoherent. minutes-model.md §7 rows
8–10 face the same class of question and it is not settled there either.]`

---

## FU-52 — signals that need an endpoint this client does not call

**Deferred from:** [minutes-model.md](minutes-model.md) §2, which enumerates unused
signal *within* `bootstrap-static` and stops there. The signals below are not in that
payload at any depth. **Filing only — the model change is not designed here.**

**The four wanted.** Share of available minutes played last season; share across the
last five gameweeks spanning the season boundary; goals and assists last season;
clean sheets last season. All four address minutes-model.md §4.2's finding that
`p_start` has no player-specific evidence for 119 of the 332 players it rates likely
to start, because after one gameweek `starts ∈ {0, 1}` and the position prior decides.
Last season is the obvious place to look for evidence that this season has not yet
produced.

**The endpoint: `/api/element-summary/{element_id}/`, and it is reachable without
credentials.** Probed 2026-09-02 against the live API through this repo's own
`FplTransport`; HTTP 200, no authentication, no cookie. It returns three arrays:

| Key | Contents | Rows observed |
|---|---|---|
| `fixtures` | that player's *remaining* fixtures, with `difficulty`, `is_home`, `event` | 36 |
| `history` | **per-gameweek** rows for the **current** season — `round`, `minutes`, `starts`, `clean_sheets`, `goals_scored`, `assists`, `defensive_contribution`, `bps`, `value`, `selected`, `was_home`, `opponent_team` | 2 (GW1, GW2) |
| `history_past` | **per-season totals** for prior seasons — `season_name`, `minutes`, `starts`, `clean_sheets`, `goals_scored`, `assists`, `defensive_contribution`, `total_points`, `start_cost`, `end_cost` | 1–5, player-dependent |

**Three of the four are available; one is not.**

- *Share of available minutes last season* — **available.** `history_past.minutes`
  for `season_name == "2025/26"`, over 3420 (38 × 90). A full-season regular reads
  3420 exactly, which was observed, so the denominator is right.
- *Goals and assists last season* — **available**, `history_past`.
- *Clean sheets last season* — **available**, `history_past`.
- *Share across the last five gameweeks spanning the season boundary* — **not
  available.** `history` is current-season only and `history_past` is season
  aggregates. There is no per-gameweek history for a completed season anywhere in the
  public API; it is reset each year. Spanning the boundary at gameweek granularity
  would require having captured last season's `history` while it was live, which this
  project did not exist to do. **This one is not deferred work, it is unobtainable
  from current sources** — the nearest tractable substitute is last season's aggregate
  share beside this season's per-gameweek history, which is a different signal and
  should not be described as the same one.

**Defensive contributions have almost no history, as suspected — measured.**
`history_past.defensive_contribution` is **0 for every season before 2024/25** across
the players probed (element 100: 0 in 2020/21 and 2022/23, then 49 in 2024/25 and 8
in 2025/26). The stat postdates most of the archive. `starts` has a similar though
shorter hole: 0 for 2021/22 where `minutes` is 2160, so it is unpopulated rather than
genuinely zero, and appears usable from 2022/23. `minutes`, `clean_sheets`,
`goals_scored` and `assists` are populated back to 2020/21 in every row seen.

**So clean sheets and goals/assists are the tractable starting point for defenders**,
exactly as the deferral supposed, and any use of `defensive_contribution` history
must handle two seasons of data and a hard zero before that — a zero that means
"not recorded" and must never be read as "none".

**The cost, which is the reason this is a filing and not a plan.** `element-summary`
is **one request per player**: 616 requests for the current population against three
for a full `sync` today. That changes the client's shape — rate limiting, partial
failure, a cache keyed per player, and a capture format that FU-41's manifest does
not cover. It is a transport and storage question at least as much as a modelling one,
and bundling it with a minutes-model change would produce a branch nobody can review.

`[gap: probed on three elements (1, 20, 100), not on the full population. The field
lists above are from those responses; a player with no prior season returns an empty
`history_past`, which was observed for element 20 (one row), but the fully-empty case
was not. Field presence is assumed uniform across elements on the strength of three
samples.]`

`[gap: nothing here establishes that last season's minutes share predicts this
season's starts. It is a plausible signal and it is obtainable; whether it carries
information beyond `selected_by_percent`, which minutes-model.md §2.4 measured and
which is free, is unknown and is the first thing any design pass should test. Two
seasons of squad turnover, promoted clubs, and players new to the league bound how
much of the population it can even cover.]`

`[gap: the 2025/26 rows appear in `history_past` alongside 2026/27 in `history`, so
"last season" is unambiguous today. Whether the API's season rollover leaves a window
where both are stale or the current season is absent is not established, and a
consumer built on this should not assume `history` is non-empty.]`

---

## FU-53 — bound the prize before building the minutes work

**Deferred from:** [minutes-model.md](minutes-model.md) §9, which names this as the
analysis it does not perform, and which is the entry's own largest weakness: it
proposes six structural changes (S1–S6) and **none of them has a measured upside**.

**The measurement.** Substitute realised appearance for predicted appearance and
re-score. For each player in a settled gameweek, replace the model's `p_start` with
the outcome — 1.0 if the player started, and the corresponding treatment for the
substitute and non-appearance paths — leave every other term of the component model
untouched, and run `plan evaluate` as normal. The resulting figures are what the
current model would score **with a perfect minutes model and nothing else changed**.
The gap between that and the real `component/1.1-price` row is the entire prize
available from FU-51, minutes-model.md S1–S6, and any successor.

**Why it is worth doing first.** minutes-model.md §1 argues from three measurements
that minutes is the binding constraint, and the argument is structural: every
downstream term is multiplied by `p_start`, so a minutes error scales the whole
projection. That establishes the constraint *binds*; it does not establish how much
is behind it. If the perfect-minutes ceiling moves `spearman_played` from 0.359 to
0.60, the work is clearly worth its cost. If it moves it to 0.38, the six structural
changes are correct in principle and nearly worthless in practice, and the effort
belongs somewhere else — most obviously the haulers, where the signed error is −5.43
and no proposal currently addresses it.

**It is cheap.** It needs no new endpoint, no new constant, no change to any model:
one evaluation-only projection wrapper substituting known outcomes, scored through
the existing harness against `~/fpl-pinned/gw2-pre-deadline.json`,
`gw2-fixtures.json` and `gw2-live.json`. It is closer in size to
`flat_points_per_game_projections` than to any of the six changes it would be
justifying.

**It is an upper bound, not a forecast**, and must be reported as one. No achievable
minutes model is perfect; minutes-model.md §4.2 shows the model currently has no
player-specific evidence at all for 119 of 332 players, and no amount of structure
manufactures evidence that is not in the payload. The number this produces is the
ceiling, and the realistic share of it is unknown.

`[gap: substituting realised appearance is not a single well-defined operation. A
player who came off the bench has a realised `p1` of 1.0 and a realised `p_start` of
0.0, and `xmins` is known exactly — so "perfect minutes" could mean substituting the
three probabilities, or substituting `xmins` alone, or both. These give different
ceilings and the difference is not obviously small. The variant chosen must be stated
with the figure, and reporting more than one would be better than choosing.]`

`[gap: one gameweek again. A ceiling measured on GW2 alone inherits every caveat in
this file, and FU-50 §2's two-gameweek rule applies to any *decision* taken on it —
including the decision to stop work on minutes, which is one of the outcomes this
analysis exists to enable.]`

`[gap: the analysis bounds the prize from fixing minutes *within the component
model's existing structure*. It says nothing about whether a better minutes model
would help `naive/1.0`, which also multiplies by availability, and therefore nothing
about whether it would change the FU-50 §4 control comparison — which is the
comparison that decides whether the component model survives at all.]`

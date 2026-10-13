# Follow-ups — header history

**Moved verbatim from the top of [follow-ups.md](follow-ups.md) on 2026-10-13**, when
Ben dropped the open-entry table as double-handling. Kept as the record of the
2026-08-28 reconciliation, the 2026-09-12 format pass and the 2026-09-21 review.
Nothing below is maintained; figures in it are as of the dates it states.

---

# Follow-ups

Work deliberately deferred out of other tasks. Each entry records what, why it was
deferred, and what it unblocks.

Closed entries stay in place — the numbering is referenced from commit messages and
from the plans in this directory, so it must not shift. A closed entry carries a
**Status: closed** line naming the commit that closed it and what was checked in the
code, not just what the commit claimed. Its body is left as written, so where the
fix diverged from the entry the Status line says how.

**An entry that was worked on but not finished carries a dated
`**Progress: YYYY-MM-DD**` line** saying what changed and what is left, and stays
open. It is deliberately a different marker from **Status**, so that scanning for
what is done cannot pick up what is merely underway — and so that an entry which has
been half-fixed stops reading as untouched.

**Both the entry and the open-entry table below are updated in the same commit as
the work** — they are two records of one fact and they have drifted apart twice.
`CLAUDE.md`'s Follow-ups section states the obligation; this header owns the format.

**Format pass, 2026-09-12, and what it deliberately left alone.** Every entry was
checked against the table mechanically: **the two agree on every row** — the drift
found earlier that day was real and is now fixed. Two markers were added: **FU-56**,
whose close was stated in prose but carried no `Status` line and so did not scan as
closed, and **FU-60**, the live entry, whose leg-1 result was recorded only at §6.3.

**The convention was not retrofitted to historical entries, and this is a decision.**
A `Progress` line reconstructed from a plan document rather than from the work would
be a date and a claim nobody verified — inventing detail, which this repo forbids and
which would make the marker worth less than its absence. Entries worked on before
2026-09-12 carry their history in their bodies, where it has always been. The
convention binds from here.

**Last reconciled against `main`:** 2026-08-28 (`99e5afb`) for FU-1 to FU-49. Every
entry in that range was checked against the source at that commit, not against the
commit log.

**The open-entry table below was separately re-verified on 2026-09-12** — all 25
rows, against the source. **That is weaker than a reconciliation and must not be
read as one:** it checks what each *row* claims, which is a one-line summary, not
the entry body behind it. An entry whose table row is right can still have a body
that has drifted, and thirteen such bodies are known to (see the citation paragraph
below). The distinction is the whole reason the 2026-08-28 date above is still the
one that governs.

**FU-50 to FU-68 have not been through that process** — they were written between
2026-09-01 and 2026-09-12 and cite the source as it stood when each was filed. Spot-
checked 2026-09-12 (`8b58674`): the citations in the entries added this session
resolve correctly (`domain/rules.py:57`, `optimizer.py:48`).

**The pre-FU-50 citations have drifted again, and the amount is measured rather than
guessed.** Re-measured 2026-09-12: of **105** distinct `file.py:line` citations in
this file, **13 point at a blank line or a bare delimiter**. *(The total was 103 on
2026-09-12; FU-60's Status line added two on 2026-09-22, both substantive. FU-68's
`club_lookup` (2026-09-22) moved every later `cli.py` line down 21: three
previously blank citations (`:344`, `:454`, `:638`) now land on code, and two
(`:1273`, `:1303`) now land on blanks. 14 → 13. FU-71's `_start_note` then moved
them again: `:1273` and `:1303` land on code, and `:856` and `:1018` on blanks. Still 13.)* None is past end of
file. `task/component-1.2` added roughly 550 lines to `domain/projections.py`, which
remains most of the cause.

**All three figures here, and the table row count above, are asserted by
`tests/test_follow_ups_header.py` (FU-69).** Change one and the suite fails naming
both numbers. The counting rules are part of the contract, because the number is
meaningless without them and three readings of it differ by more than the drift being
measured — on 2026-09-12, 133 counting every mention, 103 distinct as written, 99
distinct source lines:

- **Distinct, as written.** Repeat mentions of one spelling count once: `cli.py:1021`
  appears six times and counts once.
- **Two spellings of one line count twice.** `projections.py:219` and
  `domain/projections.py:219` are the same source line and two separate strings. Four
  lines in this file are cited both ways. They count as two because fixing one does
  **not** fix the other — the second is still wrong and still has to be found.
- **Resolution order:** `src/fpl_cli/<path>`, then `<path>` from the repo root
  (which is what reaches `tests/` and `tools/`), then a unique basename match
  anywhere in the tree. A citation that resolves to nothing fails the suite; there
  are none today.
- **Non-substantive** means the line is blank, is a bare `"""`, `'''`, `)`, `]` or
  `}`, or is past end of file.

The list below is the assertion — the count is derived from it, so the two cannot
disagree the way they did in this paragraph's first draft. **The block is excluded
from the scan**, without which it could never empty: its own entries are citations,
and they would keep themselves alive forever.

<!-- broken-citations:start -->
```text
cli.py:50, cli.py:64, cli.py:303, cli.py:856, cli.py:1018,
domain/projections.py:218, domain/projections.py:219, projections.py:219,
domain/squad.py:68, domain/squad.py:140, optimizer.py:184, optimizer.py:321,
tests/test_optimizer.py:237
```
<!-- broken-citations:end -->

*[The earlier figure here was "13 of 62", and it named `cli.py:1021`,
`domain/projections.py:218` and `cli.py:1273` as examples. Only the middle one
belongs: `cli.py:1021` and `:1273` both land on substantive lines and so were never
in this count. They are real drift of the **other** kind — `:1021` is cited three
times as `_report_live_provenance`, which is at `:1229`, and `:1273` is cited for
`_DEFAULT_EVALUATE_MODELS`, which is at `:1280`. The examples were right about the
entries being wrong and wrong about which measure catches them.]*

**Three of the fourteen were moved into blank lines on 2026-09-12 by this repo's own
`task/fu-17-club`**, which added eight lines to `cli.py` — `:344`, `:454` and `:638`.
All three were already pointing at unrelated code before that commit, so nothing
correct was broken; an eight-line change simply converted "wrong but substantive"
into "visibly wrong", which is the only reason they are now countable. That is the
mechanism this paragraph describes, observed live in the space of one morning.

That check is weaker than a reconciliation: it establishes only that a cited line is
*substantive*, not that it says what the entry claims, so 89 is an upper bound on
how many are right — and the `cli.py:1021` case above shows the gap between the
bound and the truth is not small. `domain/projections.py:219` is cited for
`_build_schedule`, which is at `:933`. **A full re-reconciliation is deferred, not
done**, and this paragraph exists so nobody reads the 2026-08-28 line above and
believes the file is current. The recurring nature of this is itself recorded in the 2026-08-28 block
below, which found thirteen drifted citations by the same measure — the same number,
two weeks and one large refactor later.

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
  line absent. *[**This held on 2026-08-28 and has failed twice since.** `c0951aa`
  closed **FU-15** on 2026-08-30 and `72a69f6` closed **FU-21** on 2026-09-02;
  neither was marked. Both were found on 2026-09-12 — the first by someone going to
  fix the README and finding it already fixed, the second by grepping the rest of
  the table's stated bases once the first had shown the table could be wrong. Marked
  now. The bullet is left as the pass found it per the convention above. The
  correction is not that the pass was careless: it is that **a finding of this shape
  expires on the next merge**, because it is a statement about one commit and reads
  as a property of the file. **The 2026-09-12 sweep ran in two passes and is now
  complete: all 25 rows below were re-checked against the source that day.** Pass 1
  took the thirteen whose basis is mechanically greppable (FU-4, 5, 6, 12, 14, 20,
  21, 25, 29, 31, 39, 42, plus FU-15 by hand): **two were wrong** — FU-15 and FU-21,
  both closed and unmarked — and **two more had bases that no longer said what they
  meant** (FU-20, FU-29). Pass 2 took the remaining nine by hand (FU-9, 13, 22, 27,
  30, 34, 35, 40, 43, the three already-closed rows aside): **every one holds on
  substance — no further unmarked closes** — but three citations had drifted with
  `cli.py`'s growth and are corrected in place (FU-30's `384`→`565`, FU-22's
  `648`→`856`, FU-35's line range), along with FU-9's basis, which described the
  ledger payload's fields incompletely.
  **An earlier draft of this note said "twenty-two rows". The table has 25** — the
  figure came from netting off rows judged not to need checking, and was never
  stated as such. A count that cannot be reproduced from the document is the exact
  failure this file exists to stop, so it is corrected rather than quietly
  overwritten. The nine was right: 25 − 13 checked − 3 already closed = 9.]*
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
| FU-9 | Still open, **basis made precise 2026-09-12** | `to_ledger_payload` (`squad.py:437`) emits `version`, `genesis_event`, `log` and `chips_played` — no XI, captain or vice-captain, which is the claim |
| FU-12 | Still open, **lines corrected** | `from rich import print` at `cli.py:12`, still mixed with `console.print` |
| FU-13 | Open, **narrowed** by `task/fu-19-18-13` | Retitled and scoped to `plan evaluate` and `plan simulate`; explicitly not wanted on four others |
| FU-14 | Still open, **body corrected** | `plan optimise` landed; `squad import`/`export`, `players show`, `squad show` still absent |
| FU-15 | **Closed** by `c0951aa`, two days *after* this pass | Marked 2026-09-12. The pass's finding below is wrong as a general claim and was right on its date |
| FU-17 | **Closed** by `task/fu-17-club` (2026-09-12) | `BadParameter` now raised and the accepted club names listed; the short-name mismatch it exposed is filed as FU-68 |
| FU-18 | **Closed** by `task/fu-19-18-13` | Stays one file; section comments added and a 600-line split threshold recorded |
| FU-19 | **Closed** by `task/fu-19-18-13` | Block corrected, and `tests/test_claude_md_structure.py` now fails when block and tree disagree |
| FU-20 | Still open, **basis corrected 2026-09-12** | `_build_schedule` still private; still no *accessor*. `fixture_count` now exists as a local in the naive loop (`projections.py:1154, 1203`), which this row's "no `fixture_count`" would now read as false — it was never the claim |
| FU-21 | **Closed** by `72a69f6`, five days *after* this pass | Marked 2026-09-12. Parsed at `api/models.py:32`, read at `projections.py:611-613` under `component/1.2` only |
| FU-22 | Still open, **body corrected** | `--output` exists but writes a transfers plan, not a `SquadPlan` — trigger unmet |
| FU-25 | Still open, body accurate | `DEFAULT_FT_VALUE = 1.5` still a constant (`optimizer.py:48`); no estimator |
| FU-27 | Still open (won't-do), **symbols corrected** | `_xi_structure`/`_XiStructure` renamed public by FU-26; `ranked` tuples still built |
| FU-29 | Still open, **basis corrected 2026-09-12** | No `--schedule` *option*. The string now appears at `cli.py:831` — inside the warning that names FU-29 as the reason the search is capped — so the original grep-shaped basis no longer distinguishes the flag from the apology for its absence |
| FU-30 | Still open, **line re-corrected 2026-09-12** | `simulate_plan` still takes no `--model`, now `cli.py:565` (was cited `384`), and still builds `ComponentProjection` unconditionally at `:603` |
| FU-31 | Still open, **body corrected** | No `--beam`/`--first-moves`/`--max-cells`; default is now 800M, not 400M |
| FU-34 | Decided, not implemented — unchanged | No re-check needed; the entry records a decision, not a code claim |
| FU-35 | **Still open, and confirmed so by FU-28's own source comment** | `optimizer.py:220-223` names FU-35 as the owner of the admission line; the admission line at `:231` is unchanged (both re-checked 2026-09-12) |
| FU-39 | Still open, body accurate | `DEFAULT_MAX_CELLS` still appears in exactly two places, both `optimizer.py` (`:60`, `:851`) |
| FU-40 | Open permanently; **two passages superseded** | Standing rule, not closable; FU-41 landed the bundle format it assumed absent |
| FU-42 | Still open, body accurate | `--archive-dir` at `cli.py:248`; all four cache paths still hardcoded; `FPL_SNAPSHOT` still the only env var read |
| FU-43 | **Partially closed** | Gate landed; `capture.py` still writes two files, so event-live is not pinned |

---

# Review — 2026-09-21: validity, and what to do in what order

A full pass over the open entries, asked for as a planning exercise rather than a
reconciliation. **It does not supersede the 2026-08-28 reconciliation**, which
remains the last time entry *bodies* were checked line by line; this checked each
open entry's **headline claim** against the source and then ranked the work.

**Written the evening GW5 settled**, and the ordering below is a direct consequence
of that result — see [gw5-evaluation.md](gw5-evaluation.md). A review written a day
earlier would have ranked this list very differently, which is itself worth knowing.

## What was checked

41 entries are open on `main`. Every one's headline claim was checked against the
source or the data. **None was found closed-in-code-but-unmarked** — the failure the
2026-09-12 sweep found twice. Specifically confirmed still true: no SQLite anywhere
(FU-4); no chip logic anywhere in `domain/` (FU-5); `doubtful_chance` still reachable
only through the `status == "d"` branch (FU-48); `plan evaluate` still **warns
loudly and scores anyway** on unsettled actuals, with no refusal (FU-49); the ramp
still registered at the identity (FU-51); `squad.json` still `genesis_event: 1` with
15 log entries (FU-66); `--club` still keyed on `name` only (FU-68);
`DEFAULT_FT_VALUE` still the literal 1.5 (FU-25, FU-64).

**FU-71 and FU-72 are not in this file on `main`** — they are on the unmerged
promotion stack, and this review covers what `main` carries. *[Superseded
2026-09-22: that stack merged in `60b6324` the same evening, so both entries are on
`main` now, as is FU-73, filed after. Counting every entry without a `Status:
closed`, `landed` or `REFUTED` line gives **44 open as of 2026-09-22**, FU-60 now
closed. The same rule gives **42**, not 41, for `main` on this review's date; the
rule behind 41 is not stated and the one-entry difference is not resolved.]*

## What the GW5 result does to the ranking

Three gameweeks of decomposition now exist, and they say something the September
plans did not anticipate:

- **S1–S5 has never moved the metric**: +0.003, −0.006, +0.0003. Three readings,
  indistinguishable from zero. minutes-model.md §9 predicted this in terms.
- **S6(a) is large and unstable**: +0.029, +0.0065, −0.033. Mean near zero, spread
  wider than every margin any decision here has turned on.

So **the minutes work as a whole is not measurably earning its place**, and the
entries that assume it is — FU-57 and FU-58 especially — have lost their premise
rather than merely their urgency. FU-57's own measurable symptom is *gone* (the
suppression count fell 59 → 4 as appearances accumulated) while S6(a) got worse,
which means FU-57 no longer explains what S6(a) is doing.

## The order

**1 — Write the next pre-registration. Nothing model-side can proceed without it.**
No entry covers what to do about three variants that are now within noise of each
other. FU-60 is spent; FU-50 §4 has been settled in the family's favour; and
`component/1.2-availability` has been best or joint-best twice while being barred
from the default by FU-60 §6.2 for want of a criterion of its own. This is the
gating artefact and it must be written **before GW6 settles** — its deadline is
2026-10-10, so there is time, and that time is the only reason it can be done
properly. It should also decide whether the S6(a)/S1–S5 split is worth continuing to
measure at all.
*[Done 2026-09-22: FU-73, binding. It keeps measuring the split: `1.3 − 1.3-fixtures`
is S6(a)'s fourth reading. It does not give `component/1.2-availability` a criterion of
its own. That variant's minutes term becomes 1.3's, so it is tested through 1.3.]*

**2 — FU-72: score the optimiser. This is now the largest unknown in the project.**
Four gameweeks have gone into measuring projections; **zero** have gone into the
half that produces the actual output. And the projection side has just produced its
least encouraging result yet, which makes "are we polishing the wrong half?" a live
question rather than a rhetorical one. Step A is an overnight job with a known cost
(81× the default search, ~54 minutes). *Blocked on FU-31 or a `tools/` harness — the
entry argues for the harness.*

**3 — The GW5 confound, because it is cheap and it could undo §2's premise.**
gw5-evaluation.md's second gap: GW5 scored +30.4% against the post-rule norm, and
the variant that predicts high totals won it while the variant that predicts low
totals lost. If high-scoring gameweeks systematically favour high-predicting models,
part of GW5's ordering is the week rather than the models — and the same mechanism
would have penalised 1.1-price in a low-scoring week. **Four settled gameweeks and
two existing tools are enough to check this.** It is the highest ratio of
information to effort on this list.

**4 — FU-62 and FU-63, which survived GW5 better than anything else did.** The
compression is real and unexplained at every gameweek: 1.2 has never predicted above
about 5.2 while real players score 17. FU-63's *stability* claim is now falsified —
the bias went −7.5%, −8.0%, **+4.9%** against the post-rule norm — so that entry
needs correcting before it is worked on, not after. **FU-65 must precede any
calibration work**, and still does.

**5 — Cheap correctness and UX, none of it blocked on anything.** FU-68 (`--club`
rejects the short name the app itself prints), FU-12 (two print functions mixed),
FU-14 (`players show`, `squad import`/`export` missing), FU-13 (`--json` where it was
narrowed to). Each is a contained change with a testable claim, and FU-68 in
particular is a defect a user meets on their first command.

**6 — FU-31, promoted by FU-72.** Exposing `--beam`, `--first-moves` and
`--max-cells` was a convenience when filed. It now blocks the measurement in §2. The
entry should record that it has acquired a dependent.

**7 — FU-5 (chips), promoted for the same reason.** Filed as a feature gap. FU-72
identifies chips as a likely *large* component of the optimiser's shortfall under a
perfect forecast, so it is now a candidate answer to §2's question rather than a
nice-to-have.

**Explicitly not now:** FU-57 and FU-58 (premise gone — see above; they are unblocked
and should stay unstarted until §1 exists), FU-4 (SQLite, no demand), FU-70 (wants a
written plan and the file is currently stable), FU-59 and FU-66 (open by design),
FU-40 and FU-50 (standing rules, not closable).

## What this review did not do

`[gap: headline claims only. Entry bodies have not been checked line by line since
2026-08-28, and 14 of this file's citations still resolve to blank lines. This review
read enough of each entry to rank it, not enough to certify it.]`

`[gap: the ranking is an argument, not a measurement. §2 is placed first among the
work on the belief that an unmeasured half is riskier than a measured one performing
poorly, which is a judgement. Someone who thinks the projections are close to a
breakthrough would order this differently and would not obviously be wrong.]`

---

---

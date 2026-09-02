# FU-53 — the ceiling on fixing the minutes model, measured

**This is a result, not a plan. No model changed, no parameter was tuned, and none of
minutes-model.md's six structural changes is implemented by the branch that writes
it.** The deliverable is §3's verdict and the harness at
`tools/fu53_minutes_oracle.py` that produces it.

**Every figure is measured on** `~/fpl-pinned/gw2-pre-deadline.json` (sha256
`593f60c2e356c4e94205f10248dfd834f4797ad6c736ea73b239da610d84ffcf`, captured
2026-08-28T00:32:59Z, 16h57m before GW2's deadline), fixtures from
`~/fpl-pinned/gw2-fixtures.json` (sha256 `fbd4457e5c81…`) and outcomes from
`~/fpl-pinned/gw2-live.json` (sha256 `afdaf81a6fcd…`, GW2 settled: `finished=true`,
`data_checked=true`, fetched 2026-09-01T13:04:40Z). Model digests
`component/1.0+banded` `fb431918c08c`, `component/1.1-price+banded` `24c305e2025c`,
`component/1.1-position+banded` `877dd43d6607`, `naive/1.0` `1ad0cd721b2e`,
`official-ep/1.0` `a6d72770239f`. Cited per FU-40. GW2 is clean in FU-50 §2's sense:
10 fixtures, every one of 20 teams playing exactly once. Population 616 projected
against 626 live elements, 308 of whom played; **0 projected players lack an
outcome**.

**The harness reproduces the published GW2 run exactly.** Its as-shipped rows return
minutes-model.md §1's figures to the digit — `component/1.0` at 0.536 / 0.269,
`component/1.1-price` at 0.551 / 0.359, `naive/1.0` at 0.619 / 0.330,
`baseline/flat-ppg` at 0.613 / 0.331, and the category row +1.114 / +1.317 on Zeros
against the document's +1.11 / +1.32. That agreement is the verification: the oracle
rows below come out of the same code path as rows already known to be right.

---

## 1 — What "substitute" was decided to mean, before the run

FU-53's own gap says substituting realised appearance is not one operation.
`_MinutesProbabilities` carries four numbers — `p_start`, `p60`, `p1`, `xmins` — and
there are three defensible substitutions. **All three were computed. `full` is the
headline.**

| Mode | `p_start` / `p60` / `p1` | `xmins` |
|---|---|---|
| `p_only` | realised: started, ≥60 mins, played | **modelled** |
| `xmins_only` | **modelled** | realised minutes |
| `full` | realised | realised minutes |

**Why `full` is the headline, decided before any number existed.**

1. **It is the only one that bounds a proposal actually on the table.** No change in
   minutes-model.md §6.1 touches one half alone. S1–S4 act on `_availability`, which
   multiplies into `p_start`, `p60`, `p1` **and** `xmins` together. S6(a) and S6(b)
   change `p_start`'s prior and evidence, and `mins_per_start` feeds both `p60` and
   `xmins`. A ceiling that fixes only one half is a ceiling on a change nobody has
   proposed.
2. **It is the only one that is internally coherent.** `p_only` describes a player
   who certainly starts and is expected to play 34 minutes; `xmins_only` describes one
   who certainly plays 90 and starts with probability 0.52. Neither is a statement
   about a player, and an upper bound built from an impossible model is not obviously
   an upper bound on anything.
3. **It is the largest**, which is what "the size of the prize" asks for. The
   question is the ceiling, and the ceiling is the most generous coherent
   substitution.

**What was not substituted.** Every scoring rate arrives as the model produced it.
The harness builds the real `ComponentProjection`, calls the model's own
`shrunk_rates` and its own `_project_one`, and replaces only the
`_MinutesProbabilities` passed between them. xG, xA, dc, saves, cards and bonus are
untouched. `frac = xmins / 90` still scales the rate-driven components — that is the
minutes term doing its job, not a rate changing.

**Where the oracle is undefined, and it is not forced.** It needs a separable minutes
term. `component/*` has one; `naive/1.0` has `_availability`, so realised appearance
replaces it (and `xmins_only` is a measured no-op there — naive stamps `xmins` and
never reads it). `official-ep/1.0` is the API's own scalar with no minutes term
inside it, and `baseline/flat-ppg` models no appearance at all. For those two the run
prints "no oracle" rather than inventing a substitution; they appear as shipped only.

---

## 2 — The numbers

### 2.1 Rank correlation and error, all six models

**As shipped** (the GW2 evaluation, reproduced):

| model | sp_all | sp_played | RMSE all | MAE all | RMSE played | MAE played |
|---|---|---|---|---|---|---|
| baseline/flat-ppg | 0.613 | 0.331 | 2.943 | 1.440 | 3.974 | 2.568 |
| naive/1.0 | **0.619** | 0.330 | 2.905 | 1.419 | 3.978 | 2.567 |
| official-ep/1.0 | 0.516 | 0.251 | 2.366 | 1.467 | 3.067 | 1.902 |
| component/1.0+banded | 0.536 | 0.269 | 2.405 | 1.463 | 3.148 | 1.939 |
| component/1.1-price+banded | 0.551 | **0.359** | 2.411 | 1.569 | **3.036** | **1.901** |
| component/1.1-position+banded | 0.546 | 0.347 | 2.427 | 1.595 | 3.043 | 1.919 |

**Oracle `full`** — perfect minutes, everything else unchanged:

| model | sp_all | sp_played | RMSE all | MAE all | RMSE played | MAE played |
|---|---|---|---|---|---|---|
| naive/1.0 | 0.728 | 0.331 | 2.810 | 1.284 | 3.974 | 2.568 |
| component/1.0+banded | 0.867 | 0.525 | 2.081 | 0.912 | 2.943 | 1.824 |
| component/1.1-price+banded | **0.884** | **0.564** | **1.948** | 0.903 | **2.755** | **1.807** |
| component/1.1-position+banded | 0.882 | 0.556 | 1.960 | 0.913 | 2.772 | 1.825 |

**Oracle `p_only`** and **`xmins_only`**, reported because FU-53 asked for more than
one:

| model | `p_only` sp_all / sp_played | `xmins_only` sp_all / sp_played |
|---|---|---|
| naive/1.0 | 0.728 / 0.331 | 0.619 / 0.330 *(no-op, as predicted)* |
| component/1.0+banded | 0.793 / 0.453 | 0.557 / 0.401 |
| component/1.1-price+banded | 0.819 / 0.522 | 0.719 / 0.524 |
| component/1.1-position+banded | 0.818 / 0.515 | 0.725 / 0.521 |

### 2.2 The movement, stated as deltas

`spearman_played`, the metric the interpretation clause was written against:

| model | shipped | `p_only` | `xmins_only` | `full` | Δ full |
|---|---|---|---|---|---|
| **component/1.1-price** (default) | 0.359 | 0.522 | 0.524 | **0.564** | **+0.205** |
| component/1.0 | 0.269 | 0.453 | 0.401 | 0.525 | +0.256 |
| component/1.1-position | 0.347 | 0.515 | 0.521 | 0.556 | +0.209 |
| naive/1.0 | 0.330 | 0.331 | 0.330 | 0.331 | **+0.001** |

**The two halves overlap; they do not add.** Each alone recovers about four-fifths of
what both recover together (+0.163 and +0.165 against +0.205 for the default). They
are largely substituting the same information, which is a reason not to read
`p_only`'s figure as "the prize from fixing `p_start`" — most of it is available from
either side.

### 2.3 The error-by-category table

Signed mean error, predicted − actual. Categories bucket on **actual** points and are
therefore identical populations across every row.

| Category | n | shipped 1.0 | shipped 1.1-price | oracle `full` 1.0 | oracle `full` 1.1-price |
|---|---|---|---|---|---|
| Zeros | 332 | +1.114 | **+1.317** | +0.216 | **+0.210** |
| Blanks | 178 | +0.554 | +0.744 | +0.926 | **+1.109** |
| Tickers | 43 | −1.191 | −1.119 | +0.049 | +0.067 |
| Haulers | 63 | −5.429 | −5.438 | −4.013 | **−4.112** |

**The zeros collapse, as predicted — by 84%.** The clearest symptom in
minutes-model.md §1 goes from +1.32 to +0.21 for the shipped default. The residual is
not a minutes error: it is the 332-strong Zeros bucket containing players who *did*
feature and returned nothing, for whom perfect minutes still hands over a full
gameweek of modelled scoring rate.

**Two findings that were not asked for and are not comfortable.**

- **The Blanks get worse, by half again** (+0.744 → +1.109). Under the shipped model,
  a `p_start` below 1.0 discounts the projection of a player who then features and
  scores one or two points. Perfect minutes removes that discount and exposes a
  scoring-rate over-prediction that was previously being hidden by a minutes error
  pointing the other way. **Some of the component model's present accuracy on this
  bucket is two errors cancelling**, and fixing minutes uncovers it rather than
  fixing it.
- **The Haulers barely move** (−5.438 → −4.112, 24% of the error). Three-quarters of
  the largest signed error in the table survives a perfect minutes model untouched. No
  proposal in minutes-model.md addresses it, and FU-53 named this as the place the
  effort might belong instead — the measurement says minutes work will not take it.

### 2.4 Error by component, played only

`full` oracle against shipped, `component/1.1-price`:

| component | shipped | oracle `full` |
|---|---|---|
| appearance | −0.328 | **0.000** |
| attack | −0.224 | −0.057 |
| clean_sheet | −0.008 | +0.034 |
| conceded | +0.064 | +0.024 |
| saves | −0.010 | +0.005 |
| defcon | −0.158 | −0.001 |
| bonus | −0.050 | 0.000 |
| cards | +0.038 | +0.011 |

`appearance` going to exactly 0.000 is the oracle working as specified, not a
result: realised `p1` and `p60` reproduce the appearance points by construction. The
informative rows are the others, which all shrink toward zero **without any rate
changing** — every one of them is scaled by `frac = xmins / 90`, so a minutes error
was inflating the whole decomposition, exactly as minutes-model.md §1 argued
structurally.

---

## 3 — The verdict, against the clause fixed before the numbers existed

**The clause:** if the oracle moves `spearman_played` for the shipped default by less
than 0.05, the minutes model is not the binding constraint and minutes-model.md's six
changes should be reprioritised against other work rather than started.

**It moves it by +0.205, from 0.359 to 0.564 — four times the threshold, and the
weakest of the three substitutions still moves it by +0.163.**

**The result falls plainly on the "minutes is the binding constraint" side.** The
clause's condition is not met and its instruction — reprioritise rather than start —
does not apply. minutes-model.md §1's structural argument is now a measured one: the
prize behind the minutes model is large, and it is where the document said it was.

### What this does not license

1. **It is a ceiling, and the achievable share is unknown.** minutes-model.md §4.2
   measured that the model has no player-specific evidence at all for 119 of the 332
   players it puts over `p_start > 0.5`; `starts` is binary after one gameweek. No
   structure manufactures evidence that is not in the payload. Nothing here estimates
   what fraction of +0.205 S1–S6 would actually collect, and the honest answer is that
   nobody knows.
2. **One gameweek.** Every caveat in FU-50 §2 applies. The decision this analysis
   exists to enable — start the minutes work, or don't — is a decision, and FU-50 §2's
   two-gameweek rule is about decisions. The measurement should be repeated on a
   second settled clean gameweek before substantial effort is committed. What GW2 does
   settle is the *negative*: the case for reprioritising away from minutes on
   grounds of a small prize is not available, because the prize is not small.
3. **The prize is a selection prize, not a scoring prize.** `RMSE played` moves 9%
   (3.036 → 2.755) while `RMSE all` moves 19% (2.411 → 1.948) and `MAE all` 42%
   (1.569 → 0.903). Minutes work buys accuracy about *whether and how much a player
   features*, which is most of what the 616-player population is. It buys very little
   about how much a player who features scores — §2.3's Haulers row is the same
   finding from the other end.

### One thing the run says about FU-50 §4, offered as information and not as a decision

FU-53's third gap asks whether a better minutes model would also help `naive/1.0`, and
therefore whether it would move the control comparison. It was cheap to measure, so it
was: **a perfect minutes model moves naive's `spearman_played` by +0.001**, from 0.330
to 0.331, while moving `component/1.1-price`'s by +0.205. Naive gains on
`spearman_all` (0.619 → 0.728) and nothing at all on the metric FU-50 §4 names.

So on this one gameweek, the entire minutes prize lands on the component side of the
control comparison, and none of it on naive's. **This is not a re-reading of FU-50 §4
and must not be used as one** — §5 forbids that, the criterion is `spearman_played`
across two clean gameweeks with a real model, and an oracle is not a model. It is
recorded because the gap asked and because a reader deciding how to spend effort
should know that minutes work is not a rising tide lifting the control too.

---

## 4 — The harness: it belongs in the repo, in `tools/`

**Decision: committed, as `tools/fu53_minutes_oracle.py`.** Three reasons, and one
condition that the location enforces.

**Why it is committed rather than documented as a procedure.** §3.2 says the
measurement must be repeated on a second settled gameweek before effort is committed.
A procedure written in prose and re-implemented at GW4 would produce a number that is
not comparable with +0.205 — a different substitution mode, a different treatment of
players missing from the live payload, a different population — and the comparison
between the two gameweeks is the entire point of repeating it. That is FU-40's
argument applied to a measurement rather than a figure. Second, the run's own
validation is that its as-shipped rows reproduce minutes-model.md §1 exactly, and that
check has value only if the code that produced them still exists. Third, it is small
and it depends on `projections.py`'s internals, so it is exactly the kind of thing
that rots silently if it lives outside the tree that changes underneath it.

**Why `tools/` and not `src/fpl_cli/`.** `pyproject.toml` packages `src/fpl_cli` only.
A file in `tools/` is not installed and nothing in the package can import it, so the
containment of an outcome-leaking projection is **enforced by the build rather than by
a comment**. The alternative — a module in `domain/` marked "do not call from the
CLI" — is one careless import away from a leak-contaminated figure being printed by
`plan evaluate` with no warning. It also keeps the CLAUDE.md structure block (FU-19)
describing the shipped package, which is what it is for.

**How it is marked.** The module docstring opens with a boxed warning that the script
reads the answer before it predicts it. `require_settled` refuses to run unless the
live payload carries `finished` **and** `data_checked` — FU-43's finality argument,
with more force than usual, because an oracle built from provisional stats is not an
upper bound on anything. `require_clean_gameweek` refuses a blank or a double: the
live payload reports minutes per *event* and `_MinutesProbabilities` is per *fixture*,
and those are the same number only when every team plays once.

**What it deliberately does not have.** No `pytest` test, and no entry in the README
architecture table or the CLAUDE.md structure block — all three describe the shipped
package, and this is not part of it. Its correctness check is that it reproduces a
published run, which is stronger than a synthetic fixture would be and is re-run every
time the script is. **If it ever acquires a second consumer, or is asked to run
against something other than a pinned settled gameweek, that judgement should be
revisited** — at that point it is a component and should be tested like one.

---

## 5 — What this does not settle

`[gap: one gameweek, again, and this is the same caveat FU-50 §2 exists to enforce.
+0.205 has no error bar. GW2 had 616 players, `starts` binary, and 308 appearances;
what a second gameweek would return is unknown, and the direction of the *ceiling* is
more robust than its size only because a ceiling is bounded below by zero.]`

`[gap: the three substitution modes give +0.163, +0.165 and +0.205, and no argument
here establishes which one the achievable improvement most resembles. `full` was
chosen as the headline on the coherence and scope arguments of §1, which are arguments
about what the number *bounds*, not about what a real minutes model would look like.]`

`[gap: the oracle is perfect *and free*. A real minutes model that improved `p_start`
would also change which players clear thresholds elsewhere in the pipeline — the
optimiser's search, the `p_start > 0.5` populations FU-50 §4 reports — and none of
that is measured here. The figure bounds a projection metric, not plan quality, which
is the same limitation FU-50 §4 accepts knowingly for `spearman_played`.]`

`[gap: §2.3's Blanks finding — that the oracle makes that bucket 50% worse by
uncovering a scoring-rate over-prediction the minutes error was cancelling — is a
one-gameweek observation on 178 players and is not investigated further here. If it
holds, it means some of S1–S6's realised benefit will be offset by an error becoming
visible, and the net on that bucket could be negative. Nothing in minutes-model.md
anticipates that.]`

`[gap: no oracle exists for `official-ep/1.0` or `baseline/flat-ppg`, so two of the
six models are reported as shipped only. For `baseline` that is inherent — it has no
appearance term. For `official-ep` it means the one model that might already contain a
good minutes model internally cannot be decomposed to check, which is a standing
limitation of scoring it at all.]`

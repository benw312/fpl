# GW4 — leg 2 of FU-60's pair

**Result. No model changed, no constant touched, no criterion re-read.** FU-60 §8
governs: the metric, population and reading were fixed on 2026-09-02 and 2026-09-05,
both long before this figure existed. §§1, 5 and 6.2 were re-read from the entry
*before* the evaluation was run, and are applied below as written.

**§§1–3 of this document were written on 2026-09-12, before kick-off.** They are
left as they were, because their value is their date. §§4 onward were added
2026-09-19 once GW4 settled.

---

## 1 — Pinned inputs, cited per FU-40

**All three legs are now pinned.**

| pin | sha256 | state |
|---|---|---|
| `~/fpl-pinned/gw4-pre-deadline.json` | `de9d7d3573b27d28c3d43d8ac0932b290d5f0785903d1e07d031099d8eb49f7e` | pinned 2026-09-12 |
| `~/fpl-pinned/gw4-fixtures.json` | `85d3ef089f28bc22a1d168204ea9d1982dac6ba0af72fd28379e370fbf3eff23` | pinned 2026-09-12 |
| `~/fpl-pinned/gw4-live.json` | `8809e516a5ffeeeebf8707f219ceeac7a9231860bb7257b6753e11c6d4218342` | **pinned 2026-09-19, settled** |

The first two are byte copies of `~/.fpl-cli/archive/2026-09-12/` and **both hashes
match that capture's own `manifest.json`**. The live payload carries
`finished: true, data_checked: true` — FU-43's gate and FU-49's provisional-actuals
warning are both satisfied, and `plan evaluate` confirms it in its own line: *"GW4
actuals: final (finished, data checked)"*.

**The capture is leak-free.** `captured_at` 2026-09-12T00:03:59Z, `role` canonical,
`next_event` recording `{id: 4, captured_before_deadline: true}` — **12h 26m 01s
before the deadline**.

**Model digests, and why they are the most important line here.** `component/1.1-price`
`24c305e2025c`, `component/1.2` `4f479b2253cc`, `component/1.2-availability`
`c6143ceb6826`, `naive/1.0` `1ad0cd721b2e`. **Every one is identical to the digest
recorded in [gw3-evaluation.md](gw3-evaluation.md).** FU-60 §7 requires that 1.2 not
change between registration and evaluation, or the pair becomes two observations of
two models; that requirement is now **verified rather than asserted**.

---

## 2 — GW4 is clean in FU-50 §2's sense

*Written 2026-09-12, before kick-off.* **10 fixtures. 20 teams. Every team exactly
once. No blanks, no doubles.** No `event: null` fixtures anywhere in the payload.

**Re-confirmed 2026-09-19 against the settled payload**, which §5's gap below
required: still ten fixtures, twenty teams, all `finished: true`, and **the fixture
set is identical to the pre-deadline pin** — no postponement, nothing added or
removed. The pre-kick-off check and the post-settle check agree, so the gap that
motivated the re-check is closed rather than merely discharged.

**GW4 counts, and that it counts was established before it was played.**

---

## 3 — Population

656 players in the pinned bootstrap; 656 scored against 659 live, 307 of whom
played, 220 of whom started. GW2 projected 616 and GW3 652, so **no absolute figure
is like-for-like with its GW3 counterpart**. FU-60 §1's criterion is a
within-gameweek pairwise comparison and is unaffected.

---

## 4 — The criterion: leg 2 is met, and the pair completes

**FU-60 §1: `component/1.2` replaces `component/1.1-price` as the registered default
if and only if it scores strictly higher on `spearman_played` in each of GW3 and
GW4. No margin. A tie does not clear.**

| | `spearman_played` |
|---|---|
| `component/1.2` | **0.329665501** |
| `component/1.1-price` | 0.329148282 |
| **delta** | **+0.000517219** |

**Strictly greater. Leg 2 is met.** With leg 1 (GW3, +0.032) this completes the
pair, and **under FU-60 §1 `component/1.2` becomes the registered default.**

**The margin is 62 times smaller than GW3's, and the criterion has no margin
clause.** Both facts are true and neither modifies the other. §1 says "no margin"
because FU-60 §3 argued a threshold chosen after the fact is the result choosing the
rule; introducing one now — in either direction — is precisely what §8 forbids.
**What the size of the margin licenses is commentary, not a different verdict**, and
§4 predicted the shrinkage in advance, which is the subject of §6 below.

Figures are quoted to nine decimal places because at three the delta is
`0.330 − 0.329` and a reader cannot tell a real ordering from a rounding artefact.
They reproduce `plan evaluate`'s own pipeline against the same pinned trio.

### The full table

| variant | sp_played | sp_all | RMSE all | MAE all | RMSE played | MAE played |
|---|---|---|---|---|---|---|
| baseline/flat-ppg | 0.338 | 0.645 | 2.468 | 1.360 | 3.267 | 2.286 |
| naive/1.0 | 0.342 | 0.694 | 2.311 | 1.248 | 3.246 | 2.275 |
| component/1.1-price | 0.329 | 0.661 | 2.285 | 1.392 | 3.120 | **2.088** |
| **component/1.2** | **0.3297** | 0.662 | **2.228** | **1.230** | 3.160 | 2.095 |
| component/1.2-availability | 0.323 | 0.646 | 2.294 | 1.403 | 3.129 | 2.096 |
| official-ep/1.0 | **0.353** | **0.706** | 2.282 | 1.234 | 3.229 | 2.295 |

`spearman_all` is reported and is **not** a criterion (FU-50 §1). Note it anyway:
`naive/1.0` leads the component family on it again, and `official-ep/1.0` leads
everything.

---

## 5 — The three-way reading: Case A

FU-60 §6.2 fixed four readings in advance, on 2026-09-05.

| | `spearman_played` | contribution |
|---|---|---|
| `component/1.2` | 0.329666 | |
| `component/1.2-availability` | 0.323130 | **S6(a) = +0.006535** |
| `component/1.1-price` | 0.329148 | **S1–S5 = −0.006018** |

1.2 beats 1.2-availability and 1.2 beats 1.1-price, so this is **Case A**, whose
fixed reading is: *"The bundle wins and S6(a) contributes on top of S1-S5."*

**At GW3 this was also Case A, and the decomposition has changed sign.** S6(a) went
+0.029 → +0.0065 and **S1–S5 went +0.003 → −0.006**. The two now nearly cancel,
which is the whole explanation of why the bundle clears its control by 0.0005 rather
than 0.032.

**S1–S5 subtracting is new and is not covered by any fixed reading**, because §6.2's
table is written over orderings and this is a decomposition detail underneath one.
It is therefore recorded and **not acted on**. Two readings are available — that
S1–S5's availability fixes genuinely cost rank accuracy at GW4, or that a −0.006
movement on one gameweek is noise around zero — and nothing here separates them. It
is the second observation of this split ever taken; gw3-evaluation.md §8 flagged in
advance that the +0.029/+0.003 division "could look quite different at GW4".

---

## 6 — §4's recession is confirmed, by its own pre-specified measurement

FU-60 §4 predicted, before any of this existed, that the comparison **loses
discriminating power with every gameweek** as `a` grows: the S6(a) separation for a
MID `<1%` band falls to 62% of its GW2 value by GW4, and FU-57's defect is "partly
dissolved" at GW4 against "essentially intact" at GW3.

§4.2 named the measurement that would show it — the count of players with `s = a`
rated `p_start ≤ 0.5`. Produced by `tools/minutes_diagnostics.py`:

| | GW3 (`a = 2`) | GW4 (`a = 3`) |
|---|---|---|
| players with `starts = a` | 183 | 163 |
| rated ≤ 0.5 under **1.2** | **59** | **5** |
| of which actually started | 48 | 3 |
| rated ≤ 0.5 under 1.1-price | 1 | 1 |

**FU-57's defect has largely dissolved on its own, exactly as predicted and with no
code change** — the digests in §1 prove no code change. The 59 → 5 collapse and the
0.032 → 0.0005 margin collapse are the same phenomenon measured two ways.

**§4.2's exact clause does not fire, and the difference matters.** It reads: *"If it
collapses between GW3 and GW4 **while `spearman_played` rises**, accumulation is the
live explanation for the GW4 movement specifically."* The count collapsed; 1.2's
`spearman_played` **fell**, 0.348 → 0.3297. So the stated antecedent is not
satisfied and that reading is not invoked.

**What survives is §4.1, which is why the pair was specified as it was.** A GW3 win
cannot be attributed to accumulation, because at GW3 accumulation had not yet
happened. GW3 was clean and usable, so the pair is self-controlling as designed and
§4.3's "criterion met on a moving target, say so, do not launder it" clause — which
applies when GW3 is unusable — does not apply.

---

## 7 — FU-50 §4's control clause: the first failure

Not a criterion of this document, and **it is the most consequential number here.**

§4: *if the **best** component variant fails to beat `naive/1.0` on
`spearman_played` across **two clean gameweeks**, `naive/1.0` becomes the default.*

| | best component variant | `naive/1.0` | clears? |
|---|---|---|---|
| GW2 | `component/1.1-price` 0.359 | 0.330 | yes, +0.029 |
| GW3 | `component/1.2` 0.348 | 0.229 | yes, +0.119 |
| **GW4** | **`component/1.2` 0.329666** | **0.342232** | **no, −0.012567** |

**The demotion is not triggered — the clause requires two clean gameweeks and this
is one.** But it is the first failure the component family has recorded against its
own control, and it arrives in the same gameweek the family is promoted internally.
`official-ep/1.0` also beat every component variant, at 0.353.

**Nothing about this changes §1's verdict**, and §6.2 anticipated the temptation in
terms: *"'Which model came top' is a tempting reading and is **not** the
criterion."* §1 is a pairwise comparison against 1.1-price and it is met. But FU-50
§4 is a *separate standing rule* with its own trigger, it is now one gameweek from
firing, and **GW5 is the gameweek that would fire it.** That should be recorded
before GW5 is settled, which is what this section is.

---

## 8 — Diagnostics (not criteria)

FU-60 §5 names Brier and log loss as diagnostics of the minutes term, records the
reading in advance, and forbids either becoming a gate.

| variant | Brier | log loss | Σ `p_start` | actual starters |
|---|---|---|---|---|
| component/1.1-price | 0.1131 | 0.3590 | 261.3 | 220 |
| **component/1.2** | **0.0984** | **0.3138** | **195.0** | 220 |
| component/1.2-availability | 0.1140 | 0.3610 | 260.9 | 220 |

**No disagreement: 1.2 wins `spearman_played`, Brier and log loss.** §5's clause
does not fire, as at GW3.

**The tracked residual, recorded as §5 requires.** Log loss delta (1.1-price minus
1.2; positive favours 1.2): **GW2 −0.0238 → GW3 +0.0848 → GW4 +0.0452.**

§5 fixed this reading in advance: *"If it narrows between GW3 and GW4 **with no code
change**, that is direct evidence for §4's recession hypothesis, obtained free."* It
narrowed, from +0.0848 to +0.0452, and §1's digests establish there was no code
change. **That clause fires, and it corroborates §6 on a second, independent
measurement.**

`component/1.2` still under-calls starters — Σ`p_start` 195.0 against 220 actual,
**−11.4%**, against GW3's −12.7%. 1.1-price over-calls at 261.3, **+18.8%**.

---

## 9 — Category error and scale

| Category | n | naive/1.0 | 1.1-price | **1.2** | 1.2-availability |
|---|---|---|---|---|---|
| Zeros | 376 | +0.52 | +0.91 | **+0.60** | +0.92 |
| Blanks | 165 | +1.10 | +0.81 | **+0.51** | +0.79 |
| Tickers | 44 | −0.13 | −1.02 | −1.21 | −1.05 |
| Haulers | 71 | −4.35 | −5.38 | **−5.40** | −5.39 |

Same shape as GW3: 1.2 improves Zeros and Blanks markedly and is worst on Haulers.
Per FU-61 the Haulers row selects on the outcome and is not a defect measure.

**FU-63's scale bias has widened.** `tools/distribution_check.py`: 1.2 projects 792
against 921 realised, **−14.0%**, and **−8.0%** against the post-rule norm — against
−7.5% at GW3. 1.1-price runs +5.2% against realised. **FU-63 is unresolved and
moving in the wrong direction**, and the handoff's "expect overshoot when FU-57 is
fixed" warning now has less headroom than it did, not more.

**FU-62's compression persists.** 1.2's predicted SD 1.19 and max 5.17 against a
realised SD of 2.65 and max 17. Above 5 points, 1.2 places 1 player where 22.0% of
those who played scored 5 or more.

**Positional share against the post-rule reference** (the correct one — FU-67's
pooled reference was refuted): 1.2 puts 36.3% on DEF against the reference's 35.0%,
and 43.6% on MID against 45.3%. The mild defender skew that FU-67 measured survives
against the post-rule reference, smaller than the refuted figure suggested.

---

## 10 — What follows, and what does not

1. **`component/1.2` becomes the registered default** under FU-60 §1. That is a code
   change to the registry and is **not made by this document** — prepared separately
   on `task/promote-component-1.2`, unmerged, for review.
2. **FU-60 §7's freeze lifts** with the pair complete, which unblocks **FU-57** and
   **FU-58**.
3. **FU-57's urgency has fallen sharply and its character has changed.** §6 measures
   the defect largely dissolving on its own as `a` grows. It is still structurally
   wrong — pooling marginally over `starts` where the signal is an interaction — but
   the case for it as "the first thing to do" rested on a size that GW4 shows was
   partly a function of `a = 2`. rank-calibration.md §6's ordering should be re-argued
   against this before it is followed.
4. **FU-50 §4 is one gameweek from firing.** GW5 settles it either way.

---

## 11 — Gaps

`[gap: +0.000517 on one gameweek, with no error bar. GW3's +0.032 had none either.
FU-50 §2's two-gameweek floor is "a coin flip's worth of confirmation" in its own
words, and a margin this small is inside any plausible resampling interval. The
criterion is met as written; the evidence it rests on is thin and the thinness is
concentrated in leg 2.]`

`[gap: §5's decomposition sign change — S1-S5 from +0.003 to -0.006 — is the second
observation of a quantity that has now pointed both ways. Nothing distinguishes "the
availability fixes cost rank accuracy" from "noise around zero", and a third reading
at GW5 would still not separate them without an error bar.]`

`[gap: §7 records that naive/1.0 beat every component variant at GW4 and that
official-ep/1.0 beat everything. Under FU-50 §4 that is one failure of two. It is
also the first gameweek in which the persistence baseline has been competitive since
GW2, and no explanation for that is offered here — the fixture-difficulty spread and
the number of rotated sides in GW4 were not examined.]`

`[gap: the GW4 evaluation reached fixtures through the snapshot service, which cannot
be pinned (FU-40, and the handoff's standing trap). The figures were reproduced from
the pinned `gw4-fixtures.json` and agree, and §2 establishes the GW4 fixture set is
identical between the pre-deadline pin and the settled payload — so for this event
the unpinnable input is verified not to matter. That is a check, not a fix: the next
evaluation needs the same check again.]`

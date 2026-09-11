# GW3 — leg 1 of FU-60's pair

**Result only. No model changed, no constant touched, no criterion re-read.**
FU-60 §8 governs: the metric, population and reading were fixed on 2026-09-02 and
2026-09-05, both before this figure existed.

**Pinned inputs, cited per FU-40.** Projection snapshot
`~/fpl-pinned/gw3-pre-deadline.json` (sha256
`0cc7193b5e20567e379e437a58c3ae6e73379ff892742479af9c0654f3264a0e`), the canonical
capture of 2026-09-04, `captured_at` 2026-09-04T00:01:59Z — **17h28m before GW3's
17:30Z deadline**, so the run is leak-free. Fixtures
`~/fpl-pinned/gw3-fixtures.json` (sha256 `5cc5817d3385…`); both hashes match the
capture's own manifest. Outcomes `~/fpl-pinned/gw3-live.json` (sha256
`cd86195071cd…`), **GW3 settled: `finished=true`, `data_checked=true`**. Model
digests `component/1.1-price+banded` `24c305e2025c`, `component/1.2+banded`
`4f479b2253cc`, `component/1.2-availability+banded` `c6143ceb6826`, `naive/1.0`
`1ad0cd721b2e`, `official-ep/1.0` `a6d72770239f`.

**GW3 is clean in FU-50 §2's sense:** 10 fixtures, 20 teams, every team once.
Population 652 projected against 654 live, 307 of whom played, 220 of whom started.
Appearances `a = 2`.

---

## 1 — The criterion: leg 1 is met

**FU-60 §1: `component/1.2` replaces `component/1.1-price` only if it scores
strictly higher on `spearman_played` in each of GW3 and GW4.**

| | `spearman_played` |
|---|---|
| `component/1.2` | **0.348** |
| `component/1.1-price` | 0.316 |
| **delta** | **+0.032** |

**Strictly greater. Leg 1 of the GW3+GW4 pair is met.** Nothing is promoted yet —
§1 requires both legs, and GW4's deadline is 2026-09-12T12:30Z.

### The full table

| variant | sp_all | sp_played | RMSE all | MAE all | RMSE played | MAE played |
|---|---|---|---|---|---|---|
| baseline/flat-ppg | 0.675 | 0.231 | 2.535 | 1.344 | 3.443 | 2.401 |
| naive/1.0 | **0.703** | 0.229 | 2.446 | 1.288 | 3.445 | 2.405 |
| component/1.1-price | 0.677 | 0.316 | 2.081 | 1.347 | **2.725** | 1.806 |
| **component/1.2** | 0.700 | **0.348** | **1.994** | **1.115** | 2.795 | **1.797** |
| component/1.2-availability | 0.678 | 0.319 | 2.074 | 1.330 | **2.725** | 1.804 |
| official-ep/1.0 | 0.694 | 0.210 | 2.413 | 1.308 | 3.423 | 2.426 |

`spearman_all` is reported and is **not** a criterion (FU-50 §1's rule). Note it
anyway: `naive/1.0` still leads it at 0.703 against 1.2's 0.700 — a gap of 0.003,
down from 0.068 at GW2.

---

## 2 — The three-way reading: Case A

FU-60 §6.2 fixed four readings in advance. This is **Case A**: `component/1.2`
beats both.

| | `spearman_played` | contribution |
|---|---|---|
| `component/1.2` | 0.348 | |
| `component/1.2-availability` | 0.319 | **S6(a) = +0.029** |
| `component/1.1-price` | 0.316 | **S1–S5 = +0.003** |

§6.2's reading of Case A, unchanged: *"The bundle wins and S6(a) contributes on top
of S1-S5. One leg of §1's pair is met; GW4 still required. Nothing else changes."*

### The decomposition is the finding, and it is lopsided

**Almost all of 1.2's gain is S6(a). S1–S5 contribute +0.003, which is nothing.**
The same pattern holds on every other column: `component/1.2-availability` sits
within 0.007 of `component/1.1-price` on `spearman_all`, RMSE played and MAE played,
and is indistinguishable from it on the category table.

**This is what minutes-model.md §9 said would happen**, in terms, before any of it
was built: *"S1–S5 are argued as structurally correct, and none of them is
*measured* to improve any metric … The claim made here is that they fix category
errors … not that they will move Spearman. They may not."* They did not.

**But a one-event evaluation structurally cannot see most of them, and that is the
more important half of the reading.** Measured on this capture:

| | what it touches at a GW3 evaluation |
|---|---|
| **S1** per-event availability | **cannot fire.** One event is projected; there is no horizon across which a scalar could be wrongly reused |
| **S2** `this_round` | **fires.** 66 of 652 players differ between the two fields; 23 differ once nulls fall through to the `next_round` path |
| **S3** return dates | **cannot fire.** 8 players carry a parseable date, but GW3 *is* the nearest gameweek, and the implementation deliberately does not consult the return date there — the API's direct statement about that round is fresher |
| **S4** departed | **fires, changes nothing.** 91 `status='u'` players, all already at `chance_of_playing_next_round = 0` |
| **S5** provenance | changes no number by construction |

So the +0.003 is **S2 alone**, and the honest statement is not "S1–S5 do not work"
but **"a single-event evaluation can only see one of them"**. S1 and S3 pay off
across a horizon, in `plan optimise`, which nothing in this repo measures. The gap
recorded in component-1.2-results.md §6 anticipated exactly this and is now
confirmed rather than closed.

---

## 3 — Diagnostics (not criteria)

FU-60 §5 names Brier and log loss as diagnostics of the minutes term, records the
reading in advance, and forbids either becoming a gate.

| variant | Brier | log loss | Σ `p_start` | actual starters |
|---|---|---|---|---|
| component/1.1-price | 0.1314 | 0.4042 | 277.5 | 220 |
| **component/1.2** | **0.1003** | **0.3194** | **192.0** | 220 |
| component/1.2-availability | 0.1291 | 0.3977 | 274.4 | 220 |

**The GW2 disagreement did not repeat. §5's clause does not fire.** At GW2, 1.2 won
`spearman_played` and Brier while losing log loss (0.5254 against 0.5016). At GW3 it
wins all three, and log loss by a wide margin. Recorded as FU-60 §5 requires: the
log loss delta, which is the tracked size of FU-57's residual, has gone from
**−0.0238 (against 1.2) at GW2 to +0.0848 (for 1.2) at GW3**.

**That is consistent with the recession FU-60 §4 predicted**, and it is not proof of
it. `a` moved from 1 to 2, so the evidence term's weight rose from 1/5 to 2/6 and
1.2's low priors bind less hard. But the population also changed (616 → 652), the
fixtures differed, and no error bar accompanies either figure.

---

## 4 — FU-57's defect is alive, large, and did not stop 1.2 winning

FU-60 §4.2 asks for the mechanism to be measured rather than inferred: the count of
players who have started every finished gameweek (`s = a = 2`) yet are rated at or
below 0.5.

183 players have `starts = 2`; 163 of them started GW3.

| variant | rated ≤ 0.5 | of which actually started GW3 |
|---|---|---|
| component/1.1-price | 1 | 0 |
| **component/1.2** | **59** | **48** |
| component/1.2-availability | 1 | 0 |

**1.2 suppresses 48 players who had started both previous gameweeks and started this
one too.** That is FU-57 exactly — the ownership prior pooled marginally over
`starts` — and it is entirely attributable to S6(a), since the variant without it
suppresses one player.

At the 0.5 diagnostic cut (not a decision boundary; nothing compares `p_start` to
0.5):

| variant | over 0.5 | caught | recall | precision |
|---|---|---|---|---|
| component/1.1-price | 280 | 200 / 220 | 91% | 71% |
| component/1.2 | 146 | 130 / 220 | **59%** | **89%** |
| component/1.2-availability | 278 | 200 / 220 | 91% | 72% |

**The reading that matters: 1.2 wins every headline metric *despite* this, not
because the defect went away.** Fixing FU-57 is therefore not a correction to a
model that is already winning by accident — it is upside on top of a model that is
winning while carrying a measured, localised fault. §7 still freezes it until the
pair completes.

---

## 5 — Category error

| Category | n | naive/1.0 | 1.1-price | **1.2** | 1.2-availability |
|---|---|---|---|---|---|
| Zeros | 354 | +0.356 | +0.972 | **+0.547** | +0.943 |
| Blanks | 179 | +1.168 | +0.801 | **+0.368** | +0.792 |
| Tickers | 54 | +0.028 | −0.954 | −1.042 | −0.969 |
| Haulers | 65 | −4.358 | −4.975 | −5.030 | −4.967 |

Zeros and Blanks both improve markedly under 1.2 and are untouched by S1–S5.
Tickers and Haulers are slightly worse, as at GW2 — and the Haulers error remains
the largest signed number in the table, still unaddressed by anything in
minutes-model.md, exactly as FU-53's oracle measured.

---

## 6 — FU-50 §4's control clause is satisfied across GW2 and GW3

Not a criterion of this document, but it is the comparison that decides whether the
component family survives at all, and two clean gameweeks now exist.

§4: *if the best component variant fails to beat `naive/1.0` on `spearman_played`
across two clean gameweeks, `naive/1.0` becomes the default.*

| | best component variant | `naive/1.0` | clears? |
|---|---|---|---|
| GW2 | `component/1.1-price` 0.359 | 0.330 | yes, +0.029 |
| GW3 | `component/1.2` 0.348 | 0.229 | yes, **+0.119** |

**The demotion is not triggered.** The GW3 margin is four times GW2's, on a metric
where `naive` actually fell (0.330 → 0.229) while component rose.

---

## 7 — What happens next

**Leg 2 is GW4.** Deadline 2026-09-12T12:30Z. The capture is secured: the
`fpl-sync.timer` next fires 2026-09-12T00:03Z, ~12.5h before the deadline, and the
timer was verified healthy on 2026-09-11. **GW4's fixture list must be checked for
blanks and doubles before the gameweek counts** (FU-50 §2); on the GW3 capture's
list it is ten fixtures with every team playing once, but that list is a week old.

**Nothing is promoted and nothing changes until leg 2 lands.** FU-57 and FU-58 stay
frozen (FU-60 §7). If 1.2 fails GW4, FU-60 §6.2's tightening applies: the pair is
GW3 and GW4, and a later attempt requires fresh pre-registration naming its
gameweeks in advance.

---

## 8 — Gaps

`[gap: one leg, and the pair exists precisely because one gameweek decides nothing.
+0.032 has no error bar, and neither did GW2's +0.035. Two agreeing gameweeks is
FU-50 §2's stated floor and explicitly "a coin flip's worth of confirmation", not
statistical power.]`

`[gap: the population grew from 616 at GW2 to 652 at GW3, so no absolute figure in
this document is like-for-like with its GW2 counterpart. The criterion is a
within-gameweek pairwise comparison and is unaffected; the cross-gameweek
observations in §3 — the log loss flip in particular — are not, and the change in
denominator is an uncontrolled alternative explanation for part of that movement.]`

`[gap: §2's decomposition is one observation. `component/1.2-availability` did not
exist at GW2, so there is no second reading of the S6(a)/S1-S5 split, and the
+0.029 / +0.003 division could look quite different at GW4. It will be measurable
there, which is the payoff for registering the variant late rather than not at
all.]`

`[gap: S1 and S3 remain unmeasured by anything, and this document establishes that
a single-event evaluation cannot measure them rather than that they are worthless.
Their claimed benefit is over a projection horizon, and the only consumer of a
horizon is `plan optimise`, whose output quality nothing in this repo scores. That
is the same limitation FU-50 §4 accepts knowingly, arriving in a second place.]`

`[gap: §4's 48 suppressed nailed starters is measured against `p_start ≤ 0.5`, a
cut with no standing in the model. The count is a legible proxy for the defect's
size and not a measure of its cost, which would have to be expressed in projected
points or in transfer decisions, and is not.]`

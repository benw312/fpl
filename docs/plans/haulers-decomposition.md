# The haulers error — decomposed, and mostly not what it looked like

**Analysis only. No model changed, no constant touched, no `src/` file modified.**
FU-50 §3 governs: where this points at a number, it is filed and left.

**Pinned inputs, cited per FU-40.** GW2: `~/fpl-pinned/gw2-pre-deadline.json`
(sha256 `593f60c2e356…`), `gw2-fixtures.json` (`fbd4457e5c81…`), `gw2-live.json`
(`afdaf81a6fcd…`). GW3: `gw3-pre-deadline.json` (`0cc7193b5e20…`),
`gw3-fixtures.json` (`5cc5817d3385…`), `gw3-live.json` (`cd86195071cd…`). Both
gameweeks settled and clean. Digests `component/1.1-price+banded` `24c305e2025c`,
`component/1.2+banded` `4f479b2253cc`, `naive/1.0` `1ad0cd721b2e`.

**Why this was started.** The Haulers row has been the largest signed error in every
category table since GW1 — −5.44 at GW2, −5.03 at GW3 — and FU-53 measured that a
*perfect minutes model* only takes it to −4.11, so roughly three-quarters of it is
not minutes. Nothing in minutes-model.md addresses it. The intention was to localise
it by component and then bound the prize with an oracle, as FU-53 did for minutes.

**The oracle was not needed, and should not be built for this.** The decomposition
answered a different question than the one asked.

---

## 1 — Where the haulers error sits, by component

Signed mean error over the Haulers bucket (actual points ≥ 5), `component/1.2`:

| component | GW2 (n=63) | share | GW3 (n=65) | share |
|---|---|---|---|---|
| attack | −2.659 | **48%** | −1.717 | **34%** |
| clean_sheet | −1.158 | 21% | −1.583 | **31%** |
| bonus | −0.818 | 15% | −0.809 | 16% |
| appearance | −0.607 | 11% | −0.516 | 10% |
| defcon | −0.236 | 4% | −0.295 | 6% |
| conceded | −0.067 | 1% | −0.134 | 3% |
| saves, cards | −0.039 | 1% | +0.025 | −1% |
| *[unmapped]* | +0.032 | −1% | +0.000 | 0% |
| **total** | **−5.552** | | **−5.030** | |

Three components — attack, clean sheet, bonus — carry 84% and 81%.
`component/1.1-price` is within 0.05 of these on every row, so the split is a
property of the component model rather than of the minutes work.

**That table is true and it is not the finding**, because of §2.

---

## 2 — The Haulers row is substantially a selection-on-outcome artefact

The bucket is defined by the **realised** total. Hauling is a tail event: a player
with 0.4 xG who scores twice hauls, and the same player is a blank most weeks. So
conditioning on "scored ≥ 5" and then measuring signed error asks a well-calibrated
model to have predicted the upper tail of its own distribution, which by
construction it does not.

Two pieces of evidence that the row is measuring the bucket rather than the model.

**The model's prediction is nearly flat across the bucket while the outcome is not.**
`component/1.2` at GW3:

| band | n | mean actual | mean predicted | error |
|---|---|---|---|---|
| 5–8 | 49 | 6.41 | 2.41 | −4.00 |
| 9–12 | 13 | 10.23 | 2.68 | −7.55 |
| 13+ | 3 | 14.00 | 3.04 | −10.97 |

Predictions move 0.6 points across a 7.6-point spread of outcomes. The error is
almost exactly the outcome minus a constant — the signature of a conditional mean
being scored against tail realisations, not of a broken component.

**And the least-biased model on this bucket is the most over-predicting model
overall.** `naive/1.0` shows a Haulers error of −4.36 at GW3 against component's
−5.03 — while over-predicting total points by 5.8%. Component's "worse" Haulers row
is substantially the arithmetic consequence of it being the less over-predicting
model, not of a weaker attacking term.

**Conclusion: do not direct effort at the Haulers row on the strength of its size.**
The correct diagnostic bins on the **prediction**, not the outcome, which is what §3
does. Filed as **FU-61**, because the category table is presented in every
evaluation run with no such warning attached.

---

## 3 — Calibration by predicted bin, which is the diagnostic that works

Binning on predicted xP removes the selection. GW3, all projected players:

| predicted xP | n | mean pred | mean actual | bias | P(haul) |
|---|---|---|---|---|---|
| **component/1.1-price** | | | | | |
| 0–1 | 150 | 0.02 | 0.01 | +0.01 | 0% |
| 1–2 | 290 | 1.60 | 0.76 | **+0.84** | 4% |
| 2–3 | 174 | 2.45 | 3.18 | −0.73 | 25% |
| 3–4 | 34 | 3.35 | 3.26 | +0.09 | 24% |
| **component/1.2** | | | | | |
| 0–1 | 370 | 0.43 | 0.35 | +0.08 | 2% |
| 1–2 | 141 | 1.47 | 2.06 | −0.59 | 14% |
| 2–3 | 88 | 2.52 | 2.97 | −0.45 | 20% |
| 3–4 | 37 | 3.40 | 4.16 | −0.76 | 41% |
| 4–5 | 13 | 4.42 | 4.77 | −0.35 | 38% |

**The model discriminates.** P(haul) runs 2% → 41% across `component/1.2`'s bins.
The information is present; the haulers are not invisible to it.

**`component/1.1-price` over-predicts the bulk and under-predicts above it.** The
1–2 bin holds 290 of 652 players and is over-predicted by 0.84 — the single largest
mass of error anywhere in this analysis, and it does not appear in the category
table at all. 1.2 removes most of it (+0.08 and −0.59 in the two lowest bins).

---

## 4 — The real finding: a stable aggregate scale bias

| | GW2 | GW3 |
|---|---|---|
| `component/1.1-price` total predicted vs actual | **+20.2%** | **+12.3%** |
| `component/1.2` | **−13.5%** | **−13.6%** |
| `naive/1.0` | +5.7% | +5.8% |

**1.2 under-predicts total points by 13.5% and 13.6% in two consecutive gameweeks.**
That stability across a changed population (616 → 652) and different fixtures is not
noise; it is a systematic scale error.

**It is substantially the minutes term, which makes FU-57 worth more than it
looked.** The minutes term is the only difference between the two variants, and they
sit either side of zero. At GW3 `component/1.2` predicts 192.0 starters against 220
realised — **−12.7%** — against a total-points error of −13.6%. The two track each
other closely. `component/1.1-price` over-calls starters by 26% and over-predicts
points by 12.3%; the mapping is not 1:1, and no formal decomposition is offered
here, but the direction and rough magnitude line up in both variants and both
gameweeks.

FU-57 was filed as a recall problem. It is also the aggregate calibration problem.

### Why a uniform scale error mostly does not matter — and where it does

`spearman_played` is rank-based and therefore scale-invariant, and the optimiser
maximises summed xP over paths, so a uniform multiplicative error leaves the argmax
unchanged. **Every criterion in FU-50 and FU-60 is blind to this by design.**

It is not harmless everywhere. Two constants in the objective are denominated in
**real** points and are netted against model xP:

- `DEFAULT_FT_VALUE = 1.5` (`optimizer.py:48`), the terminal value of a banked free
  transfer;
- `_hit_points`, the 4-point charge per extra transfer.

Against an xP scale running 13.6% low, a 4-point hit costs the equivalent of 4.63
model-points and a banked transfer is worth 1.74 — so the optimiser systematically
**under-takes hits and over-values holding**. Filed as **FU-63**.

---

## 5 — Range compression

| | predicted SD | predicted max | actual SD | actual max |
|---|---|---|---|---|
| GW3 `component/1.1-price` | 1.01 | 4.61 | 2.40 | 15 |
| GW3 `component/1.2` | 1.12 | 5.68 | 2.40 | 15 |
| GW3 `naive/1.0` | 2.22 | 12.50 | 2.40 | 15 |
| GW2 `component/1.2` | 0.95 | 4.36 | 2.60 | 23 |

**A conditional expectation *should* have lower dispersion than the outcome** — that
is the law of total variance, not a defect, and naive's 2.22 is mostly noise rather
than signal. So this is not straightforwardly wrong.

What it does mean is that **the component model cannot express a captaincy-grade
pick**. Its entire output lives in [0, 5.7] while outcomes reach 15–23, so the gap
between the best and fourth-best option is a few tenths and small errors reorder the
top of the list freely. Whether the model's dispersion is as large as the available
information permits is **not established here** and is the substantive open
question. Filed as **FU-62**.

---

## 6 — What was filed, and what was deliberately not built

**FU-61** — the Haulers row is a selection-on-outcome artefact and the category
table carries no warning saying so.
**FU-62** — prediction range compression; whether the dispersion is as large as the
signal allows.
**FU-63** — the aggregate scale bias, its link to FU-57, and the two real-points
constants it interacts with.

**The attacking oracle was not built.** The plan was to bound the attacking prize as
FU-53 bounded the minutes prize. §2 shows the premise was wrong: substituting
realised goals and assists would drive the attack error to zero by construction and
report a large "prize" that is mostly the tail of a Poisson being read as
predictable. FU-53's technique works for minutes because appearance is genuinely
close to deterministic given the right information; it does not transfer to scoring,
and building it would have produced a confidently wrong number. **That is the main
thing this analysis bought.**

---

## 7 — Gaps

`[gap: two gameweeks, 63 and 65 haulers. Every figure in §1 is a mean over a bucket
of that size with no error bar, and the attack/clean-sheet split moved from 48/21 to
34/31 between them — which is either a real difference between gameweeks or the
noise you would expect from n=63.]`

`[gap: §4 asserts the scale bias is "substantially" the minutes term on the strength
of two variants differing only there, plus a numerical coincidence at GW3 (−12.7%
starters against −13.6% points). No decomposition is offered, and the 1.1-price arm
does not line up nearly as well (+26% against +12.3%). The claim is directional and
should not be quoted as a measurement.]`

`[gap: §5 does not establish that the compression is a defect. Testing it means
comparing the model's dispersion against the maximum achievable given the payload,
which needs a second model with access to the same information and more dispersion —
or a variance decomposition this analysis does not perform.]`

`[gap: the calibration bins in §3 are equal-width in predicted xP, not equal-count,
so the top bins hold 13-37 players and their biases carry correspondingly little
weight. A quantile binning would read differently and was not done.]`

`[gap: `official-ep/1.0` has predicted SD 0.85 and max 4.00 at GW2 but 2.17 and
12.50 at GW3 — the API's own projection apparently changed character between
captures. Noticed and not investigated; it may be an artefact of `ep_next` being
populated differently early in the season, and it bears on how much weight
official-ep deserves as a comparator.]`

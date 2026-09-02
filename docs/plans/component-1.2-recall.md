# Why component/1.2 lost recall on starters — diagnosis

**Analysis only. No constant changed, no parameter adjusted, no model touched.**
The branch that writes this modifies no `src/` file. FU-50 §3 governs throughout:
where the diagnosis points at a number, it is filed and left.

**Pinned inputs, cited per FU-40.** `~/fpl-pinned/gw2-pre-deadline.json` (sha256
`593f60c2e356c4e94205f10248dfd834f4797ad6c736ea73b239da610d84ffcf`, captured
2026-08-28T00:32:59Z), `~/fpl-pinned/gw2-fixtures.json` (sha256 `fbd4457e5c81…`),
outcomes from `~/fpl-pinned/gw2-live.json` (sha256 `afdaf81a6fcd…`, GW2 settled).
Model versions `component/1.1-price+banded` (digest `24c305e2025c`) and
`component/1.2+banded` (digest `4f479b2253cc`). 616 players, 220 of whom started
GW2.

---

## 0 — The answer in one paragraph

**At `appearances = 1` and `shrinkage_k = 4`, one start is worth exactly 0.2 of
probability, so a player with one start clears `p_start > 0.5` only if their prior
exceeds 0.375.** `component/1.1-price`'s four flat priors — 0.85, 0.65, 0.55, 0.55
— all exceed it, so *every* available player with a start cleared the threshold
automatically, whoever they were. That is what its 88% recall was: not knowledge,
but a prior uniformly above the bar. `component/1.2`'s pooled band priors are below
0.375 in all four `<1%`-ownership cells, and **84 of the 94 missed starters sit in
one of those four cells**. The ownership conditioning fired for them and pushed them
*down*, because the band prior is pooled marginally over `starts` while §2.4's
signal is an interaction between the two.

---

## 1 — The 94, characterised

Of the 220 actual GW2 starters, 1.1-price missed 26 and 1.2 misses 94. **70 are
newly missed**; 2 are newly rescued.

| | n | started GW1 | mean `p_start` 1.1-price | mean `p_start` 1.2 |
|---|---|---|---|---|
| **all newly missed** | **70** | **62** | 0.669 | 0.347 |
| GKP | 5 | 3 | 0.800 | 0.286 |
| DEF | 30 | 24 | 0.680 | 0.323 |
| MID | 34 | 34 | 0.640 | 0.380 |
| FWD | 1 | 1 | 0.640 | 0.256 |
| `<1%` owned | **66** | 61 | 0.670 | 0.356 |
| 1–5% owned | 3 | 1 | 0.693 | 0.267 |
| 5–15% owned | 1 | 0 | 0.520 | 0.000 |
| `starts = 1` | **62** | 62 | 0.683 | 0.379 |
| `starts = 0` | 8 | 0 | 0.560 | 0.103 |

**Confirmed: the concentration is exactly where predicted.** 62 of 70 started GW1,
and 66 of 70 are in the `<1%` ownership band. Position × band, the newly missed:

| | `<1%` | 1–5% | 5–15% | `>15%` |
|---|---|---|---|---|
| GKP | 3 | 2 | 0 | 0 |
| DEF | 28 | 1 | 1 | 0 |
| MID | **34** | 0 | 0 | 0 |
| FWD | 1 | 0 | 0 | 0 |

### The arithmetic: confirmed in direction, understated in magnitude

The expectation was that a MID who started reads `(1 + 4 × 0.341) / 5 = 0.473` on
the **position** prior — below the threshold on the prior alone. That is right, and
the real figure is lower still, because 1.2 does not use the position prior for
these players. It uses the `<1%` **band** prior, which for MID pools to **0.225**:

```
    (1 + 4 × 0.225) / 5  =  0.380     against a realised start rate of 0.756
```

**The general form, which is the cleanest statement of the defect.** With
`appearances = 1`:

```
    p_start = (1 + k·prior) / (1 + k)  >  0.5   ⟺   prior > 0.375     [k = 4]
```

One start buys `1/(1+k) = 0.2` of probability and nothing else can change that.
Against that bound, the sixteen (position, band) cells split cleanly:

| cell | band prior | one start clears 0.5? | missed starters here |
|---|---|---|---|
| GKP `<1%` | 0.095 | **no** | 3 |
| DEF `<1%` | 0.235 | **no** | 28 |
| MID `<1%` | 0.225 | **no** | 48 |
| FWD `<1%` | 0.070 | **no** | 5 |
| GKP 1–5% | 0.466 | yes | 2 |
| DEF 1–5% | 0.654 | yes | 1 |
| MID 1–5% | 0.567 | yes | 5 |
| FWD 1–5% | 0.486 | yes | 1 |
| DEF 5–15% | 0.821 | yes | 1 |
| *(the other six cells)* | 0.415–0.808 | yes | 0 |

**84 of the 94 sit in a cell where a single start mathematically cannot clear the
threshold.** The remaining 10 are unavailability cases — a `chance_of_playing`
below 100 scaling an otherwise-sufficient `p_start` under the bar.

---

## 2 — The ownership band fired, and it fired the wrong way

**Of the 94 missed starters, 84 sit in a band whose prior is *below* the position
prior; only 10 sit in one that lifts them.** Band conditioning did not fail to
rescue these players — it is the reason they fell.

**The signal §2.4 measured is real.** Within the `starts = 1` stratum, realised GW2
start rates by ownership band on this capture:

| | `<1%` | 1–5% | 5–15% | `>15%` |
|---|---|---|---|---|
| DEF | 0.800 (n=30) | 0.968 (n=31) | 0.833 (n=18) | 1.000 (n=8) |
| MID | 0.756 (n=45) | 0.741 (n=27) | 0.909 (n=11) | 1.000 (n=9) |
| GKP | 0.667 (n=3) | 0.900 (n=10) | 1.000 (n=3) | 1.000 (n=4) |

§2.4's 76%→100% spread is reproduced. **The implementation applies it in the wrong
place.** §2.4's table stratifies by `starts` *and* ownership; `build_start_priors`
conditions the prior on ownership **marginally over `starts`**, then re-introduces
`starts` as evidence at 20% weight. In the `<1%` band the population is dominated
by players who never start — MID `<1%` holds 202 players of whom 157 have
`starts = 0` — so the band prior pools to 0.223 and encodes *"a randomly chosen
`<1%`-owned midfielder rarely starts"*. True, and irrelevant to a `<1%`-owned
midfielder who started last week.

**This is a modelling error, not a tuning error.** The prior is marginal where the
measured discriminator is an interaction, and no value of any constant fixes that.

### What `own_band_prior_appearances = shrinkage_k` does to the band's influence

The band prior is shrunk toward the position prior with weight 4 appearances
against a band exposure of `players × appearances`. On this capture:

| cell | players | exposure | band's own weight | raw pooled | shrunk |
|---|---|---|---|---|---|
| MID `<1%` | 202 | 202 | **98.1%** | 0.223 | 0.225 |
| DEF `<1%` | 131 | 131 | **97.0%** | 0.229 | 0.235 |
| FWD `<1%` | 41 | 41 | 91.1% | 0.049 | 0.070 |
| GKP `<1%` | 40 | 40 | 90.9% | 0.075 | 0.095 |
| MID 5–15% | 13 | 13 | 76.5% | 0.846 | 0.727 |
| GKP 5–15% | 3 | 3 | 42.9% | 1.000 | 0.597 |

**The thin-band guard does essentially nothing where the misses are.** In the four
populous `<1%` bands the prior is 91–98% the band's own pooled rate, so §8.7's
protection is inert exactly where the damage occurs — it is designed for the
opposite case, and it does work there (GKP 5–15%, n=3, pulled from 1.000 to 0.597).
Reusing `shrinkage_k` is therefore doing what FU-55 claimed for it and is not
implicated in the recall loss: **a larger band weight would pull every band toward
a position prior that is itself below 0.375 for GKP, MID and FWD, and would not
help.**

---

## 3 — The pooled prior's shape: every position is bimodal

Per-player realised start rate over the two settled gameweeks (GW1 from the
capture's `starts`, GW2 from the live payload). Two observations, so the only
attainable values are 0, 0.5 and 1 — which is itself most of the finding.

| position | n | rate 0 | rate 0.5 | rate 1 | pooled mean | median | share strictly between |
|---|---|---|---|---|---|---|---|
| GKP | 68 | 46 | **4** | 18 | 0.294 | 0.0 | **5.9%** |
| DEF | 205 | 108 | 20 | 77 | 0.424 | 0.0 | 9.8% |
| MID | 270 | 158 | 39 | 73 | 0.343 | 0.0 | 14.4% |
| FWD | 73 | 47 | 11 | 15 | 0.281 | 0.0 | 15.1% |

**No position is unimodal, and goalkeepers are the extreme case as expected.** 46
goalkeepers never started, 18 always did, 4 did once. The pooled mean of 0.294 is a
value **almost no goalkeeper takes**: it is a mixture weight between two near-degenerate
populations, not a central estimate of anything. The median is 0.0 in every
position — the pooled mean does not even sit on the modal side of the distribution
for three of four.

**What follows.** Shrinking a player toward the pooled mean shrinks them toward a
point in the trough between the two modes. For a player in the upper mode that is a
large error in one direction; for one in the lower mode it is a smaller error in
the other. It is a defensible operation only if the prior is genuinely uninformative
about which mode the player is in — and ownership plus `starts` is precisely
information about which mode the player is in, which is §2's whole argument. **The
right structure conditions on mode membership; the current one averages across it.**

`[gap: two observations per player is the minimum at which "bimodal" is even
sayable, and the 0/0.5/1 support is forced by that rather than discovered. The
shape is consistent with everything §2.4 and §2.5 measured and with how football
squads work, but the histogram above cannot distinguish a genuinely bimodal
population from any other with two draws per player. Re-measure once `starts` has
range — the same condition FU-50 §3 and minutes-model.md §9 already name.]`

---

## 4 — The departed-player contamination: real, small, and not the cause

The suspicion recorded in component-1.2-results.md §6 was that pooling over a
population containing players who will never appear was the most likely cause of
the recall loss. **Measured, it is not.**

45 players have `can_select = False` or `removed = True`. All 45 have `status = 'u'`;
**none started GW2**. The 44 that S4's news regex identifies are a strict subset.

Pooled position priors, recomputed over each population:

| population | n | GKP | DEF | MID | FWD |
|---|---|---|---|---|---|
| as shipped (all 616) | 616 | 0.294 | 0.424 | 0.341 | 0.288 |
| validator-selectable | 571 | 0.339 | 0.458 | 0.357 | 0.328 |
| not departed (S4's set) | 572 | 0.339 | 0.458 | 0.357 | 0.323 |
| **delta, selectable** | | **+0.045** | **+0.034** | **+0.016** | **+0.040** |

And in the `<1%` bands, where 84 of the 94 sit:

| | shipped | selectable | delta |
|---|---|---|---|
| GKP `<1%` | 0.095 | 0.124 | +0.030 |
| DEF `<1%` | 0.235 | 0.265 | +0.030 |
| MID `<1%` | 0.225 | 0.239 | **+0.014** |
| FWD `<1%` | 0.070 | 0.092 | +0.022 |

**For the MID `<1%` cell the correction moves `p_start` from 0.380 to 0.391 against
a realised 0.756 — it closes 3% of the gap, and leaves the cell far below the 0.375
prior bound.** Excluding unselectable players does not restore a single one of the
84. The earlier suspicion is refuted and should not be carried forward.

### Is excluding them the correct definition on its own terms?

**Yes, independently of what it does to the numbers, and that is the argument for
doing it.** The prior answers "how likely is a player of this description to start".
A player the validator rejects cannot be in a squad, cannot be transferred in, and
cannot start; including them puts a structural zero into an estimate of a
behavioural rate. The population the prior describes should be the population the
prior is applied to, and `domain/rules.py:57` already defines that population for
every other purpose in the repo. The prior currently uses a different one for no
stated reason.

The measurement above is what stops this being self-serving: the correction is
small and does not rescue the metric, so adopting it is a correctness argument
rather than a result-chasing one — which is the only condition under which it can
honestly be adopted at all. **Filed as FU-58**, together with a second finding it
turned up.

### The second finding: S4 parses prose for a boolean the API publishes

`has_departed` runs a regex over `news` looking for transfer and loan phrasings. It
finds 44 players. `can_select = False or removed = True` finds those same 44 **plus
one** — Uche, `status='u'`, news `"has returned to Getafe CF"`, a phrasing the
regex's anchors miss and which did not start GW2. The boolean is published by the
API, is already parsed onto `Player`, needs no pattern, cannot drift as the
templates change, and is what the squad validator already trusts. **S4 should read
it.** No chosen constant, strictly simpler, one more player caught. Also FU-58.

---

## 5 — A correction to how the loss was reported

component-1.2-results.md §4 framed this as recall 88% → 57%, precision 58% → 83%,
and said the model had moved "from over-calling by half to under-calling by a
third". **The direction is right and the magnitude was overstated**, because
`p_start > 0.5` is a diagnostic cut from §4.2 and not a decision boundary: nothing
in the code compares `p_start` to 0.5, and the optimiser consumes it as a
continuous multiplier inside `xp_total`. Threshold-free, against the 220 realised
starts:

| model | Brier | log loss | Σ `p_start` | actual |
|---|---|---|---|---|
| component/1.1-price | 0.1727 | **0.5016** | 292.3 | 220 |
| component/1.2 | **0.1310** | 0.5254 | **188.6** | 220 |

**1.2's expected number of starters is 188.6 against 220 — short by 14%, not by a
third** — where 1.1-price predicted 292.3, long by 33%. On Brier score 1.2 is
substantially better. It is worse on log loss, which is the honest counterweight
and says exactly what §1 diagnosed: log loss punishes confident errors, and 1.2 is
confidently wrong about 84 real starters it has pushed toward the bottom of the
`<1%` band.

So the fair summary is that **1.2 is better calibrated in aggregate and by Brier,
worse by log loss, and carries one concentrated, diagnosable defect** — not that it
has broadly lost the ability to identify starters.

---

## 6 — What is filed, and what is left alone

**Structural, no chosen constant — filed:**

- **FU-57.** The ownership prior is marginal over `starts` where §2.4's signal is an
  interaction between the two. The fix conditions the prior within the `starts`
  stratum, which needs a second observation per player and therefore the
  per-gameweek start series of minutes-model.md §4.3(c). That work was already
  deferred in §6.3 on cost grounds; this gives it the measured motivation it
  lacked. **There is no fix available inside a single snapshot**: within one
  finished gameweek every `starts = 1` player has a start rate of exactly 1.0, so
  the conditional prior is degenerate and carries no information.
- **FU-58.** Define the prior population as the one the validator accepts, and read
  `can_select`/`removed` instead of regexing `news` for S4.

**Parameter — filed and left for FU-50 §3:**

- **FU-59.** `shrinkage_k = 4.0` is directly implicated: it sets the 0.375 bound, and
  §6.2 already named it "the one most obviously implicated by §4.2". It is not
  touched here, and this document is not evidence that it should be — one gameweek,
  `starts` binary, no error bars. minutes-model.md §6.2's own note that S6 "reduces
  the pressure on it structurally" now reads differently: S6(a) as built *increases*
  the pressure, because a lower prior makes the 20% evidence weight bind harder.

`[gap: one gameweek, and the arithmetic in §1 is specific to `appearances = 1`.
**Corrected 2026-09-02 by FU-60 — the first version of this gap said 0.167, which is
the per-start evidence weight `1/(a+k)` at `a = 2` and not a prior bound at all.**
The bound is `prior > 0.5 + (0.5a − s)/k` for `s` starts in `a` appearances. It
loosens only for a player who starts *every* appearance: 0.375, 0.250, 0.125, 0.000
at `a` = 1 to 4. For one with a single start it tightens: 0.375, 0.500, 0.625. So the
defect recedes for nailed starters — the MID `<1%` band clears 0.5 at `a = 3`, which
is the GW4 evaluation — and deepens for rotation players. A fix designed against the
GW2 arithmetic is chasing a target moving in both directions at once. FU-60 fixes
what a GW3 or GW4 result may be read to mean in light of this.]`

`[gap: §2 shows band conditioning hurt the `<1%` stratum and §1's table shows it
helped every other one — DEF 5–15% and `>15%` reach 0.821 and 0.808 against a flat
0.65. Whether S6(a) is net positive on `spearman_played` is measured (0.359 →
0.394, component-1.2-results.md §5) but not decomposed, so this document cannot say
how much of that gain came from the bands it helped against the loss from the band
it hurt.]`

`[gap: the whole diagnosis is conditional on `p_start` being the quantity that
matters. §5 shows the 0.5 threshold overstated the problem, and nothing here
measures the effect on `plan optimise`'s output — the same limitation FU-50 §4
accepts knowingly for `spearman_played`. 84 players moved from 0.6 to 0.35 changes
which transfers are recommended, and nothing in this repo measures whether it
changes them for the better.]`

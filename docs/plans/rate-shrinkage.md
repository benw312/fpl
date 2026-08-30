# Rate shrinkage — the unshrunk per-90 terms, and what to do about them

**Status:** design only. Nothing implemented; `src/` untouched on this branch.
**Answers:** [follow-ups.md](follow-ups.md) FU-47.
**Supersedes FU-47 in two places**, both recorded in §1.4: the scope is six rates
rather than four, and the prior should be *derived from the snapshot* rather than
hand-picked as the entry proposes. FU-47's body is left as written — it is the
record of what was believed when it was filed, and correcting it in place would
lose that. Where the two disagree, this document wins.
**Measured against:** `~/fpl-pinned/gw2-pre-deadline.json` and
`~/fpl-pinned/gw2-fixtures.json` (`captured_at` 2026-08-28T07:26:38Z), under model
version **`component/1.0+banded`**, 2026-08-29, per FU-40 — which since
`task/model-versioning` requires the model version alongside the two captures. Every
figure below is reproducible from that triple. The "before" column throughout is
`component/1.0` as registered in `domain/variants.py`; the "after" columns are the
demonstration parameters named in §5 and are **not** a registered variant, because no
model reads `RateShrinkageConfig` yet.

---

## 1 — The defect

### 1.1 It is an inconsistency, not a modelling judgement

`domain/projections.py` already knows that a rate estimated from a small sample
must be pulled toward a prior. It does this three times:

- `shrunk_start_rate = (starts + k·prior) / (appearances + k)`, `k = 4`
  (`projections.py:84`)
- `e_mins_start`, shrunk toward `mins_per_start_prior = 75.0` with the same `k`
  (`projections.py:91-93`)
- `shrunk_bonus_per_90 = raw · minutes / (minutes + 450)` (`projections.py:172`)

And then, in the same function, it consumes four rates exactly as the API publishes
them and builds two more from raw counts inline. The file applies the principle to
some terms and not others, with nothing recording a reason. That is what makes this
a defect rather than a judgement call: **no argument was ever made for the
asymmetry.**

### 1.2 What it produces

Measured on the pinned capture, projecting GW3:

| Player | Input | Consequence |
|---|---|---|
| De Cuyper (BHA, DEF) | `xG90 = 1.72` from **77 minutes** | `xp_attack = 7.96` of a 10.28 total; ranks 1st, ahead of every forward |
| Alcaraz (EVE, MID) | `dc90 = 270.0` from **1 minute** — 3 actions | `xp_defcon` saturates at its 2.00 cap; ranks 3rd |
| J.Murphy (MID) | `yellow_per_90 = 6.43` from **14 minutes** | 41× the league rate of 0.156 |
| Haaland (MCI, FWD) | `xG90 = 0.74` from a full 90 | 3.43 total, 26th |

A 270-per-90 rate from one minute is indefensible whatever any evaluation says.
That claim does not depend on GW2, on this capture, or on the projections being
validated — see §9.

### 1.3 There are six rates, not four

FU-47 names four. Two more have the same defect and were found while measuring for
this document:

| Rate | Treatment today | Verdict |
|---|---|---|
| `expected_goals_per_90` | raw from API | unshrunk |
| `expected_assists_per_90` | raw from API | unshrunk |
| `defensive_contribution_per_90` | raw from API | unshrunk |
| `saves_per_90` | raw from API | unshrunk |
| yellow / red per 90 | **built raw inline** at `projections.py:175-176` | unshrunk — **not in FU-47** |
| bonus per 90 | shrunk, but **toward zero** | wrong prior — **not in FU-47** |

The cards terms compute `player.yellow_cards / (player.minutes / 90)` in the body
of `_component_points_for_fixture`. They never touch an API per-90 field, so a fix
scoped to "the four `*_per_90` inputs" would leave them untouched.

`xp_bonus` is shrunk with the right algebra toward the wrong target. Its prior is
`0.0`: a player with 450 minutes at exactly the league bonus rate keeps half of it
and is pulled toward zero rather than toward the league rate of **0.293** per 90.
That biases every bonus estimate downward, and hardest for the players with fewest
minutes.

**This is the strongest argument for the guard test in §8.** The task that
commissioned this document asked for a test that stops the defect returning "for a
fifth component later". A fifth already existed and had gone unnoticed through two
plans and a follow-up entry.

### 1.4 Where this supersedes FU-47

1. **Scope.** Four rates → six.
2. **The prior.** FU-47 proposes *"a positional prior … a new
   `[assumption: no empirical basis]`, flagged alongside the existing seven"*.
   §3 shows the prior is computable from the snapshot, so it need not be invented
   and should not be. The fix **reduces** the count of hand-picked constants in the
   file rather than adding to it.

---

## 2 — What `bootstrap-static` provides, and what it does not

Checked against the pinned capture: 109 fields per element.

**Not available — say so plainly:**

- **No last-season data of any kind.** No previous-season totals, rates, or points.
  Season history lives on `element-summary/{id}`, which is not implemented (FU-4).
  Any prior built from "what this player did last year" is out of reach today and
  would need that endpoint first.
- **No shot or attempt counts.** `xG` is published, the shot count behind it is not.
  This matters for §4's choice of unit.
- **No minutes-by-gameweek.** `minutes` is a season total, so exposure cannot be
  attributed to particular fixtures without `element-summary`.

**Available and load-bearing:**

- **The cumulative count behind every rate.** `expected_goals`,
  `expected_assists`, `defensive_contribution` and `saves` are each published
  alongside their per-90. Verified: `per_90 == cumulative / (minutes/90)` for all
  310 players with minutes, maximum absolute deviation **0.005**, which is
  two-decimal rounding in the payload. The per-90 fields carry no information the
  count and the minutes do not.

  This is the structural fact the whole design rests on. Shrinkage can be a
  pseudo-count posterior on the numerator rather than a fudge applied to a ratio.
- **`now_cost`.** FPL's own pre-season assessment of a player, available before a
  ball is kicked and not derived from this season's results. §3 measures whether it
  carries signal.
- **Set-piece flags** — `penalties_order` (66 players), `direct_freekicks_order`
  (56), `corners_and_indirect_freekicks_order` (81). Not used by this design; noted
  because they are the obvious next prior source and are already in the payload.

---

## 3 — What each rate shrinks toward

### 3.1 Pooled, not the mean of ratios

The prior for a rate is the **minutes-weighted pooled rate** for the group:
`sum(count) / sum(minutes) × 90`. It is *not* the average of players' per-90
figures, and the difference is the defect in miniature:

| Rate | Position | Pooled | Mean of ratios |
|---|---|---|---|
| dc90 | MID | **8.396** | 11.475 |
| dc90 | DEF | 7.573 | 7.637 |
| xG90 | FWD | 0.469 | 0.406 |

The MID row is inflated by Alcaraz's 270.0. A prior computed as a mean of ratios
would import the very outlier the shrinkage exists to suppress. Pooling weights
each player by exposure, which is the correct estimator and is immune to it.

Derived per position from the pinned capture:

| | GKP | DEF | MID | FWD |
|---|---|---|---|---|
| xG90 | 0.000 | 0.083 | 0.157 | 0.469 |
| xA90 | 0.003 | 0.065 | 0.122 | 0.090 |
| dc90 | 0.000 | 7.573 | 8.396 | 4.149 |
| saves90 | 2.950 | 0.000 | 0.000 | 0.000 |

Two things fall out of this table that a single shared prior would get wrong.
`xA90` is **higher for midfielders than for forwards** (0.122 vs 0.090). And
`saves90` is exactly zero for every outfielder and is consumed only for
goalkeepers (`projections.py:158`), so its prior is one number, not a table.

### 3.2 Does price carry signal? Measured, and the answer differs by rate

Spearman correlation between `now_cost` and the realised rate, among players with
≥45 minutes:

| Rate | GKP | DEF | MID | FWD |
|---|---|---|---|---|
| xG90 | — | 0.194 | **0.458** | **0.455** |
| xA90 | 0.156 | 0.173 | **0.356** | −0.145 |
| dc90 | — | −0.060 | −0.103 | −0.318 |
| saves90 | −0.087 | — | — | — |

**Price predicts attacking output and does not predict defensive contribution.**
That is not a surprise once stated — defensive contribution was introduced as a
route for cheap defenders to score, and the negative FWD coefficient says expensive
forwards do less defensive work, which is true and is not a signal worth importing.

So the answer to "what does each rate shrink toward" is genuinely four answers:

| Rate | Prior | Because |
|---|---|---|
| xG90, xA90 | **price-conditioned position rate** | ρ ≈ 0.46 (xG90, MID/FWD) and 0.36 (xA90, MID). Price is pre-season information the position mean throws away, and it is what separates Haaland from a £4.5m bench forward before either has played. |
| dc90 | **position rate only** | ρ ∈ [−0.32, −0.06]. Conditioning on price would add noise, or worse, signal with the wrong sign. |
| saves90 | **GKP rate only** (2.950) | ρ = −0.087. The real confound is team defensive quality, and the model already handles it: `saves_lambda` scales by `xg_against / league_mean` (`projections.py:159`). Conditioning the prior on price too would double-count it. |
| yellow, red | **position rate only** | Rare events with no plausible price story. DEF and MID book more than FWD, so position still matters. |
| bonus | **position rate** (currently `0.0`) | The algebra is already right; only the target is wrong. §1.3. |

### 3.3 A price band of one player must not become its own prior

Pooled xG90 by price band, minutes-weighted:

```
FWD  £4m:0.00  £5m:0.34  £6m:0.42  £7m:0.41  £8m:1.10  £9m:1.09  £15m:0.74
MID  £4m:0.00  £5m:0.09  £6m:0.21  £7m:0.41  £8m:0.24  £9m:0.56  £12m:0.08
```

The bands are not monotone, and the top band is worst: **Haaland is the only £15m
forward**, so his band's pooled rate is his own rate, and shrinking him toward it
would do nothing at all. The £12m MID cell has the same problem.

**The band estimate must itself be shrunk toward the position rate** — a two-level
hierarchy:

```
band_prior = (band_pooled · band_minutes + position_pooled · BAND_M) / (band_minutes + BAND_M)
```

A thin band is pulled to the position rate and a well-populated one keeps its own
level. `BAND_M` is a variant constant (§7); the measurements in §5 use 900.

---

## 4 — The shrinkage form, and its parameter

### 4.1 The form is already in the file

For a rate with cumulative count `c` over `m` minutes (exposure `e = m/90`), prior
rate `p`, and prior weight `M` minutes:

```
shrunk = (c + p·M/90) / ((m + M)/90)          # pseudo-count posterior
       = raw · m/(m+M)  +  p · M/(m+M)        # convex combination — identical
```

The two forms are algebraically the same. The second, with `p = 0`, is exactly
`shrunk_bonus_per_90 = raw · m/(m+450)` as already written at `projections.py:172`.

**So this is a generalisation of code that is already there, not a new mechanism.**
`xp_bonus` is the general form with the prior accidentally pinned to zero. That
matters for review: the diff should read as "give the existing shrinkage a prior
argument and apply it to the other five rates", not as a new modelling layer.

### 4.2 The unit is minutes — argued, not assumed

The evidence behind a per-90 rate is **exposure**, and exposure is measured in
minutes. Three ways to count it:

- **Matches.** Rejected. It is precisely the assumption that produces the defect:
  counting Alcaraz's one minute as one match of evidence is what makes 270 per 90
  look like a season's worth of defensive work. The existing `shrinkage_k = 4` for
  the start rate *is* in matches, and correctly so — a start is a per-match event,
  and the quantity being estimated is a per-match probability. Rates per 90 are not
  per-match events, so they do not inherit that unit.
- **Attempts.** Theoretically better for xG, where the natural denominator is shots
  taken. Not available: `bootstrap-static` publishes no shot count (§2). Recorded as
  the refinement `element-summary` would unlock.
- **Minutes.** Correct for every rate here, and it is what `bonus_shrinkage_minutes`
  already uses.

So the file will end up with two units for two different kinds of quantity, which is
right: matches for per-match probabilities, minutes for per-90 rates. That should be
stated in the code, because the next reader will otherwise try to unify them.

### 4.3 The parameter cannot be estimated from this data — measured

The obvious move is to avoid choosing `M` at all and estimate it by empirical Bayes.
For a Gamma-Poisson model with per-player rates `r_i = c_i/e_i`:

```
Var(r) = mu/e  (sampling)  +  mu/beta  (true heterogeneity)
beta   = mu / (Var(r) − E[mu/e])          M = 90·beta
```

Run against the pinned capture by method of moments:

| Rate | Position | mu | Var(r) | E[mu/e] | excess | beta |
|---|---|---|---|---|---|---|
| xG | DEF | 0.083 | 0.047 | 0.249 | **−0.202** | ∞ |
| xG | MID | 0.157 | 0.088 | 0.675 | **−0.588** | ∞ |
| xG | FWD | 0.469 | 0.145 | 2.577 | **−2.432** | ∞ |
| xA | MID | 0.122 | 0.049 | 0.524 | **−0.475** | ∞ |
| dc | DEF | 7.573 | 27.875 | 22.652 | 5.223 | 1.45 (M ≈ 131) |
| dc | MID | 8.396 | 536.666 | 36.182 | 500.484 | 0.02 (M ≈ 2) |
| dc | FWD | 4.149 | 11.369 | 22.805 | −11.436 | ∞ |
| saves | GKP | 2.950 | 1.847 | 2.950 | −1.103 | ∞ |

**The excess variance is negative almost everywhere.** Observed spread between
players is *smaller* than Poisson sampling noise alone predicts, so the method
cannot detect any player-to-player heterogeneity and returns "shrink infinitely" —
which would flatten every forward to 0.469 and is obviously wrong. The one
plausible-looking cell, dc DEF at M ≈ 131, sits next to dc MID at M ≈ 2, an artefact
of the single Alcaraz outlier inflating the variance to 536.

Two reasons it fails, both worth recording:

1. **One gameweek is not enough.** Almost every player has the same exposure (~90
   minutes), so there is no leverage to separate sampling noise from real spread.
2. **The Poisson sampling model is wrong for xG and xA.** These are not counts —
   they are expectations over shots, already variance-reduced by the xG model
   itself. `Var = mu/e` therefore overstates their sampling noise, which is what
   drives the excess negative. This cuts in a specific direction: **xG and xA need
   less shrinkage than a count-based analysis would suggest**, because the API has
   already done some smoothing.

**Conclusion: `M` must be chosen by comparing variants under `plan evaluate`.**
That is exactly the sequencing this work was deferred into, and §9 keeps it separate
from what is being fixed on principle. Re-run this estimator once six or eight
gameweeks exist — with real exposure variation it may well become identifiable, and
it would replace a chosen constant with a measured one.

---

## 5 — What the fix does to the current output

All figures: GW3, pinned capture, `component/1.0+banded`, players filtered to
`can_select and not removed`. **Demonstration parameters, not proposed values:**
xG/xA price-conditioned at `M = 270`, dc position-only at `M = 90`, saves
position-only at `M = 270`, `BAND_M = 900`, band width £0.5m.

`[gap: these runs cover the four API rates only. Cards and bonus are simulated
nowhere in this section, because their inputs are integer counts in the payload and
rewriting them to fractional effective counts would not round-trip through the
Pydantic model. Their inflation is quantified separately in §1.3. So the measured
before/after understates the full proposal's effect, and understates it most for
low-minutes players — the ones cards inflation hits hardest.]`

### 5.1 The three named players

| Player | raw | position prior | **price-conditioned** | prior-only floor |
|---|---|---|---|---|
| De Cuyper | **1** / 10.28 | 1 / 4.48 | **1 / 4.53** | 4 / 2.86 |
| Alcaraz | **3** / 6.49 | 439 / 1.60 | **480 / 1.47** | 442 / 1.59 |
| Haaland | 26 / 3.43 | 15 / 2.99 | **13 / 3.03** | 6 / 2.84 |
| Saka | 16 / 3.94 | 64 / 2.55 | **50 / 2.67** | — |
| Isak | 14 / 4.35 | 4 / 3.22 | **3 / 3.32** | — |

*(cells are rank / xP)*

**De Cuyper behaves as a correct fix should.** He falls from 10.28 to 4.53 — a drop
of 56% — but the "prior-only floor" column shows where he would land if his own 77
minutes counted for nothing: 2.86. He retains **22% of his excess above that floor**
and stays rank 1. One strong match is treated as real evidence, weaker than an
unshrunk per-90 implies but far from discarded. Had the proposal returned him to
≈2.86 it would be shrinking too hard, and the sweep in §5.3 shows what that looks
like.

**Alcaraz collapses, correctly.** 3rd to 480th. His floor is 1.59 and he lands at
1.47 — *below* the prior, because the minutes model independently penalises a player
with one minute played. One minute is not evidence, and the fix says so.

**Price conditioning helps consistently but modestly**: Haaland 15→13, Saka 64→50,
Isak 4→3. Every movement is in the direction the pre-season information implies.

### 5.2 Top 30 under the proposal

```
  1. De Cuyper · BHA · DEF     4.53  (raw 10.28, #1)     16. Lewis-Potter · BRE · MID 2.99  (raw 4.64, #11)
  2. Guéhi · MCI · DEF         4.05  (raw  6.99, #2)     17. Senesi · TOT · DEF       2.96  (raw 3.17, #43)
  3. Isak · LIV · FWD          3.32  (raw  4.35, #14)    18. Hinshelwood · BHA · MID  2.92  (raw 6.32, #4)
  4. Thiago · BRE · FWD        3.31  (raw  4.47, #12)    19. O'Reilly · MCI · DEF     2.91  (raw 3.77, #18)
  5. Szoboszlai · LIV · MID    3.30  (raw  5.08, #7)     20. Mateta · CRY · FWD       2.90  (raw 3.78, #17)
  6. Tzolakis · HUL · GKP      3.24  (raw  3.61, #22)    21. Kelleher · BRE · GKP     2.89  (raw 3.08, #49)
  7. Kayode · BRE · DEF        3.21  (raw  4.79, #9)     22. Collins · BRE · DEF      2.88  (raw 3.70, #20)
  8. Egan · HUL · DEF          3.14  (raw  3.70, #19)    23. Gvardiol · MCI · DEF     2.87  (raw 3.20, #39)
  9. Nketiah · CRY · FWD       3.10  (raw  5.19, #5)     24. Tavernier · BOU · MID    2.85  (raw 3.23, #34)
 10. Ajayi · HUL · DEF         3.09  (raw  5.18, #6)     25. Kinsky · TOT · GKP       2.85  (raw 3.23, #36)
 11. Mendy · HUL · DEF         3.07  (raw  4.97, #8)     26. Rogers · CHE · MID       2.85  (raw 4.37, #13)
 12. Emersonn · IPS · FWD      3.05  (raw  4.06, #15)    27. A.Becker · LIV · GKP     2.83  (raw 2.83, #70)
 13. Haaland · MCI · FWD       3.03  (raw  3.43, #26)    28. Donnarumma · MCI · GKP   2.83  (raw 2.83, #71)
 14. Gakpo · LIV · MID         3.00  (raw  3.29, #32)    29. M.Bizot · AVL · GKP      2.83  (raw 2.83, #69)
 15. Trafford · LEE · GKP      2.99  (raw  3.00, #51)    30. Justin · LEE · DEF       2.79  (raw 2.71, #82)
```

### 5.3 The counter-finding: the table does not become more plausible

**Goalkeepers in the top 30 go from 1 to 7.** Three of them — Becker, Donnarumma,
Bizot — are unchanged at 2.83 and rise purely because everyone else falls. And
**Saka falls from 16th to 50th**, which no football-literate reader would call an
improvement.

This holds across every parameterisation tried, not just the one above:

| Config | GKPs in top 30 | Saka | Haaland |
|---|---|---|---|
| raw (as shipped) | 1 | 16 | 26 |
| uniform M=270 | 8 | 59 | 13 |
| dc 90 / xG-xA 270 / sv 270 | 7 | 64 | 15 |
| dc 90 / xG-xA 450 / sv 450 | 7 | 98 | 11 |
| dc 180 / xG-xA 180 / sv 270 | 8 | 48 | 13 |
| dc 45 / xG-xA 270 / sv 180 | 4 | 65 | 18 |

**The cause is not the shrinkage.** Once single-match rate noise is removed, the
component model has almost nothing left with which to separate outfield players at
GW1, so `xp_total` is driven by `p_start`, appearance points and the clean-sheet
term — and goalkeepers have the highest `p_start` of anyone (0.88 against 0.72 for
defenders). The ranking falls back on availability because that is the only thing
the model still knows.

**The noise was doing the work of discrimination.** That is a finding about the
model, not an argument against the fix: a ranking driven by single-match extrapolation
was never measuring player quality, it only looked like it was. It does mean the fix
should not be sold as an improvement to the table, and it is a strong argument for
the set-piece and penalty-order priors noted in §2 — the model needs a real source
of pre-season discrimination, and price alone is not enough.

---

## 6 — The GW2 recommendation changes

Run directly through `optimise()` at `from_event=2, horizon=5, max_hit` uncapped,
`decay=0.84`, `ft_value=1.5`, `now` set to the capture instant so GW2's deadline is
still open. 92 s and 87 s respectively.

**Baseline (raw rates), score 65.4939:**

```
GW2: Gabriel→De Cuyper + E.Le Fée→Alcaraz     ← −4 hit
GW3: Tzolis→Hinshelwood
GW4: Igor Jesus→Nketiah
GW5: Calafiori→Ajayi
GW6: Palmer→Rogers
```

**Shrunk (position priors; xG/xA 270, dc 90, sv 270), score 11.5809:**

```
GW2: Gabriel→De Cuyper                         ← single transfer, no hit
GW3: Shaw→Kayode
GW4: Igor Jesus→Nketiah
GW5: Calafiori→Ajayi
GW6: Kayode→O'Shea
```

**The second transfer and the four-point hit vanish.** The tool was recommending
that a manager pay 4 points to bring in a player whose entire appeal was three
defensive actions in one minute. That is the clearest statement of the defect's
cost available: not a mis-ranked table, a mis-recommended hit.

De Cuyper survives the fix, and GW4 and GW5 are unchanged. The move that was right
stays right, which is the outcome that makes the change trustworthy rather than
merely different.

`[gap: ~/fpl-pinned/gw2-recommendation.json's own provenance.snapshot names a live
snapshot at 2026-08-28T13:25:28Z, not the 07:26:38Z capture this document is pinned
to, and its fixtures likewise. Its recommendation string matches the baseline above
exactly, so the move is confirmed; its score of 63.358 is not comparable to 65.4939
and no conclusion is drawn from the difference. The baseline here was recomputed from
the pinned pair rather than read from that file.]`

`[gap: score 65.4939 → 11.5809 is not a "58% worse plan". Scores are decayed sums of
projected points, and every projection falls when rates are shrunk toward a mean, so
the two numbers are on different scales. Only the moves are comparable across the
two runs.]`

---

## 7 — What varies: the enumeration for model versioning

This is the input to the versioning work, so it is exhaustive rather than
illustrative. Seven rates, each with two knobs, plus two shared:

| # | Constant | Applies to | Type | Plausible range | Note |
|---|---|---|---|---|---|
| 1 | `M_xg` | xG90 | float, minutes | 90–900 | §4.3 argues the low end |
| 2 | `M_xa` | xA90 | float, minutes | 90–900 | usually tied to `M_xg` |
| 3 | `M_dc` | dc90 | float, minutes | 45–450 | high counts per 90 → less shrinkage |
| 4 | `M_saves` | saves90 | float, minutes | 90–900 | GKP only |
| 5 | `M_yellow` | yellow/90 | float, minutes | 450–1800 | rare event, needs heavy shrinkage |
| 6 | `M_red` | red/90 | float, minutes | 900–3600 | rarer still; most players are at 0 all season |
| 7 | `M_bonus` | bonus/90 | float, minutes | 180–900 | **exists today at 450** |
| 8–14 | `prior_source` × 7 | each rate | enum: `position` \| `price_conditioned` \| `zero` | — | `zero` reproduces today's bonus behaviour |
| 15 | `BAND_M` | price-conditioned priors | float, minutes | 450–1800 | §3.3's second level |
| 16 | `band_width` | price-conditioned priors | int, price units | 5 or 10 (£0.5m / £1.0m) | — |

**Sixteen knobs: fourteen continuous or discrete numerics and seven categoricals**
(rows 8–14 are one enum each). Two properties matter for the registry design:

1. **They are per component, not shared.** `MinutesModelConfig` is seven flat fields
   that apply to one model stage. This is a *mapping from rate to (M, prior_source)*,
   and any variant type built as "another `MinutesModelConfig`" will not express it.
   A registry keyed on `MinutesModelConfig` alone cannot hold these variants — which
   is the finding this section exists to deliver.
2. **Two are categorical.** A sweep over floats will not reach them; the variant
   space is a product of a numeric grid and a small categorical set.

**What is deliberately *not* on this list:** the per-position and per-band prior
*values*. There are 4 positions × 7 rates ≈ 28 numbers, and every one is derived
from the snapshot at construction time (§3.1). Hardcoding them would add 28
`[assumption]` constants to a file that already carries seven, and would go stale
every time the league's scoring profile moved. Deriving them is the single largest
reason to prefer this design over FU-47's proposal.

`[gap: the derived priors are computed from the same snapshot being projected from,
so at GW1 the prior technically contains the gameweek being projected. This is a
population-level statistic over ~600 players, so a single player's contribution to
their own prior is negligible — but it is not zero, and under `plan evaluate` it is a
leak of exactly the kind Decision 6 warns about. Whether to compute priors from the
pinned pre-deadline capture instead is unresolved and should be settled before any
evaluation figure is quoted.]`

---

## 8 — Tests

Specified to be implementable directly. Every assertion mutation-tested per the repo
discipline: demonstrated failing against the defect it claims to catch before it is
kept.

### 8.1 The guard — no unshrunk rate may reach a component

The one the commissioning task requires, and the reason §1.3 matters. In the idiom
of FU-3's `typer.Exit` AST scan and `tests/test_claude_md_structure.py`:

Parse `domain/projections.py`. Within the body of `_component_points_for_fixture`,
assert **zero** occurrences of:

- any `ast.Attribute` whose `attr` ends in `_per_90` and whose value resolves to the
  `player` parameter;
- any `ast.BinOp` division whose right operand is `player.minutes / 90` or
  `player.minutes` — the shape that builds a rate inline, which is how cards evaded
  FU-47.

The fix must therefore compute all six rates once per player into a frozen
`_ShrunkRates` dataclass, alongside `_minutes_probabilities` in
`ComponentProjection.project`, and pass it in. A seventh rate added later either goes
through that struct or fails this test by name.

**Must be demonstrated failing against today's code**, where it should report all six
violations — the four `*_per_90` reads at `projections.py:146-147, 159, 168` and the
two inline divisions at `:171, 175-176`. Report every violation, not the first: the
FU-19 lesson is that a guard sending you back once per site stops being used.

### 8.2 Bounded output under absurd input

Alcaraz's exact shape, as a fixture: one player, 1 minute, 3 defensive
contributions, `dc90 = 270.0`. Assert `xp_defcon` is below a stated bound
(the prior-implied value plus a small margin). Today it saturates at the 2.00
scoring cap. This is the behavioural counterpart to 8.1 — the guard proves the rate
went through shrinkage, this proves the shrinkage did something.

### 8.3 The two algebraic forms agree

`shrink(raw, minutes, prior, M)` must equal both `raw·m/(m+M) + prior·M/(m+M)` and
`(count + prior·M/90) / ((m+M)/90)` to 1e-12, over randomised inputs. §4.1 claims
they are the same expression; nothing else would catch them drifting apart if the
implementation is later rewritten into the count form for speed.

### 8.4 Limits and degenerate inputs

- `M = 0` → exactly `raw`.
- `M → ∞` (a large finite value) → within epsilon of `prior`.
- `minutes = 0` → exactly `prior`, with **no division by zero**. This is the common
  case: 306 of 616 players in the pinned capture have zero minutes.
- `minutes = 0 and M = 0` → `prior`, not `nan`.

### 8.5 Monotonicity

For fixed `raw > prior`: the shrunk value is non-increasing in `M` and
non-decreasing in `minutes`. Property test over random inputs. This is the formal
statement of "more evidence means more weight on the player's own rate", and it is
what would catch a sign error that the point tests above would pass.

### 8.6 The prior is pooled, not averaged

Construct a position group containing one extreme-rate, low-minutes player (the
Alcaraz shape) among several ordinary ones. Assert the derived prior equals
`sum(counts)/sum(minutes)*90` and is **not** the mean of the per-90 ratios, and that
the outlier moves it by less than a stated amount. This pins §3.1's lesson, which is
the one most likely to be undone by someone "simplifying" the prior computation.

### 8.7 A thin price band cannot become its own prior

A band containing exactly one player, whose rate is far from the position rate.
Assert the resulting band prior is closer to the position rate than to the player's
own — the Haaland-at-£15m case from §3.3.

---

## 9 — What is being fixed, and what is being chosen

The commissioning task asked for these to be separated. They are not the same kind
of claim and should not be defended together.

### 9.1 Fixed because it is wrong

Independent of GW2, of this capture, and of whether `plan evaluate` ever runs:

- A rate of **270 per 90 derived from one minute** must not enter a projection at
  its face value. No parameter choice makes that defensible.
- **A yellow-card rate of 6.43 per 90 from 14 minutes** must not either — same
  defect, in a term FU-47 did not name.
- The file **applies shrinkage to three inputs and not to six others, with no
  recorded reason**. Whatever the right parameters are, the asymmetry is not a
  position anyone argued for.
- `xp_bonus` shrinks toward **zero**, which asserts that a player with few minutes
  will earn no bonus rather than about the league average. That is a wrong prior,
  not a conservative one.

These would be worth fixing if the evaluation harness never existed. They are
defects of internal consistency, and §8's tests are what stop them recurring.

### 9.2 Chosen because it looked best, and must be measured

Everything with a number attached:

- Every `M` in §7. The demonstration values in §5 (270 / 90 / 270) were picked
  because they showed the effect clearly, **not because they are good**. §4.3
  measured that they cannot be estimated from the data available.
- `BAND_M = 900` and the £0.5m band width.
- The decision to price-condition xG and xA. The correlation is real (ρ ≈ 0.46) but
  a real correlation is not proof that conditioning improves projection error.
- The prior source for each rate in §3.2's table, wherever it is not forced.

**None of these should be settled by looking at the table.** §5.3 is the argument
for that: the parameterisation that most improves Haaland's position also sends Saka
to 98th, and nothing on the screen says which is right. They are to be chosen by
comparing variants under `plan evaluate` once model versioning lands, on a gameweek
whose deadline post-dates a capture.

### 9.3 The consequence for sequencing

§9.1 could be implemented now, with the §9.2 parameters set to any defensible value,
and the result would be *more internally consistent but not measurably better*. That
is an honest state to ship, and it is the state the whole model is already in — but
it must be recorded as such in the commit and not presented as an improvement to
accuracy. The alternative is to wait for versioning and land both together, which
is the sequencing FU-47's closing note already argues for.

---

## 10 — What this document does not settle

- `[gap: cards and bonus are specified but not measured end to end (§5's opening
  note). Their inflation is quantified but their effect on the ranking and on the
  recommendation is not. Measuring it needs either a fractional-count path through
  the Pydantic model or the implementation itself.]`
- `[gap: the derived priors are computed from the snapshot being projected from, so
  they contain the projected gameweek at GW1 (§7's closing note). Negligible per
  player, non-zero in aggregate, and unresolved for evaluation purposes.]`
- `[gap: no position other than the four exists today, but `saves90`'s prior is
  written as a position table with three zeros. If a fifth position ever appeared the
  prior would silently be 0.0 rather than absent. Cheap to guard, not guarded here.]`
- `[gap: the price-conditioning measurement is one gameweek and one capture. ρ ≈ 0.46
  on 94 midfielders is suggestive, not established, and the FWD xA90 coefficient is
  negative (−0.145) on 21 players, which is probably noise but is left standing rather
  than explained away.]`
- `[gap: §5.3's goalkeeper finding implies the model lacks a pre-season
  discrimination source beyond price. `penalties_order` and the set-piece flags are
  in the payload (§2) and unused. That is a larger change than this one and is not
  designed here.]`
- `[gap: the empirical-Bayes estimator in §4.3 should be re-run once six to eight
  gameweeks exist. If it becomes identifiable it replaces chosen constants with
  measured ones, which would remove most of §9.2. Nothing schedules that.]`

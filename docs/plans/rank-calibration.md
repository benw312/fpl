# Rank calibration — mapping the model's predictions onto the outcome distribution

**Design pass only. Nothing here is implemented and no `src/` file is touched by the
branch that writes it.** The deliverables are §3's constraint, which decides whether
this is worth doing at all, §7's enumeration, and §9's sequencing argument — which
says *not yet*.

**Figures quoted below are measured**, on `~/fpl-pinned/gw2-*` and `gw3-*`
(sha256s in [haulers-decomposition.md](haulers-decomposition.md) and
[gw3-evaluation.md](gw3-evaluation.md)), model `component/1.2+banded` digest
`4f479b2253cc`. Cited per FU-40. **No parameter is proposed and none may be fitted
here** — FU-50 §3 governs.

---

## 1 — The proposal, stated technically

Use the model to **order** players, then replace its raw `xp_total` with an estimate
of `E[actual points | predicted]` learned from data. The prediction stops being a
point forecast in its own units and becomes an index into an empirical distribution.

This is ordinary **calibration** — isotonic regression, histogram matching,
distributional recalibration. It is a well-posed, standard technique, and the repo
already contains a crude version of its input: the calibration-by-predicted-bin
table in haulers-decomposition.md §3.

---

## 2 — The evidence that there is something to calibrate

Three measurements, all on the shipped model, all already filed.

| | GW2 | GW3 |
|---|---|---|
| total predicted vs actual (`component/1.2`) — **FU-63** | −13.5% | −13.6% |
| predicted SD against realised SD — **FU-62** | 0.95 vs 2.60 | 1.12 vs 2.40 |
| predicted max against realised max | 4.36 vs 23 | 5.68 vs 15 |

And the per-bin bias is not flat, which is what makes a *monotone* correction
available rather than merely a scale factor. At GW3, `component/1.2` by predicted
bin: +0.08, −0.59, −0.45, −0.76, −0.35. `component/1.1-price` over-predicts its 1–2
bin by **+0.84 across 290 of 652 players**.

So a monotone map exists that would reduce RMSE, MAE and the aggregate bias. That
much is not in doubt.

---

## 3 — The constraint that decides the shape of this work

**A strictly monotone map preserves ranks exactly, so it cannot change
`spearman_played` or `spearman_all` at all.**

Not "barely" — exactly, by construction. Spearman is Pearson correlation on ranks;
a strictly increasing transformation leaves every rank untouched. **Every criterion
this project has pre-registered is therefore blind to this work**: FU-50 §1
(price vs position), FU-50 §4 (the control clause), and FU-60 §1 (1.2 vs 1.1-price)
all decide on `spearman_played`.

What a calibrated variant *would* move:

| metric | moves? |
|---|---|
| `spearman_played`, `spearman_all` | **no — exactly unchanged** |
| RMSE, MAE (all and played) | yes |
| the error-by-category table | yes |
| Brier / log loss on `p_start` | no — `p_start` is not remapped |
| optimiser recommendations | yes, through `_hit_points` |

The optimiser channel is measured, not assumed:
[fu-63-optimiser-sensitivity.md](fu-63-optimiser-sensitivity.md) found a
recommendation flip at `α = 0.96` on a one-free-transfer state, with the decision
sitting 4% from the boundary against a 13.6% bias.

**Consequence: this cannot be evaluated under any existing criterion, and building it
before a criterion exists would mean choosing one afterwards — the exact failure
FU-50 was written about.** A pre-registration entry must land first. Filed as
**FU-65**.

Note the pleasing coincidence that the property making this invisible to Spearman is
the same one §5 requires for correctness: strict monotonicity.

---

## 4 — Two data sources, and they are not equally hard

### 4.1 In-repo rolling calibration — cheap, and it improves weekly

Fit the map on GW1…k, apply it to GW k+1, roll forward. Same model, same scoring
rules, same fields, same population definition. Out-of-sample by construction, and
the leak test is simple to write (§8.4).

**Cost:** the map is fitted from three settled gameweeks today, which is too thin.
It becomes usable somewhere around GW8–10 on exposure grounds — the same argument
FU-50 §3 makes for the rate constants, though calibration needs less data than
variance estimation because it is fitting a one-dimensional monotone curve rather
than a dispersion parameter.

### 4.2 vaastav/Fantasy-Premier-League — the harder half

The external archive of historical FPL data. Three obstacles, in descending
severity.

**(a) Our model does not exist historically, and cannot be made to.** Learning "our
rank X → Y points" needs *our* predictions on past gameweeks, which needs
`bootstrap-static`-shaped snapshots carrying every field `ComponentProjection`
consumes: `selected_by_percent`, `chance_of_playing_this_round` and `_next_round`,
`expected_goals_per_90`, `expected_assists_per_90`, `saves_per_90`,
`defensive_contribution_per_90`, `starts`, `minutes`, team strength ratings, and
`game_config.scoring`. **`defensive_contribution_per_90` does not exist before the
2025/26 rule change at all**, and expected-goals fields appeared in the FPL payload
only in recent seasons. The further back the archive reaches, the less of our model
can be run on it. `[gap: which fields are present in which of vaastav's seasons is
asserted from general knowledge and is NOT verified — no fetch was made. Verifying it
is the first step of any work here, and it may kill (a) outright.]`

**(b) The scoring rules changed.** Defensive contribution points are new this
season. The distribution of weekly points — how many haulers, how heavy the tail —
is therefore not comparable across the change, so even the *outcome* side of the
archive needs a cut-off.

**(c) It is a new class of dependency.** CLAUDE.md's first line describes "a local,
read-only Fantasy Premier League planning tool … over the official (undocumented)
FPL API". A third-party GitHub dataset is neither the official API nor local. That
is an architecture decision, not a data one, and it is not this document's to make.

**The narrow use that survives (a) and (c).** Use the archive for the **outcome
distribution only** — how many players score ≥5 in a typical gameweek, what the
upper tail looks like, how stable that is season to season. That needs no historical
run of our model and no new runtime dependency if the extract is taken once by hand.
It answers a real question — *is the distribution we are calibrating toward the right
shape?* — and is a fraction of the work.

---

## 5 — The shape of the map, and the trap in it

**The map must be strictly monotone and smooth. A step function on coarse bins is
wrong and would be actively damaging.** Two players at 4.60 and 4.55 falling in one
bin would receive identical calibrated values, destroying an ordering the model got
right — and ordering is the one thing the component model demonstrably does well
(`spearman_played` 0.348 against naive's 0.229 at GW3). Collapsing ties would also
break §3's exact-rank-preservation property and make the change visible to Spearman
in the worst possible way: as a loss.

So: isotonic regression **with interpolation**, or a low-parameter monotone
parametric family. Not a lookup table.

**What to calibrate.** `xp_total` directly. Per-component calibration multiplies the
parameter count by eight, invites double-counting against the components' own
shrinkage, and targets a quantity the optimiser never reads. Calibrating the minutes
term instead is FU-57's job and is a different change.

---

## 6 — Why this is the wrong thing to do next, and what is

**Most of the miscalibration in §2 has an identified cause with a structural fix
already filed.** FU-63 measured that `component/1.2`'s −13.6% aggregate bias tracks
its −12.7% under-call on starters, and the minutes term is the only difference
between the variants that sit either side of zero. FU-57 names the cause: the
ownership prior is pooled marginally over `starts` where the signal is an
interaction.

**Fitting a calibration map now would fit a curve to a known bug.** Worse, it would
have to be refitted the moment FU-57 lands, and a stale map is harder to notice than
an uncalibrated model — the numbers would look plausible and be wrong.

**Sequencing, recommended:**

1. **FU-57 first.** Frozen until FU-60's GW3+GW4 pair completes, which is days away.
2. **Re-measure the residual.** Repeat haulers-decomposition.md §3's bin table and
   FU-63's aggregate figures against the post-FU-57 model. If the bias collapses,
   this document is largely moot and should say so.
3. **Only if a material residual survives**, pre-register a criterion (FU-65) and
   build §4.1's in-repo rolling calibration.
4. **§4.2's narrow use is independent** and can be done at any time, by anyone
   willing to take the architecture decision in (c). It answers a different question.

---

## 7 — What varies, for the registry

In rate-shrinkage.md §7's and minutes-model.md §7's shape, so a variant can hold
these if this is ever built.

| # | Constant | Type | Range | Note |
|---|---|---|---|---|
| 1 | `calibration_source` | enum | `none` \| `in_repo` \| `external` | `none` is today |
| 2 | `fit_window` | enum | `expanding` \| `rolling_k` | |
| 3 | `rolling_k` | int, gameweeks | 3–10 | read only when #2 is `rolling_k` |
| 4 | `map_family` | enum | `isotonic` \| `affine` \| `power` | a shape choice, not a fitted one |
| 5 | `per_position` | bool | — | 4× the parameters on the same data |
| 6 | `min_gameweeks` | int | 4–10 | below this the map is the identity |
| 7 | `extrapolation` | enum | `clamp` \| `linear` | behaviour beyond the fitted range |

Rows 3 and 7 are conditional on 2 and 4, so `MinutesStructureConfig`'s precedent
applies: validate the dependency or make the unused values inert and say so.

**Row 6 is the safety property, not a tuning knob.** Below the threshold the map is
the identity and the model ships uncalibrated — which is what makes a fresh install,
or GW1, behave correctly rather than calibrating against four data points.

---

## 8 — Tests

Specified to be implementable directly, each naming the mutation it must fail
against.

**8.1 Under-exposure is the identity.** With fewer than `min_gameweeks` of history,
every calibrated projection equals its raw one, field for field.
*Mutation:* applying the map regardless of exposure changes the first row.

**8.2 Ranks are preserved exactly.** Over a realistic population, assert
`spearman(raw, calibrated) == 1.0` exactly, not approximately.
*Mutation:* a binned lookup table introduces ties and drops it below 1.0.

**8.3 Near-neighbours do not collapse.** Two players differing in the third decimal
of `xp_total` must differ after calibration.
*Mutation:* rounding to bin centres makes them equal.

**8.4 The fit never sees the gameweek it is applied to.** Construct a history where
GW k+1's outcomes would move the map materially, fit on GW1…k, and assert the map is
byte-identical whether or not k+1's outcomes are present in the input.
*Mutation:* an off-by-one in the window includes k+1 and the map moves.

**8.5 A calibrated model is the identity on calibrated input.** Feed the fitter a
synthetic model whose predictions already equal outcome means; assert the resulting
map is the identity to within tolerance.
*Mutation:* a fitter with a bias term returns a non-identity map.

**8.6 Extrapolation is monotone and bounded.** A prediction above anything in the
fit window must map above everything else and must not exceed the maximum plausible
score.
*Mutation:* unbounded linear extrapolation returns an absurd value on the first
outlier.

**8.7 The map survives a population change.** The element set grew 616 → 652 between
GW2 and GW3. Assert fitting across that boundary neither raises nor silently drops
players.

---

## 9 — What this document does not settle

`[gap: §2's evidence is two gameweeks. The −13.5%/−13.6% stability is striking but
the population changed underneath it, and no error bar accompanies either figure.]`

`[gap: §4.2's obstacle (a) rests on unverified claims about which fields exist in
which of vaastav's seasons. Nothing was fetched. If the archive turns out to carry
reconstructable snapshots for recent seasons, the external route is much more
attractive than this document implies — and if it does not, (a) is fatal and §4.2
reduces to the narrow use.]`

`[gap: the whole document assumes the target is `E[points]`. If what the optimiser
actually wants is a distribution — because captaincy doubles the tail and a chip
strategy cares about variance — then calibrating the mean is solving the wrong
problem, and FU-62's compression finding would need re-reading as "the model has no
variance estimate" rather than "its mean is compressed". Nothing here addresses
that, and it may be the more important question.]`

`[gap: no criterion is proposed. §3 establishes that the existing ones cannot serve
and FU-65 is filed to write a new one, but this document deliberately does not write
it — a plan proposing both the change and the test it will be judged by is the
arrangement FU-50 exists to prevent.]`

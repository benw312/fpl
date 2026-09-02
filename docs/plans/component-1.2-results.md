# component/1.2 — the minutes structure, built and measured

**What this is.** minutes-model.md §6.1's S1-S6 implemented and registered as
`component/1.2` (version `component/1.2+banded`, digest `4f479b2253cc`).
**`component/1.1-price` remains the default.** 1.2 is registered alongside it and
scored in the same `plan evaluate` run; whether it is promoted is FU-50 §2's
two-gameweek question and is not decided here.

**Pinned inputs, cited per FU-40.** `~/fpl-pinned/gw2-pre-deadline.json` (sha256
`593f60c2e356…`, captured 2026-08-28T00:32:59Z, 16h57m before GW2's deadline),
`~/fpl-pinned/gw2-fixtures.json` (sha256 `fbd4457e5c81…`), and for the scoring
table `~/fpl-pinned/gw2-live.json` (sha256 `afdaf81a6fcd…`, GW2 settled). 616
players. The capture predates the deadline, so the evaluation is leak-free — with
one caveat recorded in §6.

---

## 1 — The registry needed widening, and what it cost

§7's first property: *"a variant holding only a `MinutesModelConfig` cannot express
rows 1-10, so the variant type needs a second config object, not seven more flat
fields."* That is what was built — `MinutesStructureConfig`, a second config on
`ModelVariant`, exactly as `RateShrinkageConfig` is for the rate side.

**The cost that mattered was the digest.** `ModelVariant.digest` hashes
`as_dict()`, and `tests/test_variants.py` pins six digests with a comment saying
re-pinning "is correct only when the change provably cannot move a projection".
Two of those six — `fb431918c08c` and `24c305e2025c` — are cited as provenance in
minutes-model.md and fu-53-minutes-ceiling.md. Emitting the new field
unconditionally would have moved all six and broken every one of those citations to
record a field none of the six sets.

So `as_dict` omits an identity structure, the `RateShrinkageConfig.is_identity`
precedent. **All six existing digests are unchanged**, asserted by
`test_adding_the_structure_field_moved_no_existing_digest`, and only
`component/1.2` is newly pinned. `is_identity` deliberately ignores rows 6, 7, 9
and 10, which are read only when the row they depend on is active (§7's second
property): a config differing only in an unread value *is* today's model.

One further guard: `variants.build` **refuses** a `naive` variant carrying a
non-identity structure rather than silently ignoring it. `naive/1.0` is the control
FU-50 §4 judges the component family against, and giving it the component model's
minutes work would remove the comparison.

---

## 2 — What went in, and what did not

| | Change | In 1.2 | Note |
|---|---|---|---|
| S1 | `horizon_availability = per_event` | **on** | §3.1's category error |
| S2 | `this_round_source = this_then_next` | **on** | 99 players take it at GW2 |
| S3 | `news_return_dates = True` | **on** | 7 dated; 3 return by GW4 |
| S4 | `departed_policy = zero` | **on** | 44 departed; see below |
| S5 | `Availability` structure | **on** | not a knob — unconditional |
| S6(a) | `start_prior_source = ownership_conditioned` | **on** | removes 4 constants |
| S6(b) | `start_evidence` | **off** | identity — **FU-54** |
| FU-51 | `return_ramp_events = 0` | **off** | identity, by instruction |

**S6(b) is off because implementing it means choosing a constant the plan refuses
to choose.** §6.1 claims S6 "adds no `[assumption]` constant"; §7 row 10 lists
`partial_start_weight` with a plausible range, and §9's first gap says the
functional form is "not chosen" and that "choosing on that data would be fitting to
three points". Rows 8-10 are built and registrable; 1.2 sets
`partial_start_weight = 1.0`, at which `minutes_weighted` is arithmetically
identical to `count`, so the default makes no claim. Filed as **FU-54**.

**S6(a) turned out to need no constant, but only after correcting §7 row 6.** The
row specifies `OWN_BAND_M` in *minutes*, mirroring rate-shrinkage's `BAND_M = 900`.
A rate's exposure is minutes; a start's is appearances, which is the distinction
`shrink_rate`'s docstring already instructs the reader not to collapse. 900
appearances is twenty-four seasons. The knob is `own_band_prior_appearances`,
defaulting to `None` = reuse `shrinkage_k`, which introduces no new number and
gives §8.7's thin-band guard for free. Filed as **FU-55**.

**S6(a) removes four chosen constants.** `start_priors` GKP 0.85 / DEF 0.65 /
MID 0.55 / FWD 0.55 are replaced by priors pooled from the snapshot. On this
capture those pool to **GKP 0.294 / DEF 0.424 / MID 0.341 / FWD 0.288** — the
hardcoded values are roughly double the rate observed in the payload they describe,
and that is the mechanism behind §4.2's 119 players clearing 0.5 on the prior
alone.

**S4 is structurally correct and a measured no-op on this capture.** All 44
departed players already publish `chance_of_playing_next_round = 0`, so
`_availability` already returned 0.0 for them. `zero` was chosen over `exclude`
because §7's third property is that `exclude` changes `N` from 616 and makes any
figure incomparable with any figure measured before it. This is FU-48's shape of
finding: a correct branch that today changes nothing.

---

## 3 — Verification

### 3.1 `component/1.1-price` is byte-identical to main

Required, and the branch must not move it. Every field of every `Projection` —
`xp_total`, all eight components, `p_start`, `xmins`, `fixtures`, `model_version` —
for all 616 players across GW2-GW6, 3,080 rows, hashed and compared against a
`git worktree` of `main`:

| variant | sha256 over 3,080 rows | main | branch |
|---|---|---|---|
| `component/1.1-price` | `cffdbc9ef56bd8fc82f2daedfcf95580da5f4ae78487be6fa39c62bd02a18593` | ✓ | ✓ |
| `component/1.0` | `2c86597274501b371998c994006a585ccf1f0ead36d60ff00b1e152580a432a1` | ✓ | ✓ |
| `component/1.1-position` | `f072abdd437646346d54ff2ab55989e3298a233644080d933463f467a64d7928` | ✓ | ✓ |

A five-gameweek horizon rather than one event on purpose: S1 moves
`_minutes_probabilities` inside the event loop, and a single-event comparison
cannot see whether that changed anything. Re-run and still identical after the
FU-56 clamp landed.

### 3.2 Tests

40 new assertions in `tests/test_minutes_structure.py` covering §8.1-§8.11. §8.12
is not written: it covers §4.3(c), which this branch does not build.

**Mutation-tested, per §8's requirement: 26 mutations applied to the source, 26
caught, 0 survived.** Three earlier mutations survived a first pass and all three
were the harness's fault rather than the tests' — two did not actually remove the
behaviour they claimed to, and one, `_as_probability`'s upper bound, was genuinely
unreachable through §8.8's parametrisation because `p_start`'s existing clip
absorbs a modest over-range value. That third one was a real coverage hole: a case
extreme enough to reach `p1` through the substitute term was added, plus a direct
contract test on the helper.

448 tests pass.

### 3.3 Wall-clock

616 players, on the pinned capture: `component/1.1-price` 40 ms for one event,
`component/1.2` **41 ms** — and **146 ms** for a five-gameweek horizon, where the
pre-1.2 model computed the minutes term once per player and 1.2 computes it once
per player per event. `naive/1.0` is 9 ms. No optimisation was needed or done.

---

## 4 — The headline number: 31% → 10%

Of the players the model rates above 0.5 to start, how many did not play in GW2.
This is the figure minutes-model.md §1 opens with and the one the work exists to
move.

| | `component/1.1-price` | `component/1.2` |
|---|---|---|
| `p_start > 0.5` | 332 | **151** |
| of those, did not play GW2 | 104 (**31%**) | 15 (**10%**) |
| `status='a'`, `starts=1`, over 0.5 | 213, 18 wrong (8%) | 135, 8 wrong (6%) |
| `status='a'`, `starts=0`, over 0.5 | **119, 86 wrong (72%)** | **14, 6 wrong (43%)** |
| distinct `p_start` values across 616 players | 11 | **43** |

**§4.2's 119-player cohort — the players with no player-specific evidence, put over
the threshold by the position prior alone.** Under 1.2, **107 of the 119 fall below
0.5**; mean `p_start` across the cohort goes from 0.568 to 0.211. Of the 119, 33
(28%) did in fact play, so the cohort was mostly wrong and dropping it is mostly
right.

`p_start` also stops being a lookup table: 11 distinct values across 616 players
becomes 43, which is §4.2's other complaint answered.

### The cost, stated plainly

The headline improved by trading recall for precision, and the trade is large:

| | over 0.5 | actual starters caught | recall | precision |
|---|---|---|---|---|
| `component/1.1-price` | 332 | 194 / 220 | **88%** | 58% |
| `component/1.2` | 151 | 126 / 220 | **57%** | **83%** |

**220 players actually started GW2. 1.1-price called 332 — over-calling by half.
1.2 calls 151 — under-calling by a third.** The model has moved from one side of
the true count to the other. The 31%→10% figure is real and is the metric the plan
named, but a reader who saw only that number would not know that 94 real starters
now sit below 0.5 where 26 did before.

> **Correction, 2026-09-02 (`task/component-1.2-recall`).** The direction above is
> right and the magnitude is overstated. `p_start > 0.5` is §4.2's diagnostic cut,
> not a decision boundary — nothing in the code compares `p_start` to 0.5, and the
> optimiser consumes it as a continuous multiplier. Threshold-free against the 220
> realised starts: 1.2's **expected** starter count is 188.6, short by 14%, against
> 1.1-price's 292.3, long by 33%; Brier 0.1310 against 0.1727 (1.2 better), log loss
> 0.5254 against 0.5016 (1.2 worse, which is the diagnosable defect showing up).
> "Under-calling by a third" is a threshold artefact. See
> [component-1.2-recall.md](component-1.2-recall.md) §5.

`[gap: whether over-calling or under-calling is worse for the thing the tool
actually does is not established here. `plan optimise` sums projected points over a
squad and a horizon; a suppressed real starter is a transfer never recommended,
which is invisible, while an inflated non-starter is a bad transfer recommended,
which is not. Nothing in this repo measures plan quality end to end — the same
limitation FU-50 §4 accepts knowingly.]`

---

## 5 — The GW2 table

Scored against settled GW2 actuals. **Expect this to look different rather than
better in places, and it does.**

| model | sp_all | sp_played | RMSE all | MAE all | RMSE played | MAE played |
|---|---|---|---|---|---|---|
| baseline/flat-ppg | 0.613 | 0.331 | 2.943 | 1.440 | 3.974 | 2.568 |
| naive/1.0 | **0.619** | 0.330 | 2.905 | 1.419 | 3.978 | 2.567 |
| component/1.0 | 0.536 | 0.269 | 2.405 | 1.463 | 3.148 | 1.939 |
| component/1.1-price | 0.551 | 0.359 | 2.411 | 1.569 | **3.036** | 1.901 |
| component/1.1-position | 0.546 | 0.347 | 2.427 | 1.595 | 3.043 | 1.919 |
| **component/1.2** | **0.604** | **0.394** | **2.254** | **1.261** | 3.045 | **1.830** |

1.2 beats 1.1-price on five of six and loses `RMSE played` by 0.009. It still loses
`spearman_all` to `naive/1.0`, 0.604 against 0.619 — closer than 1.1-price's 0.551
but not past it.

**Against FU-53's measured ceiling.** The oracle put perfect minutes at
`spearman_played` 0.564 for 1.1-price. 1.2 reaches 0.394 from 0.359, so it collects
**about 17% of the measured prize**. That is consistent with what FU-53 said to
expect: §4.2 established the model has no player-specific evidence at all for 119 of
332 players, and no structure manufactures evidence that is not in the payload.

### Error by category

| Category | n | 1.1-price | **1.2** | oracle ceiling |
|---|---|---|---|---|
| Zeros | 332 | +1.317 | **+0.775** | +0.210 |
| Blanks | 178 | +0.744 | **+0.190** | +1.109 |
| Tickers | 43 | −1.119 | −1.413 | +0.067 |
| Haulers | 63 | −5.438 | −5.552 | −4.112 |

**Zeros close 41% of the way to the ceiling** and Blanks improve more than the
oracle does — which is not a paradox but the FU-53 finding in action: perfect
minutes *worsens* the Blanks by removing a discount that was cancelling a
scoring-rate over-prediction, and 1.2's partial correction happens to sit near the
cancelling point. That is luck, not calibration, and it should not be quoted as a
1.2 result.

**Tickers and Haulers both get slightly worse**, by 0.294 and 0.114. Suppressing
`p_start` for marginal players necessarily suppresses it for some who scored, and
neither S1-S6 nor anything else in the plan addresses the −5.4 on haulers. FU-53
already measured that a *perfect* minutes model only takes it to −4.1.

### Availability provenance (S5), 616 players

| source | GW2 (the nearest event) | GW4 |
|---|---|---|
| `status_available` | 448 | 448 |
| `chance_this_round` | **99** | — |
| `chance_next_round` | 25 | 117 |
| `departed` | 44 | 44 |
| `news_return_pending` | — | 4 |
| `news_return_reached` | — | **3** |

S2 fires for 99 players at the nearest gameweek; S3 for 7 at GW4, of whom 3 have
returned. Both match §3.2's tables. This breakdown exists only because S5 made
availability carry its provenance — under the pre-1.2 float it could not have been
produced at all.

### Top 30 under 1.2

Ranked by `xp_total` at GW2. `act` is actual GW2 points. Top-30 overlap with
1.1-price: **16 of 30**.

| # | player | pos | own% | st | xP 1.2 | xP 1.1p | ps 1.2 | ps 1.1p | act |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Guéhi | DEF | 19.3 | 1 | 4.356 | 3.772 | 0.847 | 0.720 | 2 |
| 2 | Rogers | MID | 26.0 | 1 | 4.332 | 3.432 | 0.838 | 0.640 | 5 |
| 3 | De Cuyper | DEF | 7.4 | 1 | 4.330 | 3.710 | 0.857 | 0.720 | 0 |
| 4 | Szoboszlai | MID | 43.1 | 1 | 4.055 | 3.216 | 0.838 | 0.640 | 4 |
| 5 | Senesi | DEF | 7.7 | 1 | 3.892 | 3.139 | 0.857 | 0.720 | 0 |
| 6 | Palmer | MID | 15.2 | 1 | 3.861 | 3.037 | 0.838 | 0.640 | 7 |
| 7 | Isak | FWD | 16.5 | 1 | 3.683 | 3.242 | 0.747 | 0.640 | 8 |
| 8 | Thiago | FWD | 16.7 | 1 | 3.668 | 3.229 | 0.747 | 0.640 | 2 |
| 9 | Lacroix | DEF | 9.5 | 1 | 3.634 | 2.982 | 0.857 | 0.720 | 1 |
| 10 | João Pedro | FWD | 67.5 | 1 | 3.633 | 3.198 | 0.747 | 0.640 | 9 |
| 11 | Mbeumo | MID | 36.1 | 1 | 3.612 | 2.880 | 0.838 | 0.640 | 11 |
| 12 | Gakpo | MID | 6.0 | 1 | 3.576 | 2.968 | 0.782 | 0.640 | 5 |
| 13 | Ndiaye | MID | 16.0 | 1 | 3.566 | 2.757 | 0.838 | 0.640 | 4 |
| 14 | Kayode | DEF | 7.2 | 1 | 3.515 | 3.008 | 0.857 | 0.720 | 2 |
| 15 | Haaland | FWD | 68.0 | 1 | 3.378 | 2.975 | 0.747 | 0.640 | 13 |
| 16 | Virgil | DEF | 19.6 | 1 | 3.326 | 2.780 | 0.847 | 0.720 | 1 |
| 17 | Ajayi | DEF | 1.7 | 1 | 3.317 | 3.303 | 0.723 | 0.720 | 6 |
| 18 | Egan | DEF | 2.0 | 1 | 3.314 | 3.296 | 0.723 | 0.720 | 9 |
| 19 | Mendy | DEF | 3.4 | 1 | 3.271 | 3.254 | 0.723 | 0.720 | 1 |
| 20 | Saka | MID | 10.4 | 1 | 3.265 | 2.750 | 0.782 | 0.640 | 11 |
| 21 | M.Sangaré | MID | 8.0 | 1 | 3.233 | 2.646 | 0.782 | 0.640 | 4 |
| 22 | Hume | DEF | 6.5 | 1 | 3.217 | 2.751 | 0.857 | 0.720 | 6 |
| 23 | Gvardiol | DEF | 13.4 | 1 | 3.177 | 2.689 | 0.857 | 0.720 | 5 |
| 24 | O'Reilly | DEF | 21.0 | 1 | 3.142 | 2.727 | 0.847 | 0.720 | 2 |
| 25 | Tarkowski | DEF | 8.8 | 1 | 3.140 | 2.622 | 0.857 | 0.720 | 12 |
| 26 | Cunha | MID | 9.5 | 1 | 3.133 | 2.654 | 0.782 | 0.640 | 9 |
| 27 | Thomas | DEF | 7.9 | 1 | 3.100 | 2.566 | 0.857 | 0.720 | 8 |
| 28 | Shaw | DEF | 19.7 | 1 | 3.100 | 2.682 | 0.847 | 0.720 | 2 |
| 29 | Wirtz | MID | 11.6 | 1 | 3.088 | 2.611 | 0.782 | 0.640 | 4 |
| 30 | B.Fernandes | MID | 48.6 | 1 | 3.073 | 2.447 | 0.838 | 0.640 | 23 |

**Every player in the top 30 has `starts = 1`**, which was not true before: the
ownership-conditioned prior raises `p_start` for owned players who started (MID
0.640 → 0.838, DEF 0.720 → 0.857) and lowers it for the unowned who did not. Rows
17-19 — Ajayi, Egan, Mendy at 1.7-3.4% ownership — barely move (0.720 → 0.723),
which is the band pooling working: a thinly-owned band of players who all started
is not evidence of anything much, so it shrinks back to the position prior.

`[gap: this list is `xp_total` at GW2 and every entry is a defender or midfielder
whose ceiling is low. That is the same shape the pre-1.2 model produced and is a
property of the component model's calibration, not of the minutes work — the
`act` column shows 1.2 ranking Guéhi (2 points) above B.Fernandes (23). Minutes
was never the binding constraint on that, which is FU-53's Haulers finding.]`

---

## 6 — What this does not settle

`[gap: one gameweek. Every figure in §5 is GW2, and FU-50 §2's two-gameweek rule
governs any decision to promote 1.2 over 1.1-price. 1.2 was not pre-registered
against a criterion, so the numbers above are descriptive and nothing in FU-50
§§1-4 has been met or claimed.]`

`[gap: S6(a) pools its priors from the same snapshot it projects from —
rate-shrinkage.md §7's self-reference caveat, transplanted unchanged. The GW2
figures are leak-free with respect to *outcomes*, but the priors are a population
statistic of the capture, and a band prior derived from 616 players who are about
to be scored is not the same thing as one derived from a prior season.]`

`[gap: minutes-model.md §9's ownership gap stands and is now more load-bearing.
`selected_by_percent` at the GW2 deadline partly reflects managers reacting to GW1
team news, so it encodes information the model could in principle derive from
`starts`. With `starts` binary after one gameweek, how much of the signal is
independent cannot be established. 1.2 now depends on that signal for its priors.]`

`[gap: S1 and S3 are horizon changes and a single-event evaluation cannot see them.
The GW2 table exercises S2, S4 and S6(a) and essentially nothing of S1 or S3 — GW2
is the nearest event, where the return-date path is deliberately not consulted.
Their effect shows in `plan optimise`, which nothing here measures. The §5
provenance table for GW4 is the only evidence in this document that S3 fires at
all.]`

`[gap — DIAGNOSED 2026-09-02, component-1.2-recall.md. The original text follows,
and its guess was wrong: the departed-player contamination is real but small
(+0.014 to +0.030 on the `<1%` band priors) and rescues none of the 84. The cause is
that the ownership prior is pooled marginally over `starts` while §2.4's signal is
an interaction — at `appearances = 1` and `shrinkage_k = 4` a single start clears
0.5 only if the prior exceeds 0.375, and all four `<1%` band priors fall below it.
FU-57, FU-58, FU-59.]`

`[gap: the recall collapse in §4 — 220 real starters, 194 caught before and 126
after — is reported but not diagnosed. Whether it is the pooled position priors
being too low (they are pooled over a 616-player population including 44 departed
players and many who will never play), the band edges, or `shrinkage_k` at 4
carrying too much prior weight, is not established. The first of those is the most
suspicious and is the cheapest to test, and it is a population question rather than
a tuning one, so testing it would not breach FU-50 §3.]`

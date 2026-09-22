# component/1.3 — design

**Status: design agreed 2026-09-22. Nothing here is built yet.** The pre-registration
that governs it is FU-73, **binding from 2026-09-22**. This document is the *what* and
*why*; FU-73 is the decision rule. The split follows minutes-model.md / FU-60.

**Agreed on 2026-09-22, before any 1.3 figure exists and before GW6 is played.** Each of
these closes a gap that the first draft left open:

- **The minutes term is `component/1.2-availability`'s** (§2): S1–S5 kept, S6(a)
  dropped. Change 1 needs no new code.
- **The shrinkage strength comes from empirical Bayes** (§3.2). The rule is written
  down, including what happens when it cannot be estimated.
- **Which team ratings feed which term** (§3.1). The team's own defence now enters
  the clean-sheet term, and that is stated as part of change 2.
- **§4's decomposition is corrected.** The draft claimed that `1.3-fixtures −
  1.1-price` isolates the fixture change. It does not.

---

## 1 — The diagnosis this responds to

Three settled gameweeks of decomposition, plus a split visible only after GW5.

**The minutes work has not paid.** S1–S5: +0.003, −0.006, +0.0003 — never moved the
metric. S6(a): +0.029, +0.0065, −0.033 — mean near zero, spread wider than every
margin any decision here has turned on.

**And the two metrics disagree about where we are weak.** On `spearman_all` —
effectively the *"will he play"* problem, since most of 659 players score zero —
the component family **loses to `naive/1.0` and to `official-ep/1.0`** at GW4 and
GW5. On `spearman_played` — *"how many points given he played"* — it wins GW3 and
GW5.

**So the rate half earns its place and the minutes half is worse than doing almost
nothing. `component/1.2` spent its entire effort on the minutes half.** 1.3 inverts
that: take effort *out* of minutes, and put it into the fixture term that feeds the
rates.

---

## 2 — Change 1: subtract the minutes elaboration

**What.** Revert the availability/minutes term to the simplest form that works,
dropping S6(a)'s ownership-conditioned start prior and the S1–S5 structure with it.

**Why, on evidence rather than taste.** At GW5, `component/1.1-price` (0.414226) and
`component/1.2-availability` (0.414502) are indistinguishable, and both beat
`component/1.2` (0.381725). The elaborate term is not merely failing to help; S6(a)
is actively costing 0.033 on the most recent settled gameweek.

**This is a deletion, not a rewrite**, which is the cheapest change available and the
one the data most directly supports. `component/1.1-price`'s existing availability
scalar is the target shape.

**Decided 2026-09-22: the second candidate.** 1.3's structure is
`replace(COMPONENT_V12.structure, start_prior_source="position")`. That is exactly how
`component/1.2-availability` is built, so the two cannot drift apart. **Change 1 is
therefore already built**, and 1.3 is change 2 applied on top of 1.2-availability.

*Why not 1.1-price's scalar.* S1–S5 has measured as zero on `spearman_played` three
times: +0.003, −0.006, +0.0003. On `spearman_played`, FU-73's primary metric, the
choice between the two candidates is therefore expected to be a wash. With that
settled, the decision is made on correctness. S1–S5 fixes category errors that the
optimiser consumes directly: departed players, dated returns from injury, and
availability across the horizon. The scalar would put those errors back in order to
gain nothing measurable. *The counter-argument, recorded rather than dismissed:* on
`spearman_all`, 1.1-price beat 1.2-availability by about 0.015 at both GW4 and GW5.
That is one development reading each, on the metric FU-73 declined, and it is not
used here.

---

## 3 — Change 2: a fitted team-strength model

**What is there now.** `attack_scale = rates.xg_for / league_mean_goals`, applied to
the player's shrunk xG and xA rates. `xg_for` and `xg_against` come from
`DifficultyBandRatesModel` — *"v1: `xg_for`/`xg_against` from the opponent's
difficulty band"* — which is the FPL difficulty rating, an integer band, used as a
lookup.

**What to replace it with.** A Poisson team attack/defence model fitted from actual
match results: each team gets an attack rating and a defence rating, with home
advantage, and expected goals for a fixture come from the fitted ratings rather than
a band. Ratings shrunk toward the league mean, using the machinery rate-shrinkage.md
already establishes for player rates.

### 3.1 — Which ratings feed which term (agreed 2026-09-22)

`_component_points_for_fixture` consumes the two rates differently. `xg_for` only
ever enters as `attack_scale = xg_for / league_mean_goals`, multiplying the player's
own shrunk xG and xA rates. `xg_against` enters the clean-sheet probability
(`exp(-xg_against)`), goals conceded, and the saves scale.

- **`xg_for = μ · def_opp · venue`: the opponent's defence only.** A player's xG rate
  already contains the player's own team's attacking strength. Multiplying by the team's
  attack rating as well would count it twice. The banded model makes the same choice
  today.
- **`xg_against = μ · att_opp · def_own · venue`: now including the team's own
  defence.** No player-level clean-sheet rate exists, so nothing else carries it.
  Today `BandedTeamRates` sets `xg_against = mean / band(opponent)`, so every
  defender facing a given band gets the same clean-sheet chance, whatever side they
  play for. That is a category error of the same kind S1–S5 fixed on the minutes
  side.

**Adding own defence is part of change 2, not a third change.** FU-73's fixture
comparisons measure the fitted model *including* it. If change 2 is shown to help,
this part is not separately attributed. That is accepted: leaving a known category
error in place in order to keep attribution clean would be the wrong trade.

`venue` is the fitted home factor for the home side and the fitted away factor for
the away side (§3.2). `μ` is the fitted league mean, **which retires
`LEAGUE_MEAN_GOALS = 1.45` for the fitted model.** That value was always marked as an
assumption; measured from GW1–4 results it is 1.425.

### 3.2 — The fit and its shrinkage (agreed 2026-09-22, fixed before any figure)

- **Data:** only fixtures marked `finished` in the capture's own fixtures file, and
  never one whose event is at or after the target event. Match results only: goals
  for and goals against.
- **μ** = mean goals per team per match. **Home factor** = mean home goals / μ;
  **away factor** = mean away goals / μ.
- **Prior:** each team's attack and defence multiplier has prior mean 1. The prior's
  strength is estimated separately for attack and for defence, by method of moments
  on the per-team goal means: `excess = Var(team means) − μ/n`, where `n` is games
  per team. That gives a prior variance `σ² = excess / μ²` on the multiplier, which
  is equivalent to `1/(σ²·μ)` pseudo-games at the league mean.
- **Posterior:** `rating = (observed goals + pseudo-goals) / (expected goals +
  pseudo-goals)`. "Expected" takes account of venue and the opponent's current
  rating, and is iterated to convergence.
- **Simplification, stated:** the prior strength is estimated from *raw* team means,
  without adjusting for opponents. After four or five games the schedule's
  imbalance is part of what that raw variance contains.
- **Fallback, fixed now:** if the excess for either attack or defence is ≤ 0, the
  estimator cannot find any spread between teams. **For that capture, that variant
  then uses `BandedTeamRates` unchanged**, and the run records that it did.
  It is expected to fire at GW2, with one game per team.
- **Measured before this was written, on match results only** (the GW5 pre-deadline
  fixtures, GW1–4, 4 games per team): the attack excess is **+0.244** and the defence
  excess is **+0.151**. Both are positive, so the estimator can be identified. That
  is the opposite of the player-rate case in rate-shrinkage.md §4.3, where it failed
  everywhere. No evaluation figure was read to reach this.

**No constant in this section is chosen.** Every number is either fitted from match
results or produced by the fallback rule above. None is to be tuned against GW2–GW5
Spearman (FU-50 §3).

### 3.3 — Why this and not something else

- **The seam already exists and was built for this.** `strength.py` defines a
  `TeamRatesModel` Protocol with `rates(team, opponent, home)`, `league_mean_goals()`
  and `name()`. projections-v1.md Decision 1 calls it the fixture-strength strategy
  seam. A new model is a drop-in, not a refactor.
- **It is fitted, not chosen.** Every parameter comes from match results. This
  matters: FU-50 §3 forbids picking constants on thin data, and a fitted model does
  not ask anyone to pick one.
- **It amplifies the half that works.** The opponent is the largest single swing in
  any gameweek, and it is currently represented by a 1–5 integer.

*Resolved 2026-09-22.* The shrinkage strength comes from empirical Bayes (§3.2).
It is not a chosen constant.

**A prior from the previous season (the vaastav archive) is declined for 1.3.** It
would need an external dataset fetched and pinned. Promoted clubs have no prior at
all. And the weight a previous season deserves is itself a judgement. It stays a
candidate for a later version if the current-season estimate proves too thin early in
the season.

**FPL's own team strengths cannot be the prior either.** `strength_attack_*` and
`strength_defence_*` are 0 for every club in the 2026-27 bootstrap.

---

## 4 — Two new variants, scored with three existing ones

Two changes in one variant cannot be attributed. This is the mistake `component/1.2`
made — a bundle whose entire gain turned out to be one unstable part — and FU-60 §6.1
records the further mistake of registering the decomposition variant *late*, so it
could never be scored on GW3.

| variant | fixture model | minutes term |
|---|---|---|
| `component/1.1-price` | difficulty band | scalar (control, existing) |
| `component/1.2` | difficulty band | S1–S6 (incumbent default, existing) |
| `component/1.2-availability` | difficulty band | S1–S5 (existing) |
| **`component/1.3-fixtures`** | **fitted** | S1–S6(a), unchanged from the incumbent |
| **`component/1.3`** | **fitted** | **S1–S5**, 1.2-availability's |

Each comparison changes exactly one thing:

- **`1.3-fixtures − 1.2`**: the fixture change, with the minutes term held at the
  incumbent's.
- **`1.3 − 1.2-availability`**: the fixture change again, with minutes held at S1–S5.
  This is a second, independent reading.
- **`1.3 − 1.3-fixtures`**: removing S6(a), under fitted strength. This is S6(a)'s
  fourth reading, and its sign is flipped relative to the table in gw5-evaluation.md.

*Corrected 2026-09-22.* The first draft said `1.3-fixtures − 1.1-price` isolates the
fixture change. It does not. That difference changes the strength model **and** the
whole minutes term, from the scalar to S1–S6(a).

**All five are scored in one run against one capture**, which is the whole point of
`plan evaluate --model` being repeatable.

---

## 5 — Deliberately excluded

Parked so that 1.3 stays attributable, not because they are weak:

- **Blending `ep_next`.** FPL publishes its own expected points; we parse the field
  and ignore it, and `official-ep/1.0` tops `spearman_all` at GW4 and GW5. Strong,
  cheap, and a third change would make the decomposition unreadable.
- **Rank-ensembling** the five or six models already scored every run.
- **Splitting P(plays) from E[points | plays]** into two separately evaluated
  problems. The most principled response to §1's diagnosis and the most work.

**Not FU-62.** Spearman is invariant to monotone transforms, so the compression into
[0, 5.2] cannot hurt either ranking metric. It hurts magnitudes, which only the
optimiser consumes — it belongs behind FU-72, not in a model change.

**Not FU-57 or FU-58.** Their premise is gone and both entries now say so.

---

## 6 — Development, and the line that keeps it honest

**Four gameweeks are backtestable: GW2, GW3, GW4, GW5**, each with a complete pinned
trio in `~/fpl-pinned/`. **GW1 is not and cannot be** — its deadline was
2026-08-21T17:30Z and the capture archive begins 2026-08-28; that route is closed
permanently.

**Fitting team ratings from match results is fitting to data and is fine. Tuning any
constant against our own evaluation metric on four gameweeks is what FU-50 §3
forbids.** That distinction is the difference between a model and a flattering
curve, and it is the first thing that slips under time pressure.

**GW2–GW5 are contaminated as a test set.** Every one has been read in detail and
this design is a response to what they showed. That is what a development set is for.
It is also why FU-73 names GW6 and GW7, and why the criterion must be committed
before GW6's deadline of **2026-10-10**.

---

## 7 — Development check, GW2–GW5 (2026-09-22, report only)

**Built on `task/model-1.3`.** Digests: `component/1.3` `d02bb0a770d1`,
`component/1.3-fixtures` `500b1d355ef9`. **Nothing was changed after these figures
were seen.** FU-73 §6 forbids it: changing the rule now would need a new
pre-registration.

**Pinned inputs (sha256).** The GW5 trio is as cited in gw5-evaluation.md §1.

| pin | sha256 |
|---|---|
| `gw2-pre-deadline.json` | `593f60c2e356c4e94205f10248dfd834f4797ad6c736ea73b239da610d84ffcf` |
| `gw2-fixtures.json` | `fbd4457e5c819f38cb34228453596f8c6eb3ae345bc64a11996682187bdf09a8` |
| `gw2-live.json` | `afdaf81a6fcdce4000aa4b6f362dc56aa8b1d099a845dd3c4b94c445b5c7d6c9` |
| `gw3-pre-deadline.json` | `0cc7193b5e20567e379e437a58c3ae6e73379ff892742479af9c0654f3264a0e` |
| `gw3-fixtures.json` | `5cc5817d3385a671e2fe92f0a7bec3f15869ea8367a0bc32a23125b46e679573` |
| `gw3-live.json` | `cd86195071cd72e0546e24e1980202c7ea6db34784c10821eda159838d1626a4` |
| `gw4-pre-deadline.json` | `de9d7d3573b27d28c3d43d8ac0932b290d5f0785903d1e07d031099d8eb49f7e` |
| `gw4-fixtures.json` | `85d3ef089f28bc22a1d168204ea9d1982dac6ba0af72fd28379e370fbf3eff23` |
| `gw4-live.json` | `8809e516a5ffeeeebf8707f219ceeac7a9231860bb7257b6753e11c6d4218342` |

**The pipeline was checked before the new figures were read.** Every existing variant
reproduces its published `spearman_played` to six places: GW3 `1.2` 0.348254, GW4
`1.2` 0.329666, and GW5 `1.2` 0.381725 and `1.2-availability` 0.414502. **The event
bound holds.** Fitting from the current fixtures file, which has 50 finished results
including GW5's own, gives a fit identical to the one from each pinned file, at GW3,
GW4 and GW5.

### What the fit found

| capture | results | fell back? | μ | home / away | excess att / def | prior (games) att / def |
|---|---|---|---|---|---|---|
| GW2 | 10 | **yes** — excess −0.050 / −0.050 | — | — | — | — |
| GW3 | 20 | no | 1.550 | 1.194 / 0.806 | +0.297 / +0.073 | 5.2 / 21.4 |
| GW4 | 30 | no | 1.417 | 1.129 / 0.871 | +0.182 / +0.071 | 7.8 / 20.0 |
| GW5 | 40 | no | 1.425 | 1.035 / 0.965 | +0.244 / +0.151 | 5.8 / 9.5 |

GW2 fell back, as §3.2 predicted. There, `1.3` projects identically to
`1.2-availability`, and `1.3-fixtures` identically to `1.2`, to six places. That is
the fallback working as specified.

### `spearman_played`

| | 1.2 | 1.2-avail | **1.3-fixtures** | **1.3** | 1.1-price | naive | official-ep |
|---|---|---|---|---|---|---|---|
| GW3 | 0.348254 | 0.319355 | 0.320985 | 0.238761 | 0.316227 | 0.229472 | 0.210042 |
| GW4 | 0.329666 | 0.323130 | 0.329047 | 0.317090 | 0.329148 | 0.342232 | 0.353172 |
| GW5 | 0.381725 | 0.414502 | 0.364813 | 0.386618 | 0.414226 | 0.336305 | 0.380525 |

| | fixture change, minutes at 1.2's | fixture change, minutes at S1–S5 | removing S6(a) under fitted strength | 1.3 − 1.2 (FU-73 §1's comparison) |
|---|---|---|---|---|
| GW3 | −0.027269 | −0.080594 | −0.082224 | −0.109493 |
| GW4 | −0.000619 | −0.006040 | −0.011957 | −0.012576 |
| GW5 | −0.016912 | −0.027884 | +0.021805 | +0.004893 |

**The fitted strength model lost in all six fixture readings on the development set.**
Three of the six are small; GW3's −0.081 is not. `spearman_all` moves the same way:
1.3-fixtures and 1.3 are at or below their controls at every identified gameweek.

**What this is, and is not.** GW2–GW5 are the development set (§6). They were read
closely before 1.3 was designed, and they are not the test FU-73 names. Nor is this
noise that the rule can be tuned out of. Per FU-73 §6, the rule does not move in
response to these figures without a new pre-registration.

**One observation, not acted on.** Home advantage is fitted from the pooled home and
away means and is **not shrunk**, because §3.2 did not ask for it to be. At GW3 it
comes from 20 matches and splits home and away by ±19%. That is the largest single
multiplier in the model at that gameweek, larger than any team's opponent-defence
rating (0.92–1.07). GW3 is also where the loss is largest. `[gap: the loss has not
been decomposed into its venue and opponent-rating parts. Doing so means scoring
further variants against the development set, which is a decision for Ben, not a
diagnostic to run in passing.]`

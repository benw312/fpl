# The minutes model — the binding constraint, and what to do about it

**Design pass only. Nothing here is implemented, and no `src/` file is touched by
the branch that writes it.** The deliverable is §7's enumeration, which is what
makes the work implementable, and §8's tests, which are specified to be written
without further design.

**Every figure below is measured on `~/fpl-pinned/gw2-pre-deadline.json`**
(sha256 `593f60c2e356c4e94205f10248dfd834f4797ad6c736ea73b239da610d84ffcf`,
captured 2026-08-28T00:32:59Z, 16h57m before GW2's deadline), with outcomes from
`~/fpl-pinned/gw2-live.json` (sha256 `afdaf81a6fcd…`, GW2 settled) and fixtures
from `~/fpl-pinned/gw2-fixtures.json` (sha256 `fbd4457e5c81…`). Model versions
`component/1.0+banded` (digest `fb431918c08c`) and `component/1.1-price+banded`
(digest `24c305e2025c`). Cited per FU-40.

**No parameter is tuned here and none may be.** FU-50 §3 commits to not fitting the
rate `M` constants at GW4 or GW5, and the same argument applies with more force to
the minutes constants: there is one gameweek of per-player exposure, `starts` is a
binary, and anything fitted to it would be fitted to noise. This document proposes
**structural** changes, which are defensible on argument today, and defers every
numeric choice. Where it names a number it is reproducing one that already exists,
not proposing a new one.

---

## 1 — The evidence: scoring is not the weakness, selection is

Three measurements from the GW2 evaluation, all from the one pinned run.

**1. Nearly a third of the players the model considers likely starters do not play
at all.** Of the 332 players `component/1.0` gives `p_start > 0.5`, **104 (31%) did
not appear in GW2**. Identical under `component/1.1-price` — 332 and 104 — because
rate shrinkage does not touch the minutes stage at all.

**2. The error on non-scorers is large, positive, and got worse with shrinkage.**

| Category | n | component/1.0 | component/1.1-price |
|---|---|---|---|
| Zeros | 332 | **+1.11** | **+1.32** |
| Blanks | 178 | +0.55 | +0.74 |
| Tickers | 43 | −1.19 | −1.12 |
| Haulers | 63 | −5.43 | −5.44 |

The model hands more than a point of expected return, on average, to each of 332
players who returned nothing.

**3. Component wins decisively wherever the play/didn't-play split is removed, and
loses wherever it dominates.**

| Population | component/1.0 | component/1.1-price | naive/1.0 | baseline |
|---|---|---|---|---|
| Spearman, all 616 | 0.536 | 0.551 | **0.619** | 0.613 |
| Spearman, 308 who played | 0.269 | **0.359** | 0.330 | 0.331 |
| RMSE, played | 3.148 | **3.036** | 3.978 | 3.974 |
| MAE, played | 1.939 | **1.901** | 2.567 | 2.568 |

On the players who actually featured, component beats both persistence controls on
every error column and — after shrinkage — on rank correlation too. On the full
population it loses to a model that multiplies last week's score by availability.

**The three read as one finding.** The component machinery is doing its job on the
question "given this player features, how much will they score". The population where
it fails is the one whose composition is decided by the minutes model. Every
downstream term is multiplied by `p_start`, `p60` or `p1`, so a minutes error scales
the entire projection; no improvement to xG shrinkage, team strength or defcon
thresholds can compensate for putting a squad player at 0.52 to start.

`[gap: this is one gameweek, and §1's whole argument rests on it. The direction is
consistent across four independent populations and two model variants, which is why
it is treated as established enough to design against — but FU-50 §2's two-gameweek
rule is about *decisions*, and adopting anything proposed here should meet it.]`

---

## 2 — What signal exists and is unused

Measured on the pinned capture. `bootstrap-static` carries 109 fields per element;
`api/models.py`'s `Player` parses 30 of them.

### 2.1 Parsed and used

`status`, `chance_of_playing_next_round`, `starts`, `minutes`. That is the whole of
the minutes model's input.

### 2.2 Present in the payload, **not parsed by `Player` at all**

| Field | Content on this capture | Why it matters |
|---|---|---|
| `selected_by_percent` | 616/616 populated, float-as-string | Strong within-stratum discriminator — §2.4 |
| `chance_of_playing_this_round` | 616/616, **differs from `next_round` for 49 players** | The horizon question — §3 |
| `news_added` | 168/616 populated, ISO timestamps spanning 2026-07-23 → 2026-08-27 | Recency of the news that set `status` |
| `penalties_order`, `corners_and_indirect_freekicks_order`, `direct_freekicks_order` | populated for set-piece takers | Named in rate-shrinkage.md §5.3's gap as an unused discrimination source; not pursued here |

### 2.3 Parsed but unused by the minutes model

`news` is parsed into `Player.news` and read by nothing in `domain/projections.py`.
It is not free text in the useless sense — it is templated:

| News shape | n (of the 124 with availability < 1.0) |
|---|---|
| `<injury> - Unknown return date` | 54 |
| `Has joined <club> …` / `… on loan …` | 44 |
| `<injury> - Expected back <D Mon>` | **7** |
| `Suspended …` | 1 |
| other | 1 |

All 124 players with availability below 1.0 have non-empty news. **Seven carry a
machine-readable return date**, and **44 have left the league entirely** — the
latter are permanently unavailable, are still carried in the 616-player projection
population, and still appear in every evaluation denominator.

### 2.4 `selected_by_percent` is a real discriminator, measured

Stratifying by `starts` (the only per-player signal the model currently has) and
then by ownership, against whether the player actually started GW2:

| `starts` | `selected_by_percent` | n | started GW2 |
|---|---|---|---|
| 1 | <1% | 80 | 76% |
| 1 | 1–5% | 79 | 84% |
| 1 | 5–15% | 35 | 86% |
| 1 | >15% | 26 | **100%** |
| 0 | <1% | 334 | 7% |
| 0 | 1–5% | 54 | 22% |
| 0 | >5% | 8 | 25% |

Ownership separates within both strata, monotonically, over a 24-point range among
players who had started once. It is not a causal signal — it is the aggregated
opinion of several million managers about who is nailed — but that is precisely what
the model lacks and cannot derive.

### 2.5 Minutes *given* a start is a strong discriminator, and is currently discarded

`minutes` is read only to compute `mins_per_start`, which feeds `p60`. It carries
direct information about `p_start` that nothing uses:

| GW1 minutes (among the 220 who started) | n | started GW2 |
|---|---|---|
| <60 | 10 | **20%** |
| 60–84 | 74 | 76% |
| 85–90 | 136 | **92%** |

A player hooked before the hour is less than a quarter as likely to start again as
one who played the full match. The model treats all 220 identically.

### 2.6 The archive supports differencing, and it works

`select_archived_snapshot` already reads `~/.fpl-cli/archive/`. Differencing
`bootstrap-2026-08-28.json` (pre-GW2) against `archive/2026-09-01/` (post-GW2):

- 616 ids in the earlier capture, 626 in the later, **616 common, 10 new**
- per-GW2 `starts` delta: **396 zeros, 220 ones** — clean, no negatives
- `minutes` delta: no negatives, max exactly 90

Season-to-date `starts` is therefore convertible into a **per-gameweek start
series**, which is the input a real minutes model wants and the thing
`_appearances`' snapshot-level proxy exists to fake. The daily capture cadence is
fine enough: `sum(starts)` advances 220 → 242 → 330 → 418 → 440 across 2026-08-28
to 09-01, tracking the fixture schedule.

**Three caveats, all of which the differencing code must handle.** The element set
grows (612 → 629 over eight captures), so a player may be absent from the earlier
capture; captures taken mid-gameweek are partial, so only pairs bracketing a
**settled** gameweek may be differenced — the same finality argument as FU-43, and
the flags to check are the same; and the four earliest captures are bare files whose
mtimes were rewritten by copying, so `archived_capture_time` and FU-41's manifest are
the ordering authority, not the filesystem.

`[gap: differencing is verified for one gameweek transition on this machine's
archive. Whether the API ever *revises* `starts` downward after settlement — which
would produce a negative delta and require a policy — is not established. No negative
delta was observed here, which is not the same as none existing.]`

---

## 3 — Availability across the horizon: it is a scalar, and it is wrong

### 3.1 The structure, established from the source

`ComponentProjection.project` (`projections.py:537-546`) computes
`_minutes_probabilities(...)` **once per player, outside the `for event in events`
loop**, and passes the same `_MinutesProbabilities` to `_project_one` for every
event in the horizon. `_availability` reads `chance_of_playing_next_round`, which is
by its own name a statement about **one** round.

So a single scalar derived from the next round is applied unchanged to all five
gameweeks of the default horizon.

### 3.2 How many players this affects, measured

**124 players have availability below 1.0** on the pinned capture (107 at exactly
0.0, 17 between). Every one of them carries that value across GW3–GW7.

Of the seven with a machine-readable return date, **six return inside the horizon**:

| Player | Expected back | First GW on/after | Currently projected |
|---|---|---|---|
| Doku | 5 Sep | **GW4** | 0.0 for GW3–GW7 |
| Jacob | 5 Sep | **GW4** | 0.0 for GW3–GW7 |
| Gelhardt | 5 Sep | **GW4** | 0.0 for GW3–GW7 |
| Burn | 14 Sep | **GW5** | 0.0 for GW3–GW7 |
| Ferguson | 10 Oct | **GW6** | 0.0 for GW3–GW7 |
| Cairney | 10 Oct | **GW6** | 0.0 for GW3–GW7 |
| Minteh | 28 Nov | GW12 | 0.0 for GW3–GW7 — correct |

And the converse: `chance_of_playing_this_round` differs from `next_round` for **49
players**, including several `status='a'` players at 0% this round and 100% next
(Christie, Fofana). The model reads only `next_round`, so for a five-gameweek horizon
starting at GW3 it uses the *right* field for the first gameweek and the same value
for four more.

### 3.3 Does it matter? Yes, and the direction is asymmetric

Six players wrongly suppressed to zero across a whole horizon is small against 616.
But the affected set is not a random sample: it is injured players, who are
disproportionately the expensive, high-owned ones a transfer plan is actually about
— Doku is the clearest case here. And `plan optimise` searches over transfers into
and out of these players, so a horizon-wide zero does not merely misprice a player,
it removes an entire branch of the search. An optimiser cannot recommend buying a
player it projects at zero for every gameweek it can see.

The error is **one-directional**: a returning player is suppressed for the whole
horizon, and there is no compensating case where the scalar wrongly *inflates* a
later gameweek, because `chance_of_playing_next_round` is about the nearest round and
injuries resolve forward in time. So this is a systematic downward bias on exactly
the population the tool exists to reason about.

**Verdict: it matters, and the structural fix is available now.** It requires no new
constant.

---

## 4 — The structural problem with `p_start`

### 4.1 The arithmetic, and why filler clears the threshold

```
p_start = availability × (starts + k·prior) / (appearances + k)
```

with `k = 4.0`, `appearances = 1` (finished gameweeks, not per-player), and
`prior ∈ {GKP 0.85, DEF 0.65, MID 0.55, FWD 0.55}`. For a `status='a'` player:

| Position | `starts=0` | `starts=1` |
|---|---|---|
| GKP | **0.680** | 0.880 |
| DEF | **0.520** | 0.720 |
| MID | 0.440 | 0.640 |
| FWD | 0.440 | 0.640 |

`k = 4` against `appearances = 1` means the prior carries 80% of the weight, so a
goalkeeper or defender who has never started is over 0.5 on the prior alone.

### 4.2 What that does, measured

**`p_start` takes 11 distinct values across all 616 players.** It is a lookup table
on (position, starts, availability), not a per-player estimate.

Of the 332 players above 0.5:

| | n | did not play GW2 |
|---|---|---|
| `status='a'`, `starts=1` | 213 | 18 (8%) |
| `status='a'`, `starts=0` | 119 | **86 (72%)** |

**The 31% headline is almost entirely the second row.** Players who had started once
are well classified — 8% wrong. Players who had never started are put over the
threshold by the position prior, and 72% of them did not play. The model is not
mis-weighting evidence; for 119 of 332 players it has no player-specific evidence at
all and the prior alone decides.

### 4.3 What would separate them, and what it costs

Three candidates, ordered by cost.

**(a) Ownership as a prior input — cheap, available today.** Replace the flat
per-position prior with one conditioned on `selected_by_percent`, exactly as
rate-shrinkage.md §3.2 conditions rate priors on price, and with the same
band-pooling machinery (§3.3's thin-band guard applies unchanged: a band of one
player must not become its own prior). §2.4 shows the signal is monotonic and
sizeable. **Cost:** one new field on `Player`, a prior derived from the snapshot
rather than hardcoded (so no new `[assumption]` constant), and the same
self-reference caveat rate-shrinkage.md §7 already carries — the prior is pooled from
the snapshot being projected from.

**(b) Minutes-given-start as evidence for `p_start`, not just `p60` — cheap,
available today.** §2.5 shows a 20%/76%/92% spread that the model currently
discards. Structurally this means `p_start`'s evidence term stops being the integer
`starts` and becomes a quality-weighted count. **Cost:** a functional form, which is
a genuine design choice and is where this proposal is least settled — see §9.

**(c) A per-gameweek start series from differenced captures — the principled fix,
and the expensive one.** §2.6 establishes it is possible. It replaces the
`_appearances` snapshot proxy with a real per-player denominator and makes recency
expressible (last three gameweeks weighted above the first). **Cost:** a new storage
concern reading the archive during projection, the finality gating of §2.6, a policy
for players absent from earlier captures, and a hard dependency on capture history
that a fresh install does not have. This is a plan of its own and should not be
bundled with (a) and (b).

**Recommendation: (a) and (b) now, (c) filed.** Both are structural, both use fields
already in the payload, and neither requires estimating a new constant from one
gameweek. (c) is the better model and the worse next step.

---

## 5 — FU-48 and the shape of `_availability`

FU-48 measured, over 6,788 player-observations across 11 captures, that two of
`_availability`'s four branches are never taken: `status == "d"` → `doubtful_chance`
(0 times) and the final `return 0.0` fallback (0 times). Every non-`a` status
publishes a percentage, so the first branch always fires for them.

**Reproduced on this capture**, and the picture is unchanged:

| status | chance | n |
|---|---|---|
| `a` | `None` | 448 |
| `a` | 100 | 44 |
| `d` | 75 | 16 |
| `d` | 50 | 1 |
| `i` | 0 | 61 |
| `u` | 0 | 45 |
| `s` | 0 | 1 |

**What follows for the function's shape — and it is not "delete the dead branches".**
The four-branch structure encodes a *policy*: what to do when the API declines to
say. Two branches are unreachable on all data seen so far, but they are the
fallback, and FU-48 established that `doubtful_chance = 0.75` is well chosen (179 of
203 `status='d'` observations publish exactly 75%). Deleting a correct fallback
because the primary path has not yet failed is how a system acquires a crash.

The change worth making is to **stop calling it `_availability` and stop returning a
bare float**. It answers two questions at once — "is this player available" and "for
which gameweek" — and §3 shows the second is silently dropped. The recommendation is
that it return a small structure carrying the value, which branch produced it, and
which gameweek it is a statement about. That makes §3's per-gameweek fix expressible
and makes the dead branches self-documenting rather than merely dead: a projection
whose availability came from the fallback is one whose provenance a reader can see,
which is the same argument FU-43 made for the event-live envelope.

`[gap: FU-48's branch counts are reachability over captures, not a coverage run, and
that caveat carries over unchanged. This section adds one capture to the eleven and
does not change the conclusion.]`

---

## 6 — Structure versus parameters

The division rate-shrinkage.md §9 draws, applied here. **This is the section to read
if the plan is being triaged.**

### 6.1 Fixed because it is wrong — actionable today, no new constants

| # | Change | Why it needs no data |
|---|---|---|
| S1 | Availability evaluated **per gameweek** across the horizon, not once | `chance_of_playing_next_round` is by name about one round; applying it to five is a category error, not a tuning choice |
| S2 | Parse `chance_of_playing_this_round` and use it for the nearest gameweek | The field exists, differs for 49 players, and is the correct one for that gameweek |
| S3 | Parse the `Expected back <date>` shape from `news` and zero availability only **before** that date | Templated, machine-readable, and affects 6 of 7 dated players inside a five-gameweek horizon |
| S4 | Treat `status='u'` with a transfer/loan news shape as permanently unavailable | 44 players have left the league and are carried through every projection and every evaluation denominator |
| S5 | `_availability` returns a provenance-carrying structure, not a float | §5 |
| S6 | `p_start` evidence conditioned on ownership band and on minutes-given-start | §4.3(a),(b) — the *structure* changes; the prior values are derived from the snapshot, not chosen |

S1–S5 change no number that was ever chosen. S6 introduces a functional form, which
is a structural commitment, and derives its priors from the snapshot the way
rate-shrinkage.md §3.1 does — so it adds no `[assumption]` constant, but it does add
a shape that could be wrong.

### 6.2 Chosen, and must not be tuned now

The seven constants in `MinutesModelConfig` stay exactly as they are:
`shrinkage_k = 4.0`, the four `start_priors`, `mins_per_start_prior = 75.0`,
`p_sub_appearance = 0.35`, `mins_per_sub = 20.0`, `doubtful_chance = 0.75`,
`bonus_shrinkage_minutes = 450.0`. All carry
`[assumption: no empirical basis for any constant in this block]` and continue to.

**`shrinkage_k = 4.0` is the one most obviously implicated by §4.2** — it is why the
prior carries 80% of the weight and why 119 players clear 0.5 on it alone. It is
therefore exactly the constant it would be most tempting to change on this evidence,
and exactly the one FU-50's logic forbids changing: one gameweek, `starts ∈ {0,1}`,
no error bars. **Note that S6 reduces the pressure on it structurally** — a prior
conditioned on ownership is a better prior at the same weight — which is the argument
for doing structure first and letting the parameter question be asked later against a
model that is no longer obviously mis-specified.

### 6.3 Deferred, with the condition stated

| Item | Condition to revisit |
|---|---|
| Tuning `shrinkage_k` and the start priors | FU-50 §3's three conditions, read for minutes: six to eight gameweeks of exposure, a stable estimate, and resistance to dropping the largest single contributor |
| §4.3(c), per-gameweek starts from differenced captures | Its own plan. Needs the finality gate, an absent-player policy, and a fresh-install fallback |
| Set-piece and penalty order as discrimination inputs | rate-shrinkage.md §5.3's standing gap; unrelated to minutes |
| Calibrating `p_start` — it is described in the UI as "not calibrated" (`cli.py:340`) | Needs several gameweeks of predicted-vs-realised start rates; the differenced series of §2.6 is the input |

---

## 7 — What varies: the enumeration for model versioning

Exhaustive rather than illustrative, in rate-shrinkage.md §7's shape, so the registry
can hold these variants. **This is the deliverable that makes the plan
implementable.**

| # | Constant | Applies to | Type | Plausible range | Note |
|---|---|---|---|---|---|
| 1 | `horizon_availability` | S1 | enum: `scalar` \| `per_event` | — | `scalar` reproduces today exactly |
| 2 | `this_round_source` | S2 | enum: `next_only` \| `this_then_next` | — | `next_only` is today |
| 3 | `news_return_dates` | S3 | bool | — | `False` is today |
| 4 | `departed_policy` | S4 | enum: `ignore` \| `exclude` \| `zero` | — | `ignore` is today; `exclude` also changes the evaluation denominator, which is why it is separate from `zero` |
| 5 | `start_prior_source` | S6(a) | enum: `position` \| `ownership_conditioned` | — | mirrors rate-shrinkage.md's `prior_source`; `position` is today |
| 6 | `OWN_BAND_M` | S6(a) | float, minutes | 450–1800 | prior weight for the ownership-conditioned prior; mirrors `BAND_M` |
| 7 | `own_band_edges` | S6(a) | tuple of float, percent | e.g. (1, 5, 15) | §2.4's strata; a *shape* choice, not a fitted one |
| 8 | `start_evidence` | S6(b) | enum: `count` \| `minutes_weighted` | — | `count` is today: the integer `starts` |
| 9 | `full_match_minutes` | S6(b) | int, minutes | 60–90 | threshold above which a start counts fully; only read when #8 is `minutes_weighted` |
| 10 | `partial_start_weight` | S6(b) | float | 0.0–1.0 | weight of a start below the threshold |
| 11 | `shrinkage_k` | existing | float, gameweeks | 1–8 | **exists today at 4.0; not to be changed** |
| 12–15 | `start_priors` × 4 | existing | float | 0–1 | **exist today; not to be changed** |
| 16 | `mins_per_start_prior` | existing | float, minutes | 45–90 | **exists today at 75.0** |
| 17 | `p_sub_appearance` | existing | float | 0–1 | **exists today at 0.35** |
| 18 | `mins_per_sub` | existing | float, minutes | 10–30 | **exists today at 20.0** |
| 19 | `doubtful_chance` | existing | float | 0–1 | **exists today at 0.75; FU-48 shows it is unreachable and correct** |

**Nineteen knobs: five categorical (rows 1, 2, 4, 5, 8), one boolean (3), one
tuple-shaped (7), and twelve numeric of which nine already exist.** Three properties
matter for the registry:

1. **Rows 1–10 are new and rows 11–19 are today's `MinutesModelConfig`.** A variant
   holding only a `MinutesModelConfig` cannot express rows 1–10, so the same finding
   rate-shrinkage.md §7 delivered about `RateShrinkageConfig` applies again: the
   variant type needs a second config object, not seven more flat fields.
2. **Rows 9 and 10 are conditional on row 8**, and rows 6 and 7 on row 5. The config
   must either validate that dependency or make the unused values inert and say so —
   the `RateShrinkageConfig.is_identity` precedent applies.
3. **Row 4 is the only knob that changes the evaluation population.** Excluding
   departed players changes `N` from 616, so any figure measured under `exclude` is
   not comparable with any figure measured before it. That is a versioning hazard of
   a different kind from the others and should be called out wherever it is set.

**Deliberately not on this list:** the per-band prior *values* for row 5. Like
rate-shrinkage.md's 28 rate priors, they are derived from the snapshot at
construction time, not hardcoded. Adding four ownership bands × four positions as
constants would put 16 new `[assumption]` values into a file carrying seven.

---

## 8 — Tests

Specified to be implementable directly. Every assertion is to be demonstrated
failing against a mutation of the line it covers before it is kept, per the repo
discipline; each test below names its mutation.

### 8.1 Availability is evaluated per gameweek
Build a snapshot with one player, `status='i'`, `chance_of_playing_next_round=0`,
news `"Knee injury - Expected back 5 Sep"`, and a fixture list giving them one
fixture in each of GW3 (deadline before 5 Sep) and GW4 (deadline after). Assert
`p_start` is 0.0 for GW3 and strictly greater than 0.0 for GW4.
*Mutation:* hoisting `_minutes_probabilities` back out of the event loop makes both
gameweeks equal and fails.

### 8.2 `scalar` mode reproduces today byte-for-byte
Project all players over GW3–GW7 under a variant with
`horizon_availability='scalar'`, `this_round_source='next_only'`,
`news_return_dates=False`, `departed_policy='ignore'`,
`start_prior_source='position'`, `start_evidence='count'`, and assert every field of
every `Projection` equals `component/1.1-price`'s. This is the
`legacy_rate_config()` precedent: the new structure must contain the old behaviour
exactly, or no comparison across the change is valid.
*Mutation:* any default flipped to a new behaviour fails on the first row.

### 8.3 `chance_of_playing_this_round` is used for the nearest gameweek only
A player with `this_round=0`, `next_round=100`, `status='a'` — the Christie/Fofana
shape, which exists on the pinned capture. Assert `p_start` is 0.0 for the nearest
gameweek and non-zero for the second.
*Mutation:* reading `next_round` for both gameweeks fails the first assertion;
reading `this_round` for both fails the second.

### 8.4 A malformed or absent return date does not zero a player, and does not raise
Parametrise over `""`, `"Knee injury - Unknown return date"`,
`"Expected back 31 Feb"`, `"Expected back tomorrow"`, and a date with no year.
Assert no exception and that availability falls back to the `status`/`chance` path
unchanged.
*Mutation:* an unguarded `datetime.strptime` raises on the third case.

### 8.5 The return-date parser is anchored to the templated shape
Assert `"Expected back 5 Sep"` parses and that a news string merely *containing* a
date-like substring in another context does not. Include the year-boundary case: a
capture in December with `"Expected back 5 Jan"` must resolve to the following year,
not the current one.
*Mutation:* naive `%d %b` parsing defaults to 1900 and fails; appending the capture's
own year unconditionally fails the December case.

### 8.6 Ownership-conditioned priors are pooled by exposure, not averaged
The direct analogue of rate-shrinkage.md §8.6. Construct two bands with very
different player counts and assert the pooled prior equals total starts over total
appearances, not the mean of per-player rates.
*Mutation:* `statistics.mean` over ratios gives a different, wrong number.

### 8.7 A thin ownership band cannot become its own prior
rate-shrinkage.md §8.7's guard, transplanted. A band containing one player must fall
back to the position-level prior rather than shrinking that player toward themselves.
*Mutation:* removing the minimum-band-size check makes the player's own rate their
prior, and `p_start` becomes their raw start rate.

### 8.8 `p_start` stays in [0, 1] under absurd input
Property-style over: `starts` greater than `appearances` (the double-gameweek case
the existing `min(1.0, ...)` clip guards), zero appearances, `selected_by_percent`
at 0 and at 100, negative minutes, and `chance_of_playing` outside 0–100.
*Mutation:* dropping the clip produces `p_start > 1` on the first case.

### 8.9 Minutes-weighted start evidence is monotonic
For two otherwise identical players with one start each, assert the one with more
minutes in that start has `p_start` greater than or equal to the other, and that
`start_evidence='count'` makes them exactly equal.
*Mutation:* inverting the weight fails the inequality.

### 8.10 Departed players under each policy
A `status='u'` player with `"Has joined Paris Saint-Germain permanently"`. Under
`ignore`, they appear in the projection with today's behaviour; under `zero`,
`p_start` is 0.0 and they remain in the population; under `exclude`, they are absent
from the returned mapping entirely. Assert the population size differs between
`zero` and `exclude` — that is the versioning hazard of §7's row 3 made visible.
*Mutation:* implementing `exclude` as `zero` leaves the counts equal and fails.

### 8.11 The dead branches of `_availability` are exercised directly
FU-48 established they are never taken on real data. Construct the inputs that reach
them — `status='d'` with `chance=None`, and an unrecognised status with
`chance=None` — and assert 0.75 and 0.0 respectively.
*Mutation:* deleting either branch raises or returns the wrong value. These are the
only tests that will ever reach those lines, which is the argument for having them.

### 8.12 The archive differencing helper, if §4.3(c) is ever built
Not required by S1–S6. Specified here so it is not redesigned later: assert that
differencing two captures bracketing a settled gameweek yields non-negative deltas,
that a player absent from the earlier capture is handled by an explicit policy rather
than a `KeyError`, and that a pair not bracketing a settled gameweek is refused —
the FU-43 finality argument, applied to a second consumer.

---

## 9 — What this document does not settle

`[gap: the functional form for §4.3(b) — how minutes-given-start weights the
evidence term — is named as a variant knob (§7 rows 8–10) but not chosen. Three
shapes are plausible: a hard threshold, a linear ramp between two minute values, and
a continuous `minutes/90` weight. §2.5's three buckets cannot distinguish them, and
choosing on that data would be fitting to three points. The enumeration is written so
the choice is a registered variant rather than a decision this document makes.]`

`[gap: §6.1's S1–S5 are argued as structurally correct, and none of them is
*measured* to improve any metric. That measurement does not exist and cannot until
the change is built and scored across two clean gameweeks per FU-50 §2. The claim
made here is that they fix category errors — applying a next-round field to five
rounds, ignoring a machine-readable return date, projecting players who have left the
league — not that they will move Spearman. They may not.]`

`[gap: the ownership signal in §2.4 is measured against GW2 outcomes on a capture
taken before GW2, which is leak-free for that measurement. But `selected_by_percent`
at the GW2 deadline partly reflects managers reacting to GW1 team news, so it
encodes information the model could in principle derive itself from `starts`. How
much of the 76%→100% spread is independent of `starts` is not established — the
stratification controls for `starts` being 0 or 1, which after one gameweek is all
the variation there is. Re-measure once `starts` has range.]`

`[gap: everything in §1 and §2 rests on a single gameweek and a 616-player
population, and `starts` is binary on this capture, so every stratification here has
exactly two levels of the strongest available signal. The measurements are
descriptive, not inferential, and no confidence interval accompanies any of them.]`

`[gap — CLOSED 2026-09-02 by FU-53, see fu-53-minutes-ceiling.md. The original text
follows. Measured on the same pinned capture: substituting realised appearance for
the modelled one and leaving every scoring rate untouched moves
`component/1.1-price`'s `spearman_played` from 0.359 to **0.564, +0.205**, and
collapses the Zeros error from +1.317 to +0.210. §1's structural argument is now a
measured one and the prize is large. Two qualifications belong here rather than only
there: it is a **ceiling**, and §4.2's 119 players with no player-specific evidence
bound the achievable share well below it; and the Haulers error survives the oracle
almost intact (−5.438 → −4.112), so nothing in §6.1's S1–S6 will address the largest
signed error in §1's table.]`

`[gap: no attempt is made to quantify what fixing the minutes model would be worth.
The `p_start > 0.5` population is 31% wrong; whether correcting that moves
`spearman_played` by 0.05 or 0.005 is unknown, and §1's argument that minutes is the
binding constraint is a structural argument, not a sensitivity analysis. A cheap
version of that analysis — substituting realised `played` for `p_start` and
re-scoring — would bound the prize, and is not done here.]`

`[gap: `p_sub_appearance = 0.35` governs the substitute term for every player who
does not start, and is therefore a large part of what the model says about the 396
players with `starts=0`. It is untouched by every proposal above, and none of §2's
unused signals is applied to it. Whether the sub-appearance probability should also
be conditioned is not considered here.]`

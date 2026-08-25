# Plan: projected points — the scoring input for `domain/optimizer.py`

## Context

`domain/optimizer.py` is the last unwritten module in the README Agent Plan, and
its stated job is to "maximize projected points minus transfer hits" over a
"configurable horizon". Nothing in the app produces projected points. The
optimiser cannot rank one candidate squad above another without them, so the
scoring input has to be settled before the search is designed.

The README's Decisions section states: *"External injury, lineup, or prediction
APIs are deferred."* Everything below is therefore constrained to the official
endpoints.

**Scope of this document:** decide how a projected-points number is produced,
where that code lives, and whether the `fixtures` endpoint is required. It does
**not** design the optimiser — no search strategy, no beam width, no captaincy,
no chip logic.

No code written yet.

---

## What the API actually provides

Verified against the cached snapshot (`~/.fpl-cli/bootstrap-static.json`,
fetched 2026-08-25) and a live `GET /api/fixtures/` (2026-08-25, 380 fixtures,
141 KB), not assumed. 610 elements, 20 teams, 38 events.

**Timing matters for reading these numbers:** the snapshot is at **Gameweek 1**
(`events[0].is_current = true`, `finished` empty, `teams[].played = 0`). Every
season-to-date statistic below is one gameweek deep. Several findings are
artefacts of that and are marked as such.

| Signal | Field | Type | Notes |
|---|---|---|---|
| FPL's own next-GW projection | `elements[].ep_next` | string decimal | present on all 610 |
| FPL's own current-GW projection | `elements[].ep_this` | string decimal | 581/610 identical to `ep_next` |
| Form | `elements[].form` | string decimal | rolling mean, window in `game_settings.stats_form_days` = `30` |
| Points per game | `elements[].points_per_game` | string decimal | season mean |
| Expected goals / assists | `expected_goals`, `expected_assists`, `expected_goal_involvements` | string decimal | cumulative; `_per_90` variants are floats |
| Expected goals conceded | `expected_goals_conceded(_per_90)` | string / float | team-defence proxy, per player |
| Minutes signals | `minutes`, `starts`, `starts_per_90` | int / float | one GW deep |
| Availability | `status`, `chance_of_playing_next_round`, `news` | str / int\|null / str | see Finding 6 |
| Scoring table | `game_config.scoring` | object | full points-per-event table, by position |
| Opponent difficulty | `teams[].strength_overall_home` / `_away` | int 2–5 | see Finding 5 |
| Schedule | `fixtures/` endpoint | array | `event`, `team_h`, `team_a`, `kickoff_time`, `*_difficulty` |

### Finding 1 — the API already ships a projection

`ep_next` is populated for every one of the 610 elements. It is exactly `0.0`
for all 94 players with `status` in `i` (injured, 54), `u` (unavailable, 39) and
`s` (suspended, 1), and positive for all 492 `status = a` players. The 24 `d`
(doubtful) players keep a positive value. Availability is therefore already
folded in, and the encoding is clean enough to rely on.

This is the single most important fact for the build/buy decision: the naive
option is not "compute form × something", it is "parse one string".

### Finding 2 — but `ep_next` is severely compressed

Measured across the snapshot:

- Maximum value over all 610 players: **4.0**
- Only **20 distinct values** across the 492 available players
- Standard deviation across those 492: **0.55**

Haaland (`now_cost` 155) and Raya (`now_cost` 60) both score `ep_next = 4.0`.
So does Gabriel (80) and B.Fernandes (120). At this point in the season
`ep_next` cannot separate a premium forward from a budget goalkeeper — and
separating exactly those is what a squad optimiser spends its entire budget
doing.

[Unverified: whether `ep_next` decompresses once several gameweeks of data
exist. I have one snapshot, taken at GW1. It is plausible that the ceiling of
4.0 is a cold-start floor-and-cap rather than a permanent property, and this
should be re-measured around GW6 — see the follow-ups.]

### Finding 3 — `ep_this` adds nothing

Identical to `ep_next` for 581 of 610 players. Not an independent signal.

### Finding 4 — form and points-per-game are currently the same number

292 players have a non-zero `form`; the same 292 have a non-zero
`points_per_game`; and after one gameweek the two are equal for every player
(Saka `form 9.0 / ppg 9.0`, Palmer `13.0 / 13.0`). `form` is a 30-day rolling
mean (`stats_form_days`), so it only becomes independent of `points_per_game`
from roughly GW4–GW5, and only becomes a *stable* estimate later than that.

Practical consequence: the "naive form" option has literally zero information
beyond `points_per_game` for the first month of the season, and both are built
on a 1–4 match sample.

### Finding 5 — fixture difficulty carries nothing the bootstrap lacks

Checked over all 380 fixtures. The identity is exact, 380/380:

```
fixture.team_h_difficulty == teams[fixture.team_a].strength_overall_home
fixture.team_a_difficulty == teams[fixture.team_h].strength_overall_away
```

Cross-checked from the other direction: of the 40 (opponent, venue) keys, **0**
have more than one distinct difficulty value. Difficulty is a pure lookup on
opponent and venue, fixed for the whole season, never updated for form, injury
or results. Observed values are 2, 3, 4, 5 — no fixture in the season is rated 1.

Two consequences, both load-bearing:

1. **The fixtures endpoint is not needed for difficulty ratings.** Those are
   already derivable from `teams[]` in a snapshot the app already caches.
2. **It is still needed for the schedule** — who plays whom, in which gameweek,
   at home or away, and how many times. That is not in `bootstrap-static` at
   all, and it is the only thing that makes a horizon longer than one gameweek
   possible.

### Finding 6 — the attack/defence strength split is unusable right now

All 20 teams report `strength_attack_home = strength_attack_away =
strength_defence_home = strength_defence_away = 0`, with `strength = None` and
`teams[].form = None`. Only `strength_overall_home` (values 2–4) and
`strength_overall_away` (2–5) carry data, and `strength_overall_away >=
strength_overall_home` for every team.

Any model that wants "this is a good defence but a weak attack" has no inputs.
[Unverified whether these populate later in the season; in prior seasons these
fields carried a ~1000–1400 scale, and `strength` carried the 1–5 band that
`strength_overall_*` now appears to carry. The shape has changed — a live
example of the `CLAUDE.md` warning that the API is undocumented and may change.]

### Finding 7 — the full scoring table is derivable

`game_config.scoring` gives goals by position (GKP 10 / DEF 6 / MID 5 / FWD 4),
assists 3, clean sheets 4/4/1/0, `defensive_contribution` 2/2/2/0, saves 1,
`long_play` 2, `short_play` 1, cards and own goals. A bottom-up xG-to-points
model can therefore derive every coefficient from the snapshot rather than
hardcoding it, satisfying the `CLAUDE.md` rule. What it *cannot* derive is bonus
points (`bonus: 1` is the per-bonus-point value, not a model of who earns them).

### Signal against noise, measured locally

Among the 210 players who played ≥60 minutes in GW1:

| | mean | sd | range |
|---|---|---|---|
| Actual GW1 points | 3.95 | **3.51** | −2 to 17 |
| `ep_next` for those same players | 2.03 | **0.58** | 0.8 to 4.0 |

A single-gameweek projection is fighting roughly a 6:1 noise-to-signal ratio.
This is the backdrop for every accuracy claim below: the gap between a good
model and a mediocre one is small relative to the variance either is trying to
predict, and it only becomes visible when aggregated over 15 players and a
multi-gameweek horizon.

[This is one gameweek, n=210. It illustrates the scale of the problem; it is not
a validation of anything.]

---

## How wrong is each option likely to be?

Stated up front, because it constrains what the rest of this document can
honestly claim: **I cannot backtest any of these.** The repo holds one snapshot,
at GW1, with no historical per-gameweek points. `element-summary/{id}` carries
`history_past` (season totals for prior seasons, four entries for Palmer) but
not the per-gameweek series for *this* season beyond what has been played, which
is one round.

So the accuracy column below is reasoned bounds and failure modes, not measured
error. The honest ranking is on *structural* grounds — what each option can and
cannot represent — and that ranking is decisive on its own, as Decision 1 shows.

---

## The options

### Option A — passthrough `ep_next`

Read `elements[].ep_next`, parse to float, use directly.

- **Build cost:** ~20 lines plus tests. No new endpoint. Half a day at most.
- **Assumes:** FPL's internal model is better than anything derivable here (very
  likely true), and that its output is usable as a *ranking* (Finding 2 says it
  currently is not).
- **How wrong:** for a single gameweek, probably the most accurate option
  available — it is a real model with data we do not have. But the compression
  in Finding 2 makes it near-useless as an optimiser objective at GW1, and it
  covers **only the next gameweek**. There is no `ep_next+2`.
- **Breaks when:** the horizon exceeds 1. Which is the entire point of the
  module it feeds.

### Option B — rate × expected minutes

Take a per-appearance scoring rate (`form` early, blending toward
`points_per_game` as the sample grows — or simply `points_per_game`), scale by
an availability/minutes multiplier derived from `status` and
`chance_of_playing_next_round`, and multiply by fixtures in the gameweek.

- **Build cost:** ~80–120 lines plus tests. No new endpoint *if* you assume one
  fixture per gameweek per team; with the fixtures endpoint it also handles
  blanks and doubles. One to two days.
- **Assumes:** past scoring rate persists; every gameweek is interchangeable;
  minutes are predictable from status flags.
- **How wrong:** systematically wrong in a specific, known direction — it
  cannot see fixtures, so it will over-rate a player on a good run about to face
  three top-six sides, and under-rate the reverse. Over a 5–8 gameweek horizon
  that error does not cancel; fixture runs are precisely what is autocorrelated.
  Early season it is also fitting a 1–4 match sample (Finding 4).
- **Breaks when:** the horizon is long enough for fixture swings to dominate,
  which for FPL planning is basically always.

### Option C — fixture-adjusted rate

Option B, plus a per-gameweek multiplier from the opponent's
`strength_overall_home` / `_away` (equivalently the FDR, per Finding 5), a
home/away term, and a fixture count per gameweek from the schedule.

- **Build cost:** Option B plus the fixtures fetch, model, cache and its
  stale-fallback path — see Decision 3. Roughly ~150–220 lines of new code
  across `api/` and `domain/`, plus tests. Two to three days.
- **Assumes:** a coarse 4-level opponent band, fixed at the start of the season,
  is a usable proxy for fixture difficulty; and that a multiplicative adjustment
  is the right functional form. The band coefficients themselves are **not**
  derivable from the API and will be a stated assumption in code, in the same
  style as `points_per_extra_transfer` in `domain/transfers.py`.
- **How wrong:** the *rate* term inherits every weakness of Option B. The
  fixture term is coarse — 4 bands, never updated, and Finding 6 means it cannot
  distinguish attack from defence, so a clean-sheet-hunting defender and a
  goal-hunting forward get the same adjustment against the same opponent, which
  is plainly wrong. But it is directionally right where Option B is
  directionally blind, and it is the cheapest option that can represent a
  gameweek being different from another gameweek at all.
- **Breaks when:** the preseason bands go stale (a promoted side outperforming,
  a big side collapsing) — with no in-season update, that error persists all
  year.

### Option D — bottom-up xG to points

Convert `expected_goals_per_90`, `expected_assists_per_90` and
`expected_goals_conceded_per_90` into a points expectation using the position
coefficients in `game_config.scoring`, scaled by expected minutes and adjusted
for fixture.

- **Build cost:** everything in Option C, plus a minutes model, plus a
  clean-sheet probability model from `expected_goals_conceded`, plus a bonus
  model that has no data source at all. Realistically needs
  `element-summary/{id}` history for the minutes model — 610 requests. A week
  or more, and genuinely open-ended.
- **Assumes:** underlying rates are more predictive than realised points (true,
  and the main reason to want this); and that per-90 rates from a small sample
  are stable (currently false — 148 of 610 players have a non-zero
  `expected_goals`, all from one match).
- **How wrong:** in principle the most accurate option by mid-season; right now
  it would be fitting noise. Bonus points are a material fraction of a good
  player's score and this model has nothing to say about them.
- **Breaks when:** built too early. It needs a sample it does not have.

### Summary

| | endpoints | new code | horizon >1 | fixture-aware | usable at GW1 |
|---|---|---|---|---|---|
| A `ep_next` | bootstrap only | ~20 lines | **no** | implicitly | poorly (Finding 2) |
| B rate × minutes | bootstrap only | ~100 lines | yes | no | yes, on thin data |
| C fixture-adjusted | + `fixtures` | ~200 lines | yes | coarsely | yes, on thin data |
| D bottom-up xG | + `element-summary` | ~500 lines+ | yes | yes | **no** |

---

## Decision 1 — build Option C, shipping Option B's model as the baseline inside it

**Recommended.** The deciding argument is structural, not accuracy.

The optimiser scores a squad over gameweeks *t* … *t+H* for a configurable *H*.
`ep_next` exists only for *t+1*. Option A therefore cannot serve the module it
would feed, whatever its single-week accuracy — it is disqualified as *the*
model by the shape of the problem, before accuracy enters the argument.

Anything that covers a horizon must know which fixtures fall in which gameweek,
which means the fixtures endpoint (Decision 3). And once the schedule is loaded,
the difficulty weighting is nearly free — Finding 5 shows the numbers are
already in the cached bootstrap. **The marginal cost of C over B is small, and
it is paid almost entirely in the fixtures plumbing that B needs anyway** the
moment it has to handle a blank or double gameweek.

Option D is the right long-term answer and the wrong thing to build now: its
inputs are one match deep.

Concretely, ship three models behind one interface:

- `NaiveProjection` — Option B. The baseline, and the thing C is diffed against.
- `FixtureAdjustedProjection` — Option C. The default.
- `OfficialEpProjection` — Option A, single-gameweek only. Cheap, and worth
  having as an external cross-check: if the optimiser's model disagrees wildly
  with FPL's own for *t+1*, that is a bug signal. It also gives Finding 2
  somewhere to be re-measured from as the season progresses.

The cost of the third is ~20 lines and it buys a sanity check against the one
model in the system that is not ours.

**Open for Ben:** Option C's band coefficients (how much a difficulty-2 fixture
is worth against a difficulty-5) are not derivable and must be asserted. I would
start with a linear multiplier in the range 1.15 down to 0.85 across bands 2–5,
flagged in code as `[assumption: not derivable from the API]`, and made a
constructor argument so it is tunable without touching the model. Flagging
rather than deciding: this is the one number in the design with no evidential
basis whatsoever.

---

## Decision 2 — projection is its own module: `domain/projections.py`

Not inside the optimiser. Four reasons:

1. **`CLAUDE.md` requires that every optimiser recommendation pass the same
   validator used for manual planning.** The same logic applies to the scoring
   input: a projection you cannot inspect independently of the search is a
   projection you cannot debug. A separate module makes `fpl players list
   --projected` or a `projection` column a natural next step, and makes the
   optimiser's output explicable — "it bought this player because it projected
   X" is only checkable if X is obtainable without running the optimiser.

2. **The optimiser's own tests need a stub.** The README verification plan says
   "use a tiny synthetic player dataset to verify known optimizer outcomes".
   Known outcomes require known projections, which requires injecting a fixed
   projection table. That is only possible if the model is a parameter of the
   search, not a private function inside it.

3. **Blast radius.** Options A/B/C/D are all going to be tried. Swapping models
   must not touch search code — the `CLAUDE.md` simplicity rule cuts directly
   toward the seam here.

4. **Precedent.** `domain/` is already split by concern — `rules.py`,
   `squad.py`, `transfers.py`. A projection module fits the existing shape;
   burying it in `optimizer.py` would be the odd one out.

Sketch, deliberately minimal:

```python
# domain/projections.py

@dataclass(frozen=True)
class Projection:
    player: int
    event: int
    points: float
    fixtures: int          # 0 for a blank, 2+ for a double
    assumptions: list[str] # surfaced to the user, not swallowed

class ProjectionModel(Protocol):
    def project(self, player_ids: Sequence[int], events: Sequence[int]) -> dict[tuple[int, int], Projection]:
        ...
```

Batch, not per-player-per-event: the optimiser evaluates the same
(player, event) cell thousands of times across candidate squads, and a
per-call interface either recomputes or hides a cache. Compute the table once,
hand the search a read-only mapping.

### Sub-decision — projected points are `float`, unlike prices

`CLAUDE.md` says "Prices are integer units: 1000 = £100.0m. Never store as
float." That rule exists because prices are *exact* quantities where rounding
error corrupts a budget calculation. A projection is an expectation over a
random variable — 4.7 is a meaningful value that no player can ever score. The
two cases are opposites, and conflating them would round away most of the signal
in Finding 2's already-compressed range. The integer rule stays scoped to money.

---

## Decision 3 — yes, the `fixtures` endpoint is required

It is the only source of the schedule, and Decision 1 depends on it.

**What it costs to add** (verified live, 2026-08-25):

- 380 fixtures, 141 KB, all 38 gameweeks at 10 fixtures each.
- Fields used: `event`, `team_h`, `team_a`, `kickoff_time`, `finished`.
  `team_h_difficulty` / `team_a_difficulty` are **not** needed — Finding 5 shows
  they are already derivable from the cached bootstrap, and reading them from
  `teams[]` keeps the difficulty lookup working even when only a stale snapshot
  is available.
- `FplTransport.get_json` is already generic (`transport.py:100`), so no
  transport change is needed. The work is a `Fixture` model in `api/models.py`,
  a `fixtures()` method on `OfficialFplApi`, a second cache file, and extending
  `SnapshotService` to load it with the same stale-fallback contract that
  `CLAUDE.md` requires of the bootstrap snapshot.

**One trap to handle:** `event` is nullable. A postponed fixture has its `event`
set to `null` until it is rescheduled — that is exactly how blank and double
gameweeks come into existence. Right now every fixture has an event (10 per
gameweek, 0 nulls), so a model that assumes one fixture per team per gameweek
will look correct all preseason and start silently mis-scoring the first time a
match is postponed. The `Fixture` model must type `event` as `int | None` and
the projection must derive its fixture count by counting, never by assuming 1.

**`element-summary/{id}` is not required and should not be added for this.**
12.6 KB per player × 610 players ≈ 7.7 MB and 610 requests against an
IP-rate-limited, unauthenticated API — the README already explains why hammering
that endpoint is a bad trade. Its per-player `fixtures` array duplicates the
global endpoint. Its `history` array (per-gameweek minutes, points, xG) is the
one thing it uniquely offers, and that is Option D's input. Defer it with
Option D.

---

## Decision 4 — expected minutes is the largest error term, and the snapshot barely supports it

Every option above multiplies a rate by expected minutes, so the minutes term
dominates the error: a 6-point-per-game player who is benched scores 1, and no
amount of fixture adjustment recovers that.

What the snapshot offers:

- `status` — 492 `a`, 54 `i`, 39 `u`, 24 `d`, 1 `s`.
- `chance_of_playing_next_round` — **null for 458 of 610**. Where non-null: 94
  zeros, 1 at 25, 4 at 50, 19 at 75, 34 at 100.
- `starts`, `starts_per_90`, `minutes` — real but one gameweek deep (220
  players with `starts > 0`).
- `news` — free text, non-empty for 118 players. Not machine-readable.

So for 458 players the only availability signal is `status = a`, which does not
distinguish a nailed-on starter from a fourth-choice full-back. This is the gap
the README's deferred external lineup APIs would have filled.

**Proposal:** a single explicit multiplier, derived where possible and asserted
where not —

```
chance_of_playing_next_round is not None  ->  chance / 100
status == 'a'                             ->  1.0
otherwise                                 ->  0.0
```

— combined with a *separate*, clearly-labelled rotation factor from
`starts_per_90` once enough gameweeks exist to make it meaningful. Until then
the rotation factor is 1.0 and the model says so in `Projection.assumptions`.
Flagging this loudly rather than hiding it is the point: the number this model
is least able to justify is the one that moves its output most.

---

## Scope boundary

**In:** how a projected-points number is produced; where the module sits; the
fixtures endpoint decision; the minutes-multiplier shape.

**Out:** the optimiser itself — search strategy, horizon defaults, pruning,
captaincy multipliers, chip interaction, and how transfer hits net off against
projected gain. `domain/optimizer.py` gets its own plan, written against the
interface in Decision 2.

Also out: adding a projection column to `fpl players list`, and any CLI surface.
Domain layer only, matching how `domain/transfers.py` was scoped.

---

## Verification

- Projections for a synthetic dataset with hand-computed expected values, in the
  existing mocked-API style. No live API.
- A blank gameweek (a fixture with `event = null`) yields `fixtures = 0` and
  `points = 0.0`, not a silent one-fixture assumption.
- A double gameweek yields `fixtures = 2` and roughly double the single-fixture
  projection.
- Every `status` value maps to the documented multiplier, including the
  `chance_of_playing_next_round` override for `d` players.
- `OfficialEpProjection` refuses any event other than the next one, rather than
  returning a wrong number for *t+2*.
- The fixtures cache falls back when the live fetch fails, matching
  `tests/test_stale_cache.py`'s existing contract for the bootstrap snapshot.
- Difficulty bands are read from `teams[]`, so a stale snapshot still projects.

---

## Follow-ups to file in [follow-ups.md](follow-ups.md)

- **Fixtures endpoint, model and cache** — the plumbing from Decision 3, if it
  is split out of the projections branch rather than built with it.
- **Minutes model from `element-summary` history** — Option D's prerequisite,
  and the fix for Decision 4's 458 unknown players.
- **Re-measure `ep_next` compression around GW6** — Finding 2's ceiling of 4.0
  may be a cold-start artefact. If it decompresses, `OfficialEpProjection` gets
  materially more useful and Decision 1 is worth revisiting for the *t+1* term.
- **Re-check `strength_attack_*` mid-season** — Finding 6. All zero at GW1. If
  they populate, an attack/defence split becomes possible and fixes Option C's
  worst structural flaw.
- **Bonus points have no model and no data source** — noted in Finding 7,
  affects every option, no fix identified.

---

## Assumptions

- `[Not derivable]` The difficulty-band coefficients in Option C. Asserted, made
  a constructor argument, flagged in code.
- `[Not derivable]` The rotation factor for players with a null
  `chance_of_playing_next_round`. Held at 1.0 and declared in
  `Projection.assumptions`.
- `[Unverified]` That `ep_next`'s compression is a GW1 artefact.
- `[Unverified]` That `strength_attack_*` / `strength_defence_*` populate later
  in the season. They were meaningful in prior seasons on a different scale;
  the field shape has changed.
- `[Unmeasured]` Every accuracy claim in "The options". One snapshot at GW1, no
  historical per-gameweek points, no backtest possible from local data.

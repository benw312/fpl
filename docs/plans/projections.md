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

**Companion document:**
[docs/research/projections-survey.md](../research/projections-survey.md) surveys
public FPL projection methodologies and open-source implementations. This plan's
findings about the API are first-hand, measured against a live snapshot; where
the two documents touch the same question, the survey supplies the outside view
and this plan records the decision. Decisions 1, 4 and 5 were each revised after
reading it, and the revisions are marked in place.

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

This was originally flagged as possibly a GW1 cold-start artefact.
[projections-survey.md](../research/projections-survey.md) records `ep_next`
compression as documented, current API behaviour rather than a snapshot
artefact, so the hedge is withdrawn: do not plan on it decompressing.

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

### Finding 6 — the attack/defence strength split is unusable, and will stay that way

All 20 teams report `strength_attack_home = strength_attack_away =
strength_defence_home = strength_defence_away = 0`, with `strength = None` and
`teams[].form = None`. Only `strength_overall_home` (values 2–4) and
`strength_overall_away` (2–5) carry data, and `strength_overall_away >=
strength_overall_home` for every team.

Any model that wants "this is a good defence but a weak attack" has no inputs.

In prior seasons these fields carried a ~1000–1400 scale, and `strength` carried
the 1–5 band that `strength_overall_*` now appears to carry. The shape changed
with the 2025/26 season — a live example of the `CLAUDE.md` warning that the API
is undocumented and may change.

**This is settled, not pending.**
[projections-survey.md](../research/projections-survey.md) is explicit: build no
component that depends on the strength fields repopulating. The route to an
attack/defence split is to fit team strength ourselves from results (a
Dixon-Coles Poisson on the fixtures endpoint is the community standard), not to
wait on the API. That is out of scope here — see the follow-ups.

### Finding 7 — the full scoring table is derivable

`game_config.scoring` gives goals by position (GKP 10 / DEF 6 / MID 5 / FWD 4),
assists 3, clean sheets 4/4/1/0, `defensive_contribution` 2/2/2/0, saves 1,
`long_play` 2, `short_play` 1, cards and own goals. The component decomposition
(Decision 1) can therefore price every term from the snapshot rather than
hardcoding it, satisfying the `CLAUDE.md` rule.

Two things it does **not** give: bonus points (`bonus: 1` is the per-bonus-point
value, not a model of who earns them), and the defensive-contribution
*thresholds* — the 2-point value is here, the 10 / 12 action counts that trigger
it are not. See Decision 5.

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

For an external sense of the ceiling,
[projections-survey.md](../research/projections-survey.md) reports published
benchmarks: at a one-gameweek horizon, fixture adjustment plus minutes modelling
buys roughly a 5–34% RMSE reduction over a naive baseline, depending on return
category. Meaningful, but not transformative — most of the residual is
irreducible football variance, which is the same story the local 6:1
noise-to-signal measurement tells. Nothing in this module will make projections
*good*; the aim is to make them better than a flat average and honest about
their assumptions.

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

### Option D — the component decomposition

Rather than projecting one aggregate number, project each scoring term
separately and sum them:

```
xp = xp_appearance + xp_attack + xp_clean_sheet + xp_conceded
   + xp_saves + xp_defcon + xp_bonus + xp_cards
```

Appearance from an expected-minutes model; attack from
`expected_goals_per_90` / `expected_assists_per_90` scaled by minutes and
fixture, priced with the position coefficients in `game_config.scoring`; clean
sheet from a per-fixture probability; defensive contribution from a threshold
model (Decision 5); bonus from a heuristic on xGI and defensive actions.

- **Build cost:** the largest of the four — a term per scoring category, each
  independently testable. Its *inputs*, however, are the same bootstrap fields
  Options B and C already use. It does **not** require `element-summary`; that
  endpoint only becomes necessary for a per-match minutes model, which is a
  later refinement of one term rather than a precondition for the structure.
- **Assumes:** underlying rates are more predictive than realised points (true
  in the literature, and the main reason to want this); and that per-90 rates
  from a small sample are usable (currently weak — 148 of 610 players have a
  non-zero `expected_goals`, all from one match).
- **How wrong:** at GW1, roughly as wrong as Option C, and possibly worse on
  attacking returns, because it is fitting per-90 rates on one match instead of
  leaning on realised points. Bonus is a material fraction of a good player's
  score and no option here models it well.
- **Breaks when:** its coefficients are trusted early. The structure is sound
  from day one; the numbers inside it are not.

### Summary

| | endpoints | new code | horizon >1 | fixture-aware | usable at GW1 |
|---|---|---|---|---|---|
| A `ep_next` | bootstrap only | ~20 lines | **no** | implicitly | poorly (Finding 2) |
| B rate × minutes | bootstrap only | ~100 lines | yes | no | yes, on thin data |
| C fixture-adjusted | + `fixtures` | ~200 lines | yes | coarsely | yes, on thin data |
| D decomposition | + `fixtures` | ~400 lines | yes | yes, per term | yes, on thin data |

---

## Decision 1 — ship the full component decomposition (Option D) at v1

**Decided.** An earlier draft of this plan recommended Option C and deferred the
decomposition on the grounds that its inputs are one match deep. That reasoning
was about *accuracy*, and it was answering the wrong question.
[projections-survey.md](../research/projections-survey.md) makes the case for
building the decomposition immediately, and it is accepted here.

Two arguments survive from the earlier draft and still hold:

The optimiser scores a squad over gameweeks *t* … *t+H* for a configurable *H*.
`ep_next` exists only for *t+1*. Option A therefore cannot serve the module it
would feed, whatever its single-week accuracy — it is disqualified as *the*
model by the shape of the problem, before accuracy enters the argument.

Anything that covers a horizon must know which fixtures fall in which gameweek,
which means the fixtures endpoint (Decision 3). And once the schedule is loaded,
the difficulty weighting is nearly free — Finding 5 shows the numbers are
already in the cached bootstrap.

### Why the decomposition, given that it is not more accurate at v1

**The value of the decomposition is interface stability, not v1 accuracy.**

At GW1 the decomposition is roughly as accurate as Option C and may be worse on
attacking returns, since it fits per-90 rates on one match instead of leaning on
realised points. That is not the argument for it. The argument is that every
subsequent improvement — a fitted team-strength model replacing the fixture
bands, a per-match minutes model replacing the status heuristic, a real bonus
model replacing the placeholder — is a change to **one term** rather than a
change to the model's output contract. The optimiser, its tests, and the
`Projection` object are untouched by any of them.

Building Option C first and decomposing later inverts that: it buys marginally
better GW1 numbers, then pays for them with a reshaped interface at exactly the
point when the optimiser has been written against the old one. The interface is
the expensive thing to change; the coefficients are cheap. Get the shape right
while nothing depends on it.

The corollary is that **v1's numbers must not be trusted just because the
structure is principled.** The decomposition makes the model easy to improve, it
does not make it good. Verification treats it as unproven — see the benchmark
below.

### What ships

Behind one interface (Decision 2):

- `ComponentProjection` — Option D. The default. Every term implemented, with
  the weak ones explicitly labelled in `Projection.assumptions`.
- `NaiveProjection` — Option B, flat `points_per_game` × minutes × fixture
  count. Not a stepping stone: it is the **control**. The literature's standard
  baseline is a "last 5 games mean", and a component model that cannot beat a
  flat average is a component model with a bug. This must be kept and must stay
  runnable.
- `OfficialEpProjection` — Option A, single-gameweek only. ~20 lines, and it
  buys a sanity check against the one model in the system that is not ours: if
  our *t+1* disagrees wildly with FPL's, that is a bug signal.

**Fixture bands stay a labelled heuristic.** The survey searched for a published
empirical band-to-points mapping and found none — sites quoting per-band point
figures are unsourced. So the multiplier (1.15 / 1.05 / 1.00 / 0.90 / 0.85
across bands 2–5, with a home/away split) is asserted, not derived. It stays a
constructor argument, tagged in code as
`[assumption: heuristic, no published empirical basis]`, alongside
`points_per_extra_transfer` in `domain/transfers.py` as a value the API does not
give us. Deriving it empirically from a historical archive is possible and is
filed as a follow-up, not done here.

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

Sketch. The component fields are the point of Decision 1 — the simpler models
(`NaiveProjection`, `OfficialEpProjection`) emit the same object with their
unmodelled terms at `0.0` and a note in `assumptions`, so the optimiser never
branches on which model it was handed:

```python
# domain/projections.py

@dataclass(frozen=True)
class Projection:
    player: int
    event: int
    points: float          # the sum of the components below
    # components, so a projection can be explained and each term improved alone
    appearance: float
    attack: float
    clean_sheet: float
    conceded: float
    saves: float
    defcon: float          # Decision 5
    bonus: float
    cards: float
    expected_minutes: float
    fixtures: int          # 0 for a blank, 2+ for a double
    model: str             # which model produced this, for cross-checks
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
one thing it uniquely offers, and that feeds a per-match minutes model — a later
refinement of the `appearance` term, not a precondition for shipping the
decomposition. Deferred as a follow-up.

---

## Decision 4 — expected minutes is the largest error term, and a categorical model is enough

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

**Decided:** an explicit availability multiplier, derived where possible and
asserted where not, following the community convention recorded in
[projections-survey.md](../research/projections-survey.md) —

```
chance_of_playing_next_round is not None  ->  chance / 100
status == 'd'  (doubtful, no percentage)  ->  0.75   # heuristic
status == 'a'                             ->  1.0
otherwise  (i, s, u)                      ->  0.0
```

The `0.75` for doubtful-without-a-percentage replaces an earlier draft that sent
that case to `0.0`, which was badly wrong in a way the current snapshot hides:
**all 24 `d` players currently carry a non-null
`chance_of_playing_next_round`**, so the branch has zero instances today and a
test built only on this snapshot would never reach it. The API does emit `d`
with a null chance at other times, so the rule is a defensive default and needs
a synthetic test rather than a snapshot-derived one.

Note what this does *not* fix: all 458 null-chance players are `status = a` and
still map to `1.0`. The nailed-starter-versus-fourth-choice problem is untouched
by this rule.

Two things temper the earlier draft's alarm about that:

- The survey cites OpenFPL — which "dispenses with proprietary 'expected
  minutes' projections, using instead the categorical availability tags provided
  by the FPL API" — as rivalling the leading commercial model. A simple
  categorical minutes model is evidently adequate, so the 458 nulls are less
  damaging than assumed.
- Where the commercial benchmark does beat it is precisely on zeros and blanks,
  from proprietary start/rest information the official API does not carry. That
  gap is real and unclosable from official data, which is what the README's
  deferred lineup APIs would have addressed.

A *separate*, clearly-labelled rotation factor from `starts_per_90` follows once
enough gameweeks exist to make it meaningful. Until then it is `1.0` and the
model says so in `Projection.assumptions`. Flagging this loudly rather than
hiding it is the point: the number this model is least able to justify is the
one that moves its output most — and per the survey, if v1 fails to beat the
`NaiveProjection` control, expected minutes is the first place to look, not the
fixture model.

---

## Decision 5 — defensive contribution is its own term, with a threshold model

**Decided.** `defensive_contribution` scores 2 points (`game_config.scoring`:
DEF 2 / MID 2 / FWD 2 / GKP 0), and it is **not** a quantity that can be
projected by multiplying an average by a fixture multiplier. It is a threshold:

- a **defender** scores +2 for ≥10 CBIT (clearances, blocks, interceptions,
  tackles) in a match;
- a **midfielder or forward** scores +2 for ≥12 CBIRT (the same, plus ball
  recoveries);
- capped at +2 per match regardless of volume; goalkeepers ineligible.

[The thresholds 10 and 12 are **not** in `bootstrap-static` — `game_config.scoring`
carries the 2-point value but no threshold. They come from the published rules
via [projections-survey.md](../research/projections-survey.md) and must be
flagged in code the same way `points_per_extra_transfer` is in
`domain/transfers.py`. Re-verify against the API before hardcoding, in case a
threshold field appears.]

Why this cannot be folded into a fixture-multiplied total: the payoff is a
capped step function, so the expectation is `P(volume >= threshold) × 2`, and
that probability does not scale linearly with anything. Doubling a player's
expected defensive actions does not double the term — past the threshold it adds
nothing at all, and a hard fixture that *raises* a defender's clearance volume
moves this term the opposite way from every other term in the model. Applying
the fixture multiplier to an aggregate that silently contains this bonus gets
the sign wrong for exactly the players it matters most to.

**Model:** estimate per-match defensive-action volume from
`defensive_contribution_per_90` × (expected minutes / 90), then map to a
probability of clearing the position threshold. 267 of 610 players already carry
a non-zero `defensive_contribution_per_90`, so the input exists from GW1 — on a
one-match sample, like everything else here.

[The distributional assumption — how volume varies match to match around its
mean — is a modelling choice with no support in the snapshot. Start with the
simplest defensible form, keep it in one function, and label it. This is a term
where the community has published no usable constants either.]

**Consequences elsewhere:** the fixture multiplier applies to `attack`,
`clean_sheet` and `conceded`, and **not** to `defcon`. That asymmetry is the
main reason `Projection` carries components rather than a single number
(Decision 2) — it cannot be expressed at all in a design that multiplies one
aggregate.

---

## Scope boundary

**In:** how a projected-points number is produced; where the module sits; the
fixtures endpoint decision; the minutes-multiplier shape; the defensive
contribution term.

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
  `chance_of_playing_next_round` override, and **including `status = 'd'` with a
  null chance → 0.75**. That branch has no instances in the current snapshot
  (Decision 4), so it needs a synthetic fixture; a test built from live data
  would pass while never executing it.
- `Projection.points` equals the sum of its component fields, for every model.
  This is the invariant that lets the optimiser read one number while each term
  is improved independently.
- The fixture multiplier is applied to `attack`, `clean_sheet` and `conceded`
  and **not** to `defcon` (Decision 5) — asserted directly, since getting this
  wrong is silent and only mis-ranks defensive midfielders.
- `defcon` is zero for goalkeepers at every difficulty, and responds to the
  position threshold boundary (a DEF at 9 versus 10 expected actions).
- `NaiveProjection` and `OfficialEpProjection` emit the same `Projection` shape
  with unmodelled components at `0.0` and a populated `assumptions` list.
- `OfficialEpProjection` refuses any event other than the next one, rather than
  returning a wrong number for *t+2*.
- The fixtures cache falls back when the live fetch fails, matching
  `tests/test_stale_cache.py`'s existing contract for the bootstrap snapshot.
- Difficulty bands are read from `teams[]`, so a stale snapshot still projects.

**The benchmark, not a unit test:** `ComponentProjection` must beat
`NaiveProjection` on realised points once a few gameweeks exist — RMSE per
player-gameweek and Spearman rank correlation, per the survey's account of
standard practice. Until that has been run, v1 is unproven regardless of how
principled its structure is (Decision 1). If it fails, the survey's guidance is
to fix expected minutes before adding model complexity. This needs accrued
results, so it cannot run at GW1 and is not a merge gate for the module.

---

## Follow-ups to file in [follow-ups.md](follow-ups.md)

- **Fixtures endpoint, model and cache** — the plumbing from Decision 3, if it
  is split out of the projections branch rather than built with it.
- **Fitted team-strength model to replace the fixture bands** — a Dixon-Coles
  Poisson on accrued results from the fixtures endpoint, per
  [projections-survey.md](../research/projections-survey.md). This is the
  intended replacement for Finding 6's missing attack/defence split, and the
  single largest improvement available. Needs ~4–6 gameweeks of results before
  it is stable, with the bands kept as the cold-start fallback. Because it
  replaces one term, it lands without touching the interface — which is the
  Decision 1 bet being cashed in.
- **Derive the fixture-band multipliers empirically** — from a historical
  archive, replacing the labelled heuristic in Decision 1. No published mapping
  exists to copy.
- **Minutes model from `element-summary` history** — refines Decision 4's
  `appearance` term. Note this is no longer a prerequisite for anything, only an
  improvement to one component.
- **Re-verify the defensive-contribution thresholds** — Decision 5's 10 / 12 are
  from published rules, not the API. Check whether a threshold field appears in
  `game_config`.
- **Bonus points have no model and no data source** — noted in Finding 7,
  affects every option. The survey notes BPS was reworked for 2026/27, so any
  approximation borrowed from older sources is stale.

---

## Assumptions

- `[Not derivable]` The fixture-band coefficients. Asserted as a heuristic with
  no published empirical basis, made a constructor argument, flagged in code.
- `[Not derivable]` `0.75` for a doubtful player with no stated chance
  (Decision 4). Community convention, not an API value.
- `[Not derivable]` The rotation factor for `status = 'a'` players with a null
  `chance_of_playing_next_round`. Held at 1.0 and declared in
  `Projection.assumptions`.
- `[Not in the API]` The defensive-contribution thresholds of 10 CBIT (DEF) and
  12 CBIRT (MID/FWD), and the match-to-match distribution of defensive-action
  volume used to turn them into a probability (Decision 5).
- `[No data source]` Bonus points. Affects every option.
- `[Unmeasured]` Every accuracy claim in "The options", and the claim that the
  component model beats the naive control. One snapshot at GW1, no historical
  per-gameweek points, no backtest possible from local data — hence the
  benchmark under Verification rather than a number here.

Two hedges from the first draft of this plan are **withdrawn**, on the strength
of [projections-survey.md](../research/projections-survey.md): that `ep_next`'s
compression might be a GW1 artefact (Finding 2), and that the
`strength_attack_*` / `strength_defence_*` fields might repopulate later in the
season (Finding 6). Both are current API behaviour and should be designed
around, not waited out.

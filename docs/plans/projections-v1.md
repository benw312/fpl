# Plan: `domain/projections.py` v1 — the full xP decomposition

## Context

`domain/optimizer.py` is the last unwritten module in the README Agent Plan and
cannot rank one candidate squad above another without a projected-points input.
[projections.md](projections.md) settled *what* to build — Option D, the full
component decomposition, behind a stable `Projection` interface — and *why*: the
interface is the expensive thing to change, the coefficients are cheap, so the
shape must be right while nothing depends on it.

This plan settles *how*. It covers the decomposition itself, the two new
endpoints it needs (`fixtures/`, `event/{gw}/live/`), the strategy seam that
lets v2's Dixon-Coles model replace the fixture heuristic without touching the
decomposition, and the evaluation harness that decides whether any of it works.

The intended outcome: `fpl plan evaluate --event N` prints RMSE and Spearman for
the component model against a flat `points_per_game` baseline, so the survey's
decision rule — *if v1 fails to beat the baseline, fix minutes before adding
model complexity* — is answerable with a command rather than an argument.

**Companion documents:** [projections.md](projections.md) is the decision record
(what and why); [projections-survey.md](../research/projections-survey.md) is the
outside view. Where this plan departs from either, it says so and gives the
measurement.

---

## Verification performed for this plan

Measured against the cached snapshot (`~/.fpl-cli/bootstrap-static.json`,
fetched 2026-08-25 11:00) and one live `GET /api/event/1/live/`. These correct
or confirm points the survey flagged as needing confirmation.

**Defensive-contribution thresholds — confirmed empirically, not taken on
trust.** `event/1/live`'s `explain` block names `defensive_contribution` as a
scored identifier, so the threshold can be bracketed directly from who did and
did not receive it:

| Position | Scored (n, min `dc`) | Did not score (n, max `dc`) | Verdict |
|---|---|---|---|
| GKP | 0 | 20, max 0 | Ineligible — confirmed |
| DEF | 19, min **10** | 89, max **9** | **>=10 confirmed** |
| MID | 12, min **12** | 135, max **11** | **>=12 confirmed** |
| FWD | 0 | 35, max 8 | **Unconfirmed** — no forward exceeded 8 |

The only points value ever awarded is `2`, confirming the cap. The FWD threshold
of 12 is `[assumed by parity with MID, per published rules; untestable at GW1]`
and must be re-checked once a forward reaches 12.

**No threshold field exists anywhere in the API.** Searched `game_settings`,
`game_config.rules`, `game_config.scoring`, `element_stats`, and every nested key
in the payload. `game_config.scoring.defensive_contribution` carries the 2-point
value only. The follow-up "check whether a threshold field appears in
`game_config`" is answered: it has not.

**`defensive_contribution` is pre-combined by the API.** Across all 310 players
with minutes, `dc == clearances_blocks_interceptions + tackles` for every DEF
(0 mismatches) and `dc == cbi + tackles + recoveries` for every MID/FWD
(0 mismatches). We do not assemble CBIT/CBIRT ourselves —
`defensive_contribution_per_90` is the input, and 267 of 610 players already
carry a non-zero one.

**BPS constants are absent from the API entirely.** The survey's caveat "the
exact BPS conversion constants should be re-verified against `bootstrap-static`
`game_settings`" resolves to: they are not there. `scoring.bps = 0` means BPS
itself awards no points, not that a table exists elsewhere. The only BPS data is
each player's realised season total. This forecloses any structural bonus model
at v1 and drives the bonus decision below.

**The scoring table reconstructs `total_points` exactly.** Pricing every term
from `game_config.scoring` and summing over all 310 played players leaves a
residual of exactly 0 (n=279) or exactly 2 (n=31, all DefCon) — no unexplained
points. Two consequences: the module can price every component from the snapshot
with no hardcoded scoring values, satisfying the `CLAUDE.md` rule; and the
evaluation harness can decompose *actual* points per component via `explain`,
measuring per-term error rather than only total RMSE.

**Per-90 inputs all exist:** `expected_goals_per_90`, `expected_assists_per_90`,
`expected_goals_conceded_per_90`, `saves_per_90`, `starts_per_90`,
`clean_sheets_per_90`, `goals_conceded_per_90`, `defensive_contribution_per_90`.
Coverage at GW1 is thin as expected: 148 non-zero `expected_goals_per_90`,
19 `saves_per_90`, 267 `defensive_contribution_per_90`.

**`event/{gw}/live/` shape (live, 200, 436 KB):** `{"elements": [{"id", "stats",
"explain", "modified"}]}`, 610 elements. `stats` mirrors the bootstrap stat
names plus `total_points` and `played`. `explain` is a **list per fixture** — a
double gameweek yields two entries — each `{"fixture", "stats": [{"identifier",
"points", "value", "points_modification"}]}`.

---

## Decision 1 — the strategy seam returns match rates, not a scalar multiplier

This is the load-bearing design choice and the thing that makes "v2's
Dixon-Coles slots in without touching the decomposition" actually true.

A scalar fixture multiplier (`1.15` for an easy fixture) cannot express a clean
sheet. Dixon-Coles natively produces expected goals for and against; squashing
that into one scalar and re-deriving P(CS) from it would mean v2 rewriting the
clean-sheet, goals-conceded and saves terms. So the injectable strategy returns
rates, and the decomposition owns the conversion from rates to points:

```python
# domain/strength.py

@dataclass(frozen=True)
class MatchRates:
    """Expected goals for and against one team in one fixture."""
    xg_for: float
    xg_against: float

class TeamRatesModel(Protocol):
    def rates(self, *, team: int, opponent: int, home: bool) -> MatchRates: ...
    @property
    def league_mean_goals(self) -> float: ...
    @property
    def name(self) -> str: ...   # lands in Projection.model_version
```

Everything the decomposition needs follows from `MatchRates` by Poisson:

- `P(clean sheet) = exp(-xg_against)`
- `E[goals-conceded deduction]` = sum over k of `P(k) * floor(k/2) *
  scoring.goals_conceded[pos]` — summed over the pmf, **not** `xg_against / 2`,
  because the floor is nonlinear
- attack scaling = `xg_for / league_mean_goals`, applied to the player's
  xG90/xA90
- save volume scaling = `xg_against / league_mean_goals`

**v1 implementation — `BandedTeamRates`.**
`xg_for = league_mean * band_multiplier(opponent, venue)`,
`xg_against = league_mean / band_multiplier(...)`. The band comes from
`teams[].strength_overall_home/_away` per projections.md Finding 5, so the
fixtures endpoint is needed for the *schedule* only and a stale snapshot still
projects.

```python
# [heuristic, no published empirical basis — see projections-survey.md §5]
BAND_MULTIPLIERS = {1: 1.15, 2: 1.15, 3: 1.05, 4: 0.90, 5: 0.85}
LEAGUE_MEAN_GOALS = 1.45  # [assumption: ~2.9 goals/game long-run PL average,
                          # not derivable from the API pre-results]
```

Both are constructor arguments, not module constants baked into behaviour, in
the same style as `points_per_extra_transfer` in `domain/transfers.py:23`.

**`home_advantage = 1.0` is correct for `BandedTeamRates`, and for that
implementation specifically — not as a statement about home advantage.** The
survey recommends a multiplicative gamma≈1.2 on the home scoring rate. That is
right in general and wrong here, because this strategy's input is already
venue-resolved: Finding 5 measured
`team_h_difficulty == teams[team_a].strength_overall_home` across all 380
fixtures, so difficulty is a pure lookup on *(opponent, venue)* and a team's band
against the same opponent already differs home from away. Multiplying by gamma on
top would apply venue twice. `BandedTeamRates` therefore takes
`home_advantage: float = 1.0` and documents the reason at the parameter. It stays
a constructor argument rather than being removed so the assumption is visible and
falsifiable against the data, not because it is a knob to tune.

**v2's Dixon-Coles still requires a fittable gamma — this does not carry over.**
That model fits alpha/beta/gamma/rho on raw scorelines from the fixtures endpoint
(`team_h_score`/`team_a_score`), and a scoreline carries no venue adjustment of
any kind. Venue can enter the likelihood only through gamma, so it is not merely
permitted there but necessary: omit it and the fit attributes home advantage to
the attack parameters of whichever teams have played more home fixtures, biasing
every rating for as long as the schedule is unbalanced — which is most of the
first half of the season. Seed gamma≈1.2, fit it, and re-estimate through the
season; the survey documents Premier League home advantage as declining and
volatile (~0.3 goals/game historically, 0.04 in a 2024/25 in-season analysis,
~0.25 in 2025), so it must not be pinned.

The two positions are consistent: gamma is 1.0 in v1 because venue is already
applied upstream in the band, and fitted in v2 because gamma is the only place
venue can enter at all.

**Once results accrue, `league_mean_goals` stops being an assumption** — it is
computable from the fixtures endpoint's `team_h_score`/`team_a_score`. Wire it as
a method on `BandedTeamRates` that prefers the measured value when enough
fixtures have finished and falls back to the constant otherwise. A genuine
improvement for ~10 lines that removes one invented number.

---

## Decision 2 — the `Projection` interface

```python
# domain/projections.py

@dataclass(frozen=True)
class Projection:
    player: int
    event: int
    xp_total: float           # == sum of the components below, invariant-tested

    xp_appearance: float
    xp_attack: float
    xp_clean_sheet: float
    xp_conceded: float
    xp_saves: float
    xp_defcon: float
    xp_bonus: float
    xp_cards: float

    p_start: float            # P(starts), before the fixture count
    xmins: float              # expected minutes across all fixtures in the event
    fixtures: int             # 0 = blank, 2+ = double
    model_version: str        # e.g. "component/1.0+banded"
    assumptions: tuple[str, ...]

class ProjectionModel(Protocol):
    def project(
        self, players: Sequence[int], events: Sequence[int]
    ) -> Mapping[tuple[int, int], Projection]: ...
```

Batch, per projections.md Decision 2: the optimiser evaluates the same
(player, event) cell thousands of times, so the table is computed once and handed
over read-only. The optimiser reads `xp_total` and nothing else; every other
field exists for explanation and debugging.

Three models ship, all emitting the same object with unmodelled components at
`0.0`:

- **`ComponentProjection`** — the default, all eight terms.
- **`NaiveProjection`** — `points_per_game * availability * fixtures`. The
  control, not a stepping stone. Must stay runnable.
- **`OfficialEpProjection`** — `ep_next` parsed. Refuses any event but the next
  one rather than returning a wrong number for *t+2*.

`model_version` composes the decomposition version with the rates strategy name,
so a projection table is self-describing about which team model produced it.

---

## Decision 3 — the fixtures endpoint, and how its cache relates to the bootstrap cache

**The chain, unchanged from the bootstrap path.** `FplTransport.get_json` is
already generic (`transport.py:100`) and handles a top-level JSON *list*
(`transport.py:190` accepts `dict | list`), so no transport change is needed.

1. `api/models.py` — `Fixture`, with **`event: int | None`**. A postponed
   fixture has `event = null` until rescheduled; that is exactly how blanks and
   doubles arise. All 380 currently have an event, so a model that assumes one
   fixture per team per gameweek looks correct all preseason and silently
   mis-scores the first postponement. Fixture count is always derived by
   counting, never assumed.
2. `api/official.py` — `OfficialFplApi.fixtures() -> list[Fixture]`, wrapping
   `ValidationError` in `FplApiError` exactly as `bootstrap_static` does
   (`official.py:47-52`).
3. `storage/cache.py` — see below.
4. `api/snapshots.py` — `SnapshotService.load_fixtures() -> FixturesResult`,
   with the same try-live / fall-back-to-cache / re-raise-if-no-cache contract as
   `load()` (`snapshots.py:28-41`), and `refresh_fixtures()` mirroring
   `refresh()`.

**Cache: separate store, independent staleness.**

`SnapshotCache` (`storage/cache.py:10`) is generalised into a path-keyed JSON
document cache with typed accessors — one save/load implementation, three files:

```
~/.fpl-cli/bootstrap-static.json     (existing, unchanged path)
~/.fpl-cli/fixtures.json
~/.fpl-cli/events/{n}-live.json      (Decision 6)
```

**They go stale independently.** Each has its own file, its own mtime-derived
`fetched_at`, and its own `stale` flag in its result object. Reasons:

- The two resources change on different cadences. Prices and availability move
  daily in bootstrap; the fixture list is near-static except for reschedules and
  results. Bundling them means a failed bootstrap fetch discards a perfectly good
  fixtures response.
- The `CLAUDE.md` stale-cache guarantee is per-resource: "cached snapshots must
  keep the app usable during failures". A combined blob makes any single
  endpoint's failure poison the whole cache.
- Finding 5 already decoupled them for the thing that matters — difficulty bands
  come from `teams[]`, so **a stale fixtures file still yields correct difficulty
  ratings**, and a stale bootstrap still yields a correct schedule.

**The cost of independence, and how it is surfaced.** Two stores can disagree: a
fresh bootstrap saying GW5 is current alongside a fixtures file cached before a
postponement will project a fixture that no longer exists. There is no way to
detect this from the data, so it is disclosed rather than solved —
`ProjectionInputs` carries both `stale` flags, and `ComponentProjection` appends
`"fixtures list is stale (cached {ts}); blanks and doubles may be wrong"` to
`Projection.assumptions` whenever the fixtures store is stale. The alternative,
an atomic both-or-neither bundle, trades a rare and visible inconsistency for a
common and invisible loss of availability. Not worth it.

`fpl sync` refreshes both and reports both.

*(FU-4 proposes a SQLite backend "once the second and third endpoints land". That
moment has arrived, but SQLite is not adopted here: three JSON documents do not
need a database, and bundling a storage-layer migration with a new domain module
would violate the one-concern-per-branch rule. FU-4 is re-pointed at the
per-event live payloads, where the file count actually grows.)*

---

## Decision 4 — the minutes model

Every term multiplies through expected minutes, so this dominates the error, and
per the survey it is the first place to look if v1 fails the benchmark.

**Availability** — the community convention, unchanged from projections.md
Decision 4:

```
chance_of_playing_next_round is not None  ->  chance / 100
status == 'd' with no percentage          ->  0.75   # [heuristic]
status == 'a'                             ->  1.0
otherwise (i, s, u)                       ->  0.0
```

**Start rate.** `p_start = availability * shrunk_start_rate`, where
`shrunk_start_rate = (starts + k*prior) / (appearances + k)` — a shrinkage toward
a positional prior that collapses to the prior at GW1 (where every player has at
most one appearance) and converges on realised behaviour by ~GW6. `k` and the
prior are `[assumption: no empirical basis; k=4 chosen so the realised rate
dominates from about GW5]`, exposed as constructor arguments.

**Minutes, and the three probabilities the components need:**

```
p60   = p_start * P(>=60 | start)
p1    = p_start + (1 - p_start) * p_sub_appearance
xmins = p_start * E[mins | start] + (1 - p_start) * p_sub_appearance * E[mins | sub]
```

`E[mins | start]` is taken from realised `minutes / starts` where `starts > 0`,
shrunk to a prior; `E[mins | sub]` and `p_sub_appearance` are flat heuristics.
All flagged.

**`p60` is not decoration.** Clean sheet points require 60+ minutes played, so
`xp_clean_sheet` is gated on `p60`, not on `p1` or `xmins`. Getting this wrong
over-rates rotation-risk defenders — silently, and by exactly the amount that
matters.

**The unfixable gap, restated so it is not mistaken for an oversight:** 458 of
610 players are `status = 'a'` with a null `chance_of_playing_next_round`, and
nothing in the official API distinguishes a nailed starter from a fourth-choice
full-back. The survey's evidence (OpenFPL rivals the commercial benchmark on
categorical tags alone, losing only on Zeros/Blanks, which is precisely where
proprietary start/rest data helps) says this is tolerable, not that it is solved.

---

## Decision 5 — the eight components

Each is one function, independently testable, priced from `game_config.scoring`.
`sc = snapshot.raw["game_config"]["scoring"]`; `pos` is `singular_name_short`.

| Component | Model |
|---|---|
| `xp_appearance` | `(p1 - p60) * sc["short_play"] + p60 * sc["long_play"]` |
| `xp_attack` | `(xg90 * attack_scale * xmins/90) * sc["goals_scored"][pos]` + `(xa90 * attack_scale * xmins/90) * sc["assists"]`, where `attack_scale = xg_for / league_mean` |
| `xp_clean_sheet` | `p60 * exp(-xg_against) * sc["clean_sheets"][pos]` |
| `xp_conceded` | `sum_k P(k; xg_against) * floor(k/2) * sc["goals_conceded"][pos] * (xmins/90)`, k over 0..12 |
| `xp_saves` | GK only: `E[floor(saves/3)] * sc["saves"]` over Poisson(`saves_per_90 * xmins/90 * xg_against/league_mean`) |
| `xp_defcon` | `P(N >= threshold) * sc["defensive_contribution"][pos]`, `N ~ Poisson(dc_per_90 * xmins/90)`, thresholds **10 DEF / 12 MID / 12 FWD / ineligible GKP** (Verification above) |
| `xp_bonus` | `shrunk_bonus_per_90 * xmins/90 * sc["bonus"]` |
| `xp_cards` | `(yellow_per_90 * sc["yellow_cards"] + red_per_90 * sc["red_cards"]) * xmins/90` |

Then `xp_total = sum(components)`, summed over every fixture the player's team
has in that event. `fixtures = 0` yields all-zero components, not a silent
single-fixture assumption.

**`xp_defcon` takes no fixture adjustment** — projections.md Decision 5, and the
reason `Projection` carries components at all. The payoff is a capped step
function, so a hard fixture that *raises* a defender's clearance volume moves
this term opposite to every other term. Multiplying an aggregate that silently
contains it gets the sign wrong for exactly the players it matters most to.
`[The Poisson assumption for defensive-action counts is the weakest link here:
real CBIT counts are almost certainly over-dispersed, which biases P(hit) near
the threshold. Negative binomial is the v2 refinement; one distributional
assumption is kept for now rather than two.]`

**`xp_bonus` uses realised bonus, shrunk** — chosen because the API has no BPS
constants to build a structural model from (Verification above), and inventing a
third set of coefficients on top of the fixture bands and the minutes priors
would be worse than using the one signal that actually exists.
`[This term is backward-looking and does not respond to fixture: a premium with
an easy run gets no bonus uplift. That is a known, stated bias, and it is the
term the harness's per-component error breakdown should be watched on first.]`

---

## Decision 6 — the evaluation harness

`domain/evaluation.py` plus a thin `fpl plan evaluate --event N` command. The
scope boundary in projections.md was "domain layer only, no CLI"; it is broken
deliberately and narrowly here, because a benchmark that needs a throwaway
script to run is a benchmark that does not get run.

**The third endpoint, same chain as the other two.**
`OfficialFplApi.event_live(event)` -> `LiveEvent` / `LiveElement` models -> cache
-> `SnapshotService.load_event_live(event)` with the same stale-fallback
contract.

**Caching rule — only cache what is final.** A live payload for an in-flight
gameweek is provisional (bonus is not awarded until the round finishes;
`points_modification` exists for retrospective adjustment). So: write
`~/.fpl-cli/events/{n}-live.json` only when the bootstrap's `events[n]` reports
`finished and data_checked`; otherwise fetch fresh every time and do not persist.
A cached finished gameweek is immutable and never needs refetching.

**What it reports**, for each of `ComponentProjection`, `NaiveProjection`,
`OfficialEpProjection` and the flat `points_per_game` baseline:

- RMSE and MAE per player-gameweek — over all players, and over `stats.played`
  only. Both, because RMSE over all 610 is dominated by zeros and flatters
  everything equally.
- **Spearman rank correlation**, average-rank tie handling, implemented directly
  (~15 lines). `[Deliberately not adding scipy for one statistic — it would be
  the largest dependency in the project, for a function that fits on a screen.]`
- Return-category breakdown per the survey's OpenFPL yardstick: Zeros (0),
  Blanks (1-2), Tickers (3-4), Haulers (5+). This is what tells you *where* the
  model is weak; models are typically weakest on Zeros, which is a minutes
  problem.
- **Per-component error**, from `explain`: map each identifier to our component
  (`minutes`->`xp_appearance`, `goals_scored`/`assists`->`xp_attack`,
  `clean_sheets`->`xp_clean_sheet`, `goals_conceded`->`xp_conceded`,
  `saves`->`xp_saves`, `defensive_contribution`->`xp_defcon`,
  `bonus`->`xp_bonus`, cards->`xp_cards`) and report signed mean error per term.
  This is what turns "v1 lost to the baseline" into "the bonus term is biased low
  by 0.4/player".

**Leakage, and the snapshot archive.** A projection computed from today's
snapshot already contains the gameweek being scored — `expected_goals_per_90`,
`form` and `points_per_game` all include it. So `fpl sync` gains one behaviour:
after a successful refresh it also writes
`~/.fpl-cli/archive/bootstrap-{YYYY-MM-DD}.json` (idempotent within a day).
`fpl plan evaluate --event N` then selects the newest archived snapshot whose
mtime precedes event N's `deadline_time`, and projects from that. If none exists
it falls back to the current snapshot and prints a prominent warning that the
result is optimistic and not a backtest.

This makes leak-free evaluation possible from the next gameweek onward. It cannot
retrofit GW1 — nothing was archived before that deadline.

---

## Files

**New**

- `src/fpl_cli/domain/strength.py` — `MatchRates`, `TeamRatesModel`,
  `BandedTeamRates`. Its own module rather than living inside `projections.py`,
  so that v2's Dixon-Coles fit lands beside it and imports the Protocol without a
  circular dependency. Costs one extra module; makes the injectable seam
  physically obvious.
- `src/fpl_cli/domain/projections.py` — `Projection`, `ProjectionModel`, the
  minutes model, the eight component functions, three models.
- `src/fpl_cli/domain/evaluation.py` — metrics, return categories, per-component
  error, archive selection.
- `tests/test_projections.py`, `tests/test_strength.py`,
  `tests/test_evaluation.py`, `tests/test_fixtures_cache.py`.

**Modified**

- `src/fpl_cli/api/models.py` — `Fixture`; `LiveEvent`/`LiveElement`/
  `ExplainEntry`; and **extend `Player`** with the projection inputs it currently
  drops (`models.py:9-26` has `extra="ignore"`, so `expected_goals_per_90`,
  `expected_assists_per_90`, `defensive_contribution_per_90`, `saves_per_90`,
  `starts`, `starts_per_90`, `minutes`, `bonus`, `points_per_game`, `ep_next`,
  `yellow_cards`, `red_cards` are all silently discarded today).
- `src/fpl_cli/api/official.py` — `fixtures()`, `event_live(event)`.
- `src/fpl_cli/api/snapshots.py` — `FixturesResult`, `load_fixtures()`,
  `refresh_fixtures()`, `load_event_live()`.
- `src/fpl_cli/storage/cache.py` — generalise to a path-keyed JSON document
  cache; `SnapshotCache` keeps its existing path and public shape.
- `src/fpl_cli/cli.py` — `fpl plan evaluate`; `sync` refreshes fixtures and
  writes the dated archive.
- `src/fpl_cli/presentation.py` — an evaluation results table, matching the
  existing `simulation_table` style.
- `tests/conftest.py` — extend the synthetic players with the new fields; add
  `fixtures_payload` and `live_event_payload` fixtures.
- [follow-ups.md](follow-ups.md) — re-point FU-4 at per-event live payloads; file
  the new follow-ups below.

---

## Sequencing — five branches, not one

`CLAUDE.md`: one concern per branch, never bundle a refactor with a feature. This
plan spans a storage refactor, two endpoints, a domain module and a CLI surface.
Each lands separately, in dependency order:

1. `task/json-document-cache` — generalise `storage/cache.py`. Pure refactor, no
   behaviour change, existing tests must pass untouched.
2. `task/fixtures-endpoint` — `Fixture` model, `fixtures()`, cache, service
   method, stale-fallback tests, `sync` refreshing both.
3. `task/projections-v1` — `strength.py` + `projections.py` + tests. The bulk.
4. `task/event-live-endpoint` — third endpoint, models, conditional caching.
5. `task/projection-evaluation` — `evaluation.py`, `fpl plan evaluate`, and the
   `sync` archive write.

Steps 4 and 5 could reasonably merge (the endpoint has no other consumer), but
they are kept apart so the endpoint's stale-cache contract is tested on its own
terms. Only step 3 is blocked on anything non-trivial — it needs 1 and 2.

---

## Verification

**Unit — synthetic data, mocked API, no live calls** (`CLAUDE.md`):

- `xp_total` equals the sum of its eight components, for every model. The
  invariant that lets the optimiser read one number while each term evolves.
- Blank gameweek: a fixture with `event = null` yields `fixtures = 0` and
  `xp_total = 0.0`.
- Double gameweek: `fixtures = 2` and roughly double the single-fixture total.
- Every `status` maps to its multiplier, **including `status = 'd'` with a null
  chance -> 0.75**. All 24 current `d` players carry a non-null chance, so this
  branch has zero live instances — it needs a synthetic fixture, or a test built
  from real data would pass without ever executing it.
- `xp_clean_sheet` is gated on `p60`, not `p1`: a player with `p_start = 1.0` but
  `P(>=60 | start) = 0.5` gets half the clean-sheet points, not all of them.
- The rates strategy is applied to `xp_attack`, `xp_clean_sheet`, `xp_conceded`
  and `xp_saves`, and **not** to `xp_defcon` — asserted directly, since getting
  it wrong is silent and only mis-ranks defensive midfielders.
- `xp_defcon` is 0.0 for goalkeepers at every difficulty, and responds to the
  threshold boundary (a DEF at 9 vs 10 expected actions; a MID at 11 vs 12).
- `xp_conceded` uses the pmf sum, not `xg_against / 2`: asserted against a
  hand-computed Poisson for a known `xg_against`.
- Swapping `BandedTeamRates` for a stub `TeamRatesModel` returning fixed rates
  changes the output and touches no decomposition code — the v2 seam, tested.
- `NaiveProjection` / `OfficialEpProjection` emit the same shape with unmodelled
  components at 0.0 and a populated `assumptions`.
- `OfficialEpProjection` raises for any event other than the next one.
- Fixtures cache falls back on a failed live fetch, matching the contract in
  `tests/test_stale_cache.py`; a stale fixtures store still projects, and its
  staleness appears in `Projection.assumptions`.
- Difficulty bands read from `teams[]`, so a stale bootstrap still projects.
- `event_live` is cached only when the event is `finished and data_checked`.

**End-to-end, against real data:**

```bash
pip install -e ".[dev]" && pytest -q
fpl sync                      # refreshes both stores, writes the dated archive
fpl plan evaluate --event 1   # warns: no pre-deadline archive for GW1, optimistic
```

**The benchmark, not a merge gate.** `ComponentProjection` must beat the flat
`points_per_game` baseline on RMSE and Spearman once a few gameweeks exist. GW1
can only be evaluated with leakage; the first honest run is the first gameweek
whose deadline post-dates an archived snapshot. Until then v1 is unproven however
principled its structure. **If it loses, the survey's rule applies: fix the
minutes model before adding model complexity** — and the per-component error
breakdown says which term to look at first.

---

## Trade-offs taken, with the reasoning

- **Rates over a scalar multiplier** (Decision 1). Costs a slightly larger v1
  strategy interface; buys a v2 that changes one class. A scalar would force v2
  to rewrite three components.
- **`home_advantage = 1.0` in `BandedTeamRates`** (Decision 1). Departs from the
  survey, which treats gamma as additive information. Against a venue-resolved
  difficulty band it double-counts. Scoped to this strategy only: v2's
  Dixon-Coles fits gamma from raw scorelines, where it is required rather than
  redundant.
- **Separate cache files, independent staleness** (Decision 3). Costs a possible
  invisible inconsistency between a fresh bootstrap and a stale fixtures list;
  buys per-resource availability, which is what `CLAUDE.md` actually requires.
  Mitigated by disclosure in `assumptions`, not by bundling.
- **Poisson everywhere** — clean sheets, goals conceded, saves and defensive
  contributions all use it. One distributional assumption is easier to defend and
  to replace than four. It is wrong in a known direction for DefCon counts.
- **Bonus from realised per-90, shrunk** (Decision 5). The alternatives were zero
  (honest, but systematically under-rates the premiums the optimiser must
  separate) and an invented monotone function of xGI (responds to fixture, but
  adds a third set of baseless coefficients). Uses the only signal that exists.
- **Evaluation gets a CLI command** (Decision 6), breaking projections.md's
  domain-only scope. A benchmark that needs a throwaway script does not get run.
- **`fpl sync` archives a dated snapshot** (Decision 6). Outside the projections
  module, and the only way a leak-free comparison is ever possible.
- **No scipy** (Decision 6). Spearman is written out rather than pulling in a
  large dependency for one function.
- **`strength.py` as a separate module** — one more file at v1 than strictly
  needed, in exchange for a clean import graph when Dixon-Coles lands.

---

## Assumptions

- `[Not derivable]` `BAND_MULTIPLIERS` — heuristic, no published empirical basis.
- `[Not derivable]` `LEAGUE_MEAN_GOALS = 1.45` — until finished fixtures exist,
  at which point it is measured.
- `[Not derivable]` `0.75` for a doubtful player with no stated chance.
- `[Not derivable]` The minutes-model priors: shrinkage `k`, `E[mins | start]`
  prior, `E[mins | sub]`, `p_sub_appearance`.
- `[Not in the API]` DefCon thresholds. DEF 10 and MID 12 are now **measured**
  (Verification); FWD 12 remains assumed by parity with MID.
- `[Modelling choice]` Poisson for goals, saves and defensive-action counts.
- `[No data source]` A structural bonus model — confirmed absent from the API.
- `[Unmeasured]` That `ComponentProjection` beats the baseline at all. No
  leak-free evaluation is possible until the first gameweek following an archived
  snapshot.

---

## Follow-ups to file in [follow-ups.md](follow-ups.md)

- **FWD defensive-contribution threshold is unconfirmed** — no forward exceeded 8
  actions in GW1. Re-run the `explain` bracket once one reaches 12.
- **Negative binomial for defensive-action counts** — Poisson under-disperses;
  this biases P(hit) near the threshold.
- **Dixon-Coles `TeamRatesModel`** — the v2 slot-in. alpha/beta/gamma/rho fitted
  on fixtures-endpoint results, xi=0.00186/day, tau low-score correction; bands
  as the pre-GW4/5 cold start and as a promoted-team prior. Replaces one class.
  **gamma is fitted, not inherited from v1's 1.0** — scorelines carry no venue
  adjustment, so gamma is the only route by which venue enters the likelihood.
- **Measure `league_mean_goals` from finished fixtures** — removes an invented
  constant as soon as results accrue.
- **Derive the band multipliers empirically** from a historical archive; no
  published mapping exists to copy.
- **Bonus has no structural model** — confirmed unbuildable from the API. Revisit
  only if the per-component breakdown shows it dominating the error.
- **FU-4 (SQLite) re-pointed** at per-event live payloads, where the file count
  grows with the season.
- **Minutes model from `element-summary` history** — refines the appearance term
  once per-match minutes matter more than the categorical tags.

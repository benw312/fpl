"""The fixture-strength strategy seam (docs/plans/projections-v1.md Decision 1).

`TeamRatesModel` returns expected goals for and against, not a scalar fixture
multiplier — a scalar cannot express a clean sheet. `BandedTeamRates` is the v1
implementation. `FittedTeamRates` is component/1.3's, specified in
docs/plans/model-1.3.md §3.1–3.2 and fixed there by FU-73 before any figure for it
existed; it slots in beside the banded model without touching
domain/projections.py.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fpl_cli.api.models import BootstrapSnapshot, Fixture

# [heuristic, no published empirical basis — see projections-survey.md §5]
BAND_MULTIPLIERS: dict[int, float] = {1: 1.15, 2: 1.15, 3: 1.05, 4: 0.90, 5: 0.85}
# [assumption: ~2.9 goals/game long-run PL average, not derivable from the API
# pre-results. FU: measure from finished fixtures once they exist.]
LEAGUE_MEAN_GOALS = 1.45


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
    def name(self) -> str: ...


class BandedTeamRates:
    """v1: `xg_for`/`xg_against` from the opponent's difficulty band.

    Bands come from `teams[].strength_overall_home/_away`, not the fixtures
    endpoint's `team_h_difficulty`/`team_a_difficulty` (which they equal
    exactly — Finding 5), so a stale fixtures file still yields correct
    difficulty ratings; only the schedule (who plays whom, and when) needs
    fixtures to be fresh.
    """

    def __init__(
        self,
        snapshot: BootstrapSnapshot,
        *,
        band_multipliers: dict[int, float] | None = None,
        league_mean_goals: float = LEAGUE_MEAN_GOALS,
        # Stays 1.0 for this strategy specifically: the band lookup below is
        # already venue-resolved (home and away difficulty are looked up from
        # different fields), so multiplying by a home boost on top would
        # apply venue twice. Kept as a constructor argument, not removed, so
        # the assumption is visible and falsifiable against the data.
        home_advantage: float = 1.0,
    ) -> None:
        self._clubs = snapshot.clubs
        self._band_multipliers = band_multipliers or BAND_MULTIPLIERS
        self._league_mean_goals = league_mean_goals
        self._home_advantage = home_advantage

    @property
    def league_mean_goals(self) -> float:
        return self._league_mean_goals

    @property
    def name(self) -> str:
        return "banded"

    def rates(self, *, team: int, opponent: int, home: bool) -> MatchRates:
        opponent_club = self._clubs[opponent]
        difficulty = opponent_club.strength_overall_home if home else opponent_club.strength_overall_away
        band = self._band_multipliers[difficulty]
        xg_for = self._league_mean_goals * band * (self._home_advantage if home else 1.0)
        xg_against = self._league_mean_goals / band
        return MatchRates(xg_for=xg_for, xg_against=xg_against)


# Numerical, not modelling: the fixed point below converges geometrically and
# these only bound the loop. Neither is a constant FU-50 §3 is about — no value
# of either moves a rating by more than the tolerance.
_FIT_TOLERANCE = 1e-12
_FIT_MAX_ITERATIONS = 1000


@dataclass(frozen=True)
class TeamStrengthFit:
    """What the fit found on one capture, kept so a run can report it.

    `attack` and `defence` are multipliers on the league mean with prior mean 1.
    `defence` is a *conceding* multiplier: above 1 concedes more than average.
    `prior_goals_*` is the gamma prior's strength in pseudo-goals; divide by
    `mu` for pseudo-games. `fallback` is None when the fit was used, otherwise
    the reason `BandedTeamRates` was used instead (model-1.3.md §3.2).
    """

    matches: int
    target_event: int | None
    mu: float
    home_factor: float
    away_factor: float
    excess_attack: float
    excess_defence: float
    prior_goals_attack: float | None
    prior_goals_defence: float | None
    attack: dict[int, float]
    defence: dict[int, float]
    fallback: str | None


def _results_before(fixtures: Sequence[Fixture], target_event: int | None) -> list[Fixture]:
    """Finished fixtures with a score, strictly before the target event.

    The event bound is not belt-and-braces. `plan evaluate` projects from an
    archived pre-deadline snapshot but loads the *current* fixtures, whose
    `finished` flags include the gameweek being scored and everything after
    it. Without the bound, a backtest would fit on its own answers.
    """
    return [
        fixture
        for fixture in fixtures
        if fixture.finished
        and fixture.event is not None
        and (target_event is None or fixture.event < target_event)
        and fixture.team_h_score is not None
        and fixture.team_a_score is not None
    ]


def fit_team_strength(snapshot: BootstrapSnapshot, fixtures: Sequence[Fixture]) -> TeamStrengthFit:
    """model-1.3.md §3.2, as fixed by FU-73. Every number is fitted from match
    results or set by the fallback rule; nothing here is chosen."""
    target_event = next((gameweek.id for gameweek in snapshot.events if gameweek.is_next), None)
    results = _results_before(fixtures, target_event)
    teams = sorted(snapshot.clubs)
    flat = {team: 1.0 for team in teams}

    def fallen_back(reason: str, **measured: float) -> TeamStrengthFit:
        return TeamStrengthFit(
            matches=len(results),
            target_event=target_event,
            mu=measured.get("mu", 0.0),
            home_factor=measured.get("home_factor", 1.0),
            away_factor=measured.get("away_factor", 1.0),
            excess_attack=measured.get("excess_attack", 0.0),
            excess_defence=measured.get("excess_defence", 0.0),
            prior_goals_attack=None,
            prior_goals_defence=None,
            attack=dict(flat),
            defence=dict(flat),
            fallback=reason,
        )

    if not results:
        return fallen_back("no finished fixtures before the target event")

    home_goals = [fixture.team_h_score for fixture in results]
    away_goals = [fixture.team_a_score for fixture in results]
    mu = (sum(home_goals) + sum(away_goals)) / (2 * len(results))
    if mu <= 0:
        return fallen_back("no goals scored in any finished fixture")
    home_factor = statistics.fmean(home_goals) / mu
    away_factor = statistics.fmean(away_goals) / mu

    scored: dict[int, list[int]] = {}
    conceded: dict[int, list[int]] = {}
    for fixture in results:
        scored.setdefault(fixture.team_h, []).append(fixture.team_h_score)
        scored.setdefault(fixture.team_a, []).append(fixture.team_a_score)
        conceded.setdefault(fixture.team_h, []).append(fixture.team_a_score)
        conceded.setdefault(fixture.team_a, []).append(fixture.team_h_score)

    # Method of moments on raw per-team means, no opponent adjustment — the
    # simplification §3.2 states. Sampling variance of a mean of n Poisson(mu)
    # counts is mu/n; what the spread exceeds that by is between-team variance.
    games_per_team = statistics.fmean(len(goals) for goals in scored.values())
    sampling = mu / games_per_team

    def excess(per_team: dict[int, list[int]]) -> float:
        if len(per_team) < 2:
            return 0.0
        return statistics.pvariance([statistics.fmean(goals) for goals in per_team.values()]) - sampling

    excess_attack = excess(scored)
    excess_defence = excess(conceded)
    measured = {
        "mu": mu,
        "home_factor": home_factor,
        "away_factor": away_factor,
        "excess_attack": excess_attack,
        "excess_defence": excess_defence,
    }
    if excess_attack <= 0 or excess_defence <= 0:
        return fallen_back("between-team excess variance <= 0: no spread to estimate", **measured)

    # Gamma(a, a) prior on each multiplier: mean 1, variance 1/a. Matching that
    # variance to excess/mu^2 gives a = mu^2/excess, in pseudo-goals.
    prior_attack = mu * mu / excess_attack
    prior_defence = mu * mu / excess_defence

    attack = dict(flat)
    defence = dict(flat)
    for _ in range(_FIT_MAX_ITERATIONS):
        exposure_attack = {team: 0.0 for team in teams}
        exposure_defence = {team: 0.0 for team in teams}
        observed_attack = {team: 0.0 for team in teams}
        observed_defence = {team: 0.0 for team in teams}
        for fixture in results:
            h, a = fixture.team_h, fixture.team_a
            # Expected goals under the team's own multiplier = 1.
            exposure_attack[h] += mu * home_factor * defence[a]
            exposure_attack[a] += mu * away_factor * defence[h]
            exposure_defence[h] += mu * away_factor * attack[a]
            exposure_defence[a] += mu * home_factor * attack[h]
            observed_attack[h] += fixture.team_h_score
            observed_attack[a] += fixture.team_a_score
            observed_defence[h] += fixture.team_a_score
            observed_defence[a] += fixture.team_h_score
        new_attack = {
            team: (observed_attack[team] + prior_attack) / (exposure_attack[team] + prior_attack) for team in teams
        }
        new_defence = {
            team: (observed_defence[team] + prior_defence) / (exposure_defence[team] + prior_defence)
            for team in teams
        }
        change = max(
            max(abs(new_attack[team] - attack[team]) for team in teams),
            max(abs(new_defence[team] - defence[team]) for team in teams),
        )
        attack, defence = new_attack, new_defence
        if change < _FIT_TOLERANCE:
            break

    return TeamStrengthFit(
        matches=len(results),
        target_event=target_event,
        mu=mu,
        home_factor=home_factor,
        away_factor=away_factor,
        excess_attack=excess_attack,
        excess_defence=excess_defence,
        prior_goals_attack=prior_attack,
        prior_goals_defence=prior_defence,
        attack=attack,
        defence=defence,
        fallback=None,
    )


class FittedTeamRates:
    """component/1.3: team attack and conceding multipliers fitted from results.

    Which rating feeds which term is model-1.3.md §3.1, fixed by FU-73:

    - `xg_for` uses the **opponent's defence only**. It reaches a player only
      as `attack_scale = xg_for / league_mean_goals`, multiplying the player's
      own xG and xA rates, which already carry the team's attack — so the team's own
      attack rating would count it twice.
    - `xg_against` uses the **opponent's attack and the team's own defence**.
      No player-level clean-sheet rate exists, so nothing else carries the
      latter. `BandedTeamRates` omits it, which gives every defender facing a
      given band the same clean-sheet chance.

    When the fit falls back (§3.2), every call is delegated to the banded
    model unchanged, and `fit.fallback` says why.
    """

    def __init__(self, fit: TeamStrengthFit, fallback: BandedTeamRates) -> None:
        self.fit = fit
        self._fallback = fallback

    @property
    def league_mean_goals(self) -> float:
        return self._fallback.league_mean_goals if self.fit.fallback else self.fit.mu

    @property
    def name(self) -> str:
        return "fitted"

    def rates(self, *, team: int, opponent: int, home: bool) -> MatchRates:
        if self.fit.fallback:
            return self._fallback.rates(team=team, opponent=opponent, home=home)
        fit = self.fit
        venue_for = fit.home_factor if home else fit.away_factor
        venue_against = fit.away_factor if home else fit.home_factor
        return MatchRates(
            xg_for=fit.mu * fit.defence.get(opponent, 1.0) * venue_for,
            xg_against=fit.mu * fit.attack.get(opponent, 1.0) * fit.defence.get(team, 1.0) * venue_against,
        )

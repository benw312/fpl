"""The fixture-strength strategy seam (docs/plans/projections-v1.md Decision 1).

`TeamRatesModel` returns expected goals for and against, not a scalar fixture
multiplier — a scalar cannot express a clean sheet. `BandedTeamRates` is the v1
implementation; v2's Dixon-Coles model slots in beside it without touching
domain/projections.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fpl_cli.api.models import BootstrapSnapshot

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

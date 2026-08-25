from __future__ import annotations

from datetime import UTC, datetime

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings
from fpl_cli.domain.strength import BAND_MULTIPLIERS, BandedTeamRates, MatchRates


def _snapshot(clubs: list[Club]) -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=[],
        teams=clubs,
        element_types=[],
        elements=[],
        game_settings=GameSettings(),
        raw={},
        fetched_at=datetime.now(UTC),
        season="test",
    )


def test_rates_home_uses_opponents_strength_overall_home() -> None:
    """Finding 5: team_h_difficulty == teams[team_a].strength_overall_home."""
    us = Club(id=1, name="Us", strength_overall_home=3, strength_overall_away=3)
    opponent = Club(id=2, name="Them", strength_overall_home=5, strength_overall_away=2)
    model = BandedTeamRates(_snapshot([us, opponent]))

    rates = model.rates(team=1, opponent=2, home=True)

    band = BAND_MULTIPLIERS[5]
    assert rates.xg_for == model.league_mean_goals * band
    assert rates.xg_against == model.league_mean_goals / band


def test_rates_away_uses_opponents_strength_overall_away() -> None:
    us = Club(id=1, name="Us", strength_overall_home=3, strength_overall_away=3)
    opponent = Club(id=2, name="Them", strength_overall_home=5, strength_overall_away=2)
    model = BandedTeamRates(_snapshot([us, opponent]))

    rates = model.rates(team=1, opponent=2, home=False)

    band = BAND_MULTIPLIERS[2]
    assert rates.xg_for == model.league_mean_goals * band
    assert rates.xg_against == model.league_mean_goals / band


def test_easier_band_raises_xg_for_and_lowers_xg_against() -> None:
    us = Club(id=1, name="Us")
    weak_opponent = Club(id=2, name="Weak", strength_overall_home=1)
    strong_opponent = Club(id=3, name="Strong", strength_overall_home=5)
    model = BandedTeamRates(_snapshot([us, weak_opponent, strong_opponent]))

    against_weak = model.rates(team=1, opponent=2, home=True)
    against_strong = model.rates(team=1, opponent=3, home=True)

    assert against_weak.xg_for > against_strong.xg_for
    assert against_weak.xg_against < against_strong.xg_against


def test_home_advantage_default_is_neutral() -> None:
    """[home_advantage stays 1.0 for this strategy — the band lookup is already
    venue-resolved, so a default of 1.0 must leave home and away xg_for
    symmetric around the same opponent-difficulty pairing.]
    """
    us = Club(id=1, name="Us")
    opponent = Club(id=2, name="Them", strength_overall_home=3, strength_overall_away=3)
    model = BandedTeamRates(_snapshot([us, opponent]))

    home = model.rates(team=1, opponent=2, home=True)
    away = model.rates(team=1, opponent=2, home=False)

    assert home.xg_for == away.xg_for


def test_home_advantage_multiplies_only_the_home_leg() -> None:
    us = Club(id=1, name="Us")
    opponent = Club(id=2, name="Them", strength_overall_home=3, strength_overall_away=3)
    model = BandedTeamRates(_snapshot([us, opponent]), home_advantage=1.2)

    home = model.rates(team=1, opponent=2, home=True)
    away = model.rates(team=1, opponent=2, home=False)

    assert home.xg_for == away.xg_for * 1.2


def test_league_mean_goals_and_name_are_exposed() -> None:
    model = BandedTeamRates(_snapshot([Club(id=1, name="Us")]), league_mean_goals=1.6)

    assert model.league_mean_goals == 1.6
    assert model.name == "banded"


def test_custom_band_multipliers_override_the_default() -> None:
    us = Club(id=1, name="Us")
    opponent = Club(id=2, name="Them", strength_overall_home=3)
    model = BandedTeamRates(_snapshot([us, opponent]), band_multipliers={3: 2.0})

    rates = model.rates(team=1, opponent=2, home=True)

    assert rates.xg_for == model.league_mean_goals * 2.0


def test_match_rates_is_a_frozen_value_object() -> None:
    rates = MatchRates(xg_for=1.5, xg_against=1.2)

    assert rates.xg_for == 1.5
    assert rates.xg_against == 1.2

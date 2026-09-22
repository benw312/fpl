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


# --- FittedTeamRates: component/1.3's strength model (model-1.3.md §3.1–3.2) ---
#
# Every test names the mutation it must fail against, and was run against that
# mutation before being kept.

from fpl_cli.api.models import Fixture, Gameweek  # noqa: E402
from fpl_cli.domain.strength import FittedTeamRates, fit_team_strength  # noqa: E402


def _league(next_event: int = 4) -> BootstrapSnapshot:
    clubs = [Club(id=team, name=f"Club {team}", strength_overall_home=3, strength_overall_away=3) for team in (1, 2, 3, 4)]
    snapshot = _snapshot(clubs)
    snapshot.events.extend(
        Gameweek(id=event, name=f"Gameweek {event}", is_next=event == next_event) for event in range(1, 7)
    )
    return snapshot


def _result(fixture_id: int, event: int, home: int, away: int, home_goals: int, away_goals: int, *, finished: bool = True) -> Fixture:
    return Fixture(
        id=fixture_id,
        event=event,
        team_h=home,
        team_a=away,
        team_h_score=home_goals,
        team_a_score=away_goals,
        finished=finished,
    )


# Club 1 scores freely; club 4 leaks. Three rounds, every club plays three.
_RESULTS = [
    _result(1, 1, 1, 2, 4, 0),
    _result(2, 1, 3, 4, 3, 1),
    _result(3, 2, 1, 3, 3, 0),
    _result(4, 2, 2, 4, 2, 2),
    _result(5, 3, 4, 1, 0, 5),
    _result(6, 3, 2, 3, 0, 1),
]


def _banded(snapshot: BootstrapSnapshot) -> BandedTeamRates:
    return BandedTeamRates(snapshot)


def test_the_synthetic_league_is_identifiable() -> None:
    """Precondition for the tests below: both excesses are positive, so the fit
    is used rather than the fallback. Without this, every later test could be
    passing against `BandedTeamRates`.

    Mutation: returning `fallen_back(...)` unconditionally fails here.
    """
    fit = fit_team_strength(_league(), _RESULTS)
    assert fit.fallback is None
    assert fit.excess_attack > 0 and fit.excess_defence > 0
    assert fit.matches == 6
    assert fit.mu == 21 / 12


def test_results_at_or_after_the_target_event_are_not_fitted() -> None:
    """`plan evaluate` loads current fixtures beside an archived snapshot, so
    the gameweek being scored arrives marked finished. It must not be fitted.

    Mutation: dropping `fixture.event < target_event` from `_results_before`.
    """
    leaked = [*_RESULTS, _result(7, 4, 2, 1, 9, 0), _result(8, 5, 3, 2, 7, 0)]
    assert fit_team_strength(_league(), leaked) == fit_team_strength(_league(), _RESULTS)


def test_unfinished_fixtures_are_not_fitted() -> None:
    """A live score is not a result.

    Mutation: dropping `fixture.finished` from `_results_before`.
    """
    in_play = [*_RESULTS, _result(9, 3, 1, 4, 0, 6, finished=False)]
    assert fit_team_strength(_league(), in_play) == fit_team_strength(_league(), _RESULTS)


def test_ratings_are_the_gamma_poisson_posterior_under_section_3_2s_prior() -> None:
    """§3.2 fixed the rule in writing: prior strength `mu^2 / excess` pseudo-goals,
    and each rating is `(observed + prior) / (exposure + prior)` at the fixed
    point. Checked for club 1's attack and club 4's defence from the returned
    ratings, so the test does not re-implement the loop.

    A bound on the raw ratio was tried first and **survived** the no-shrinkage
    mutation — the opponent adjustment alone kept club 1 under it — so the
    identity is asserted instead.

    Mutation: setting `prior_attack = 0.0` (no shrinkage) fails the rule.
    """
    fit = fit_team_strength(_league(), _RESULTS)
    assert fit.prior_goals_attack == fit.mu * fit.mu / fit.excess_attack
    assert fit.prior_goals_defence == fit.mu * fit.mu / fit.excess_defence

    def venue(home: bool) -> float:
        return fit.home_factor if home else fit.away_factor

    club1 = [(f, f.team_h == 1) for f in _RESULTS if 1 in (f.team_h, f.team_a)]
    scored = sum(f.team_h_score if home else f.team_a_score for f, home in club1)
    exposure = sum(fit.mu * venue(home) * fit.defence[f.team_a if home else f.team_h] for f, home in club1)
    prior = fit.prior_goals_attack
    assert abs(fit.attack[1] - (scored + prior) / (exposure + prior)) < 1e-9

    club4 = [(f, f.team_h == 4) for f in _RESULTS if 4 in (f.team_h, f.team_a)]
    conceded = sum(f.team_a_score if home else f.team_h_score for f, home in club4)
    exposure = sum(fit.mu * venue(not home) * fit.attack[f.team_a if home else f.team_h] for f, home in club4)
    prior = fit.prior_goals_defence
    assert abs(fit.defence[4] - (conceded + prior) / (exposure + prior)) < 1e-9
    assert 1.0 < fit.attack[1] and 1.0 < fit.defence[4]


def test_own_defence_moves_xg_against_and_never_xg_for() -> None:
    """model-1.3.md §3.1. Against the same opponent at the same venue, a leaky
    side and a tight side get the same `xg_for` — player xG already carries own
    attack — and different `xg_against`.

    Mutations: using `fit.attack[team]` or `fit.defence[team]` in `xg_for`;
    dropping `fit.defence.get(team, 1.0)` from `xg_against`.
    """
    model = FittedTeamRates(fit_team_strength(_league(), _RESULTS), _banded(_league()))
    leaky = model.rates(team=4, opponent=2, home=True)
    tight = model.rates(team=3, opponent=2, home=True)
    assert leaky.xg_for == tight.xg_for
    assert leaky.xg_against > tight.xg_against


def test_venue_factors_are_fitted_and_applied_the_right_way_round() -> None:
    """Home sides score 15 here and away sides 9, so the home factor must exceed
    the away factor, and home `xg_for` must exceed away `xg_for` for the same
    pairing.

    Mutation: swapping `venue_for`'s two branches.
    """
    home_heavy = [
        _result(1, 1, 1, 2, 4, 0),
        _result(2, 1, 3, 4, 3, 1),
        _result(3, 2, 1, 3, 3, 0),
        _result(4, 2, 2, 4, 3, 2),
        _result(5, 3, 4, 1, 2, 5),
        _result(6, 3, 2, 3, 0, 1),
    ]
    fit = fit_team_strength(_league(), home_heavy)
    assert fit.fallback is None
    assert fit.home_factor > 1.0 > fit.away_factor
    model = FittedTeamRates(fit, _banded(_league()))
    assert model.rates(team=1, opponent=2, home=True).xg_for > model.rates(team=1, opponent=2, home=False).xg_for


def test_no_spread_between_teams_falls_back_to_the_banded_model_exactly() -> None:
    """§3.2's fallback, fixed before any figure: when the between-team excess is
    <= 0 the estimator has nothing to estimate, and the variant is the banded
    model for that capture — every rate, and the league mean.

    Mutation: removing the `excess <= 0` fallback (the fit then runs with a
    negative prior and returns ratings that are not the banded rates).
    """
    level = [_result(index, 1 + index // 3, home, away, 1, 1) for index, (home, away) in enumerate(
        [(1, 2), (3, 4), (1, 3), (2, 4), (4, 1), (2, 3)]
    )]
    snapshot = _league()
    model = FittedTeamRates(fit_team_strength(snapshot, level), _banded(snapshot))
    assert model.fit.fallback is not None
    banded = _banded(snapshot)
    assert model.league_mean_goals == banded.league_mean_goals
    for team, opponent, home in [(1, 2, True), (4, 3, False)]:
        assert model.rates(team=team, opponent=opponent, home=home) == banded.rates(
            team=team, opponent=opponent, home=home
        )


def test_no_results_at_all_falls_back() -> None:
    """GW1 has nothing to fit.

    Mutation: removing the `if not results` guard raises ZeroDivisionError.
    """
    assert fit_team_strength(_league(next_event=1), _RESULTS).fallback is not None


# --- The season prior: component/1.4 (model-1.4.md §2) ---------------------------

from fpl_cli.domain.strength import SeasonPrior, fit_results  # noqa: E402

_TEAMS = (1, 2, 3, 4)
_VENUE = (1.11, 0.89)
# Club 1 was strong last season, club 4 weak; 2 and 3 average.
_PRIOR_RATINGS = {1: (1.3, 0.8), 2: (1.0, 1.0), 3: (1.0, 1.0), 4: (0.7, 1.25)}


def test_change_a_fixes_the_venue_factors_at_the_prior_seasons() -> None:
    """model-1.4.md §2.1: last season's factors replace this season's fit.

    Mutation: ignoring `prior.venue` and refitting from the current results.
    """
    fit = fit_results(_RESULTS, _TEAMS, prior=SeasonPrior(mu=1.4, venue=_VENUE))
    assert (fit.home_factor, fit.away_factor) == _VENUE
    assert fit.fallback is None


def test_a_flat_prior_with_the_fitted_venue_reproduces_13_exactly() -> None:
    """Change B at r_i = 1 everywhere is 1.3's shrinkage, so 1.3 cannot have
    been altered by generalising the fit. (The synthetic schedule is balanced,
    so the spread about mu equals the variance of the team means.)

    Mutation: taking `mu` from `prior.mu` rather than fitting it from the current
    results (the prior's `mu` is 0.0 here precisely so that mutation shows).
    """
    plain = fit_results(_RESULTS, _TEAMS)
    venue = (plain.home_factor, plain.away_factor)
    flat = fit_results(_RESULTS, _TEAMS, prior=SeasonPrior(mu=0.0, venue=venue, ratings={t: (1.0, 1.0) for t in _TEAMS}))
    for team in _TEAMS:
        assert abs(flat.attack[team] - plain.attack[team]) < 1e-12
        assert abs(flat.defence[team] - plain.defence[team]) < 1e-12


def test_ratings_are_the_gamma_posterior_about_each_clubs_prior_mean() -> None:
    """model-1.4.md §2.2: rating = (observed + r²/σ²) / (exposure + r/σ²).
    Checked for club 1's attack (prior 1.3) from the returned ratings.

    Mutations: dropping `** 2` on the prior mean in the numerator; dropping the
    prior mean from the denominator (both shrink toward 1, not toward r).
    """
    prior = SeasonPrior(mu=1.4, venue=_VENUE, ratings=_PRIOR_RATINGS)
    fit = fit_results(_RESULTS, _TEAMS, prior=prior)
    assert fit.prior_unchanged is None, fit
    inverse_s2 = fit.prior_goals_attack
    games = [(f, f.team_h == 1) for f in _RESULTS if 1 in (f.team_h, f.team_a)]
    observed = sum(f.team_h_score if home else f.team_a_score for f, home in games)
    exposure = sum(
        fit.mu * (_VENUE[0] if home else _VENUE[1]) * fit.defence[f.team_a if home else f.team_h] for f, home in games
    )
    r = _PRIOR_RATINGS[1][0]
    assert abs(fit.attack[1] - (observed + inverse_s2 * r * r) / (exposure + inverse_s2 * r)) < 1e-9


def test_the_excess_is_measured_about_each_clubs_prior_expectation() -> None:
    """model-1.4.md §2.2: excess = mean[(m_i − μ·r_i)²] − μ/n, not the variance
    of the team means.

    Mutation: using `pvariance` of the team means when a prior is given.
    """
    prior = SeasonPrior(mu=1.4, venue=_VENUE, ratings=_PRIOR_RATINGS)
    fit = fit_results(_RESULTS, _TEAMS, prior=prior)
    scored: dict[int, list[int]] = {}
    for f in _RESULTS:
        scored.setdefault(f.team_h, []).append(f.team_h_score)
        scored.setdefault(f.team_a, []).append(f.team_a_score)
    expected = sum((sum(g) / len(g) - fit.mu * _PRIOR_RATINGS[t][0]) ** 2 for t, g in scored.items()) / 4 - fit.mu / 3
    assert abs(fit.excess_attack - expected) < 1e-12


def test_no_spread_beyond_the_prior_uses_the_prior_unchanged_not_the_band() -> None:
    """model-1.4.md §2.2's fallback differs from 1.3's: the prior stands, and
    `fallback` (which means "banded") stays None.

    Mutation: returning 1.3's banded fallback when a prior is given.
    """
    level = [_result(i + 1, 1 + i // 2, h, a, 1, 1) for i, (h, a) in enumerate([(1, 2), (3, 4), (1, 3), (2, 4), (4, 1), (2, 3)])]
    prior = SeasonPrior(mu=1.4, venue=_VENUE, ratings={t: (1.0, 1.0) for t in _TEAMS})
    fit = fit_results(level, _TEAMS, prior=prior)
    assert fit.fallback is None and fit.prior_unchanged is not None
    assert fit.attack == {t: 1.0 for t in _TEAMS}
    snapshot = _league()
    model = FittedTeamRates(fit, _banded(snapshot))
    assert model.rates(team=1, opponent=2, home=True) != _banded(snapshot).rates(team=1, opponent=2, home=True)


def test_no_results_with_a_prior_uses_the_prior_seasons_mean() -> None:
    """GW1: nothing to fit a league mean from, so last season's stands in.

    Mutation: leaving `mu` at 0.0 on the prior path.
    """
    prior = SeasonPrior(mu=1.375, venue=_VENUE, ratings=_PRIOR_RATINGS)
    fit = fit_results([], _TEAMS, prior=prior)
    assert fit.mu == 1.375
    assert fit.attack[1] == 1.3 and fit.defence[4] == 1.25

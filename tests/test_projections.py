from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, Fixture, GameSettings, Gameweek, Player, Position
from fpl_cli.domain.projections import (
    ComponentProjection,
    DEFCON_THRESHOLDS,
    MinutesModelConfig,
    NaiveProjection,
    OfficialEpProjection,
    _availability,
    _component_points_for_fixture,
    _minutes_probabilities,
    _poisson_pmf,
    _MinutesProbabilities,
    _ShrunkRates,
)
from fpl_cli.domain.strength import BandedTeamRates, MatchRates, TeamRatesModel

def _unshrunk(player: Player) -> _ShrunkRates:
    """The rates a player carries with no shrinkage applied.

    These tests predate rate shrinkage and are about the *component pricing*,
    not about the rates reaching it, so they keep feeding the raw values the
    model used to read off the Player directly. `component/1.0` behaves this
    way by registration, so this is not a fiction for the tests' benefit.
    """
    minutes = player.minutes
    per_90 = (lambda count: count / (minutes / 90) if minutes > 0 else 0.0)
    return _ShrunkRates(
        xg=player.expected_goals_per_90,
        xa=player.expected_assists_per_90,
        dc=player.defensive_contribution_per_90,
        saves=player.saves_per_90,
        yellow=per_90(player.yellow_cards),
        red=per_90(player.red_cards),
        # The one rate that was already shrunk before FU-47, toward zero.
        bonus=per_90(player.bonus) * minutes / (minutes + 450.0) if minutes > 0 else 0.0,
    )


SCORING = {
    "short_play": 1,
    "long_play": 2,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    "bonus": 1,
    "yellow_cards": -1,
    "red_cards": -3,
}

_POSITIONS = [
    Position(id=1, singular_name_short="GKP", squad_select=2, squad_min_play=1, squad_max_play=1),
    Position(id=2, singular_name_short="DEF", squad_select=5, squad_min_play=3, squad_max_play=5),
    Position(id=3, singular_name_short="MID", squad_select=5, squad_min_play=2, squad_max_play=5),
    Position(id=4, singular_name_short="FWD", squad_select=3, squad_min_play=1, squad_max_play=3),
]


def _club(club_id: int, difficulty: int = 3) -> Club:
    return Club(id=club_id, name=f"Club {club_id}", strength_overall_home=difficulty, strength_overall_away=difficulty)


def _events(*, finished_count: int = 1, next_id: int = 2) -> list[Gameweek]:
    events = [Gameweek(id=i, name=f"GW{i}", finished=True) for i in range(1, finished_count + 1)]
    events.append(Gameweek(id=next_id, name=f"GW{next_id}", is_next=True))
    return events


def _snapshot(
    players: list[Player],
    *,
    clubs: list[Club] | None = None,
    events: list[Gameweek] | None = None,
) -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=events if events is not None else _events(),
        teams=clubs or [_club(1), _club(2), _club(3), _club(4)],
        element_types=_POSITIONS,
        elements=players,
        game_settings=GameSettings(),
        raw={"game_config": {"scoring": SCORING}},
        fetched_at=datetime.now(UTC),
        season="test",
    )


def _player(
    player_id: int,
    *,
    position: int = 3,
    team: int = 1,
    status: str = "a",
    chance: int | None = None,
    starts: int = 5,
    minutes: int = 450,
    xg90: float = 0.0,
    xa90: float = 0.0,
    dc90: float = 0.0,
    saves90: float = 0.0,
    bonus: int = 0,
    yellow: int = 0,
    red: int = 0,
    points_per_game: str = "3.0",
    ep_next: str | None = "3.0",
) -> Player:
    return Player(
        id=player_id,
        web_name=f"P{player_id}",
        team=team,
        element_type=position,
        now_cost=50,
        status=status,
        chance_of_playing_next_round=chance,
        starts=starts,
        minutes=minutes,
        expected_goals_per_90=xg90,
        expected_assists_per_90=xa90,
        defensive_contribution_per_90=dc90,
        saves_per_90=saves90,
        bonus=bonus,
        yellow_cards=yellow,
        red_cards=red,
        points_per_game=points_per_game,
        ep_next=ep_next,
    )


def _fixture(fixture_id: int, *, event: int | None, team_h: int, team_a: int) -> Fixture:
    return Fixture(id=fixture_id, event=event, team_h=team_h, team_a=team_a)


class _StubRates:
    """A TeamRatesModel stub, for the v2-seam test — no BandedTeamRates involved."""

    def __init__(self, xg_for: float = 1.5, xg_against: float = 1.0, league_mean_goals: float = 1.4) -> None:
        self._rates = MatchRates(xg_for=xg_for, xg_against=xg_against)
        self._league_mean_goals = league_mean_goals

    def rates(self, *, team: int, opponent: int, home: bool) -> MatchRates:
        return self._rates

    @property
    def league_mean_goals(self) -> float:
        return self._league_mean_goals

    @property
    def name(self) -> str:
        return "stub"


# --- xp_total invariant ------------------------------------------------------


def test_component_projection_xp_total_equals_sum_of_components() -> None:
    player = _player(1, xg90=0.5, xa90=0.2, dc90=8.0, bonus=10, yellow=2)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot))

    projection = model.project([1], [2])[(1, 2)]

    components = (
        projection.xp_appearance
        + projection.xp_attack
        + projection.xp_clean_sheet
        + projection.xp_conceded
        + projection.xp_saves
        + projection.xp_defcon
        + projection.xp_bonus
        + projection.xp_cards
    )
    assert projection.xp_total == pytest.approx(components)


def test_naive_projection_xp_total_equals_sum_of_components() -> None:
    player = _player(1)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = NaiveProjection(snapshot, fixtures)

    projection = model.project([1], [2])[(1, 2)]

    assert projection.xp_total == pytest.approx(projection.xp_appearance)
    assert projection.xp_attack == 0.0
    assert projection.xp_clean_sheet == 0.0


def test_official_ep_projection_xp_total_equals_sum_of_components() -> None:
    player = _player(1, ep_next="5.0")
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = OfficialEpProjection(snapshot, fixtures)

    projection = model.project([1], [2])[(1, 2)]

    assert projection.xp_total == pytest.approx(5.0)
    assert projection.xp_appearance == pytest.approx(5.0)


# --- Blanks and doubles ------------------------------------------------------


def test_blank_gameweek_yields_zero_fixtures_and_zero_total() -> None:
    player = _player(1, xg90=0.5)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=None, team_h=1, team_a=2)]  # postponed
    model = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot))

    projection = model.project([1], [2])[(1, 2)]

    assert projection.fixtures == 0
    assert projection.xp_total == 0.0


def test_double_gameweek_roughly_doubles_the_single_fixture_total() -> None:
    player = _player(1, xg90=0.5, xa90=0.1, dc90=6.0)
    snapshot = _snapshot([player], clubs=[_club(1), _club(2), _club(3)])
    single_fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    double_fixtures = [
        _fixture(1, event=2, team_h=1, team_a=2),
        _fixture(2, event=2, team_h=3, team_a=1),
    ]

    single = ComponentProjection(snapshot, single_fixtures, BandedTeamRates(snapshot)).project([1], [2])[(1, 2)]
    double = ComponentProjection(snapshot, double_fixtures, BandedTeamRates(snapshot)).project([1], [2])[(1, 2)]

    assert double.fixtures == 2
    assert double.xp_total == pytest.approx(2 * single.xp_total, rel=0.2)
    assert double.xp_total > single.xp_total


# --- Availability multiplier --------------------------------------------------


@pytest.mark.parametrize(
    ("status", "chance", "expected"),
    [
        ("a", None, 1.0),
        ("d", None, 0.75),
        ("d", 50, 0.5),
        ("i", None, 0.0),
        ("s", None, 0.0),
        ("u", None, 0.0),
        ("a", 75, 0.75),
    ],
)
def test_availability_multiplier(status: str, chance: int | None, expected: float) -> None:
    player = _player(1, status=status, chance=chance)

    assert _availability(player, MinutesModelConfig()) == pytest.approx(expected)


# --- p60 gating ---------------------------------------------------------------


def test_clean_sheet_is_gated_on_p60_not_p1() -> None:
    """A player nailed to start but hooked at half-time gets half the clean-sheet points."""
    full_minutes = _MinutesProbabilities(p_start=1.0, p60=1.0, p1=1.0, xmins=90.0)
    half_minutes = _MinutesProbabilities(p_start=1.0, p60=0.5, p1=1.0, xmins=90.0)
    rates = MatchRates(xg_for=1.4, xg_against=1.0)

    full = _component_points_for_fixture(
        "DEF", SCORING, full_minutes, rates, _unshrunk(_player(1, position=2)), 1.4, DEFCON_THRESHOLDS
    )
    half = _component_points_for_fixture(
        "DEF", SCORING, half_minutes, rates, _unshrunk(_player(1, position=2)), 1.4, DEFCON_THRESHOLDS
    )

    xp_clean_sheet_index = 2
    assert half[xp_clean_sheet_index] == pytest.approx(full[xp_clean_sheet_index] / 2)


# --- Rates strategy applied to some terms, not xp_defcon ---------------------


def test_rates_strategy_touches_attack_clean_sheet_conceded_and_saves_not_defcon() -> None:
    minutes = _MinutesProbabilities(p_start=1.0, p60=1.0, p1=1.0, xmins=90.0)
    player = _player(1, position=1, xg90=0.1, xa90=0.05, dc90=10.0, saves90=3.0)  # GKP
    easy = MatchRates(xg_for=2.0, xg_against=0.5)
    hard = MatchRates(xg_for=0.5, xg_against=2.0)

    against_easy = _component_points_for_fixture("GKP", SCORING, minutes, easy, _unshrunk(player), 1.4, DEFCON_THRESHOLDS)
    against_hard = _component_points_for_fixture("GKP", SCORING, minutes, hard, _unshrunk(player), 1.4, DEFCON_THRESHOLDS)

    xp_attack, xp_clean_sheet, xp_conceded, xp_saves, xp_defcon = 1, 2, 3, 4, 5
    assert against_easy[xp_attack] != against_hard[xp_attack]
    assert against_easy[xp_clean_sheet] != against_hard[xp_clean_sheet]
    assert against_easy[xp_conceded] != against_hard[xp_conceded]
    assert against_easy[xp_saves] != against_hard[xp_saves]
    assert against_easy[xp_defcon] == against_hard[xp_defcon]


# --- xp_defcon: GKP ineligible, threshold boundary ----------------------------


def test_defcon_is_zero_for_goalkeepers_at_every_difficulty() -> None:
    minutes = _MinutesProbabilities(p_start=1.0, p60=1.0, p1=1.0, xmins=90.0)
    player = _player(1, position=1, dc90=20.0)  # GKP, huge dc rate
    for rates in (MatchRates(xg_for=2.0, xg_against=0.5), MatchRates(xg_for=0.5, xg_against=2.0)):
        components = _component_points_for_fixture("GKP", SCORING, minutes, rates, _unshrunk(player), 1.4, DEFCON_THRESHOLDS)
        assert components[5] == 0.0


def test_defcon_responds_to_the_threshold_boundary_for_def_and_mid() -> None:
    minutes = _MinutesProbabilities(p_start=1.0, p60=1.0, p1=1.0, xmins=90.0)
    rates = MatchRates(xg_for=1.4, xg_against=1.0)

    def_below = _player(1, position=2, dc90=9.0)
    def_at = _player(1, position=2, dc90=10.0)
    mid_below = _player(1, position=3, dc90=11.0)
    mid_at = _player(1, position=3, dc90=12.0)

    def_below_xp = _component_points_for_fixture("DEF", SCORING, minutes, rates, _unshrunk(def_below), 1.4, DEFCON_THRESHOLDS)[5]
    def_at_xp = _component_points_for_fixture("DEF", SCORING, minutes, rates, _unshrunk(def_at), 1.4, DEFCON_THRESHOLDS)[5]
    mid_below_xp = _component_points_for_fixture("MID", SCORING, minutes, rates, _unshrunk(mid_below), 1.4, DEFCON_THRESHOLDS)[5]
    mid_at_xp = _component_points_for_fixture("MID", SCORING, minutes, rates, _unshrunk(mid_at), 1.4, DEFCON_THRESHOLDS)[5]

    assert def_at_xp > def_below_xp
    assert mid_at_xp > mid_below_xp


# --- xp_conceded: pmf sum, not a linear approximation -------------------------


def test_conceded_uses_the_pmf_sum_not_a_linear_approximation() -> None:
    minutes = _MinutesProbabilities(p_start=1.0, p60=1.0, p1=1.0, xmins=90.0)
    xg_against = 1.3
    rates = MatchRates(xg_for=1.4, xg_against=xg_against)
    player = _player(1, position=2)

    xp_conceded = _component_points_for_fixture("DEF", SCORING, minutes, rates, _unshrunk(player), 1.4, DEFCON_THRESHOLDS)[3]

    expected = sum(_poisson_pmf(k, xg_against) * (k // 2) for k in range(13)) * SCORING["goals_conceded"]["DEF"]
    assert xp_conceded == pytest.approx(expected)
    # A linear approximation (xg_against / 2) would give a materially different number.
    linear_approx = (xg_against / 2) * SCORING["goals_conceded"]["DEF"]
    assert xp_conceded != pytest.approx(linear_approx, rel=0.05)


# --- The v2 seam: swapping the rates strategy changes output, not code -------


def test_swapping_the_rates_strategy_changes_output() -> None:
    player = _player(1, xg90=0.5, xa90=0.2)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]

    banded = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot)).project([1], [2])[(1, 2)]
    stubbed = ComponentProjection(snapshot, fixtures, _StubRates(xg_for=3.0, xg_against=0.2)).project([1], [2])[(1, 2)]

    assert banded.xp_total != stubbed.xp_total
    assert banded.model_version == "component/1.0+banded"
    assert stubbed.model_version == "component/1.0+stub"


# --- NaiveProjection / OfficialEpProjection: shape and assumptions ----------


def test_naive_projection_emits_same_shape_with_unmodelled_components_zero() -> None:
    player = _player(1, points_per_game="4.0")
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]

    projection = NaiveProjection(snapshot, fixtures).project([1], [2])[(1, 2)]

    assert projection.xp_total == pytest.approx(4.0)
    assert projection.xp_defcon == 0.0
    assert projection.xp_bonus == 0.0
    assert projection.assumptions


def test_official_ep_projection_emits_same_shape_with_unmodelled_components_zero() -> None:
    player = _player(1, ep_next="2.5")
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]

    projection = OfficialEpProjection(snapshot, fixtures).project([1], [2])[(1, 2)]

    assert projection.xp_total == pytest.approx(2.5)
    assert projection.xp_defcon == 0.0
    assert projection.xp_bonus == 0.0
    assert projection.assumptions


def test_official_ep_projection_raises_for_any_event_but_the_next() -> None:
    player = _player(1)
    snapshot = _snapshot([player])  # is_next=True on event 2
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = OfficialEpProjection(snapshot, fixtures)

    with pytest.raises(ValueError, match="next event"):
        model.project([1], [3])


# --- Fixtures-stale disclosure -----------------------------------------------


def test_stale_fixtures_store_still_projects_and_discloses_staleness() -> None:
    player = _player(1, xg90=0.4)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    fetched_at = datetime(2026, 1, 1, tzinfo=UTC)
    model = ComponentProjection(
        snapshot, fixtures, BandedTeamRates(snapshot), fixtures_stale=True, fixtures_fetched_at=fetched_at
    )

    projection = model.project([1], [2])[(1, 2)]

    assert projection.fixtures == 1
    assert projection.xp_total > 0.0
    assert any("stale" in note for note in projection.assumptions)
    assert fetched_at.isoformat() in projection.assumptions[0]


def test_no_staleness_note_when_fixtures_are_fresh() -> None:
    player = _player(1)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot))

    projection = model.project([1], [2])[(1, 2)]

    assert projection.assumptions == ()


# --- Minutes model shrinkage ---------------------------------------------------


def test_start_rate_collapses_to_the_prior_at_zero_appearances() -> None:
    config = MinutesModelConfig()
    player = _player(1, position=2, starts=0, minutes=0)

    probs = _minutes_probabilities(player, "DEF", appearances=0, config=config)

    assert probs.p_start == pytest.approx(config.start_priors["DEF"])


def test_start_rate_converges_toward_realised_behaviour_as_appearances_grow() -> None:
    """A player who has started every game so far pulls p_start up as evidence
    accrues, away from the (lower) MID prior of 0.55 — starts <= appearances
    always, so each snapshot below reflects a player who started every game
    played to date.
    """
    config = MinutesModelConfig()

    early = _minutes_probabilities(_player(1, position=3, starts=1, minutes=90), "MID", appearances=1, config=config)
    late = _minutes_probabilities(_player(1, position=3, starts=6, minutes=540), "MID", appearances=6, config=config)

    assert late.p_start > early.p_start


# --- FU-11: substitute term gated by availability -----------------------------


def test_unavailable_player_projects_approximately_zero() -> None:
    """Pre-fix, p1/xmins's substitute term was unconditional, so an injured
    player (p_start = 0) still projected a flat 0.35 sub-appearance chance.
    Gating that term by availability should drive p1, xmins, and therefore
    the whole projection to zero.
    """
    config = MinutesModelConfig()
    player = _player(1, position=3, status="i", starts=0, minutes=0)

    probs = _minutes_probabilities(player, "MID", appearances=10, config=config)

    assert probs.p1 == pytest.approx(0.0)
    assert probs.xmins == pytest.approx(0.0)


def test_status_i_player_projects_zero_end_to_end() -> None:
    player = _player(1, status="i", xg90=0.5, xa90=0.2, dc90=10.0, bonus=10, yellow=1)
    snapshot = _snapshot([player])
    fixtures = [_fixture(1, event=2, team_h=1, team_a=2)]
    model = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot))

    projection = model.project([1], [2])[(1, 2)]

    assert projection.xp_total == pytest.approx(0.0)
    assert projection.xmins == pytest.approx(0.0)


def test_late_season_fringe_player_stays_separated_from_ruled_out() -> None:
    """The FU-11 diagnosis: the defect wasn't a missing signal, it was
    convergence — with the substitute term ungated, a fit-but-fringe player's
    p1/xmins decayed toward the same flat 0.35-sub-appearance value an
    injured player was pinned at, as `appearances` grew and shrunk_start_rate
    collapsed toward zero for both. Gating the substitute term by
    availability keeps a fit fringe player's xmins meaningfully above zero
    late-season, while a ruled-out player's stays exactly zero regardless of
    `appearances` — restoring the discrimination an optimiser needs between
    "fringe squad player" and "ruled out injured".
    """
    config = MinutesModelConfig()
    late_season_appearances = 37

    fringe_fit = _player(1, position=3, status="a", starts=0, minutes=0)
    ruled_out = _player(2, position=3, status="i", starts=0, minutes=0)

    fringe = _minutes_probabilities(fringe_fit, "MID", appearances=late_season_appearances, config=config)
    injured = _minutes_probabilities(ruled_out, "MID", appearances=late_season_appearances, config=config)

    assert injured.p1 == pytest.approx(0.0)
    assert injured.xmins == pytest.approx(0.0)
    # Both players' p_start has decayed close to zero by this point — the
    # discrimination now has to come from the gated substitute term alone.
    assert fringe.p_start < 0.1
    assert fringe.p1 - injured.p1 > 0.3
    assert fringe.xmins - injured.xmins > 8.0

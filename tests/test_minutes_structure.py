"""minutes-model.md §8's tests for the S1-S6 minutes structure (component/1.2).

Every assertion here was demonstrated failing against a mutation of the line it
covers before being kept — the mutation is named in each test's docstring, per
§8's own requirement and the repo discipline `tests/test_variants.py` follows.

§8.12 (the archive-differencing helper) is deliberately absent: it covers
§4.3(c), which this branch does not build. Writing a test for code that does not
exist would be a test of nothing; the specification stands in the plan.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, Fixture, GameSettings, Gameweek, Player, Position
from fpl_cli.domain import variants
from fpl_cli.domain.projections import (
    ComponentProjection,
    MinutesModelConfig,
    MinutesStructureConfig,
    _as_probability,
    _availability,
    _minutes_probabilities,
    availability_for_event,
    build_start_priors,
    has_departed,
    parse_return_date,
)
from fpl_cli.domain.strength import BandedTeamRates

CAPTURED_AT = datetime(2026, 8, 28, 0, 32, 59, tzinfo=UTC)

# Deadlines chosen so that GW3 falls before 5 September and GW4 after it, which
# is §8.1's requirement. GW2 is `is_next`, so neither GW3 nor GW4 is the nearest
# gameweek and both take the horizon path — the one S3 governs.
_DEADLINES = {
    1: datetime(2026, 8, 15, 17, 30, tzinfo=UTC),
    2: datetime(2026, 8, 29, 17, 30, tzinfo=UTC),
    3: datetime(2026, 9, 1, 17, 30, tzinfo=UTC),
    4: datetime(2026, 9, 8, 17, 30, tzinfo=UTC),
    5: datetime(2026, 9, 15, 17, 30, tzinfo=UTC),
}

_SCORING = {
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


def _snapshot(*players: Player, next_event: int = 2) -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=[
            Gameweek(
                id=identifier,
                name=f"Gameweek {identifier}",
                deadline_time=deadline,
                is_next=identifier == next_event,
                finished=identifier <= 1,
            )
            for identifier, deadline in _DEADLINES.items()
        ],
        teams=[Club(id=index, name=f"Club {index}") for index in range(1, 5)],
        element_types=_POSITIONS,
        elements=list(players),
        game_settings=GameSettings(),
        raw={"game_config": {"scoring": _SCORING}},
        fetched_at=CAPTURED_AT,
        season="2026_27",
    )


def _fixtures(*events: int) -> list[Fixture]:
    return [Fixture(id=event * 10, event=event, team_h=1, team_a=2) for event in events]


def _player(identifier: int = 1, **overrides) -> Player:
    base = {
        "id": identifier,
        "web_name": f"P{identifier}",
        "team": 1,
        "element_type": 3,
        "now_cost": 50,
        "selected_by_percent": "10.0",
    }
    return Player(**{**base, **overrides})


def _model(snapshot: BootstrapSnapshot, fixtures: list[Fixture], structure: MinutesStructureConfig):
    return ComponentProjection(
        snapshot, fixtures, BandedTeamRates(snapshot), minutes_structure=structure
    )


_S3_STRUCTURE = MinutesStructureConfig(
    horizon_availability="per_event", news_return_dates=True, this_round_source="this_then_next"
)


# --- §8.1 Availability is evaluated per gameweek ------------------------------


def test_availability_is_evaluated_per_gameweek() -> None:
    """§8.1. A dated returner is zero before the date and non-zero after it,
    within one projection call.

    Mutation: hoisting `_minutes_probabilities` back out of the event loop in
    `ComponentProjection.project` — computing it once per player and reusing it
    for every event, which is what the pre-1.2 model did — makes both gameweeks
    equal and fails the second assertion.
    """
    player = _player(status="i", chance_of_playing_next_round=0, news="Knee injury - Expected back 5 Sep")
    snapshot = _snapshot(player)
    model = _model(snapshot, _fixtures(3, 4), _S3_STRUCTURE)
    projections = model.project([1], [3, 4])

    assert projections[(1, 3)].p_start == 0.0
    assert projections[(1, 4)].p_start > 0.0


def test_the_pre_12_model_applies_one_scalar_to_the_whole_horizon() -> None:
    """The defect §3 measured, pinned so it cannot come back unnoticed.

    Mutation: making `horizon_availability` inert — ignoring the config and
    always taking the per-event path — makes these two differ and fails.
    """
    player = _player(status="i", chance_of_playing_next_round=0, news="Knee injury - Expected back 5 Sep")
    snapshot = _snapshot(player)
    model = _model(snapshot, _fixtures(3, 4), MinutesStructureConfig())
    projections = model.project([1], [3, 4])

    assert projections[(1, 3)].p_start == projections[(1, 4)].p_start == 0.0


# --- §8.2 `scalar` mode reproduces today byte-for-byte ------------------------


def test_scalar_mode_reproduces_today_field_for_field() -> None:
    """§8.2, the `legacy_rate_config()` precedent: the new structure must contain
    the old behaviour exactly, or no comparison across the change is valid.

    The population deliberately spans every branch the structure can change —
    a departed player, a dated returner, a `this_round`/`next_round` disagreement,
    a doubtful player and an ordinary one — so a default flipped to a new
    behaviour has something to move.

    Mutation: any default in `MinutesStructureConfig` flipped to its non-identity
    value (verified by hand for all six of `horizon_availability`,
    `this_round_source`, `news_return_dates`, `departed_policy`,
    `start_prior_source` and `start_evidence`) fails on the first differing row.
    """
    players = [
        _player(1, status="a", starts=1, minutes=90),
        _player(2, status="u", news="Has joined Paris Saint-Germain permanently", chance_of_playing_next_round=0),
        _player(3, status="i", chance_of_playing_next_round=0, news="Knee injury - Expected back 5 Sep"),
        _player(4, status="a", chance_of_playing_this_round=0, chance_of_playing_next_round=100),
        _player(5, status="d", chance_of_playing_next_round=75, element_type=2),
        _player(6, status="a", starts=0, selected_by_percent="45.0", element_type=4),
    ]
    snapshot = _snapshot(*players)
    fixtures = _fixtures(2, 3, 4, 5)
    identifiers = [p.id for p in players]
    events = [2, 3, 4, 5]

    explicit = _model(snapshot, fixtures, MinutesStructureConfig()).project(identifiers, events)
    implicit = ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot)).project(identifiers, events)

    assert explicit == implicit
    assert set(explicit) == {(pid, event) for pid in identifiers for event in events}


def test_component_12_differs_from_11_price_only_in_the_minutes_structure() -> None:
    """1.2 is 1.1-price's rates plus the minutes work, and nothing else. If it
    also moved a rate, no difference measured between them would be attributable.

    Mutation: giving `component/1.2` a different `rates` or `defcon_thresholds`
    fails here.
    """
    price = variants.get("component/1.1-price")
    twelve = variants.get("component/1.2")

    assert twelve.rates == price.rates
    assert twelve.minutes == price.minutes
    assert twelve.defcon_thresholds == price.defcon_thresholds
    assert twelve.strength == price.strength
    assert price.structure.is_identity
    assert not twelve.structure.is_identity


def test_component_12_leaves_s6b_and_fu51s_ramp_at_the_identity() -> None:
    """Both need a constant the plan declines to choose, so 1.2 sets neither.

    minutes-model.md §9 refuses to pick S6(b)'s functional form; FU-51 states
    `return_ramp_events = 0` reproduces S3 without its ramp. Turning either on
    here would be tuning on one gameweek, which FU-50 §3 forbids.

    Mutation: setting `start_evidence='minutes_weighted'` or
    `return_ramp_events=1` on the registered variant fails.
    """
    structure = variants.get("component/1.2").structure
    assert structure.start_evidence == "count"
    assert structure.return_ramp_events == 0
    # And the knobs exist, so a later variant can hold a value and be compared.
    assert replace(structure, start_evidence="minutes_weighted").as_dict()["partial_start_weight"] == 1.0
    assert replace(structure, return_ramp_events=1).as_dict()["return_ramp_minutes"] == 45.0


# --- §8.3 `chance_of_playing_this_round` is for the nearest gameweek only -----


def test_this_round_is_used_for_the_nearest_gameweek_only() -> None:
    """§8.3, the Christie/Fofana shape, which exists on the pinned capture:
    `this_round=0`, `next_round=100`, `status='a'`.

    Mutation: reading `next_round` for both gameweeks fails the first assertion;
    reading `this_round` for both fails the second.
    """
    player = _player(status="a", chance_of_playing_this_round=0, chance_of_playing_next_round=100)
    snapshot = _snapshot(player, next_event=3)
    model = _model(snapshot, _fixtures(3, 4), MinutesStructureConfig(this_round_source="this_then_next"))
    projections = model.project([1], [3, 4])

    assert projections[(1, 3)].p_start == 0.0
    assert projections[(1, 4)].p_start > 0.0


def test_a_missing_this_round_falls_back_to_next_round() -> None:
    """49 players differ between the two fields on the pinned capture, and one of
    them — Dennis — has `this_round=None` against `next_round=0`. A null must
    fall through, not read as zero.

    Mutation: `player.chance_of_playing_this_round or 0` instead of an
    `is not None` check zeroes every player whose `this_round` is null, which is
    most of the payload, and fails here.
    """
    player = _player(status="a", chance_of_playing_this_round=None, chance_of_playing_next_round=100)
    availability = availability_for_event(
        player,
        MinutesModelConfig(),
        MinutesStructureConfig(this_round_source="this_then_next"),
        event=3,
        nearest_event=3,
    )
    assert availability.value == 1.0
    assert availability.source == "chance_next_round"


# --- §8.4 / §8.5 The return-date parser ---------------------------------------


@pytest.mark.parametrize(
    "news",
    [
        "",
        "Knee injury - Unknown return date",
        "Expected back 31 Feb",
        "Expected back tomorrow",
        "Expected back 5",
        "Has joined Real Madrid",
    ],
)
def test_a_malformed_or_absent_return_date_neither_raises_nor_zeroes(news: str) -> None:
    """§8.4. The player falls back to the ordinary status/chance path.

    Mutation: an unguarded `datetime.strptime` raises on "Expected back 31 Feb";
    returning a date rather than None on a parse failure zeroes an available
    player and fails the value assertion.
    """
    player = _player(status="a", news=news)
    availability = availability_for_event(
        player, MinutesModelConfig(), _S3_STRUCTURE, event=4, nearest_event=2,
        deadline=_DEADLINES[4], captured_at=CAPTURED_AT,
    )
    assert availability.value == 1.0
    assert availability.source == "status_available"


def test_the_return_date_parser_is_anchored_to_the_templated_shape() -> None:
    """§8.5. The phrase is required; a date-like substring in another context is
    not a return date.

    Mutation: dropping "expected back" from the pattern and matching a bare
    `\\d{1,2} \\w{3}` makes the transfer-news case parse and fails.
    """
    assert parse_return_date("Knee injury - Expected back 5 Sep", CAPTURED_AT) == date(2026, 9, 5)
    assert parse_return_date("Joined on 5 Sep from Ajax", CAPTURED_AT) is None
    assert parse_return_date("Transfer completed 14 Aug - awaiting registration", CAPTURED_AT) is None


def test_the_return_date_parser_resolves_the_year_across_the_boundary() -> None:
    """§8.5's year-boundary case: a December capture reading "Expected back
    5 Jan" must resolve to the following year.

    And the converse, which the naive fix breaks: a date that has just passed
    must stay in the current year rather than being thrown a year forward, which
    would zero the player for a whole season.

    Mutation: `%d %b` parsing alone defaults to year 1900 and fails the first;
    appending the capture's own year unconditionally fails the December case;
    rolling forward whenever the candidate precedes the capture fails the third.
    """
    december = datetime(2026, 12, 20, tzinfo=UTC)
    assert parse_return_date("Expected back 5 Jan", december) == date(2027, 1, 5)
    assert parse_return_date("Expected back 28 Dec", december) == date(2026, 12, 28)
    assert parse_return_date("Expected back 5 Sep", datetime(2026, 9, 10, tzinfo=UTC)) == date(2026, 9, 5)


def test_a_dated_returner_is_zero_before_the_date_and_available_on_it() -> None:
    """The boundary itself: on the date is available, the day before is not.

    Mutation: `<=` instead of `<` in the deadline comparison zeroes the player
    in the gameweek he returns and fails the second assertion.
    """
    player = _player(status="i", chance_of_playing_next_round=0, news="Knee injury - Expected back 1 Sep")
    before = availability_for_event(
        player, MinutesModelConfig(), _S3_STRUCTURE, event=2, nearest_event=1,
        deadline=datetime(2026, 8, 31, 17, 30, tzinfo=UTC), captured_at=CAPTURED_AT,
    )
    on_the_day = availability_for_event(
        player, MinutesModelConfig(), _S3_STRUCTURE, event=3, nearest_event=1,
        deadline=datetime(2026, 9, 1, 17, 30, tzinfo=UTC), captured_at=CAPTURED_AT,
    )
    assert (before.value, before.source) == (0.0, "news_return_pending")
    assert (on_the_day.value, on_the_day.source) == (1.0, "news_return_reached")


# --- §8.6 / §8.7 Ownership-conditioned priors ---------------------------------


def _ownership_snapshot() -> BootstrapSnapshot:
    """Two ownership bands of very different sizes within one position.

    Band 0 (<1% owned): ten players, one start between them.
    Band 3 (>15% owned): two players, two starts.
    """
    players = [
        _player(index, element_type=3, selected_by_percent="0.5", starts=1 if index == 1 else 0)
        for index in range(1, 11)
    ]
    players += [_player(index, element_type=3, selected_by_percent="30.0", starts=1) for index in (11, 12)]
    return _snapshot(*players)


def test_ownership_priors_are_pooled_by_exposure_not_averaged() -> None:
    """§8.6, the direct analogue of rate-shrinkage.md §8.6.

    The prior must be total starts over total appearances, and not the mean of
    per-player rates.

    **Where the two coincide, and why the discriminating case is the one below.**
    `_appearances` is a snapshot-level count, so every player carries identical
    exposure, and with identical exposure pooling and averaging are the same
    arithmetic — `sum(s)/(n·a)` is `mean(s/a)`. The rate side had no such
    property because minutes vary per player, which is why its own §8.6 could
    use an ordinary fixture. Here the two separate only when a per-player ratio
    can exceed 1, which is exactly the double-gameweek case `_minutes_probabilities`
    already clips for: a player with three starts against two finished gameweeks
    contributes 1.5 to a pooled numerator and 1.0 to a mean of clipped ratios.

    Mutation: `mean(min(starts, appearances) / appearances)` over the players —
    the natural wrong implementation, since averaging invites clipping each term
    into [0, 1] — gives 4/24 where pooling gives 5/24, and fails.
    """
    snapshot = _ownership_snapshot()
    priors = build_start_priors(snapshot, MinutesModelConfig(), MinutesStructureConfig())

    assert priors.position["MID"] == pytest.approx(3 / 12)
    # Band 0: ten players, one start, one appearance each -> pooled 1/10,
    # shrunk toward 0.25 with shrinkage_k = 4 over exposure 10.
    assert priors.band[("MID", 0)] == pytest.approx((0.1 * 10 + 0.25 * 4) / 14)
    # Band 3: two players, two starts -> pooled 1.0, shrunk over exposure 2.
    assert priors.band[("MID", 3)] == pytest.approx((1.0 * 2 + 0.25 * 4) / 6)

    # The discriminating case: two finished gameweeks, and one player who
    # started three times in them.
    players = [_player(index, element_type=3, selected_by_percent="0.5", starts=0) for index in range(1, 12)]
    players.append(_player(12, element_type=3, selected_by_percent="0.5", starts=3))
    doubled = _snapshot(*players)
    for gameweek in doubled.events:
        gameweek.finished = gameweek.id <= 2
    pooled = build_start_priors(doubled, MinutesModelConfig(), MinutesStructureConfig())

    assert pooled.position["MID"] == pytest.approx(3 / 24)
    assert pooled.position["MID"] != pytest.approx(sum([0.0] * 11 + [1.0]) / 12)


def test_a_thin_ownership_band_cannot_become_its_own_prior() -> None:
    """§8.7, rate-shrinkage.md §8.7's guard transplanted. A band of one player
    must not shrink that player toward himself.

    Mutation: removing the shrinkage — using the band's pooled rate directly —
    makes the one-player band prior exactly 1.0, his own start rate, and fails.
    """
    players = [_player(index, element_type=3, selected_by_percent="0.5", starts=0) for index in range(1, 11)]
    players.append(_player(11, element_type=3, selected_by_percent="30.0", starts=1))
    snapshot = _snapshot(*players)
    priors = build_start_priors(snapshot, MinutesModelConfig(), MinutesStructureConfig())

    lone = priors.band[("MID", 3)]
    assert lone < 1.0
    # 1/5 of his own rate, 4/5 of the position prior — shrinkage_k = 4 over one
    # appearance of exposure.
    assert lone == pytest.approx((1.0 * 1 + priors.position["MID"] * 4) / 5)


def test_the_ownership_prior_is_only_read_when_the_source_selects_it() -> None:
    """§7's second property: rows 6 and 7 are conditional on row 5. Under
    `start_prior_source='position'` the pooled priors must not reach `p_start`.

    Mutation: `prior_for` ignoring `source` and always returning the band prior
    changes `p_start` here and fails.
    """
    snapshot = _ownership_snapshot()
    priors = build_start_priors(snapshot, MinutesModelConfig(), MinutesStructureConfig())
    player = snapshot.players_by_id[11]

    hardcoded = _minutes_probabilities(
        player, "MID", 1, MinutesModelConfig(), MinutesStructureConfig(), start_priors=priors
    )
    conditioned = _minutes_probabilities(
        player,
        "MID",
        1,
        MinutesModelConfig(),
        MinutesStructureConfig(start_prior_source="ownership_conditioned"),
        start_priors=priors,
    )
    assert hardcoded.p_start == pytest.approx((1 + 4.0 * 0.55) / 5)
    assert conditioned.p_start != hardcoded.p_start


# --- §8.8 `p_start` stays in [0, 1] -------------------------------------------


@pytest.mark.parametrize(
    "overrides, appearances",
    [
        ({"starts": 3, "minutes": 270}, 1),  # double gameweek: starts > appearances
        ({"starts": 0, "minutes": 0}, 0),  # zero appearances
        ({"starts": 1, "selected_by_percent": "0.0"}, 1),
        ({"starts": 1, "selected_by_percent": "100.0"}, 1),
        ({"starts": 1, "minutes": -30}, 1),  # negative minutes
        ({"chance_of_playing_next_round": 250}, 1),  # outside 0-100
        ({"chance_of_playing_next_round": -50}, 1),
        # Far outside, and with no starts: `p_start` is near zero, so the
        # existing clip cannot absorb the excess and it reaches `p1` and
        # `xmins` through the substitute term instead. This is the case that
        # makes `_as_probability`'s upper bound do work of its own.
        ({"chance_of_playing_next_round": 1000, "starts": 0}, 1),
    ],
)
def test_p_start_stays_in_the_unit_interval_under_absurd_input(overrides: dict, appearances: int) -> None:
    """§8.8, property-style over the cases the plan names.

    **This found a live defect.** The pre-1.2 model clipped only the upper end,
    and only on `p_start`: `chance_of_playing_next_round = -50` gave `p_start`,
    `p60`, `p1` and `xmins` all negative — minus twenty expected minutes, and an
    `xp_total` with the sign of its scoring rates flipped. `_as_probability`
    clamps at the one point a percentage enters. No capture has ever published
    such a value, so no projected number moves.

    Mutation: dropping the `min(1.0, ...)` clip on `p_start` produces
    `p_start > 1` on the double-gameweek case; dropping `_as_probability`'s
    `max(0.0, ...)` restores the negative on the last case, and its
    `min(1.0, ...)` lets `chance=250` through to a `p1` above 1.
    """
    player = _player(**overrides)
    snapshot = _snapshot(player)
    priors = build_start_priors(snapshot, MinutesModelConfig(), MinutesStructureConfig())
    for structure in (
        MinutesStructureConfig(),
        MinutesStructureConfig(start_prior_source="ownership_conditioned"),
        MinutesStructureConfig(start_evidence="minutes_weighted", partial_start_weight=0.25),
    ):
        minutes = _minutes_probabilities(
            player, "MID", appearances, MinutesModelConfig(), structure, start_priors=priors
        )
        assert 0.0 <= minutes.p_start <= 1.0
        assert 0.0 <= minutes.p60 <= 1.0
        assert 0.0 <= minutes.p1 <= 1.0
        assert minutes.xmins >= 0.0


def test_a_published_percentage_is_clamped_to_a_probability() -> None:
    """The helper's own contract, tested directly rather than only through the
    projection it protects.

    `p_start`'s `min(1.0, ...)` clip absorbs a modest over-range value on its
    own, so the emergent property in the test above cannot reach the upper
    clamp except in the extreme case parametrised there. The contract is what
    the clamp is for.

    Mutation: dropping either bound of `min(1.0, max(0.0, ...))` fails one arm.
    """
    assert _as_probability(75) == 0.75
    assert _as_probability(250) == 1.0
    assert _as_probability(-50) == 0.0


# --- §8.9 Minutes-weighted start evidence -------------------------------------


def test_minutes_weighted_start_evidence_is_monotonic() -> None:
    """§8.9. More minutes in the same number of starts cannot lower `p_start`,
    and `count` makes the two players exactly equal.

    §2.5 measured the signal this expresses: 20% / 76% / 92% start-again rates
    across <60, 60-84 and 85-90 minutes. **The registered `component/1.2` leaves
    this off** — see `test_component_12_leaves_s6b_and_fu51s_ramp_at_the_identity`.

    Mutation: inverting the weight — applying `partial_start_weight` to the full
    match rather than the partial one — fails the inequality.
    """
    full = _player(1, starts=1, minutes=90)
    partial = _player(2, starts=1, minutes=30)
    weighted = MinutesStructureConfig(start_evidence="minutes_weighted", partial_start_weight=0.25)

    def probability(player: Player, structure: MinutesStructureConfig) -> float:
        return _minutes_probabilities(player, "MID", 1, MinutesModelConfig(), structure).p_start

    assert probability(full, weighted) > probability(partial, weighted)
    assert probability(full, MinutesStructureConfig()) == probability(partial, MinutesStructureConfig())


def test_partial_start_weight_of_one_is_the_identity() -> None:
    """The default is inert by construction, which is what makes it not a
    proposed value: minutes-model.md §9 declines to choose the functional form.

    Mutation: a default below 1.0 makes `minutes_weighted` differ from `count`
    and fails.
    """
    partial = _player(2, starts=1, minutes=30)
    default = MinutesStructureConfig(start_evidence="minutes_weighted")
    assert default.partial_start_weight == 1.0
    assert _minutes_probabilities(
        partial, "MID", 1, MinutesModelConfig(), default
    ).p_start == _minutes_probabilities(
        partial, "MID", 1, MinutesModelConfig(), MinutesStructureConfig()
    ).p_start


# --- §8.10 Departed players under each policy ---------------------------------


def test_departed_players_under_each_policy() -> None:
    """§8.10. `ignore` keeps today's behaviour, `zero` zeroes and retains,
    `exclude` removes — and the population size differs between the last two,
    which is §7's row-4 versioning hazard made visible.

    Mutation: implementing `exclude` as `zero` leaves the counts equal and fails
    the final assertion.
    """
    departed = _player(1, status="u", news="Has joined Paris Saint-Germain permanently", chance_of_playing_next_round=0)
    ordinary = _player(2, status="a", starts=1, minutes=90)
    snapshot = _snapshot(departed, ordinary)
    fixtures = _fixtures(3)

    populations = {}
    for policy in ("ignore", "zero", "exclude"):
        projections = _model(
            snapshot, fixtures, MinutesStructureConfig(departed_policy=policy)
        ).project([1, 2], [3])
        populations[policy] = {pid for pid, _ in projections}
        if policy != "exclude":
            assert projections[(1, 3)].p_start == 0.0

    assert populations["ignore"] == populations["zero"] == {1, 2}
    assert populations["exclude"] == {2}
    assert len(populations["exclude"]) != len(populations["zero"])


def test_departure_needs_both_the_status_and_the_news_shape() -> None:
    """`status='u'` alone is "unavailable", not "left the league", and a loan
    *into* the league carries the news shape without the status.

    Mutation: testing only `status == 'u'` makes the injured-unavailable case
    depart and fails the second assertion.
    """
    assert has_departed(_player(status="u", news="Has joined Paris Saint-Germain permanently"))
    assert not has_departed(_player(status="u", news="Awaiting international clearance"))
    assert not has_departed(_player(status="a", news="Has joined on loan from Ajax"))


def test_component_12_uses_zero_not_exclude() -> None:
    """§7's third property: `exclude` changes `N` from 616, so any figure
    measured under it is not comparable with any figure measured before it.
    1.2 must stay comparable with 1.1-price.

    Mutation: setting `departed_policy='exclude'` on the registered variant
    fails here.
    """
    assert variants.get("component/1.2").structure.departed_policy == "zero"


# --- §8.11 The dead branches of `_availability` -------------------------------


def test_the_unreachable_availability_branches_are_exercised_directly() -> None:
    """§8.11. FU-48 established these are never taken on real data — 0 of 6,788
    player-observations across 11 captures. These are the only tests that will
    ever reach those lines, which is the argument for having them.

    They are kept rather than deleted because FU-48 also established that
    `doubtful_chance = 0.75` is well chosen (179 of 203 `status='d'`
    observations publish exactly 75%), and deleting a correct fallback because
    the primary path has not yet failed is how a system acquires a crash.

    Mutation: deleting either branch returns the wrong value — 1.0 for the
    doubtful case if it falls through to `status == 'a'`, or a raise — and fails.
    """
    doubtful = availability_for_event(
        _player(status="d", chance_of_playing_next_round=None), MinutesModelConfig(), MinutesStructureConfig()
    )
    assert (doubtful.value, doubtful.source) == (0.75, "doubtful_default")

    unknown = availability_for_event(
        _player(status="x", chance_of_playing_next_round=None), MinutesModelConfig(), MinutesStructureConfig()
    )
    assert (unknown.value, unknown.source) == (0.0, "status_unknown_default")


def test_availability_carries_its_provenance_and_its_gameweek() -> None:
    """§6.1 S5. The value alone cannot say which branch produced it or which
    gameweek it is about, and §3 measured that the second was silently dropped.

    Mutation: returning a bare float — the pre-1.2 shape — fails at the
    attribute access.
    """
    availability = availability_for_event(
        _player(status="a", chance_of_playing_next_round=50), MinutesModelConfig(), MinutesStructureConfig(), event=4
    )
    assert availability.value == 0.5
    assert availability.source == "chance_next_round"
    assert availability.event == 4


def test_the_scalar_helper_still_answers_for_the_control() -> None:
    """`NaiveProjection` reads `_availability` and must be unmoved by any of
    this: it is the control FU-50 §4 judges the component family against.

    Mutation: pointing `_availability` at a non-identity structure changes the
    departed player's value here and fails.
    """
    departed = _player(status="u", news="Has joined Ajax permanently", chance_of_playing_next_round=None)
    assert _availability(departed, MinutesModelConfig()) == 0.0
    assert _availability(_player(status="d", chance_of_playing_next_round=75), MinutesModelConfig()) == 0.75
    assert _availability(_player(status="a"), MinutesModelConfig()) == 1.0


def test_a_naive_variant_cannot_carry_a_minutes_structure() -> None:
    """The control must stay the control. Silently ignoring a structure set on a
    `naive` variant would register two names for one model.

    Mutation: dropping the guard in `variants.build` lets it construct and this
    stops raising.
    """
    snapshot = _snapshot(_player(1))
    impostor = variants.ModelVariant(
        name="naive/structured",
        family="naive",
        structure=MinutesStructureConfig(horizon_availability="per_event"),
    )
    with pytest.raises(ValueError, match="does not consume one"):
        variants.build(impostor, snapshot, _fixtures(3))


# --- The config's own guards --------------------------------------------------


def test_the_structure_config_rejects_an_unknown_enum_value() -> None:
    """A typo'd policy must not sit in a registered variant projecting today's
    numbers under a name claiming otherwise — `RateShrinkageConfig`'s precedent.

    Mutation: dropping `__post_init__` lets every one of these construct.
    """
    for field, value in (
        ("horizon_availability", "per_gameweek"),
        ("this_round_source", "this_only"),
        ("departed_policy", "drop"),
        ("start_prior_source", "ownership"),
        ("start_evidence", "minutes"),
    ):
        with pytest.raises(ValueError, match=field):
            MinutesStructureConfig(**{field: value})
    with pytest.raises(ValueError, match="ascending"):
        MinutesStructureConfig(own_band_edges=(15.0, 1.0))


def test_is_identity_ignores_values_that_cannot_be_read() -> None:
    """§7's second property: rows 6, 7, 9 and 10 are read only when the row they
    depend on is active. A config differing only in an unread value *is* today's
    model, and its digest must say so.

    Mutation: including `partial_start_weight` in `is_identity` makes the second
    assertion fail and would move six pinned digests for a difference that
    cannot reach a projected number.
    """
    assert MinutesStructureConfig().is_identity
    assert MinutesStructureConfig(partial_start_weight=0.25).is_identity
    assert MinutesStructureConfig(own_band_prior_appearances=900.0).is_identity
    assert MinutesStructureConfig(return_ramp_minutes=20.0).is_identity
    assert not MinutesStructureConfig(start_evidence="minutes_weighted").is_identity
    assert not MinutesStructureConfig(return_ramp_events=1).is_identity


def test_adding_the_structure_field_moved_no_existing_digest() -> None:
    """The reason `as_dict` omits an identity structure, asserted rather than
    only argued in a comment: six digests are cited as provenance by
    minutes-model.md and fu-53-minutes-ceiling.md (FU-40).

    Mutation: emitting `structure` unconditionally in `as_dict` changes all six
    and fails `test_a_variants_constants_cannot_diverge_from_its_version_string`
    as well as this.
    """
    for name in ("component/1.0", "component/1.1-price", "component/1.1-position", "naive/1.0"):
        assert "structure" not in variants.get(name).as_dict()
    assert "structure" in variants.get("component/1.2").as_dict()


# --- FU-51's ramp, built but not set ------------------------------------------


def test_fu51s_ramp_caps_the_returning_gameweek_only() -> None:
    """FU-51: a return date says a player is available, not that he plays ninety
    minutes. The cap applies in the gameweek he returns and not the one after.

    The cap lands on `e_mins_start`, which is FU-51's second gap made a
    decision: capping `xmins` alone would leave `p60` awarding a full
    clean-sheet probability to a player expected to last a half.

    **Not reachable in `component/1.2`**, which sets `return_ramp_events = 0`.

    Mutation: applying the cap whenever a return date exists, rather than within
    `return_ramp_events` of the return, fails the second assertion.
    """
    player = _player(status="i", chance_of_playing_next_round=0, starts=1, minutes=90,
                     news="Knee injury - Expected back 1 Sep")
    snapshot = _snapshot(player)
    ramped = replace(_S3_STRUCTURE, return_ramp_events=1, return_ramp_minutes=45.0)
    projections = _model(snapshot, _fixtures(3, 4), ramped).project([1], [3, 4])
    unramped = _model(snapshot, _fixtures(3, 4), _S3_STRUCTURE).project([1], [3, 4])

    assert projections[(1, 3)].xmins < unramped[(1, 3)].xmins
    assert projections[(1, 4)].xmins == unramped[(1, 4)].xmins
    # The cap reaches p60 too, not only xmins — the incoherence FU-51's gap names.
    assert projections[(1, 3)].xp_clean_sheet < unramped[(1, 3)].xp_clean_sheet


def test_the_ramp_is_inert_at_zero_events() -> None:
    """FU-51's own identity setting: `return_ramp_events = 0` reproduces S3
    without the ramp.

    Mutation: `<=` instead of `<` in the ramp window makes zero events still cap
    the returning gameweek and fails.
    """
    player = _player(status="i", chance_of_playing_next_round=0, starts=1, minutes=90,
                     news="Knee injury - Expected back 1 Sep")
    snapshot = _snapshot(player)
    with_ramp_off = _model(snapshot, _fixtures(3, 4), _S3_STRUCTURE).project([1], [3, 4])
    explicit_zero = _model(
        snapshot, _fixtures(3, 4), replace(_S3_STRUCTURE, return_ramp_events=0)
    ).project([1], [3, 4])
    assert with_ramp_off == explicit_zero

"""The xP decomposition (docs/plans/projections-v1.md).

Three models share one `Projection` shape: `ComponentProjection` (the eight-
term decomposition), `NaiveProjection` (the flat-rate control), and
`OfficialEpProjection` (the API's own `ep_next`, next-event only). The
optimiser reads `Projection.xp_total`; every other field is for explanation
and debugging.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from fpl_cli.api.models import BootstrapSnapshot, Fixture, Player
from fpl_cli.domain.strength import MatchRates, TeamRatesModel

# --- Minutes model (Decision 4) -------------------------------------------
# [assumption: no empirical basis for any constant in this block — see
# docs/plans/projections-v1.md Decision 4 and Assumptions.]

DEFAULT_SHRINKAGE_K = 4.0
DEFAULT_START_PRIORS: dict[str, float] = {"GKP": 0.85, "DEF": 0.65, "MID": 0.55, "FWD": 0.55}
DEFAULT_MINS_PER_START_PRIOR = 75.0
DEFAULT_P_SUB_APPEARANCE = 0.35
DEFAULT_MINS_PER_SUB = 20.0
DEFAULT_DOUBTFUL_CHANCE = 0.75
DEFAULT_BONUS_SHRINKAGE_MINUTES = 450.0

# DEF and MID measured empirically (Verification: 0 mismatches at the
# boundary). FWD assumed by parity with MID — unconfirmed, no forward
# exceeded 8 actions at GW1 (follow-up: re-check once one does). GKP is
# ineligible and deliberately absent.
DEFCON_THRESHOLDS: dict[str, int] = {"DEF": 10, "MID": 12, "FWD": 12}


@dataclass(frozen=True)
class MinutesModelConfig:
    shrinkage_k: float = DEFAULT_SHRINKAGE_K
    start_priors: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_START_PRIORS))
    mins_per_start_prior: float = DEFAULT_MINS_PER_START_PRIOR
    p_sub_appearance: float = DEFAULT_P_SUB_APPEARANCE
    mins_per_sub: float = DEFAULT_MINS_PER_SUB
    doubtful_chance: float = DEFAULT_DOUBTFUL_CHANCE
    bonus_shrinkage_minutes: float = DEFAULT_BONUS_SHRINKAGE_MINUTES


# --- Rate shrinkage (FU-47) — declared, not yet consumed ---------------------
#
# docs/plans/rate-shrinkage.md §7 enumerates the constants FU-47's variants set:
# a prior weight in minutes and a prior source per rate, plus two shared band
# parameters. The type lives here because that is where FU-47 will read it, and
# because `domain/variants.py` imports this module — putting it there would make
# the eventual consumer an import cycle.
#
# **Nothing reads it on this branch.** `variants.build` refuses to construct a
# model from a variant whose config is not the identity, rather than accepting
# the parameters and ignoring them.

PRIOR_SOURCES: tuple[str, ...] = ("position", "price_conditioned", "zero")

# The rates FU-47 shrinks. `bonus` already has shrinkage in
# `_component_points_for_fixture`; its prior source is "zero" today, which is
# the defect rather than the design (rate-shrinkage.md §1.3).
SHRINKABLE_RATES: tuple[str, ...] = ("xg", "xa", "dc", "saves", "yellow", "red", "bonus")


@dataclass(frozen=True)
class RatePrior:
    """One rate's shrinkage: how much prior weight, and toward what.

    `prior_minutes = 0.0` means no shrinkage — the rate is used as published,
    which is what every rate but `bonus` does today.
    """

    prior_minutes: float = 0.0
    prior_source: str = "position"

    def __post_init__(self) -> None:
        if self.prior_source not in PRIOR_SOURCES:
            raise ValueError(f"prior_source must be one of {PRIOR_SOURCES}; got {self.prior_source!r}.")
        if self.prior_minutes < 0:
            raise ValueError(f"prior_minutes must be non-negative; got {self.prior_minutes!r}.")


def legacy_rate_config() -> "RateShrinkageConfig":
    """The rate treatment in force before FU-47, expressed in the new form.

    Six rates unshrunk, and `bonus` shrunk toward **zero** with
    `DEFAULT_BONUS_SHRINKAGE_MINUTES` — which is exactly what
    `_component_points_for_fixture` used to do inline, and is what
    `component/1.0` must keep doing to stay byte-identical.

    Note that this is *not* `RateShrinkageConfig()`. The default config is the
    pure identity; today's model is not, because one of the seven rates was
    already shrunk. Registering that as a setting rather than leaving it in the
    function body is most of what makes the defect visible: the odd choice is
    now a named prior source, `zero`, sitting beside six that are `position`.
    """
    return RateShrinkageConfig(
        rates={"bonus": RatePrior(prior_minutes=DEFAULT_BONUS_SHRINKAGE_MINUTES, prior_source="zero")}
    )


@dataclass(frozen=True)
class RateShrinkageConfig:
    """Per-rate shrinkage, plus the two shared price-band parameters.

    The default is the identity: every rate unshrunk, which reproduces today's
    behaviour exactly. `is_identity` is what `variants.build` checks.
    """

    rates: Mapping[str, RatePrior] = field(default_factory=dict)
    band_prior_minutes: float = 900.0
    band_width: int = 5

    def __post_init__(self) -> None:
        unknown = set(self.rates) - set(SHRINKABLE_RATES)
        if unknown:
            raise ValueError(f"Unknown rate(s) {sorted(unknown)}; expected a subset of {SHRINKABLE_RATES}.")

    @property
    def is_identity(self) -> bool:
        return all(prior.prior_minutes == 0.0 for prior in self.rates.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "rates": {
                name: {
                    "prior_minutes": self.rates[name].prior_minutes,
                    "prior_source": self.rates[name].prior_source,
                }
                for name in sorted(self.rates)
            },
            "band_prior_minutes": self.band_prior_minutes,
            "band_width": self.band_width,
        }


def shrink_rate(raw: float, minutes: float, prior: float, prior_minutes: float) -> float:
    """Pull a per-90 rate toward `prior`, weighting by exposure in minutes.

    `prior_minutes` (M) is how many minutes of prior the estimate carries. The
    two algebraic forms in rate-shrinkage.md §4.1 are identical:

        raw·m/(m+M) + prior·M/(m+M)  ==  (count + prior·M/90) / ((m+M)/90)

    The convex combination is used because it needs only the published per-90
    and the minutes, which keeps `M = 0` exactly equal to the published rate —
    reconstructing a count from a two-decimal rate and dividing back would not.

    **`M = 0` returns `raw` unchanged, whatever `minutes` is.** §8.4 of the plan
    asks both for "M = 0 -> exactly raw" and for "minutes = 0 and M = 0 ->
    prior", which conflict; this resolves in favour of the first. M = 0 means no
    shrinkage was requested, so the prior is not merely unused but irrelevant,
    and component/1.0 is byte-identical only because of it.

    The unit is minutes, not matches — see §4.2. `MinutesModelConfig.shrinkage_k`
    is deliberately in *matches*, because a start is a per-match event; a rate
    per 90 is not, so it does not inherit that unit. Do not unify them.
    """
    if prior_minutes <= 0.0:
        return raw
    return (raw * minutes + prior * prior_minutes) / (minutes + prior_minutes)


# The cumulative-count field backing each shrinkable rate, and the published
# per-90 field where the API offers one. `yellow`, `red` and `bonus` have no
# published rate, which is why `_component_points_for_fixture` used to build
# theirs inline — the shape that let cards evade FU-47 entirely.
_RATE_COUNT_FIELD: dict[str, str] = {
    "xg": "expected_goals",
    "xa": "expected_assists",
    "dc": "defensive_contribution",
    "saves": "saves",
    "yellow": "yellow_cards",
    "red": "red_cards",
    "bonus": "bonus",
}
_RATE_PER_90_FIELD: dict[str, str] = {
    "xg": "expected_goals_per_90",
    "xa": "expected_assists_per_90",
    "dc": "defensive_contribution_per_90",
    "saves": "saves_per_90",
}


def _raw_rate(player: Player, rate: str) -> float:
    """The player's own per-90, before shrinkage.

    Prefers the published field where one exists: it is what the model consumed
    before this change, so preferring it is what keeps `component/1.0`
    byte-identical rather than merely close.
    """
    field = _RATE_PER_90_FIELD.get(rate)
    if field is not None:
        return float(getattr(player, field))
    if player.minutes <= 0:
        return 0.0
    return getattr(player, _RATE_COUNT_FIELD[rate]) / (player.minutes / 90)


@dataclass(frozen=True)
class RatePriors:
    """Per-rate priors pooled from a snapshot (rate-shrinkage.md §3).

    Pooled by exposure — `sum(count)/sum(minutes)*90` — and **not** the mean of
    players' per-90 ratios. The difference is the defect in miniature: dc90 for
    midfielders pools to 8.396 but averages to 11.475, the gap being one player
    with three defensive actions in one minute. Pooling weights by exposure and
    is immune to him.

    Derived from the snapshot rather than hardcoded, so the fix removes hand-set
    constants instead of adding twenty-eight of them (§7).
    """

    position: Mapping[tuple[str, str], float]
    band: Mapping[tuple[str, str, int], float]
    band_width: int

    def prior_for(self, rate: str, position: str, now_cost: int, source: str) -> float:
        if source == "zero":
            return 0.0
        position_prior = self.position.get((rate, position), 0.0)
        if source != "price_conditioned":
            return position_prior
        band = now_cost // self.band_width * self.band_width
        return self.band.get((rate, position, band), position_prior)


def build_rate_priors(snapshot: BootstrapSnapshot, config: RateShrinkageConfig) -> RatePriors:
    """Pool every rate by position, and by (position, price band) above that.

    The band level is itself shrunk toward the position rate by
    `band_prior_minutes`, so a band holding one player cannot become that
    player's own prior — the Haaland-alone-at-£15m case in §3.3, where an
    unshrunk band prior would leave him entirely unshrunk.
    """
    positions = snapshot.positions
    by_position: dict[str, list[Player]] = {}
    for player in snapshot.elements:
        position = positions[player.element_type].singular_name_short
        by_position.setdefault(position, []).append(player)

    position_priors: dict[tuple[str, str], float] = {}
    band_priors: dict[tuple[str, str, int], float] = {}
    width = config.band_width
    for position, players in by_position.items():
        played = [p for p in players if p.minutes > 0]
        total_minutes = sum(p.minutes for p in played)
        for rate, count_field in _RATE_COUNT_FIELD.items():
            if total_minutes <= 0:
                position_priors[(rate, position)] = 0.0
                continue
            pooled = sum(float(getattr(p, count_field)) for p in played) / total_minutes * 90
            position_priors[(rate, position)] = pooled
            for band in {p.now_cost // width * width for p in played}:
                in_band = [p for p in played if p.now_cost // width * width == band]
                band_minutes = sum(p.minutes for p in in_band)
                band_pooled = sum(float(getattr(p, count_field)) for p in in_band) / band_minutes * 90
                band_priors[(rate, position, band)] = shrink_rate(
                    band_pooled, band_minutes, pooled, config.band_prior_minutes
                )
    return RatePriors(position=position_priors, band=band_priors, band_width=width)


@dataclass(frozen=True)
class _ShrunkRates:
    """Every per-90 rate a component may consume, already shrunk.

    `_component_points_for_fixture` takes this instead of a `Player`, so no
    unshrunk rate can reach a component — the property
    `tests/test_rate_shrinkage.py`'s AST guard enforces. A rate added later
    either lands here or fails that test by name.
    """

    xg: float
    xa: float
    dc: float
    saves: float
    yellow: float
    red: float
    bonus: float


def shrunk_rates(
    player: Player, position: str, priors: RatePriors, config: RateShrinkageConfig
) -> _ShrunkRates:
    values: dict[str, float] = {}
    for rate in SHRINKABLE_RATES:
        setting = config.rates.get(rate, RatePrior())
        prior = priors.prior_for(rate, position, player.now_cost, setting.prior_source)
        values[rate] = shrink_rate(
            _raw_rate(player, rate), float(player.minutes), prior, setting.prior_minutes
        )
    return _ShrunkRates(**values)


@dataclass(frozen=True)
class _MinutesProbabilities:
    p_start: float
    p60: float
    p1: float
    xmins: float  # per fixture, not summed over the event


def _availability(player: Player, config: MinutesModelConfig) -> float:
    if player.chance_of_playing_next_round is not None:
        return player.chance_of_playing_next_round / 100
    if player.status == "d":
        return config.doubtful_chance
    if player.status == "a":
        return 1.0
    return 0.0


def _appearances(snapshot: BootstrapSnapshot) -> int:
    """[interpretation: the API has no per-player total-appearances field, so
    `appearances` in the shrinkage formula is read as "gameweeks played so
    far this season" — a snapshot-level count, not a per-player stat. This is
    what makes the shrinkage collapse to the prior at GW1 for every player
    regardless of their own `starts`, per Decision 4.]
    """
    return sum(1 for gameweek in snapshot.events if gameweek.finished)


def _minutes_probabilities(
    player: Player, position: str, appearances: int, config: MinutesModelConfig
) -> _MinutesProbabilities:
    availability = _availability(player, config)
    prior = config.start_priors.get(position, 0.5)
    shrunk_start_rate = (player.starts + config.shrinkage_k * prior) / (appearances + config.shrinkage_k)
    # `appearances` is a per-snapshot proxy (finished gameweek count), not a
    # per-player total — a double gameweek can put `starts` ahead of it
    # mid-season. Clip rather than let a probability exceed 1.
    p_start = min(1.0, availability * shrunk_start_rate)

    raw_mins_per_start = player.minutes / player.starts if player.starts > 0 else config.mins_per_start_prior
    e_mins_start = (
        raw_mins_per_start * player.starts + config.shrinkage_k * config.mins_per_start_prior
    ) / (player.starts + config.shrinkage_k)
    p60_given_start = min(1.0, e_mins_start / 60.0)

    p60 = p_start * p60_given_start
    # The substitute term is gated by `availability` too (FU-11): otherwise an
    # unavailable player (availability = 0, so p_start = 0) still projects a
    # flat DEFAULT_P_SUB_APPEARANCE chance of coming off the bench.
    p1 = p_start + (1 - p_start) * config.p_sub_appearance * availability
    xmins = p_start * e_mins_start + (1 - p_start) * config.p_sub_appearance * config.mins_per_sub * availability
    return _MinutesProbabilities(p_start=p_start, p60=p60, p1=p1, xmins=xmins)


# --- Poisson helpers --------------------------------------------------------
# [No scipy — see docs/plans/projections-v1.md Decision 6. These are small
# enough to hand-roll rather than add the dependency for.]


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam**k / math.factorial(k)


def _poisson_at_least(lam: float, threshold: int) -> float:
    return 1.0 - sum(_poisson_pmf(k, lam) for k in range(threshold))


def _poisson_expected_floor_div(lam: float, divisor: int, cap: int = 60) -> float:
    return sum(_poisson_pmf(k, lam) * (k // divisor) for k in range(cap))


# --- The eight components (Decision 5) --------------------------------------

_ComponentTuple = tuple[float, float, float, float, float, float, float, float]


def _component_points_for_fixture(
    position: str,
    scoring: dict[str, Any],
    minutes: _MinutesProbabilities,
    rates: MatchRates,
    player_rates: _ShrunkRates,
    league_mean_goals: float,
    defcon_thresholds: dict[str, int],
) -> _ComponentTuple:
    """Price one fixture from already-shrunk rates.

    Takes no `Player`: every rate arrives via `player_rates`, which is what
    stops an unshrunk one reaching a component. `bonus_shrinkage_minutes` is
    gone from the signature too — bonus is now shrunk with the other six in
    `shrunk_rates`, rather than being the one term that did it for itself.
    """
    p1, p60, xmins = minutes.p1, minutes.p60, minutes.xmins
    frac = xmins / 90

    xp_appearance = (p1 - p60) * scoring["short_play"] + p60 * scoring["long_play"]

    attack_scale = rates.xg_for / league_mean_goals
    xp_attack = (
        player_rates.xg * attack_scale * frac * scoring["goals_scored"][position]
        + player_rates.xa * attack_scale * frac * scoring["assists"]
    )

    xp_clean_sheet = p60 * math.exp(-rates.xg_against) * scoring["clean_sheets"][position]

    xp_conceded = (
        sum(_poisson_pmf(k, rates.xg_against) * (k // 2) for k in range(13))
        * scoring["goals_conceded"][position]
        * frac
    )

    if position == "GKP":
        saves_lambda = player_rates.saves * frac * (rates.xg_against / league_mean_goals)
        xp_saves = _poisson_expected_floor_div(saves_lambda, 3) * scoring["saves"]
    else:
        xp_saves = 0.0

    threshold = defcon_thresholds.get(position)
    if threshold is None:
        xp_defcon = 0.0
    else:
        dc_lambda = player_rates.dc * frac
        xp_defcon = _poisson_at_least(dc_lambda, threshold) * scoring["defensive_contribution"][position]

    xp_bonus = player_rates.bonus * frac * scoring["bonus"]

    xp_cards = (
        player_rates.yellow * scoring["yellow_cards"] + player_rates.red * scoring["red_cards"]
    ) * frac

    return (xp_appearance, xp_attack, xp_clean_sheet, xp_conceded, xp_saves, xp_defcon, xp_bonus, xp_cards)


# --- The public interface (Decision 2) --------------------------------------


@dataclass(frozen=True)
class Projection:
    player: int
    event: int
    xp_total: float

    xp_appearance: float
    xp_attack: float
    xp_clean_sheet: float
    xp_conceded: float
    xp_saves: float
    xp_defcon: float
    xp_bonus: float
    xp_cards: float

    p_start: float
    xmins: float
    fixtures: int
    model_version: str
    assumptions: tuple[str, ...] = ()


class ProjectionModel(Protocol):
    def project(
        self, players: Sequence[int], events: Sequence[int]
    ) -> Mapping[tuple[int, int], Projection]: ...


@dataclass(frozen=True)
class _FixtureLeg:
    opponent: int
    home: bool


def _build_schedule(fixtures: Sequence[Fixture]) -> dict[int, dict[int, list[_FixtureLeg]]]:
    """event -> team -> the legs (opponent, venue) that team plays that event.

    A postponed fixture (`event is None`) contributes to no event until
    rescheduled — this is how blanks and doubles arise; fixture count is
    always derived by counting, never assumed.
    """
    schedule: dict[int, dict[int, list[_FixtureLeg]]] = {}
    for fixture in fixtures:
        if fixture.event is None:
            continue
        schedule.setdefault(fixture.event, {}).setdefault(fixture.team_h, []).append(
            _FixtureLeg(opponent=fixture.team_a, home=True)
        )
        schedule.setdefault(fixture.event, {}).setdefault(fixture.team_a, []).append(
            _FixtureLeg(opponent=fixture.team_h, home=False)
        )
    return schedule


class ComponentProjection:
    """The default model: all eight terms, priced from `game_config.scoring`."""

    def __init__(
        self,
        snapshot: BootstrapSnapshot,
        fixtures: Sequence[Fixture],
        rates_model: TeamRatesModel,
        *,
        fixtures_stale: bool = False,
        fixtures_fetched_at: datetime | None = None,
        minutes_config: MinutesModelConfig | None = None,
        defcon_thresholds: dict[str, int] | None = None,
        rate_config: RateShrinkageConfig | None = None,
        version: str | None = None,
    ) -> None:
        self._players = snapshot.players_by_id
        self._positions = snapshot.positions
        self._scoring: dict[str, Any] = snapshot.raw["game_config"]["scoring"]
        self._rates_model = rates_model
        self._schedule = _build_schedule(fixtures)
        self._fixtures_stale = fixtures_stale
        self._fixtures_fetched_at = fixtures_fetched_at
        self._minutes_config = minutes_config or MinutesModelConfig()
        self._defcon_thresholds = defcon_thresholds if defcon_thresholds is not None else dict(DEFCON_THRESHOLDS)
        self._appearances = _appearances(snapshot)
        # Defaults to the pre-FU-47 treatment, not to the identity: direct
        # construction (which the tests use throughout) must keep behaving as
        # it did, and bonus was already shrunk before this branch.
        self._rate_config = rate_config if rate_config is not None else legacy_rate_config()
        # Pooled once per snapshot, not per player: the prior is a population
        # statistic, and recomputing it 616 times would be the same number.
        self._rate_priors = build_rate_priors(snapshot, self._rate_config)
        self._version = version

    @property
    def name(self) -> str:
        # `domain/variants.py` passes the registered variant's version, which is
        # the only path the CLI takes. The literal below is the fallback for
        # direct construction in tests and remains as drift-prone as it ever was
        # — it names the strategy class, not the constants. See variants.py.
        return self._version or f"component/1.0+{self._rates_model.name}"

    def project(self, players: Sequence[int], events: Sequence[int]) -> dict[tuple[int, int], Projection]:
        result: dict[tuple[int, int], Projection] = {}
        for player_id in players:
            player = self._players[player_id]
            position = self._positions[player.element_type].singular_name_short
            minutes = _minutes_probabilities(player, position, self._appearances, self._minutes_config)
            rates = shrunk_rates(player, position, self._rate_priors, self._rate_config)
            for event in events:
                result[(player_id, event)] = self._project_one(player, position, minutes, rates, event)
        return result

    def _project_one(
        self,
        player: Player,
        position: str,
        minutes: _MinutesProbabilities,
        player_rates: _ShrunkRates,
        event: int,
    ) -> Projection:
        legs = self._schedule.get(event, {}).get(player.team, [])
        totals = [0.0] * 8
        for leg in legs:
            rates = self._rates_model.rates(team=player.team, opponent=leg.opponent, home=leg.home)
            components = _component_points_for_fixture(
                position,
                self._scoring,
                minutes,
                rates,
                player_rates,
                self._rates_model.league_mean_goals,
                self._defcon_thresholds,
            )
            for index, value in enumerate(components):
                totals[index] += value

        assumptions: tuple[str, ...] = ()
        if self._fixtures_stale:
            fetched = self._fixtures_fetched_at.isoformat() if self._fixtures_fetched_at else "unknown"
            assumptions = (f"fixtures list is stale (cached {fetched}); blanks and doubles may be wrong",)

        return Projection(
            player=player.id,
            event=event,
            xp_total=sum(totals),
            xp_appearance=totals[0],
            xp_attack=totals[1],
            xp_clean_sheet=totals[2],
            xp_conceded=totals[3],
            xp_saves=totals[4],
            xp_defcon=totals[5],
            xp_bonus=totals[6],
            xp_cards=totals[7],
            p_start=minutes.p_start,
            xmins=minutes.xmins * len(legs),
            fixtures=len(legs),
            model_version=self.name,
            assumptions=assumptions,
        )


class NaiveProjection:
    """The control, not a stepping stone: points_per_game * availability * fixtures."""

    def __init__(
        self,
        snapshot: BootstrapSnapshot,
        fixtures: Sequence[Fixture],
        *,
        minutes_config: MinutesModelConfig | None = None,
        version: str | None = None,
    ) -> None:
        self._players = snapshot.players_by_id
        self._schedule = _build_schedule(fixtures)
        self._minutes_config = minutes_config or MinutesModelConfig()
        self._version = version

    @property
    def name(self) -> str:
        return self._version or "naive/1.0"

    def project(self, players: Sequence[int], events: Sequence[int]) -> dict[tuple[int, int], Projection]:
        result: dict[tuple[int, int], Projection] = {}
        for player_id in players:
            player = self._players[player_id]
            availability = _availability(player, self._minutes_config)
            points_per_game = float(player.points_per_game or "0.0")
            for event in events:
                fixture_count = len(self._schedule.get(event, {}).get(player.team, []))
                xp_total = points_per_game * availability * fixture_count
                result[(player_id, event)] = Projection(
                    player=player.id,
                    event=event,
                    xp_total=xp_total,
                    xp_appearance=xp_total,
                    xp_attack=0.0,
                    xp_clean_sheet=0.0,
                    xp_conceded=0.0,
                    xp_saves=0.0,
                    xp_defcon=0.0,
                    xp_bonus=0.0,
                    xp_cards=0.0,
                    p_start=availability,
                    xmins=90.0 * fixture_count,
                    fixtures=fixture_count,
                    model_version=self.name,
                    assumptions=("undecomposed: entire xp_total placed in xp_appearance",),
                )
        return result


class OfficialEpProjection:
    """The API's own `ep_next`, parsed as-is. Refuses any event but the next one."""

    def __init__(
        self, snapshot: BootstrapSnapshot, fixtures: Sequence[Fixture], *, version: str | None = None
    ) -> None:
        self._players = snapshot.players_by_id
        self._schedule = _build_schedule(fixtures)
        self._next_event = next((gameweek.id for gameweek in snapshot.events if gameweek.is_next), None)
        self._version = version

    @property
    def name(self) -> str:
        return self._version or "official-ep/1.0"

    def project(self, players: Sequence[int], events: Sequence[int]) -> dict[tuple[int, int], Projection]:
        result: dict[tuple[int, int], Projection] = {}
        for event in events:
            if event != self._next_event:
                raise ValueError(
                    f"OfficialEpProjection only projects the next event "
                    f"({self._next_event!r}); got {event!r}."
                )
            for player_id in players:
                player = self._players[player_id]
                xp_total = float(player.ep_next) if player.ep_next else 0.0
                fixture_count = len(self._schedule.get(event, {}).get(player.team, []))
                result[(player_id, event)] = Projection(
                    player=player.id,
                    event=event,
                    xp_total=xp_total,
                    xp_appearance=xp_total,
                    xp_attack=0.0,
                    xp_clean_sheet=0.0,
                    xp_conceded=0.0,
                    xp_saves=0.0,
                    xp_defcon=0.0,
                    xp_bonus=0.0,
                    xp_cards=0.0,
                    p_start=0.0,
                    xmins=0.0,
                    fixtures=fixture_count,
                    model_version=self.name,
                    assumptions=(
                        "undecomposed: entire xp_total placed in xp_appearance; "
                        "p_start and xmins are not modelled",
                    ),
                )
        return result

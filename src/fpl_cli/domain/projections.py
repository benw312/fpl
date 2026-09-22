"""The xP decomposition (docs/plans/projections-v1.md).

Three models share one `Projection` shape: `ComponentProjection` (the eight-
term decomposition), `NaiveProjection` (the flat-rate control), and
`OfficialEpProjection` (the API's own `ep_next`, next-event only). The
optimiser reads `Projection.xp_total`; every other field is for explanation
and debugging.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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


# --- The minutes *structure* (minutes-model.md §7, rows 1-10; FU-51) ---------
#
# §7's finding, applied: "a variant holding only a `MinutesModelConfig` cannot
# express rows 1-10, so the variant type needs a second config object, not seven
# more flat fields." This is that object. `MinutesModelConfig` keeps rows 11-19,
# which are today's chosen constants and are not to be changed (§6.2).
#
# **Every default below reproduces today's behaviour exactly**, which is what
# makes `component/1.1-price` byte-identical across this change and is asserted
# by `test_scalar_mode_reproduces_today`. The `legacy_rate_config()` precedent:
# the new structure must contain the old behaviour, or no comparison across the
# change is valid.

HORIZON_AVAILABILITY: tuple[str, ...] = ("scalar", "per_event")
THIS_ROUND_SOURCES: tuple[str, ...] = ("next_only", "this_then_next")
DEPARTED_POLICIES: tuple[str, ...] = ("ignore", "zero", "exclude")
START_PRIOR_SOURCES: tuple[str, ...] = ("position", "ownership_conditioned")
START_EVIDENCE: tuple[str, ...] = ("count", "minutes_weighted")

# §2.4's strata, reproduced rather than chosen: the table that establishes the
# ownership signal is monotonic buckets at <1%, 1-5%, 5-15%, >15%, and these are
# those edges. §7 row 7 calls this "a *shape* choice, not a fitted one".
DEFAULT_OWN_BAND_EDGES: tuple[float, ...] = (1.0, 5.0, 15.0)

# §2.5's bucket edge, which is also the appearance-point threshold `p60` already
# uses. Read only when `start_evidence == "minutes_weighted"`.
DEFAULT_FULL_MATCH_MINUTES = 60


@dataclass(frozen=True)
class MinutesStructureConfig:
    """minutes-model.md §7 rows 1-10, plus FU-51's two.

    `own_band_prior_appearances = None` means "reuse `shrinkage_k`", and that
    default is load-bearing rather than lazy. §7 row 6 asks for an `OWN_BAND_M`
    "float, minutes, 450-1800" mirroring rate-shrinkage's `BAND_M = 900`, but
    **that unit is wrong here and the number cannot be carried across**. A rate
    is per-90 and its exposure is measured in minutes; a start is a per-match
    event and its exposure is measured in appearances — which is exactly why
    `shrink_rate`'s docstring says `shrinkage_k` is in matches and tells the
    reader not to unify the two. 900 appearances is twenty-four seasons. Reusing
    the existing `shrinkage_k` introduces no new number, is in the right unit,
    and gives §8.7's guard for free: a band of one player carries 1/(1+4) of its
    own weight and 4/5 of the position prior. The knob still exists so a later
    variant can set it independently and be compared, which is §7's whole point.

    `partial_start_weight = 1.0` is likewise inert by construction: at 1.0 a
    partial start counts the same as a full one, so `minutes_weighted` collapses
    to `count`. **This is not a proposed value.** minutes-model.md §9 declines to
    choose the functional form for S6(b) — "§2.5's three buckets cannot
    distinguish them, and choosing on that data would be fitting to three points"
    — so the default is the one setting that makes no claim.
    """

    horizon_availability: str = "scalar"  # row 1
    this_round_source: str = "next_only"  # row 2
    news_return_dates: bool = False  # row 3
    departed_policy: str = "ignore"  # row 4
    start_prior_source: str = "position"  # row 5
    own_band_prior_appearances: float | None = None  # row 6 — see docstring
    own_band_edges: tuple[float, ...] = DEFAULT_OWN_BAND_EDGES  # row 7
    start_evidence: str = "count"  # row 8
    full_match_minutes: int = DEFAULT_FULL_MATCH_MINUTES  # row 9
    partial_start_weight: float = 1.0  # row 10 — inert; see docstring
    # FU-51. `return_ramp_events = 0` reproduces S3 without the ramp, which is
    # FU-51's own stated identity setting and what component/1.2 uses. The 45 is
    # FU-51's chosen `[assumption: no empirical basis]` value and is held here
    # only so a variant can set `return_ramp_events` and be compared.
    return_ramp_minutes: float = 45.0
    return_ramp_events: int = 0

    def __post_init__(self) -> None:
        for value, allowed, label in (
            (self.horizon_availability, HORIZON_AVAILABILITY, "horizon_availability"),
            (self.this_round_source, THIS_ROUND_SOURCES, "this_round_source"),
            (self.departed_policy, DEPARTED_POLICIES, "departed_policy"),
            (self.start_prior_source, START_PRIOR_SOURCES, "start_prior_source"),
            (self.start_evidence, START_EVIDENCE, "start_evidence"),
        ):
            if value not in allowed:
                raise ValueError(f"{label} must be one of {allowed}; got {value!r}.")
        if list(self.own_band_edges) != sorted(self.own_band_edges):
            raise ValueError(f"own_band_edges must be ascending; got {self.own_band_edges!r}.")
        if self.return_ramp_events < 0:
            raise ValueError(f"return_ramp_events must be non-negative; got {self.return_ramp_events!r}.")

    @property
    def is_identity(self) -> bool:
        """True when this config reproduces the pre-1.2 minutes model exactly.

        `RateShrinkageConfig.is_identity`'s precedent, and it does the same job
        in `variants.as_dict`: an identity structure is omitted from the digest
        so that every variant registered before 1.2 keeps the digest already
        pinned in `tests/test_variants.py` and already cited in
        minutes-model.md and fu-53-minutes-ceiling.md. Re-pinning six digests to
        add a field none of them sets would break every FU-40 citation in the
        repo to save one `if`.

        Rows 6, 7, 9 and 10 are deliberately not consulted: each is read only
        when the row it depends on is active (§7's second property), so a config
        that differs only in an unread value **is** today's model. Including them
        would make the digest claim a difference that does not exist.
        """
        return (
            self.horizon_availability == "scalar"
            and self.this_round_source == "next_only"
            and not self.news_return_dates
            and self.departed_policy == "ignore"
            and self.start_prior_source == "position"
            and self.start_evidence == "count"
            and self.return_ramp_events == 0
        )

    def as_dict(self) -> dict[str, Any]:
        """Every constant that can move a projection under *this* config.

        Conditional on the row it depends on, for the reason `is_identity`
        gives: an unread value is not part of the model, and hashing it would
        pin a difference that cannot reach a number.
        """
        payload: dict[str, Any] = {
            "horizon_availability": self.horizon_availability,
            "this_round_source": self.this_round_source,
            "news_return_dates": self.news_return_dates,
            "departed_policy": self.departed_policy,
            "start_prior_source": self.start_prior_source,
            "start_evidence": self.start_evidence,
            "return_ramp_events": self.return_ramp_events,
        }
        if self.start_prior_source == "ownership_conditioned":
            payload["own_band_prior_appearances"] = self.own_band_prior_appearances
            payload["own_band_edges"] = list(self.own_band_edges)
        if self.start_evidence == "minutes_weighted":
            payload["full_match_minutes"] = self.full_match_minutes
            payload["partial_start_weight"] = self.partial_start_weight
        if self.return_ramp_events > 0:
            payload["return_ramp_minutes"] = self.return_ramp_minutes
        return payload


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


@dataclass(frozen=True)
class Availability:
    """minutes-model.md §6.1 S5: a value, its provenance, and its horizon.

    `_availability` answered two questions at once — "is this player available"
    and "for which gameweek" — and §3 measured that the second was silently
    dropped: a scalar derived from `chance_of_playing_next_round` was applied
    unchanged to all five gameweeks of the default horizon.

    Returning a structure is what makes the per-gameweek fix expressible, and it
    makes FU-48's two unreachable branches self-documenting rather than merely
    dead: a projection whose availability came from the fallback is one whose
    provenance a reader can see. Same argument FU-43 made for the event-live
    envelope. **The dead branches are kept.** FU-48 established
    `doubtful_chance = 0.75` is well chosen (179 of 203 `status='d'`
    observations publish exactly 75%); deleting a correct fallback because the
    primary path has not yet failed is how a system acquires a crash.
    """

    value: float
    source: str
    event: int | None


# The provenance labels `Availability.source` can carry. Named rather than
# inlined so a test can assert a branch was taken, which is the point of S5.
AVAILABILITY_SOURCES: tuple[str, ...] = (
    "chance_this_round",
    "chance_next_round",
    "doubtful_default",
    "status_available",
    "status_unknown_default",
    "news_return_pending",
    "news_return_reached",
    "departed",
)

# §2.3's templated news shapes. 44 of 616 players on the pinned capture have
# left the league and are carried through every projection and every evaluation
# denominator (S4). Anchored to the shapes actually observed rather than to any
# mention of a club name.
_DEPARTED_NEWS = re.compile(r"\b(has joined|joined .* on loan|on loan (at|to)|left )", re.IGNORECASE)

# §2.3: `<injury> - Expected back <D Mon>`, 7 of 616 on the pinned capture.
# Anchored to the template (§8.5): a date-like substring elsewhere in the string
# must not parse, so the phrase is required and the date must follow it directly.
_RETURN_DATE = re.compile(r"expected back\s+(\d{1,2})\s+([A-Za-z]{3})\b", re.IGNORECASE)

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def has_departed(player: Player) -> bool:
    """§6.1 S4: `status='u'` plus a transfer or loan news shape.

    Both halves are required. `status='u'` alone is "unavailable", which is not
    the same claim as "no longer in the league", and the news shape alone
    appears on loan moves *into* the league.
    """
    return player.status == "u" and bool(_DEPARTED_NEWS.search(player.news or ""))


def parse_return_date(news: str, captured_at: datetime) -> date | None:
    """§6.1 S3: the `Expected back <D Mon>` date, or None.

    **Never raises.** §8.4's requirement: a malformed date, an unknown month, an
    impossible day, or no date at all falls back to the ordinary status/chance
    path rather than taking the player out of the projection.

    The year is absent from the template, so it is resolved against the capture
    date by taking whichever of `captured_at.year` and `+1` puts the date within
    six months before the capture. Six months is the wrap midpoint, not a
    chosen parameter: any other split would prefer one direction over the other
    with no reason to. It gets §8.5's two cases right — a December capture
    reading "Expected back 5 Jan" resolves to the following year, and a news
    string whose date has just passed stays in the current one rather than
    being thrown a year forward and zeroing the player for a season.
    """
    match = _RETURN_DATE.search(news or "")
    if match is None:
        return None
    month = _MONTHS.get(match.group(2).lower())
    if month is None:
        return None
    day = int(match.group(1))
    captured = captured_at.date()
    for year in (captured.year, captured.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None  # 31 Feb and friends
        if candidate >= captured - timedelta(days=183):
            return candidate
    return None


def _as_probability(percentage: int) -> float:
    """A published `chance_of_playing_*` as a probability, clamped to [0, 1].

    **The clamp is a defect fix, not new behaviour**, and it is here rather than
    at `p_start` because this is the only place a percentage enters the minutes
    model. Found by minutes-model.md §8.8, which asks for `chance_of_playing`
    outside 0-100 among its absurd inputs: the pre-1.2 model divided by 100 and
    passed the result straight through, so `chance = -50` gave `p_start`,
    `p60`, `p1` and `xmins` all negative — a player with minus twenty expected
    minutes, and an `xp_total` with the sign of its scoring rates flipped. The
    existing `min(1.0, ...)` on `p_start` guarded only the upper end and only
    that one field.

    No such value has ever been observed: 6,788 player-observations across 11
    captures (FU-48) publish 0, 25, 50, 75 or 100 and nothing else. So this
    moves no projected number on any real capture — verified byte-identical for
    all three pre-1.2 component variants over 3,080 rows — and exists because a
    field the API is free to change should not be able to invert a projection.
    """
    return min(1.0, max(0.0, percentage / 100))


def availability_for_event(
    player: Player,
    config: MinutesModelConfig,
    structure: MinutesStructureConfig,
    *,
    event: int | None = None,
    nearest_event: int | None = None,
    deadline: datetime | None = None,
    captured_at: datetime | None = None,
) -> Availability:
    """Availability as a statement about one gameweek (S1-S5).

    **Order of precedence, and why.**

    1. **Departed** beats everything. A player who has left the league is not
       coming back this season, whatever any other field says.
    2. **The nearest gameweek uses the API's own statement about it.** For that
       one event `chance_of_playing_this_round` is a direct claim about the
       round being asked about, and it is fresher than an inference from a news
       string — so the return date is deliberately *not* consulted there. This
       is also what makes §8.3's Christie/Fofana shape work: `this_round=0`,
       `next_round=100` gives 0.0 for the nearest gameweek and non-zero for the
       next.
    3. **Later gameweeks consult the return date.** §3's finding is that the
       model "uses the *right* field for the first gameweek and the same value
       for four more"; S2 fixes the first and S3 fixes the rest. A dated player
       is zeroed strictly before the date and available on or after it.
    4. **Otherwise the pre-1.2 scalar path**, unchanged.

    Under the default (identity) structure every branch but 4 is unreachable and
    the result is exactly `chance_of_playing_next_round`-driven — which is what
    keeps `component/1.1-price` byte-identical.
    """
    if structure.departed_policy in ("zero", "exclude") and has_departed(player):
        return Availability(value=0.0, source="departed", event=event)

    is_nearest = event is not None and nearest_event is not None and event == nearest_event
    per_event = structure.horizon_availability == "per_event"

    if is_nearest and structure.this_round_source == "this_then_next":
        if player.chance_of_playing_this_round is not None:
            return Availability(
                value=_as_probability(player.chance_of_playing_this_round),
                source="chance_this_round",
                event=event,
            )
    elif per_event and structure.news_return_dates and not is_nearest:
        return_date = (
            parse_return_date(player.news, captured_at) if captured_at is not None else None
        )
        if return_date is not None and deadline is not None:
            if deadline.date() < return_date:
                return Availability(value=0.0, source="news_return_pending", event=event)
            return Availability(value=1.0, source="news_return_reached", event=event)

    if player.chance_of_playing_next_round is not None:
        return Availability(
            value=_as_probability(player.chance_of_playing_next_round),
            source="chance_next_round",
            event=event,
        )
    if player.status == "d":
        return Availability(value=config.doubtful_chance, source="doubtful_default", event=event)
    if player.status == "a":
        return Availability(value=1.0, source="status_available", event=event)
    return Availability(value=0.0, source="status_unknown_default", event=event)


def _availability(player: Player, config: MinutesModelConfig) -> float:
    """The pre-1.2 scalar, for `NaiveProjection` and every existing caller.

    Kept as a one-line delegation rather than a second implementation: the
    identity structure takes branch 4 of `availability_for_event` and nothing
    else, so this is the same arithmetic it always was.
    """
    return availability_for_event(player, config, MinutesStructureConfig()).value


def _appearances(snapshot: BootstrapSnapshot) -> int:
    """[interpretation: the API has no per-player total-appearances field, so
    `appearances` in the shrinkage formula is read as "gameweeks played so
    far this season" — a snapshot-level count, not a per-player stat. This is
    what makes the shrinkage collapse to the prior at GW1 for every player
    regardless of their own `starts`, per Decision 4.]
    """
    return sum(1 for gameweek in snapshot.events if gameweek.finished)


@dataclass(frozen=True)
class StartPriors:
    """§6.1 S6(a): start priors pooled from the snapshot, not hardcoded.

    The direct analogue of `RatePriors`, and derived the same way — pooled by
    exposure, `sum(starts) / sum(appearances)`, never the mean of per-player
    rates (§8.6). The unit is appearances, not minutes: a start is a per-match
    event. See `MinutesStructureConfig.own_band_prior_appearances`.

    **This replaces four `[assumption]` constants with zero.** Today's
    `start_priors` — GKP 0.85, DEF 0.65, MID 0.55, FWD 0.55 — carry
    `[assumption: no empirical basis]` and are why §4.2's 119 players with no
    player-specific evidence clear 0.5 on the prior alone. Pooled from the
    pinned GW2 capture the same four positions come out at GKP 0.294, DEF 0.424,
    MID 0.341, FWD 0.288: the hardcoded values are roughly double the rate
    actually observed in the payload they are meant to describe.
    """

    position: Mapping[str, float]
    band: Mapping[tuple[str, int], float]
    edges: tuple[float, ...]

    def band_of(self, selected_by_percent: float) -> int:
        return sum(1 for edge in self.edges if selected_by_percent >= edge)

    def prior_for(self, player: Player, position: str, source: str, fallback: float) -> float:
        if source != "ownership_conditioned":
            return fallback
        band = self.band_of(float(player.selected_by_percent or "0.0"))
        return self.band.get((position, band), self.position.get(position, fallback))


def build_start_priors(
    snapshot: BootstrapSnapshot, config: MinutesModelConfig, structure: MinutesStructureConfig
) -> StartPriors:
    """Pool the start rate by position, and by (position, ownership band) above it.

    The band level is shrunk toward the position level by
    `own_band_prior_appearances`, defaulting to `shrinkage_k`. That is §8.7's
    thin-band guard and it is continuous rather than a minimum-count cutoff, for
    rate-shrinkage.md §3.3's reason: a band of one player shrunk toward itself
    is unshrunk, and a hard cutoff merely moves the cliff to the count that
    trips it. At `shrinkage_k = 4` a one-player band carries 1/5 of its own
    weight and 4/5 of the position prior.

    `appearances` is the snapshot-level finished-gameweek count, the same proxy
    `_appearances` documents — so each player contributes exactly that many
    appearances of exposure, and pooling is a straight count of starts over a
    count of player-gameweeks.
    """
    appearances = max(_appearances(snapshot), 1)
    weight = (
        config.shrinkage_k
        if structure.own_band_prior_appearances is None
        else structure.own_band_prior_appearances
    )
    positions = snapshot.positions
    edges = tuple(structure.own_band_edges)

    by_position: dict[str, list[int]] = {}
    by_band: dict[tuple[str, int], list[int]] = {}
    for player in snapshot.elements:
        position = positions[player.element_type].singular_name_short
        band = sum(1 for edge in edges if float(player.selected_by_percent or "0.0") >= edge)
        by_position.setdefault(position, []).append(player.starts)
        by_band.setdefault((position, band), []).append(player.starts)

    position_priors = {
        position: sum(starts) / (len(starts) * appearances) for position, starts in by_position.items()
    }
    band_priors: dict[tuple[str, int], float] = {}
    for key, starts in by_band.items():
        exposure = len(starts) * appearances
        pooled = sum(starts) / exposure
        parent = position_priors[key[0]]
        band_priors[key] = (pooled * exposure + parent * weight) / (exposure + weight)
    return StartPriors(position=position_priors, band=band_priors, edges=edges)


def _start_evidence(player: Player, structure: MinutesStructureConfig) -> float:
    """§6.1 S6(b): the evidence term of `p_start`, `starts` or a weighted count.

    §2.5 measured that a player hooked before the hour is less than a quarter as
    likely to start again as one who played the full match (20% / 76% / 92%),
    and the model discards it. **`component/1.2` does not turn this on**: §7 rows
    9 and 10 are a functional form minutes-model.md §9 explicitly declines to
    choose, and the default `partial_start_weight = 1.0` makes this identical to
    `count`.
    """
    if structure.start_evidence == "count" or player.starts <= 0:
        return float(player.starts)
    mins_per_start = player.minutes / player.starts
    weight = 1.0 if mins_per_start >= structure.full_match_minutes else structure.partial_start_weight
    return player.starts * weight


def _minutes_probabilities(
    player: Player,
    position: str,
    appearances: int,
    config: MinutesModelConfig,
    structure: MinutesStructureConfig | None = None,
    *,
    availability: Availability | None = None,
    start_priors: StartPriors | None = None,
    events_until_return: int | None = None,
) -> _MinutesProbabilities:
    structure = structure or MinutesStructureConfig()
    availability_value = (
        _availability(player, config) if availability is None else availability.value
    )
    fallback = config.start_priors.get(position, 0.5)
    prior = (
        fallback
        if start_priors is None
        else start_priors.prior_for(player, position, structure.start_prior_source, fallback)
    )
    evidence = _start_evidence(player, structure)
    shrunk_start_rate = (evidence + config.shrinkage_k * prior) / (appearances + config.shrinkage_k)
    # `appearances` is a per-snapshot proxy (finished gameweek count), not a
    # per-player total — a double gameweek can put `starts` ahead of it
    # mid-season. Clip rather than let a probability exceed 1.
    p_start = min(1.0, availability_value * shrunk_start_rate)

    raw_mins_per_start = player.minutes / player.starts if player.starts > 0 else config.mins_per_start_prior
    e_mins_start = (
        raw_mins_per_start * player.starts + config.shrinkage_k * config.mins_per_start_prior
    ) / (player.starts + config.shrinkage_k)
    # FU-51: a return date says a player is available, not that he plays ninety
    # minutes. The cap lands on `e_mins_start` rather than on `xmins` or on
    # `p_start`, which is FU-51's second gap made a decision: capping `xmins`
    # alone would leave an uncapped `p60` awarding a full clean-sheet
    # probability to a player expected to last a half, which the gap names as
    # incoherent. Capping the per-start minutes flows into `p60`, `p1` and
    # `xmins` together. **Unreachable in component/1.2** — `return_ramp_events`
    # is 0 there, which FU-51 states reproduces S3 without the ramp.
    if (
        structure.return_ramp_events > 0
        and events_until_return is not None
        and 0 <= events_until_return < structure.return_ramp_events
    ):
        e_mins_start = min(e_mins_start, structure.return_ramp_minutes)
    p60_given_start = min(1.0, e_mins_start / 60.0)

    p60 = p_start * p60_given_start
    # The substitute term is gated by `availability` too (FU-11): otherwise an
    # unavailable player (availability = 0, so p_start = 0) still projects a
    # flat DEFAULT_P_SUB_APPEARANCE chance of coming off the bench.
    p1 = p_start + (1 - p_start) * config.p_sub_appearance * availability_value
    xmins = (
        p_start * e_mins_start
        + (1 - p_start) * config.p_sub_appearance * config.mins_per_sub * availability_value
    )
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
        minutes_structure: MinutesStructureConfig | None = None,
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
        self._structure = minutes_structure or MinutesStructureConfig()
        # S1/S3 need to know which gameweek each event *is*: its deadline, to
        # compare against a return date, and whether it is the one
        # `chance_of_playing_this_round` speaks about.
        self._deadlines = {gameweek.id: gameweek.deadline_time for gameweek in snapshot.events}
        self._nearest_event = next(
            (gameweek.id for gameweek in snapshot.events if gameweek.is_next), None
        )
        self._captured_at = snapshot.fetched_at
        # Pooled once per snapshot, like `_rate_priors` — a population statistic,
        # and recomputing it 616 times would be the same number. Built even under
        # `start_prior_source='position'`, where `prior_for` ignores it: the cost
        # is one pass over the elements and it keeps the construction path single.
        self._start_priors = build_start_priors(snapshot, self._minutes_config, self._structure)
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

    @property
    def rates_model(self) -> TeamRatesModel:
        """Read-only, so `plan evaluate` can report what a fitted strength model
        found on the capture (model-1.3.md §3.2: a fallback is recorded)."""
        return self._rates_model

    def project(self, players: Sequence[int], events: Sequence[int]) -> dict[tuple[int, int], Projection]:
        result: dict[tuple[int, int], Projection] = {}
        for player_id in players:
            player = self._players[player_id]
            # S4 under `exclude`: the player leaves the returned mapping
            # entirely, which is the one policy that changes the evaluation
            # denominator (§7's third property). `component/1.2` uses `zero`
            # instead, so any figure it produces stays comparable with a figure
            # measured before it.
            if self._structure.departed_policy == "exclude" and has_departed(player):
                continue
            position = self._positions[player.element_type].singular_name_short
            rates = shrunk_rates(player, position, self._rate_priors, self._rate_config)
            # S1: inside the event loop, not outside it. `_minutes_probabilities`
            # used to be computed once per player and reused for every event in
            # the horizon, which applied a next-round scalar to five rounds —
            # §3.1's category error. Under the identity structure availability is
            # the same value for every event, so this recomputes to the same
            # number and `component/1.1-price` is unmoved.
            for event in events:
                minutes = self._minutes_for(player, position, event)
                result[(player_id, event)] = self._project_one(player, position, minutes, rates, event)
        return result

    def _minutes_for(self, player: Player, position: str, event: int) -> _MinutesProbabilities:
        availability = availability_for_event(
            player,
            self._minutes_config,
            self._structure,
            event=event,
            nearest_event=self._nearest_event,
            deadline=self._deadlines.get(event),
            captured_at=self._captured_at,
        )
        return _minutes_probabilities(
            player,
            position,
            self._appearances,
            self._minutes_config,
            self._structure,
            availability=availability,
            start_priors=self._start_priors,
            events_until_return=self._events_until_return(player, event),
        )

    def _events_until_return(self, player: Player, event: int) -> int | None:
        """How many events after this player's return gameweek `event` is.

        0 is the gameweek he returns in, which is the one FU-51's ramp caps.
        None when there is no parseable return date or no ramp to apply — the
        common case, and the only one `component/1.2` ever takes.
        """
        if self._structure.return_ramp_events <= 0 or not self._structure.news_return_dates:
            return None
        return_date = parse_return_date(player.news, self._captured_at)
        if return_date is None:
            return None
        dated = sorted(
            (identifier, deadline)
            for identifier, deadline in self._deadlines.items()
            if deadline is not None and deadline.date() >= return_date
        )
        first_back = next((identifier for identifier, _ in sorted(dated, key=lambda row: row[1])), None)
        if first_back is None:
            return None
        return event - first_back

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

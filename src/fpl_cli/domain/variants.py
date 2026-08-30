"""Named model variants, and the version string derived from them.

A variant is a registered configuration, not a forked module and not a branch.
FU-47 will introduce several that have to be compared against the same actuals
in one run; testing those by editing constants in place loses the comparison on
revert and produces figures citing a model that no longer exists in the tree,
which is FU-40's problem in a new place.

**Why the version string could not be trusted before this module.**
`ComponentProjection.name` was `f"component/1.0+{rates_model.name}"` — the
`component` and `1.0` halves were literals unrelated to any constant, and
`banded` named the strength model's *class* rather than its arguments. Measured
against `~/fpl-pinned/gw2-pre-deadline.json`, four materially different models
all reported `component/1.0+banded`, projecting Haaland at GW3 as 3.430, 2.993,
17.243 and 5.081 respectively. `minutes_config` and `defcon_thresholds` appeared
nowhere in the name at all. `naive/1.0` had the same defect through its own
`minutes_config`; only `official-ep/1.0` and `baseline/flat-ppg` were safe, and
only because they take no configuration.

Here the string is a property of the registered variant, and
`tests/test_variants.py` pins a digest over every constant the variant holds. A
constant cannot now move without either the digest test failing or the variant
being renamed.

Registering a variant is one entry in `_REGISTRY` below. It does not require
touching `projections.py`; adding a whole new model *family* does, and that is
the intended seam.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.domain.projections import (
    ComponentProjection,
    DEFCON_THRESHOLDS,
    MinutesModelConfig,
    NaiveProjection,
    OfficialEpProjection,
    ProjectionModel,
    RateShrinkageConfig,
    legacy_rate_config,
)
from fpl_cli.domain.strength import BAND_MULTIPLIERS, LEAGUE_MEAN_GOALS, BandedTeamRates


@dataclass(frozen=True)
class StrengthConfig:
    """The fixture-strength model and its arguments.

    `name` is the half of the version string that follows `+`. It names the
    strategy, and the digest covers the arguments — before this, `banded`
    named the class while the multipliers underneath it could be anything.
    """

    name: str = "banded"
    band_multipliers: Mapping[int, float] = field(default_factory=lambda: dict(BAND_MULTIPLIERS))
    league_mean_goals: float = LEAGUE_MEAN_GOALS
    home_advantage: float = 1.0

    def build(self, snapshot: BootstrapSnapshot) -> BandedTeamRates:
        if self.name != "banded":
            raise ValueError(
                f"No strength model named {self.name!r}. Only 'banded' exists; "
                "Dixon-Coles is docs/plans/projections-v1.md Decision 1's v2."
            )
        return BandedTeamRates(
            snapshot,
            band_multipliers=dict(self.band_multipliers),
            league_mean_goals=self.league_mean_goals,
            home_advantage=self.home_advantage,
        )


@dataclass(frozen=True)
class ModelVariant:
    """One named, fully-specified model configuration.

    Every field that can change a projected number lives here, which is what
    makes `digest` meaningful. A field added later that affects projections and
    is *not* held here reopens exactly the drift this module closes.
    """

    name: str
    family: str
    minutes: MinutesModelConfig = field(default_factory=MinutesModelConfig)
    defcon_thresholds: Mapping[str, int] = field(default_factory=lambda: dict(DEFCON_THRESHOLDS))
    strength: StrengthConfig | None = None
    rates: RateShrinkageConfig = field(default_factory=RateShrinkageConfig)
    note: str = ""

    @property
    def version(self) -> str:
        """The string that reaches `Projection.model_version` and every table.

        Deliberately *not* the digest: this commit must change nothing
        observable, and a hash in every output line is noise for a reader who
        is not chasing a drift. The digest is the test's business, not the
        table's.
        """
        return f"{self.name}+{self.strength.name}" if self.strength is not None else self.name

    def as_dict(self) -> dict[str, Any]:
        """Every constant, in a form that serialises deterministically."""
        return {
            "name": self.name,
            "family": self.family,
            "minutes": {
                "shrinkage_k": self.minutes.shrinkage_k,
                "start_priors": dict(sorted(self.minutes.start_priors.items())),
                "mins_per_start_prior": self.minutes.mins_per_start_prior,
                "p_sub_appearance": self.minutes.p_sub_appearance,
                "mins_per_sub": self.minutes.mins_per_sub,
                "doubtful_chance": self.minutes.doubtful_chance,
                "bonus_shrinkage_minutes": self.minutes.bonus_shrinkage_minutes,
            },
            "defcon_thresholds": dict(sorted(self.defcon_thresholds.items())),
            "strength": None
            if self.strength is None
            else {
                "name": self.strength.name,
                "band_multipliers": {str(k): v for k, v in sorted(self.strength.band_multipliers.items())},
                "league_mean_goals": self.strength.league_mean_goals,
                "home_advantage": self.strength.home_advantage,
            },
            "rates": self.rates.as_dict(),
        }

    @property
    def digest(self) -> str:
        """sha256 over every constant, first 12 hex characters.

        `note` is excluded on purpose — prose about a variant is not part of
        the model, and requiring a re-pin to fix a typo would train people to
        update the expected digest without reading why it moved.
        """
        payload = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# --- The registry ------------------------------------------------------------

_REGISTRY: dict[str, ModelVariant] = {}


def register(variant: ModelVariant) -> ModelVariant:
    if variant.name in _REGISTRY:
        raise ValueError(f"A variant named {variant.name!r} is already registered.")
    _REGISTRY[variant.name] = variant
    return variant


def get(name: str) -> ModelVariant:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"No registered model variant {name!r}. Registered: {', '.join(names())}.") from None


def names() -> tuple[str, ...]:
    return tuple(_REGISTRY)


def all_variants() -> tuple[ModelVariant, ...]:
    return tuple(_REGISTRY.values())


# --- Builders, one per family ------------------------------------------------
#
# Adding a *variant* of an existing family is an entry in _REGISTRY and nothing
# else. Adding a *family* is a builder here. Neither touches projections.py.


def build(
    variant: ModelVariant,
    snapshot: BootstrapSnapshot,
    fixtures: Sequence[Fixture],
    *,
    fixtures_stale: bool = False,
    fixtures_fetched_at: datetime | None = None,
) -> ProjectionModel:
    registered = _REGISTRY.get(variant.name)
    if registered is not None and registered is not variant:
        # The same defect this module closes, one level down. `ModelVariant` is
        # an ordinary dataclass, so nothing stopped an unregistered one taking a
        # registered name, holding different constants, and emitting the same
        # version string — which is *worse* than the old fallback literal,
        # because it is a string the registry blesses. A reader checking the
        # digest test would find `component/1.0` pinned and correct while the
        # figure came from something else. Measured before this guard: an
        # impostor `component/1.0` with `shrinkage_k=99, league_mean_goals=9.9`
        # built without complaint and projected Haaland at GW3 as 2.993 against
        # the registered 3.430, both stamped `component/1.0+banded`.
        #
        # Unregistered *names* stay free — that is how the negative cases in
        # tests/test_variants.py are written, and how a throwaway variant is
        # tried before it earns a name. Only impersonation is refused.
        raise ValueError(
            f"{variant.name!r} is a registered variant, but this is a different object with "
            f"digest {variant.digest} against the registered {registered.digest}. Register it "
            "under its own name, or pass variants.get(name); a figure quoted under a registered "
            "name must have come from that variant (FU-40)."
        )
    # The NotImplementedError that used to stand here is gone: FU-47 landed and
    # `ComponentProjection` reads `rates`. It existed so that a variant setting
    # M_xg=270 could not silently project identically to one that did not; that
    # is now enforced by the parameters actually being consumed.

    if variant.family == "component":
        if variant.strength is None:
            raise ValueError(f"Variant {variant.name!r} is family 'component' but names no strength model.")
        return ComponentProjection(
            snapshot,
            fixtures,
            variant.strength.build(snapshot),
            fixtures_stale=fixtures_stale,
            fixtures_fetched_at=fixtures_fetched_at,
            minutes_config=variant.minutes,
            defcon_thresholds=dict(variant.defcon_thresholds),
            rate_config=variant.rates,
            version=variant.version,
        )
    if variant.family == "naive":
        return NaiveProjection(snapshot, fixtures, minutes_config=variant.minutes, version=variant.version)
    if variant.family == "official-ep":
        return OfficialEpProjection(snapshot, fixtures, version=variant.version)
    raise ValueError(f"Variant {variant.name!r} names unknown family {variant.family!r}.")


# --- Registered variants -----------------------------------------------------
#
# `component/1.0`, `naive/1.0` and `official-ep/1.0` carry exactly the constants
# that were in force before this module existed. That is the whole content of
# the first commit on task/model-versioning: the defaults below are the module
# defaults, so registering them changes no projected number.

COMPONENT_V1 = register(
    ModelVariant(
        name="component/1.0",
        family="component",
        strength=StrengthConfig(),
        rates=legacy_rate_config(),
        note="The eight-term decomposition as shipped. Every constant is projections.py's default.",
    )
)

NAIVE_V1 = register(
    ModelVariant(
        name="naive/1.0",
        family="naive",
        note="The control: points_per_game * availability * fixtures.",
    )
)

OFFICIAL_EP_V1 = register(
    ModelVariant(
        name="official-ep/1.0",
        family="official-ep",
        note="The API's own ep_next. Takes no configuration, so it could never drift.",
    )
)

# --- A test fixture, not a candidate model -----------------------------------
#
# This variant exists to prove two registered variants can coexist and be
# evaluated side by side in one run. **It is not a proposal and must not be
# quoted as a model.** It differs from `component/1.0` in exactly one field, so
# any difference in its output is attributable to that field and nothing else.
#
# `mins_per_sub` 20.0 -> 20.5 was chosen for three properties, in this order:
# the half-minute is visibly arbitrary, so no reader could mistake it for a
# modelling claim; it is not a number anyone has argued about; and it still
# moves enough rows to prove the pipeline end to end. Measured against
# `~/fpl-pinned/gw2-pre-deadline.json` at GW3: 403 of 616 players change, by at
# most 0.013 xP.
#
# `doubtful_chance` was the first choice and was rejected on measurement: it
# changes **nothing at all** on that capture. All 17 `status="d"` players there
# publish a `chance_of_playing_next_round`, and `_availability` returns on that
# before it ever reaches the constant. A fixture that provably moves no number
# cannot demonstrate that the comparison path works.
#
# That constant is dead more widely than on one capture — 203 `status="d"`
# observations across 11 captures, none with a null percentage — and is filed
# as **FU-48**. Note what it would mean here: a variant setting `doubtful_chance`
# would earn a distinct digest and version string while projecting identically,
# which is two names for one model.
#
# Delete it once FU-47's real variants are registered, or keep it as the
# regression fixture for the multi-model path — but do not grow it.
COMPONENT_V1_FIXTURE_MINSUB = register(
    ModelVariant(
        name="component/1.0-fixture-minsub205",
        family="component",
        minutes=replace(COMPONENT_V1.minutes, mins_per_sub=20.5),
        strength=StrengthConfig(),
        rates=legacy_rate_config(),
        note=(
            "TEST FIXTURE, not a candidate model. component/1.0 with mins_per_sub "
            "20.0 -> 20.5. Exists to prove two variants can be compared in one run."
        ),
    )
)

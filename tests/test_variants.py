"""The model-variant registry and the derived version string.

Every assertion here was demonstrated failing against a mutation of the line it
covers before being kept — the mutation is named in each test's docstring.
"""

from __future__ import annotations

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.domain import variants
from fpl_cli.domain.projections import (
    SHRINKABLE_RATES,
    ComponentProjection,
    MinutesModelConfig,
    NaiveProjection,
    OfficialEpProjection,
    RatePrior,
    RateShrinkageConfig,
)
from fpl_cli.domain.strength import BandedTeamRates

# Pinned digests over every constant each registered variant holds.
#
# These are not decoration and they are not a checksum of the source: they are
# a hash of the *values*. If one moves, a constant moved with it, and the
# variant is no longer the model its name claims — which is the drift this
# whole module exists to close, and the reason `component/1.0+banded` could
# previously name four different models (variants.py's docstring measures them).
#
# When one fails, the fix is almost never to update the number. It is either to
# revert the constant, or to register a NEW variant under a new name and leave
# the old one alone. Re-pinning is correct only when the change provably cannot
# move a projection.
#
# component/1.0 and the fixture were re-pinned once, on task/fu-47-shrinkage
# (d72962d5977c -> fb431918c08c, d0737d604720 -> bd7ee99cd0aa). No constant
# moved: bonus shrinkage of 450 minutes toward zero stopped being hardcoded in
# `_component_points_for_fixture` and became an explicit `RatePrior` on the
# variant, so the digest covers something it previously could not see. The
# licence for that re-pin is that projections were verified byte-identical
# against the pinned capture across the change — sha256
# c3812c8cae30c609b41243f3a26dcc49450c8b03993604ffb6129470037a7412 over all
# 3080 rows, before and after.
EXPECTED_DIGESTS = {
    "component/1.0": "fb431918c08c",
    "naive/1.0": "1ad0cd721b2e",
    "official-ep/1.0": "a6d72770239f",
    "component/1.0-fixture-minsub205": "bd7ee99cd0aa",
    "component/1.1-price": "24c305e2025c",
    "component/1.1-position": "877dd43d6607",
    "component/1.2": "4f479b2253cc",
}

# `component/1.2` added a `structure` field to `ModelVariant` and **no digest
# above moved**. That is not luck: `as_dict` omits an identity
# `MinutesStructureConfig`, precisely so the six digests pinned before it —
# which minutes-model.md and fu-53-minutes-ceiling.md cite as the provenance of
# published figures — keep meaning what those documents say they mean. The
# alternative was re-pinning six digests to record a field none of the six sets.
# Verified alongside it: `component/1.1-price` projects byte-identically across
# this branch, sha256 over all 616 rows on ~/fpl-pinned/gw2-pre-deadline.json.

EXPECTED_VERSIONS = {
    "component/1.0": "component/1.0+banded",
    "naive/1.0": "naive/1.0",
    "official-ep/1.0": "official-ep/1.0",
    "component/1.0-fixture-minsub205": "component/1.0-fixture-minsub205+banded",
    "component/1.1-price": "component/1.1-price+banded",
    "component/1.1-position": "component/1.1-position+banded",
    "component/1.2": "component/1.2+banded",
}


def _fixtures(event: int = 3) -> list[Fixture]:
    return [
        Fixture(id=event * 10 + 1, event=event, team_h=1, team_a=2),
        Fixture(id=event * 10 + 2, event=event, team_h=3, team_a=4),
        Fixture(id=event * 10 + 3, event=event, team_h=5, team_a=1),
    ]


# --- The registry ------------------------------------------------------------


def test_registry_round_trips_every_variant_by_name() -> None:
    """`get(name)` returns the variant registered under that name, and `names()`
    lists exactly what is registered.

    Mutation: `get` returning `next(iter(_REGISTRY.values()))` passes a
    single-variant registry and fails here on the second.
    """
    assert set(variants.names()) == set(EXPECTED_DIGESTS)
    for name in variants.names():
        assert variants.get(name).name == name
    assert {v.name for v in variants.all_variants()} == set(variants.names())


def test_an_unknown_variant_names_what_is_registered() -> None:
    """Mutation: `raise KeyError(name)` alone still raises, but the message no
    longer lists the alternatives, and this fails on the second assertion."""
    with pytest.raises(KeyError) as excinfo:
        variants.get("component/9.9")
    assert "component/9.9" in str(excinfo.value)
    assert "component/1.0" in str(excinfo.value)


def test_registering_a_duplicate_name_is_refused() -> None:
    """Two variants under one name would make a quoted version string ambiguous
    in exactly the way this module exists to prevent.

    Mutation: dropping the membership check in `register` lets the second
    silently replace the first, and this stops raising.
    """
    with pytest.raises(ValueError, match="already registered"):
        variants.register(variants.ModelVariant(name="component/1.0", family="component"))


# --- The version string ------------------------------------------------------


def test_version_is_derived_from_the_variant_not_a_literal() -> None:
    """The `+strength` half comes from the strength config, and is absent for
    families that have none.

    Mutation: hardcoding `return "component/1.0+banded"` passes the component
    case and fails on naive; returning `self.name` alone fails on component.
    """
    assert {name: variants.get(name).version for name in variants.names()} == EXPECTED_VERSIONS

    renamed = variants.ModelVariant(
        name="component/test",
        family="component",
        strength=variants.StrengthConfig(name="dixon-coles"),
    )
    assert renamed.version == "component/test+dixon-coles"
    assert variants.ModelVariant(name="naive/test", family="naive").version == "naive/test"


def test_the_built_model_reports_its_variants_version() -> None:
    """The string on `Projection.model_version` is the variant's, not
    `projections.py`'s fallback literal.

    Mutation: dropping `version=variant.version` from `variants.build`'s
    `ComponentProjection` call falls back to the literal, which happens to
    equal it for `component/1.0` — so this test uses a variant whose version
    differs from the literal, and that mutation then fails.
    """
    snapshot = _snapshot()
    variant = variants.ModelVariant(
        name="component/version-probe",
        family="component",
        strength=variants.StrengthConfig(),
    )
    model = variants.build(variant, snapshot, _fixtures())
    assert model.name == "component/version-probe+banded"
    projection = model.project([3], [3])[(3, 3)]
    assert projection.model_version == "component/version-probe+banded"


# --- The drift guard ---------------------------------------------------------


def test_a_variants_constants_cannot_diverge_from_its_version_string() -> None:
    """The test the branch exists for.

    A variant's digest is a hash of every constant it holds. Pinning it here
    means a constant cannot move while the name stays put: either this fails,
    or the mover registered a new name.

    Mutation: changing any default in `MinutesModelConfig`, `DEFCON_THRESHOLDS`,
    `BAND_MULTIPLIERS` or `LEAGUE_MEAN_GOALS` moves `component/1.0`'s digest and
    fails here. Verified by hand for `shrinkage_k`, `doubtful_chance`,
    `DEFCON_THRESHOLDS["DEF"]` and `LEAGUE_MEAN_GOALS`.
    """
    assert {v.name: v.digest for v in variants.all_variants()} == EXPECTED_DIGESTS


def test_the_digest_covers_every_field_that_can_move_a_projection() -> None:
    """A digest that ignored a field would pin nothing about it.

    Each config below changes a projected number (measured in variants.py's
    docstring), so each must change the digest.

    Mutation: dropping `minutes`, `defcon_thresholds`, `strength` or `rates`
    from `as_dict` makes the corresponding case collide and fails.
    """
    base = variants.get("component/1.0")
    changed = [
        base.__class__(**{**_fields(base), "minutes": MinutesModelConfig(shrinkage_k=99.0)}),
        base.__class__(**{**_fields(base), "defcon_thresholds": {"DEF": 1, "MID": 1, "FWD": 1}}),
        base.__class__(**{**_fields(base), "strength": variants.StrengthConfig(league_mean_goals=9.9)}),
        base.__class__(
            **{
                **_fields(base),
                "rates": RateShrinkageConfig(rates={"xg": RatePrior(prior_minutes=270.0)}),
            }
        ),
    ]
    digests = [variant.digest for variant in changed]
    assert base.digest not in digests
    assert len(set(digests)) == len(digests)


def test_the_note_is_excluded_from_the_digest() -> None:
    """Prose about a variant is not part of the model. Requiring a re-pin to fix
    a typo would train people to update the expected digest without reading why
    it moved.

    Mutation: including `note` in `as_dict` fails this.
    """
    base = variants.get("component/1.0")
    assert base.__class__(**{**_fields(base), "note": "different prose"}).digest == base.digest


def _fields(variant: variants.ModelVariant) -> dict:
    return {
        "name": variant.name,
        "family": variant.family,
        "minutes": variant.minutes,
        "structure": variant.structure,
        "defcon_thresholds": variant.defcon_thresholds,
        "strength": variant.strength,
        "rates": variant.rates,
        "note": variant.note,
    }


# --- FU-47's config is expressible but refused --------------------------------


def test_a_variant_setting_rate_shrinkage_now_changes_projections() -> None:
    """The inverse of the test this replaces.

    Until FU-47 landed, `build` raised `NotImplementedError` for a variant
    carrying rate-shrinkage parameters, because nothing read them and a variant
    that silently projected identically would have been a lie. The parameters
    are consumed now, so the guarantee is demonstrated rather than refused: the
    same variant with and without shrinkage must project differently.

    Mutation: dropping `rate_config=variant.rates` from `variants.build`'s
    `ComponentProjection` call makes the two identical and fails here.
    """
    snapshot = _snapshot()
    fixtures = _fixtures()
    player_ids = [player.id for player in snapshot.elements]
    # Rates must differ between players, or the pooled prior equals every
    # player's own rate and shrinking toward it is a no-op — which is a
    # property of the fixture, not of the code, and cost this test one
    # false failure before it was noticed.
    for index, player in enumerate(snapshot.elements):
        player.minutes = 90
        rate = 0.1 * (index + 1)
        player.expected_goals_per_90 = rate
        player.expected_goals = rate  # count == rate at exactly 90 minutes

    base = variants.ModelVariant(
        name="component/probe-unshrunk", family="component", strength=variants.StrengthConfig()
    )
    shrunk = variants.ModelVariant(
        name="component/probe-shrunk",
        family="component",
        strength=variants.StrengthConfig(),
        rates=RateShrinkageConfig(rates={"xg": RatePrior(prior_minutes=270.0, prior_source="position")}),
    )
    a = variants.build(base, snapshot, fixtures).project(player_ids, [3])
    b = variants.build(shrunk, snapshot, fixtures).project(player_ids, [3])
    assert any(a[key].xp_attack != b[key].xp_attack for key in a)


def test_component_v1_carries_the_pre_fu47_rate_treatment_not_the_identity() -> None:
    """`component/1.0` is deliberately *not* the identity config.

    One of the seven rates was already shrunk before FU-47 — bonus, toward zero,
    over 450 minutes — and that lived in the body of
    `_component_points_for_fixture`. Registering it as a `RatePrior` is what
    keeps 1.0 byte-identical while making the odd choice visible: a
    `prior_source` of "zero" sitting beside six that are not.

    Mutation: registering component/1.0 with `RateShrinkageConfig()` drops the
    bonus shrinkage, fails here, and moves the pinned digest and every bonus
    figure with it.
    """
    rates = variants.get("component/1.0").rates
    assert not rates.is_identity
    assert set(rates.rates) == {"bonus"}
    assert rates.rates["bonus"].prior_minutes == 450.0
    assert rates.rates["bonus"].prior_source == "zero"

    # naive and official-ep read no rates at all, so theirs stay identity.
    assert variants.get("naive/1.0").rates.is_identity
    assert variants.get("official-ep/1.0").rates.is_identity


def test_is_identity_distinguishes_shrinkage_from_its_absence() -> None:
    """Mutation: `is_identity` returning a constant either way fails one arm."""
    assert RateShrinkageConfig().is_identity
    assert not RateShrinkageConfig(rates={"dc": RatePrior(prior_minutes=90.0)}).is_identity
    # A rate named at zero weight is still the identity — it names a rate
    # without shrinking it.
    assert RateShrinkageConfig(rates={"dc": RatePrior(prior_minutes=0.0)}).is_identity


def test_rate_config_rejects_an_unknown_rate_or_prior_source() -> None:
    """Mutation: dropping either `__post_init__` lets a typo'd rate name sit in
    a variant, contributing to its digest while affecting nothing."""
    with pytest.raises(ValueError, match="Unknown rate"):
        RateShrinkageConfig(rates={"xg90": RatePrior(prior_minutes=1.0)})
    with pytest.raises(ValueError, match="prior_source"):
        RatePrior(prior_source="vibes")
    with pytest.raises(ValueError, match="non-negative"):
        RatePrior(prior_minutes=-1.0)


# --- Equivalence with direct construction ------------------------------------


def _snapshot() -> BootstrapSnapshot:
    from conftest import _bootstrap_snapshot  # noqa: PLC0415

    return _bootstrap_snapshot()


@pytest.mark.parametrize("event", [3])
def test_registry_built_models_project_identically_to_direct_construction(event: int) -> None:
    """The infrastructure commit changes nothing observable.

    This is the synthetic-dataset counterpart of the pinned-capture check
    recorded in the branch's commit message: `component/1.0` built through the
    registry must equal `ComponentProjection(...)` built by hand, field by
    field, not merely in `xp_total`.

    Mutation: passing a non-default `minutes_config` in `build` — e.g.
    `MinutesModelConfig(doubtful_chance=0.5)` — diverges on any doubtful player
    and, for `p_start`, on every player at all.
    """
    snapshot = _snapshot()
    fixtures = _fixtures(event)
    player_ids = [player.id for player in snapshot.elements]

    pairs = [
        (
            ComponentProjection(snapshot, fixtures, BandedTeamRates(snapshot)),
            variants.build(variants.get("component/1.0"), snapshot, fixtures),
        ),
        (
            NaiveProjection(snapshot, fixtures),
            variants.build(variants.get("naive/1.0"), snapshot, fixtures),
        ),
    ]
    for direct, built in pairs:
        assert direct.project(player_ids, [event]) == built.project(player_ids, [event])
        assert direct.name == built.name


def test_official_ep_built_from_the_registry_matches_direct_construction() -> None:
    """Separate because it only projects the snapshot's own next event."""
    snapshot = _snapshot()
    next_event = next(gameweek.id for gameweek in snapshot.events if gameweek.is_next)
    fixtures = _fixtures(next_event)
    player_ids = [player.id for player in snapshot.elements]
    direct = OfficialEpProjection(snapshot, fixtures)
    built = variants.build(variants.get("official-ep/1.0"), snapshot, fixtures)
    assert direct.project(player_ids, [next_event]) == built.project(player_ids, [next_event])
    assert direct.name == built.name


def test_build_refuses_a_component_variant_with_no_strength_model() -> None:
    """`component`'s version string has a `+strength` half by construction, so a
    component variant without one could not produce a well-formed version.

    Mutation: defaulting to `StrengthConfig()` inside `build` when `strength is
    None` produces `component/no-strength` with no `+banded`, and this stops
    raising.
    """
    with pytest.raises(ValueError, match="names no strength model"):
        variants.build(
            variants.ModelVariant(name="component/no-strength", family="component"),
            _snapshot(),
            _fixtures(),
        )


def test_build_refuses_an_unknown_family_and_an_unknown_strength_model() -> None:
    """Mutation: a bare `else: return ComponentProjection(...)` in `build`
    silently treats every unknown family as a component model."""
    with pytest.raises(ValueError, match="unknown family"):
        variants.build(variants.ModelVariant(name="x/1.0", family="dixon-coles"), _snapshot(), _fixtures())
    with pytest.raises(ValueError, match="No strength model"):
        variants.build(
            variants.ModelVariant(
                name="component/dc", family="component", strength=variants.StrengthConfig(name="dixon-coles")
            ),
            _snapshot(),
            _fixtures(),
        )


# --- The fixture variant ------------------------------------------------------


def test_the_fixture_variant_differs_from_v1_in_exactly_one_field() -> None:
    """It exists to prove two variants can coexist, so its difference from
    `component/1.0` must be attributable to one field and nothing else.

    Mutation: changing a second field on the fixture — e.g. also setting
    `p_sub_appearance` — makes `differing` longer than one and fails.
    """
    base = variants.get("component/1.0")
    fixture = variants.get("component/1.0-fixture-minsub205")

    assert fixture.family == base.family
    assert fixture.defcon_thresholds == base.defcon_thresholds
    assert fixture.strength == base.strength
    assert fixture.rates == base.rates

    differing = [
        name
        for name in ("shrinkage_k", "start_priors", "mins_per_start_prior",
                     "p_sub_appearance", "mins_per_sub", "doubtful_chance",
                     "bonus_shrinkage_minutes")
        if getattr(fixture.minutes, name) != getattr(base.minutes, name)
    ]
    assert differing == ["mins_per_sub"]
    assert fixture.minutes.mins_per_sub == 20.5


def test_the_fixture_variant_actually_moves_projections() -> None:
    """A fixture that provably changed nothing could not demonstrate that the
    comparison path works — which is why `doubtful_chance` was rejected for the
    role (variants.py records the measurement).

    Mutation: registering the fixture with `mins_per_sub` unchanged at 20.0
    makes the two projections equal and fails here.
    """
    snapshot = _snapshot()
    fixtures = _fixtures()
    player_ids = [player.id for player in snapshot.elements]

    base = variants.build(variants.get("component/1.0"), snapshot, fixtures).project(player_ids, [3])
    other = variants.build(variants.get("component/1.0-fixture-minsub205"), snapshot, fixtures).project(
        player_ids, [3]
    )
    assert base.keys() == other.keys()
    assert any(base[key].xp_total != other[key].xp_total for key in base)
    assert {p.model_version for p in base.values()} == {"component/1.0+banded"}
    assert {p.model_version for p in other.values()} == {"component/1.0-fixture-minsub205+banded"}


def test_the_fixture_variant_is_labelled_as_one() -> None:
    """Its note must say so: the whole risk of a fixture in the registry is
    someone quoting it as a model.

    Mutation: emptying the note fails this.
    """
    assert "TEST FIXTURE" in variants.get("component/1.0-fixture-minsub205").note
    assert "fixture" in variants.get("component/1.0-fixture-minsub205").name


# --- Impersonation ------------------------------------------------------------


def test_an_unregistered_variant_cannot_impersonate_a_registered_name() -> None:
    """The defect this module closes, one level down.

    `ModelVariant` is an ordinary dataclass, so before the guard in `build` an
    unregistered variant could take a registered name, hold entirely different
    constants, and emit the identical version string — a string the registry
    blesses, so the digest test above would pass while the figure came from
    something else. Measured on the branch before the guard: an impostor
    `component/1.0` projected Haaland at GW3 as 2.993 against the registered
    3.430, both stamped `component/1.0+banded`.

    Mutation: dropping the `registered is not variant` check in `build` lets the
    impostor build and this stops raising. Weakening it to compare `.name` only
    (`registered.name != variant.name`) never fires at all, and also fails.
    """
    impostor = variants.ModelVariant(
        name="component/1.0",
        family="component",
        minutes=MinutesModelConfig(shrinkage_k=99.0),
        strength=variants.StrengthConfig(league_mean_goals=9.9),
    )
    # It really does collide on the version string — that is the whole problem,
    # and asserting it here stops the test passing for the wrong reason later.
    assert impostor.version == variants.get("component/1.0").version
    assert impostor.digest != variants.get("component/1.0").digest

    with pytest.raises(ValueError, match="registered variant"):
        variants.build(impostor, _snapshot(), _fixtures())


def test_the_registered_instance_itself_still_builds() -> None:
    """The guard must compare identity, not merely name-is-registered, or every
    real call would be refused.

    Mutation: `if registered is not None: raise` refuses `variants.get(...)`
    too and fails here — this is the control for the test above.
    """
    for name in variants.names():
        variant = variants.get(name)
        if variant.family == "official-ep":
            continue  # only projects the snapshot's own next event
        assert variants.build(variant, _snapshot(), _fixtures()) is not None


def test_an_unregistered_name_is_still_free() -> None:
    """Only impersonation is refused. A throwaway variant under a name nobody
    has registered must still build, or the negative cases above — and trying a
    variant before it earns a name — become impossible.

    Mutation: refusing any variant not in the registry fails here.
    """
    throwaway = variants.ModelVariant(
        name="component/scratch-not-registered",
        family="component",
        minutes=MinutesModelConfig(shrinkage_k=99.0),
        strength=variants.StrengthConfig(),
    )
    assert throwaway.name not in variants.names()
    model = variants.build(throwaway, _snapshot(), _fixtures())
    assert model.name == "component/scratch-not-registered+banded"


# --- FU-47's variants ---------------------------------------------------------


def test_the_two_11_variants_differ_only_in_the_attack_prior_source() -> None:
    """They are registered as a pair to be settled by evaluation, so any
    difference between them in a run must be attributable to price conditioning
    and to nothing else.

    Mutation: changing an M on one and not the other — or letting dc take
    `price_conditioned` in the price variant — makes `differing` longer than
    the two attack rates and fails.
    """
    price = variants.get("component/1.1-price").rates
    position = variants.get("component/1.1-position").rates

    assert price.band_prior_minutes == position.band_prior_minutes
    assert price.band_width == position.band_width
    assert set(price.rates) == set(position.rates)

    differing = sorted(
        rate for rate in price.rates if price.rates[rate] != position.rates[rate]
    )
    assert differing == ["xa", "xg"]
    for rate in differing:
        assert price.rates[rate].prior_source == "price_conditioned"
        assert position.rates[rate].prior_source == "position"
        assert price.rates[rate].prior_minutes == position.rates[rate].prior_minutes


def test_11_shrinks_all_seven_rates_including_the_two_fu47_missed() -> None:
    """Scope is six rates, seven knobs — cards splits into yellow and red.

    The two FU-47 did not name are the ones this asserts hardest: cards, which
    were built inline and so escaped a fix scoped to `*_per_90`; and bonus,
    whose prior moves from "zero" to "position" while its weight stays at
    today's 450.

    Mutation: dropping `yellow`, `red` or `bonus` from `_rate_config` leaves it
    unshrunk and fails here.
    """
    for name in ("component/1.1-price", "component/1.1-position"):
        rates = variants.get(name).rates
        assert set(rates.rates) == set(SHRINKABLE_RATES)
        assert all(prior.prior_minutes > 0 for prior in rates.rates.values())
        assert rates.rates["bonus"].prior_source == "position"
        assert rates.rates["bonus"].prior_minutes == 450.0
        assert rates.rates["yellow"].prior_source == "position"
        assert rates.rates["red"].prior_source == "position"


def test_dc_and_saves_are_never_price_conditioned() -> None:
    """§3.2 measured Spearman(price, dc90) between -0.06 and -0.32 and
    Spearman(price, saves90) at -0.087. Conditioning either on price would
    import noise, or signal with the wrong sign.

    Mutation: setting dc or saves to `price_conditioned` in `_rate_config`
    fails here for both variants.
    """
    for name in ("component/1.1-price", "component/1.1-position"):
        rates = variants.get(name).rates
        assert rates.rates["dc"].prior_source == "position"
        assert rates.rates["saves"].prior_source == "position"


def test_component_11_price_is_the_default_and_10_stays_registered() -> None:
    """The default moved to 1.1-price on task/default-1.1-and-preregistration.

    This test previously asserted the opposite — that 1.0 remained default until
    the GW2 evaluation supported a change. It is inverted rather than deleted
    because the pairing it guards is unchanged: exactly one component variant is
    the default, and `component/1.0` must stay *registered* whichever that is.
    Every figure measured before this branch is quoted against 1.0, and
    unregistering it would make them unreproducible.

    Mutation: pointing the `component` alias back at 1.0, or dropping 1.0 from
    the registry, fails here.
    """
    from fpl_cli import cli  # noqa: PLC0415

    assert cli._MODEL_ALIASES["component"] == "component/1.1-price"
    assert "component/1.1-price" in cli._DEFAULT_EVALUATE_MODELS
    assert "component/1.0" not in cli._DEFAULT_EVALUATE_MODELS
    # Still resolvable by full name, which is how the comparison is re-run.
    assert variants.get("component/1.0").name == "component/1.0"

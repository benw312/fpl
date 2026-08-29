"""The model-variant registry and the derived version string.

Every assertion here was demonstrated failing against a mutation of the line it
covers before being kept — the mutation is named in each test's docstring.
"""

from __future__ import annotations

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.domain import variants
from fpl_cli.domain.projections import (
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
EXPECTED_DIGESTS = {
    "component/1.0": "d72962d5977c",
    "naive/1.0": "1ad0cd721b2e",
    "official-ep/1.0": "a6d72770239f",
    "component/1.0-fixture-minsub205": "d0737d604720",
}

EXPECTED_VERSIONS = {
    "component/1.0": "component/1.0+banded",
    "naive/1.0": "naive/1.0",
    "official-ep/1.0": "official-ep/1.0",
    "component/1.0-fixture-minsub205": "component/1.0-fixture-minsub205+banded",
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
        "defcon_thresholds": variant.defcon_thresholds,
        "strength": variant.strength,
        "rates": variant.rates,
        "note": variant.note,
    }


# --- FU-47's config is expressible but refused --------------------------------


def test_a_variant_setting_rate_shrinkage_is_refused_rather_than_ignored() -> None:
    """The registry can express FU-47's variants (rate-shrinkage.md §7) but no
    model reads them yet. Building one must fail loudly: a variant that set
    `M_xg = 270` and projected identically to one that did not would be a worse
    lie than the drift this module closes.

    Mutation: dropping the `is_identity` check in `build` returns a model that
    silently ignores the parameters, and this stops raising.
    """
    variant = variants.ModelVariant(
        name="component/fu47-probe",
        family="component",
        strength=variants.StrengthConfig(),
        rates=RateShrinkageConfig(rates={"xg": RatePrior(prior_minutes=270.0, prior_source="price_conditioned")}),
    )
    with pytest.raises(NotImplementedError, match="rate-shrinkage"):
        variants.build(variant, _snapshot(), _fixtures())


def test_the_identity_rate_config_is_what_todays_variants_carry() -> None:
    """Mutation: `is_identity` returning `True` unconditionally makes the
    refusal above unreachable; returning `False` unconditionally breaks every
    registered variant. Both fail some assertion here.
    """
    for variant in variants.all_variants():
        assert variant.rates.is_identity
    assert RateShrinkageConfig().is_identity
    assert not RateShrinkageConfig(rates={"dc": RatePrior(prior_minutes=90.0)}).is_identity
    # A rate present at zero weight is still the identity — it names a rate
    # without shrinking it, which is what today's models do to all seven.
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

"""FU-47's guard, and the shrinkage function's own properties.

`docs/plans/rate-shrinkage.md` §8. The guard is the point of the file: a fifth
unshrunk rate already existed when the plan was written — `xp_cards` built its
own per-90 inline and so escaped a fix scoped to `*_per_90` fields — so this is
not a hypothesis about a sixth, it is a regression test for something that
already happened once.

Every assertion was demonstrated failing against a mutation of the line it
covers before being kept; the mutation is named in each docstring.
"""

from __future__ import annotations

import ast
import math
import pathlib
import random
from datetime import UTC, datetime

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, Player, Position
from fpl_cli.domain.projections import (
    RatePrior,
    RateShrinkageConfig,
    build_rate_priors,
    shrink_rate,
    shrunk_rates,
)

PROJECTIONS = pathlib.Path(__file__).resolve().parents[1] / "src" / "fpl_cli" / "domain" / "projections.py"

# The function that prices one fixture. Nothing inside it may read a rate off a
# player: rates arrive pre-shrunk on `_ShrunkRates`.
GUARDED_FUNCTION = "_component_points_for_fixture"

# The pre-FU-47 function, copied verbatim from `main` at 6c1fc91. Kept as a
# fixture so the guard is checked against the code it was written for rather
# than against a reconstruction of it.
PRE_FU47_SOURCE = '''
def _component_points_for_fixture(
    player: Player,
    position: str,
    scoring: dict[str, Any],
    minutes: _MinutesProbabilities,
    rates: MatchRates,
    league_mean_goals: float,
    defcon_thresholds: dict[str, int],
    bonus_shrinkage_minutes: float,
) -> _ComponentTuple:
    p1, p60, xmins = minutes.p1, minutes.p60, minutes.xmins
    frac = xmins / 90

    xp_appearance = (p1 - p60) * scoring["short_play"] + p60 * scoring["long_play"]

    attack_scale = rates.xg_for / league_mean_goals
    xp_attack = (
        player.expected_goals_per_90 * attack_scale * frac * scoring["goals_scored"][position]
        + player.expected_assists_per_90 * attack_scale * frac * scoring["assists"]
    )

    xp_clean_sheet = p60 * math.exp(-rates.xg_against) * scoring["clean_sheets"][position]

    xp_conceded = (
        sum(_poisson_pmf(k, rates.xg_against) * (k // 2) for k in range(13))
        * scoring["goals_conceded"][position]
        * frac
    )

    if position == "GKP":
        saves_lambda = player.saves_per_90 * frac * (rates.xg_against / league_mean_goals)
        xp_saves = _poisson_expected_floor_div(saves_lambda, 3) * scoring["saves"]
    else:
        xp_saves = 0.0

    threshold = defcon_thresholds.get(position)
    if threshold is None:
        xp_defcon = 0.0
    else:
        dc_lambda = player.defensive_contribution_per_90 * frac
        xp_defcon = _poisson_at_least(dc_lambda, threshold) * scoring["defensive_contribution"][position]

    raw_bonus_per_90 = player.bonus / (player.minutes / 90) if player.minutes > 0 else 0.0
    shrunk_bonus_per_90 = raw_bonus_per_90 * player.minutes / (player.minutes + bonus_shrinkage_minutes)
    xp_bonus = shrunk_bonus_per_90 * frac * scoring["bonus"]

    yellow_per_90 = player.yellow_cards / (player.minutes / 90) if player.minutes > 0 else 0.0
    red_per_90 = player.red_cards / (player.minutes / 90) if player.minutes > 0 else 0.0
    xp_cards = (yellow_per_90 * scoring["yellow_cards"] + red_per_90 * scoring["red_cards"]) * frac

    return (xp_appearance, xp_attack, xp_clean_sheet, xp_conceded, xp_saves, xp_defcon, xp_bonus, xp_cards)
'''


# --- §8.1 The guard ----------------------------------------------------------


def unshrunk_rate_reads(source: str, function_name: str) -> list[str]:
    """Every place `function_name` builds or reads a per-90 rate directly.

    Two shapes, because the defect arrived in two. Reported as `line: detail`
    strings and **all** of them, never just the first — FU-19's lesson is that
    a guard which sends you back once per site stops being used.
    """
    tree = ast.parse(source)
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    if target is None:
        raise AssertionError(f"{function_name} not found in projections.py — has it been renamed?")

    findings: list[str] = []
    for node in ast.walk(target):
        # (1) a published per-90 field read straight off an object
        if isinstance(node, ast.Attribute) and node.attr.endswith("_per_90"):
            base = node.value.id if isinstance(node.value, ast.Name) else "<expr>"
            findings.append(f"line {node.lineno}: reads {base}.{node.attr}")
        # (2) a rate built inline by dividing by minutes — how cards evaded FU-47
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            divisor = ast.dump(node.right)
            if "'minutes'" in divisor:
                findings.append(f"line {node.lineno}: divides by minutes to build a rate inline")
    return sorted(set(findings))


def test_no_unshrunk_rate_reaches_a_component() -> None:
    """The guard FU-47 asked for.

    Every rate must arrive on `_ShrunkRates`, computed once per player beside
    `_minutes_probabilities`. A seventh rate added later either goes through
    that struct or fails here by name.

    Mutation: restoring any one of the six original reads — e.g.
    `player.expected_goals_per_90` in `xp_attack`, or
    `player.yellow_cards / (player.minutes / 90)` in `xp_cards` — fails with
    that line named. Verified against the pre-FU-47 file, where it reports all
    six.
    """
    findings = unshrunk_rate_reads(PROJECTIONS.read_text(encoding="utf-8"), GUARDED_FUNCTION)
    assert not findings, (
        f"{GUARDED_FUNCTION} reads a rate that has not been shrunk:\n  " + "\n  ".join(findings)
    )


def test_the_guard_reports_every_site_in_the_real_pre_fu47_function() -> None:
    """The guard is only worth having if it would have caught the defect.

    `PRE_FU47_SOURCE` below is the body of `_component_points_for_fixture`
    copied verbatim from `main` before this branch, not a reconstruction — a
    hand-written approximation would prove only that the scanner catches what
    its author remembered to include.

    **Eight sites, not six.** The plan counts six *rates*; the guard counts
    *sites*, and they differ in two places: cards is two rates on two lines,
    and the bonus term touches `player.minutes` twice — once to build the raw
    rate and once to shrink it. The eighth is the pre-FU-47 shrinkage line
    itself, and flagging it is right: after the fix nothing in this function
    reads minutes at all, because rates arrive already shrunk.

    Mutation: `return findings[:1]` in the scanner, or dropping either shape
    from it, fails here.
    """
    findings = unshrunk_rate_reads(PRE_FU47_SOURCE, GUARDED_FUNCTION)
    per_90_reads = [f for f in findings if "_per_90" in f]
    inline_divisions = [f for f in findings if "divides by minutes" in f]

    assert len(findings) == 8, findings
    assert len(per_90_reads) == 4, per_90_reads
    assert len(inline_divisions) == 4, inline_divisions
    assert {f.split("reads ")[1] for f in per_90_reads} == {
        "player.expected_goals_per_90",
        "player.expected_assists_per_90",
        "player.saves_per_90",
        "player.defensive_contribution_per_90",
    }


def test_the_guard_names_the_function_if_it_is_renamed() -> None:
    """A guard that silently passes when its target vanishes guards nothing.

    Mutation: `next(..., None)` followed by `if target is None: return []`
    makes the scan vacuous on a rename, and this stops raising.
    """
    with pytest.raises(AssertionError, match="not found"):
        unshrunk_rate_reads("def something_else(): pass", GUARDED_FUNCTION)


# --- §8.3 §8.4 §8.5 the shrinkage function -----------------------------------


def test_the_two_algebraic_forms_agree() -> None:
    """§4.1 claims `raw·m/(m+M) + prior·M/(m+M)` and
    `(count + prior·M/90)/((m+M)/90)` are the same expression. Nothing else
    would catch them drifting apart if the implementation is rewritten into the
    count form for speed.

    Mutation: `(raw * minutes + prior * prior_minutes) / (minutes + prior)` —
    a plausible typo — fails at the fourth decimal on most random inputs.
    """
    rng = random.Random(20260830)
    for _ in range(500):
        raw = rng.uniform(0, 12)
        minutes = rng.uniform(1, 3400)
        prior = rng.uniform(0, 12)
        prior_minutes = rng.uniform(1, 3600)
        count = raw * minutes / 90
        count_form = (count + prior * prior_minutes / 90) / ((minutes + prior_minutes) / 90)
        assert shrink_rate(raw, minutes, prior, prior_minutes) == pytest.approx(count_form, abs=1e-12)


def test_limits_and_degenerate_inputs() -> None:
    """§8.4, with one resolution recorded.

    The plan asks both for "M = 0 -> exactly raw" and for "minutes = 0 and
    M = 0 -> prior". Those conflict. This resolves in favour of the first: M = 0
    means no shrinkage was requested, so the prior is irrelevant — and
    component/1.0's byte-identity depends on it.

    Mutation: dropping the `prior_minutes <= 0` early return makes `M = 0`
    return `raw * m / m`, which is not exactly `raw` in floating point and
    fails the first assertion for some inputs.
    """
    assert shrink_rate(1.72, 77.0, 0.083, 0.0) == 1.72  # M = 0 -> raw, exactly
    assert shrink_rate(1.72, 0.0, 0.083, 0.0) == 1.72  # both zero -> raw, never nan
    assert shrink_rate(9.9, 0.0, 0.42, 270.0) == pytest.approx(0.42)  # no minutes -> prior
    assert shrink_rate(9.9, 90.0, 0.42, 10**9) == pytest.approx(0.42, abs=1e-3)  # M huge -> prior
    assert not math.isnan(shrink_rate(0.0, 0.0, 0.0, 0.0))


def test_shrinkage_is_monotone_in_both_evidence_and_prior_weight() -> None:
    """"More evidence means more weight on the player's own rate", stated
    formally. This is what catches a sign error that the point tests pass.

    Mutation: swapping `raw` and `prior` in the numerator inverts both
    directions and fails.
    """
    rng = random.Random(1)
    for _ in range(200):
        prior = rng.uniform(0, 5)
        raw = prior + rng.uniform(0.1, 10)  # raw > prior
        minutes = rng.uniform(1, 3000)
        ms = sorted(rng.uniform(1, 3000) for _ in range(2))
        assert shrink_rate(raw, minutes, prior, ms[0]) >= shrink_rate(raw, minutes, prior, ms[1])
        mins = sorted(rng.uniform(1, 3000) for _ in range(2))
        weight = rng.uniform(1, 500)
        assert shrink_rate(raw, mins[0], prior, weight) <= shrink_rate(raw, mins[1], prior, weight)


# --- §8.6 §8.7 the priors ------------------------------------------------------


def _snapshot(players: list[Player]) -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=[],
        teams=[Club(id=1, name="Club 1", short_name="C1")],
        element_types=[Position(id=3, singular_name_short="MID", squad_select=5, squad_min_play=2, squad_max_play=5)],
        elements=players,
        raw={"game_config": {"scoring": {}}},
        fetched_at=datetime(2026, 8, 28, tzinfo=UTC),
        season="test",
    )


def _mid(pid: int, minutes: int, dc: int, now_cost: int = 50) -> Player:
    return Player(
        id=pid, web_name=f"P{pid}", team=1, element_type=3, now_cost=now_cost,
        minutes=minutes, defensive_contribution=dc,
        defensive_contribution_per_90=dc / (minutes / 90) if minutes else 0.0,
    )


def test_the_prior_is_pooled_by_exposure_not_averaged_over_ratios() -> None:
    """§3.1's lesson, and the one most likely to be undone by someone
    "simplifying" the prior computation.

    Five ordinary midfielders at 8 actions per 90, plus one who managed 3 in a
    single minute — a rate of 270. Pooling weights by exposure and barely
    notices him; averaging the ratios does not, and lands 43 higher.

    Mutation: computing the prior as `mean(count_i / (minutes_i/90))` gives
    ~51.6 and fails both assertions.
    """
    players = [_mid(i, 90, 8) for i in range(1, 6)] + [_mid(6, 1, 3)]
    priors = build_rate_priors(_snapshot(players), RateShrinkageConfig())
    pooled = priors.position[("dc", "MID")]

    expected = (5 * 8 + 3) / (5 * 90 + 1) * 90
    assert pooled == pytest.approx(expected)
    assert pooled == pytest.approx(8.58, abs=0.01)

    mean_of_ratios = sum(p.defensive_contribution_per_90 for p in players) / len(players)
    assert mean_of_ratios > 50  # the outlier dominates it
    assert abs(pooled - 8.0) < 1.0  # pooling barely moves off the honest rate


def test_a_thin_price_band_cannot_become_its_own_prior() -> None:
    """§3.3's Haaland-at-£15m case: a band holding one player, whose rate is far
    from the position rate, must not become that player's own prior — shrinking
    him toward it would leave him entirely unshrunk.

    Mutation: dropping the second-level shrink in `build_rate_priors` and
    storing `band_pooled` directly makes the band prior equal the loner's own
    30.0 and fails.
    """
    ordinary = [_mid(i, 900, 80, now_cost=50) for i in range(1, 11)]
    loner = _mid(99, 90, 30, now_cost=150)
    priors = build_rate_priors(_snapshot([*ordinary, loner]), RateShrinkageConfig(band_prior_minutes=900.0))

    position_prior = priors.position[("dc", "MID")]
    band_prior = priors.band[("dc", "MID", 150)]

    assert loner.defensive_contribution_per_90 == pytest.approx(30.0)
    assert abs(band_prior - position_prior) < abs(band_prior - 30.0)


# --- §8.2 bounded output under absurd input ----------------------------------


def test_alcaraz_shaped_input_is_bounded_by_the_prior() -> None:
    """The behavioural counterpart to the guard: the scan proves a rate went
    through shrinkage, this proves the shrinkage did something.

    One player with three defensive actions in one minute — a published rate of
    270 per 90 — among ordinary midfielders. Shrunk with M = 90 he must land
    near the position prior, not near 270.

    Mutation: `prior_minutes=0.0` on the dc rate leaves him at 270 and fails.
    """
    players = [_mid(i, 90, 8) for i in range(1, 11)] + [_mid(11, 1, 3)]
    snapshot = _snapshot(players)
    config = RateShrinkageConfig(rates={"dc": RatePrior(prior_minutes=90.0, prior_source="position")})
    priors = build_rate_priors(snapshot, config)

    absurd = snapshot.players_by_id[11]
    assert absurd.defensive_contribution_per_90 == pytest.approx(270.0)

    rates = shrunk_rates(absurd, "MID", priors, config)
    position_prior = priors.position[("dc", "MID")]
    assert rates.dc < 3 * position_prior
    assert rates.dc == pytest.approx((270.0 * 1 + position_prior * 90) / 91)

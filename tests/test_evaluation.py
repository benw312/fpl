from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl_cli.api.models import BootstrapSnapshot, ExplainEntry, ExplainStat, GameSettings, LiveElement, LiveEvent, Player
from fpl_cli.domain.evaluation import (
    CATEGORIES,
    COMPONENTS,
    ModelEvaluation,
    PlayerActual,
    _category,
    actuals_from_live_event,
    evaluate_model,
    flat_points_per_game_projections,
    select_archived_snapshot,
    spearman,
)
from fpl_cli.domain.projections import Projection
from fpl_cli.presentation import evaluation_table


def _projection(player: int, xp_total: float, **components: float) -> Projection:
    values = dict.fromkeys(COMPONENTS, 0.0)
    values.update(components)
    return Projection(
        player=player,
        event=1,
        xp_total=xp_total,
        p_start=1.0,
        xmins=90.0,
        fixtures=1,
        model_version="test",
        **values,
    )


def _actual(player: int, total_points: int, *, played: bool = True, **components: float) -> PlayerActual:
    values = dict.fromkeys(COMPONENTS, 0.0)
    values.update(components)
    return PlayerActual(player=player, total_points=total_points, played=played, component_points=values)


# --- RMSE / MAE, all vs played-only -------------------------------------------


def test_rmse_and_mae_over_all_players() -> None:
    projections = {1: _projection(1, 5.0), 2: _projection(2, 0.0)}
    actuals = {1: _actual(1, 2, played=True), 2: _actual(2, 0, played=False)}

    result = evaluate_model(projections, actuals, model_name="test")

    # errors: 5-2=3, 0-0=0
    assert result.rmse_all == pytest.approx((3.0**2 / 2) ** 0.5)
    assert result.mae_all == pytest.approx(1.5)


def test_rmse_and_mae_played_only_excludes_unplayed() -> None:
    projections = {1: _projection(1, 5.0), 2: _projection(2, 10.0)}
    actuals = {1: _actual(1, 2, played=True), 2: _actual(2, 0, played=False)}

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.n_played == 1
    assert result.mae_played == pytest.approx(3.0)  # only player 1's error


# --- Spearman ------------------------------------------------------------------


def test_spearman_perfect_agreement() -> None:
    assert spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)


def test_spearman_perfect_disagreement() -> None:
    assert spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_average_rank_tie_handling() -> None:
    # predicted has a tie at rank 1-2 (average 1.5); hand-computed expected value.
    assert spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.8660254, rel=1e-6)


def test_spearman_degenerate_inputs_return_zero() -> None:
    assert spearman([1.0], [1.0]) == 0.0
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0  # zero variance in predicted


def test_spearman_played_restricts_to_players_who_appeared() -> None:
    # Player 3 did not play. Over all three the model orders perfectly; over the
    # two who played it orders backwards. One number cannot say both.
    projections = {1: _projection(1, 2.0), 2: _projection(2, 6.0), 3: _projection(3, 0.0)}
    actuals = {
        1: _actual(1, 8, played=True),
        2: _actual(2, 3, played=True),
        3: _actual(3, 0, played=False),
    }

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.n_played == 2
    assert result.spearman_all == pytest.approx(0.5)
    assert result.spearman_played == pytest.approx(-1.0)


def test_spearman_played_ignores_the_didnt_play_split_that_inflates_spearman_all() -> None:
    """The confound the restricted column exists to expose.

    A model that predicts nothing but "who will feature" — a flat score for
    everyone who played, zero for everyone who did not — orders the full
    population well, because non-appearance is most of the ordering. It has no
    information at all about how much a player who features will score, and the
    restricted figure is what says so.
    """
    projections = {i: _projection(i, 5.0 if i <= 4 else 0.0) for i in range(1, 9)}
    actuals = {
        **{i: _actual(i, points, played=True) for i, points in zip(range(1, 5), (2, 6, 9, 13))},
        **{i: _actual(i, 0, played=False) for i in range(5, 9)},
    }

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.n_played == 4
    assert result.spearman_all > 0.9
    # Every played player got the same prediction: zero variance, no ordering.
    assert result.spearman_played == 0.0


def test_spearman_played_is_zero_when_nobody_played() -> None:
    # `spearman` returns 0.0 for n < 2 rather than raising, so an all-blank
    # gameweek reports 0.000 in the column instead of failing the run.
    projections = {1: _projection(1, 4.0), 2: _projection(2, 1.0)}
    actuals = {1: _actual(1, 0, played=False), 2: _actual(2, 0, played=False)}

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.n_played == 0
    assert result.spearman_played == 0.0


# --- Return categories ----------------------------------------------------------


@pytest.mark.parametrize(
    ("points", "expected"),
    [(0, "Zeros"), (-1, "Zeros"), (1, "Blanks"), (2, "Blanks"), (3, "Tickers"), (4, "Tickers"), (5, "Haulers"), (12, "Haulers")],
)
def test_category_boundaries(points: int, expected: str) -> None:
    assert _category(points) == expected


def test_category_breakdown_buckets_by_actual_points() -> None:
    projections = {1: _projection(1, 1.0), 2: _projection(2, 8.0)}
    actuals = {1: _actual(1, 0), 2: _actual(2, 6)}

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.categories["Zeros"].count == 1
    assert result.categories["Zeros"].mean_error == pytest.approx(1.0)
    assert result.categories["Haulers"].count == 1
    assert result.categories["Haulers"].mean_error == pytest.approx(2.0)
    assert result.categories["Blanks"].count == 0
    assert set(result.categories) == set(CATEGORIES)


# --- Per-component error --------------------------------------------------------


def test_component_error_is_signed_predicted_minus_actual_played_only() -> None:
    projections = {1: _projection(1, 5.0, xp_attack=3.0, xp_bonus=1.0)}
    actuals = {1: _actual(1, 5, played=True, xp_attack=2.0, xp_bonus=2.0)}

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.component_errors["xp_attack"] == pytest.approx(1.0)
    assert result.component_errors["xp_bonus"] == pytest.approx(-1.0)
    assert result.component_errors["xp_clean_sheet"] == pytest.approx(0.0)


def test_component_error_excludes_unplayed_players() -> None:
    projections = {1: _projection(1, 5.0, xp_attack=5.0)}
    actuals = {1: _actual(1, 0, played=False)}

    result = evaluate_model(projections, actuals, model_name="test")

    assert result.component_errors["xp_attack"] == 0.0  # empty list -> _mean([]) == 0.0


def test_actuals_from_live_event_maps_explain_identifiers_to_components() -> None:
    live = LiveEvent(
        elements=[
            LiveElement(
                id=1,
                stats={"total_points": 6, "played": True},
                explain=[
                    ExplainEntry(
                        fixture=1,
                        stats=[
                            ExplainStat(identifier="minutes", points=2, value=90),
                            ExplainStat(identifier="clean_sheets", points=4, value=1),
                            ExplainStat(identifier="goals_scored", points=0, value=0),
                        ],
                    )
                ],
            )
        ]
    )

    actuals = actuals_from_live_event(live)

    assert actuals[1].total_points == 6
    assert actuals[1].played is True
    assert actuals[1].component_points["xp_appearance"] == 2.0
    assert actuals[1].component_points["xp_clean_sheet"] == 4.0
    assert actuals[1].component_points["xp_attack"] == 0.0


def test_actuals_from_live_event_sums_double_gameweek_explain_entries() -> None:
    live = LiveEvent(
        elements=[
            LiveElement(
                id=1,
                stats={"total_points": 4, "played": True},
                explain=[
                    ExplainEntry(fixture=1, stats=[ExplainStat(identifier="minutes", points=2, value=90)]),
                    ExplainEntry(fixture=2, stats=[ExplainStat(identifier="minutes", points=2, value=90)]),
                ],
            )
        ]
    )

    actuals = actuals_from_live_event(live)

    assert actuals[1].component_points["xp_appearance"] == 4.0


def test_actuals_from_live_event_includes_points_modification() -> None:
    live = LiveEvent(
        elements=[
            LiveElement(
                id=1,
                stats={"total_points": 5, "played": True},
                explain=[
                    ExplainEntry(
                        fixture=1,
                        stats=[ExplainStat(identifier="bonus", points=1, value=1, points_modification=1)],
                    )
                ],
            )
        ]
    )

    actuals = actuals_from_live_event(live)

    assert actuals[1].component_points["xp_bonus"] == 2.0


# --- Flat baseline ---------------------------------------------------------------


def test_flat_baseline_is_undecomposed_and_ignores_fixtures_and_availability() -> None:
    snapshot = BootstrapSnapshot(
        events=[],
        teams=[],
        element_types=[],
        elements=[Player(id=1, web_name="P1", team=1, element_type=1, now_cost=50, points_per_game="4.5", status="i")],
        game_settings=GameSettings(),
        raw={},
        fetched_at=datetime.now(UTC),
        season="test",
    )

    projections = flat_points_per_game_projections(snapshot, event=2)

    assert projections[1].xp_total == pytest.approx(4.5)
    assert projections[1].model_version == "baseline/flat-ppg"
    assert projections[1].xp_attack == 0.0


# --- Archive selection -----------------------------------------------------------


def _touch(path: Path, *, mtime: datetime) -> None:
    path.write_text("{}", encoding="utf-8")
    import os

    ts = mtime.timestamp()
    os.utime(path, (ts, ts))


def test_select_archived_snapshot_picks_the_newest_before_the_deadline(tmp_path: Path) -> None:
    deadline = datetime(2026, 1, 10, tzinfo=UTC)
    older = tmp_path / "bootstrap-2026-01-05.json"
    newer = tmp_path / "bootstrap-2026-01-08.json"
    too_late = tmp_path / "bootstrap-2026-01-11.json"
    _touch(older, mtime=datetime(2026, 1, 5, tzinfo=UTC))
    _touch(newer, mtime=datetime(2026, 1, 8, tzinfo=UTC))
    _touch(too_late, mtime=datetime(2026, 1, 11, tzinfo=UTC))

    result = select_archived_snapshot(tmp_path, deadline)

    assert result == newer


def test_select_archived_snapshot_returns_none_when_directory_missing(tmp_path: Path) -> None:
    assert select_archived_snapshot(tmp_path / "does-not-exist", datetime(2026, 1, 1, tzinfo=UTC)) is None


def test_select_archived_snapshot_returns_none_when_nothing_qualifies(tmp_path: Path) -> None:
    too_late = tmp_path / "bootstrap-2026-01-11.json"
    _touch(too_late, mtime=datetime(2026, 1, 11, tzinfo=UTC))

    assert select_archived_snapshot(tmp_path, datetime(2026, 1, 1, tzinfo=UTC)) is None


# --- The evaluation table renders both Spearman columns -------------------------


def test_evaluation_table_renders_both_spearman_columns() -> None:
    """Guards the pairing, not the numbers.

    `spearman_all` and `spearman_played` are three-decimal floats in adjacent
    columns, so a renderer that dropped one or emitted the same value twice
    would look right in a table nobody diffed. Demonstrated failing against
    both mutations: removing the `spearman_played` column, and rendering
    `spearman_all` into it.
    """
    projections = {1: _projection(1, 2.0), 2: _projection(2, 6.0), 3: _projection(3, 0.0)}
    actuals = {
        1: _actual(1, 8, played=True),
        2: _actual(2, 3, played=True),
        3: _actual(3, 0, played=False),
    }
    evaluation = evaluate_model(projections, actuals, model_name="test")
    assert evaluation.spearman_all != pytest.approx(evaluation.spearman_played)

    table = evaluation_table([evaluation])

    headers = [column.header for column in table.columns]
    assert headers.count("Spearman") == 1
    assert "Spearman (played)" in headers
    rendered = [list(column.cells) for column in table.columns]
    assert rendered[headers.index("Spearman")] == [f"{evaluation.spearman_all:.3f}"]
    assert rendered[headers.index("Spearman (played)")] == [f"{evaluation.spearman_played:.3f}"]

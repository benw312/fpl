"""The projection evaluation harness (docs/plans/projections-v1.md Decision 6).

Scores any model's `{player_id: Projection}` output for one event against
that event's actual `LiveEvent` data: RMSE/MAE (over all players and over
`stats.played` only), Spearman rank correlation (likewise over both
populations), a return-category error breakdown, and per-component error via
`explain`. Also selects the archived
snapshot a leak-free evaluation must project from.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot, LiveElement, LiveEvent, Player
from fpl_cli.storage import capture
from fpl_cli.domain.projections import Projection

# The eight components, in the order they're reported.
COMPONENTS: tuple[str, ...] = (
    "xp_appearance",
    "xp_attack",
    "xp_clean_sheet",
    "xp_conceded",
    "xp_saves",
    "xp_defcon",
    "xp_bonus",
    "xp_cards",
)

# explain[].stats[].identifier -> our component. Identifiers with no
# corresponding component (own_goals, penalties_saved/missed, bps, ...) are
# left unmapped: their actual points never enter any component's error, only
# the whole-total error captured by rmse_all/mae_all.
IDENTIFIER_TO_COMPONENT: dict[str, str] = {
    "minutes": "xp_appearance",
    "goals_scored": "xp_attack",
    "assists": "xp_attack",
    "clean_sheets": "xp_clean_sheet",
    "goals_conceded": "xp_conceded",
    "saves": "xp_saves",
    "defensive_contribution": "xp_defcon",
    "bonus": "xp_bonus",
    "yellow_cards": "xp_cards",
    "red_cards": "xp_cards",
}

# The survey's OpenFPL yardstick, bucketed on ACTUAL points.
CATEGORIES: tuple[str, ...] = ("Zeros", "Blanks", "Tickers", "Haulers")


def _category(total_points: int) -> str:
    if total_points <= 0:
        return "Zeros"
    if total_points <= 2:
        return "Blanks"
    if total_points <= 4:
        return "Tickers"
    return "Haulers"


@dataclass(frozen=True)
class PlayerActual:
    player: int
    total_points: int
    played: bool
    component_points: dict[str, float]


def _actual_component_points(element: LiveElement) -> dict[str, float]:
    totals = dict.fromkeys(COMPONENTS, 0.0)
    for entry in element.explain:
        for stat in entry.stats:
            component = IDENTIFIER_TO_COMPONENT.get(stat.identifier)
            if component is not None:
                totals[component] += stat.points + stat.points_modification
    return totals


def actuals_from_live_event(live: LiveEvent) -> dict[int, PlayerActual]:
    return {
        element.id: PlayerActual(
            player=element.id,
            total_points=int(element.stats.get("total_points", 0)),
            played=bool(element.stats.get("played", False)),
            component_points=_actual_component_points(element),
        )
        for element in live.elements
    }


# --- Metrics -----------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rmse(errors: list[float]) -> float:
    return math.sqrt(_mean([error * error for error in errors])) if errors else 0.0


def _mae(errors: list[float]) -> float:
    return _mean([abs(error) for error in errors])


def _ranks(values: list[float]) -> list[float]:
    """1-indexed ranks with average-rank tie handling."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def spearman(predicted: list[float], actual: list[float]) -> float:
    """Spearman rank correlation. [No scipy — see Decision 6.]"""
    n = len(predicted)
    if n < 2:
        return 0.0
    rank_predicted = _ranks(predicted)
    rank_actual = _ranks(actual)
    mean_predicted = _mean(rank_predicted)
    mean_actual = _mean(rank_actual)
    covariance = sum((p - mean_predicted) * (a - mean_actual) for p, a in zip(rank_predicted, rank_actual))
    variance_predicted = sum((p - mean_predicted) ** 2 for p in rank_predicted)
    variance_actual = sum((a - mean_actual) ** 2 for a in rank_actual)
    if variance_predicted == 0 or variance_actual == 0:
        return 0.0
    return covariance / math.sqrt(variance_predicted * variance_actual)


# --- The report ----------------------------------------------------------------


@dataclass(frozen=True)
class CategoryStats:
    count: int
    mean_error: float  # predicted - actual, signed
    mae: float


@dataclass(frozen=True)
class ModelEvaluation:
    model_name: str
    n_players: int
    n_played: int
    rmse_all: float
    mae_all: float
    rmse_played: float
    mae_played: float
    spearman_all: float
    # Spearman over `stats.played` only. Reported beside `spearman_all` rather
    # than replacing it, because the two answer different questions and the
    # difference between them is itself the diagnostic.
    #
    # `spearman_all` ranks all elements, and in a typical gameweek over half of
    # them score zero because they did not play. Non-appearance is highly
    # persistent week to week, so a model that merely extrapolates last week's
    # points gets most of that ordering right without projecting anything —
    # which inflates it relative to a model that tries to predict *how much* a
    # player who features will score. The restricted figure removes the
    # played/didn't-play split from the comparison and asks only how well the
    # model orders players who actually appeared.
    #
    # Neither is the truer number. `spearman_all` is the right metric for a
    # question that includes "will this player feature at all", which squad
    # selection genuinely does; `spearman_played` is the right one for "given
    # they feature, who scores more". Quoting either alone hides half of it.
    spearman_played: float
    categories: dict[str, CategoryStats]
    # Signed mean error per component, over played players only — unplayed
    # players contribute ~0 to every component in both predicted and actual,
    # which would dilute the signal this breakdown exists to surface.
    component_errors: dict[str, float]


def evaluate_model(
    projections: Mapping[int, Projection], actuals: Mapping[int, PlayerActual], *, model_name: str
) -> ModelEvaluation:
    player_ids = sorted(set(projections) & set(actuals))

    errors_all: list[float] = []
    errors_played: list[float] = []
    predicted_all: list[float] = []
    actual_all: list[float] = []
    predicted_played: list[float] = []
    actual_played: list[float] = []
    category_errors: dict[str, list[float]] = {category: [] for category in CATEGORIES}
    component_errors: dict[str, list[float]] = {component: [] for component in COMPONENTS}

    for player_id in player_ids:
        projection = projections[player_id]
        actual = actuals[player_id]
        error = projection.xp_total - actual.total_points

        errors_all.append(error)
        predicted_all.append(projection.xp_total)
        actual_all.append(float(actual.total_points))
        category_errors[_category(actual.total_points)].append(error)

        if actual.played:
            errors_played.append(error)
            predicted_played.append(projection.xp_total)
            actual_played.append(float(actual.total_points))
            for component in COMPONENTS:
                component_errors[component].append(getattr(projection, component) - actual.component_points[component])

    return ModelEvaluation(
        model_name=model_name,
        n_players=len(player_ids),
        n_played=len(errors_played),
        rmse_all=_rmse(errors_all),
        mae_all=_mae(errors_all),
        rmse_played=_rmse(errors_played),
        mae_played=_mae(errors_played),
        spearman_all=spearman(predicted_all, actual_all),
        spearman_played=spearman(predicted_played, actual_played),
        categories={
            category: CategoryStats(count=len(errors), mean_error=_mean(errors), mae=_mae(errors))
            for category, errors in category_errors.items()
        },
        component_errors={component: _mean(errors) for component, errors in component_errors.items()},
    )


# --- The flat baseline (Decision 6) — not one of projections.py's three ------
# shipped models; an evaluation-only floor, per projections.md's decision
# rule: if v1 fails to beat this, fix minutes before adding model complexity.


def flat_points_per_game_projections(snapshot: BootstrapSnapshot, event: int) -> dict[int, Projection]:
    """`xp_total = points_per_game`, with no fixture or availability
    adjustment at all — distinct from (and simpler than) `NaiveProjection`,
    which already scales by both.
    """

    def _projection(player: Player) -> Projection:
        points_per_game = float(player.points_per_game or "0.0")
        return Projection(
            player=player.id,
            event=event,
            xp_total=points_per_game,
            xp_appearance=points_per_game,
            xp_attack=0.0,
            xp_clean_sheet=0.0,
            xp_conceded=0.0,
            xp_saves=0.0,
            xp_defcon=0.0,
            xp_bonus=0.0,
            xp_cards=0.0,
            p_start=1.0,
            xmins=90.0,
            fixtures=1,
            model_version="baseline/flat-ppg",
            assumptions=(
                "undecomposed: entire xp_total placed in xp_appearance; "
                "no fixture or availability adjustment at all",
            ),
        )

    return {player.id: _projection(player) for player in snapshot.elements}


# --- Archive selection (Decision 6) -------------------------------------------


def archived_capture_time(bootstrap_path: Path) -> datetime:
    """When the archived snapshot at `bootstrap_path` was captured.

    A capture directory answers from its manifest, which records the fetch. A
    bare file can only answer with its mtime, which is all it has. The
    difference is not academic: an ad-hoc capture is written hours after the
    day it belongs to, and copying a capture rewrites every mtime in it while
    changing nothing about when the data was fetched.
    """
    if bootstrap_path.name == capture.BOOTSTRAP_FILENAME:
        try:
            return capture.manifest_captured_at(capture.read_manifest(bootstrap_path.parent))
        except (OSError, ValueError):
            pass
    return datetime.fromtimestamp(bootstrap_path.stat().st_mtime, UTC)


def _archive_candidates(archive_dir: Path, *, include_adhoc: bool = False) -> list[tuple[datetime, Path]]:
    """Every archived bootstrap-static payload, with the time it was captured.

    Two shapes coexist and both are read (FU-41). A capture directory is dated
    by its manifest's `captured_at`, which is the fetch time and survives a
    copy. A bare `bootstrap-YYYY-MM-DD.json` — the four archives written before
    FU-41, one of which is the only pre-deadline capture for GW2 — is dated by
    mtime, because that is all it records. A directory whose manifest is
    missing or unreadable is skipped rather than raising: here it is one
    unusable candidate among others, not the file the run was told to use.

    Ad-hoc captures are excluded: they are the second and later captures of a
    day, kept on disk and readable through `--snapshot`, but not something
    automatic selection should silently prefer over the day's canonical one. A
    version 1 manifest records no role and reads as ad-hoc, which is why the
    bare `bootstrap-2026-08-28.json` still holds that day against the directory
    written beside it.
    """
    candidates: list[tuple[datetime, Path]] = [
        (datetime.fromtimestamp(path.stat().st_mtime, UTC), path)
        for path in archive_dir.glob("bootstrap-*.json")
        if path.is_file()
    ]
    for directory in sorted(archive_dir.iterdir()):
        if not directory.is_dir() or capture.QUARANTINE_INFIX in directory.name:
            continue
        bootstrap = directory / capture.BOOTSTRAP_FILENAME
        if not bootstrap.is_file():
            continue
        try:
            manifest = capture.read_manifest(directory)
            captured_at = capture.manifest_captured_at(manifest)
        except (OSError, ValueError):
            continue
        if not include_adhoc and capture.manifest_role(manifest) != capture.ROLE_CANONICAL:
            continue
        candidates.append((captured_at, bootstrap))
    return candidates


def select_archived_snapshot(
    archive_dir: Path, deadline: datetime, *, include_adhoc: bool = False
) -> Path | None:
    """The newest canonical archived snapshot captured before `deadline`.

    None if the directory doesn't exist or nothing qualifies — the caller
    falls back to the current snapshot and must disclose that the result is
    optimistic, not a backtest (Decision 6).
    """
    if not archive_dir.is_dir():
        return None
    qualifying = [
        (when, path)
        for when, path in _archive_candidates(archive_dir, include_adhoc=include_adhoc)
        if when < deadline
    ]
    if not qualifying:
        return None
    return max(qualifying, key=lambda candidate: candidate[0])[1]

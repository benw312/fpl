"""`tools/forecast_prize.py`'s isotonic recalibration (oracle B).

B claims to change prediction size and nothing else, so the fit must never
reverse the model's order and must never split tied predictions. Those are the
two properties a bound on "magnitudes only" rests on. Every test was run against
its named mutation first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from forecast_prize import isotonic  # noqa: E402


def test_the_fit_is_the_textbook_pool_adjacent_violators_answer() -> None:
    """Mutation: dropping the merge loop (the fit is then the raw actuals)."""
    assert isotonic([1, 2, 3, 4], [1, 3, 2, 4]) == [1, 2.5, 2.5, 4]


def test_the_fit_never_reverses_the_models_order() -> None:
    """Mutation: flipping the violation test to `<`, which merges toward a
    decreasing fit."""
    predicted = [0.1, 0.5, 0.2, 0.9, 0.7, 0.3]
    fitted = isotonic(predicted, [5, 0, 3, 1, 8, 2])
    by_prediction = [value for _, value in sorted(zip(predicted, fitted, strict=True))]
    assert by_prediction == sorted(by_prediction)


def test_tied_predictions_share_one_fitted_value() -> None:
    """Mutation: removing the tie pre-merge, so two equal predictions whose
    outcomes differ get different fitted values and the ranking gains
    information the model did not have."""
    fitted = isotonic([1.0, 1.0, 2.0], [0, 6, 9])
    assert fitted[0] == fitted[1] == 3.0
    assert fitted[2] == 9.0


def test_the_expected_conceded_penalty_matches_the_models_own_sum() -> None:
    """Oracles F and H swap the realised conceded points for E[floor(k/2)],
    k ~ Poisson(xGC). It must be the same quantity the model computes for its own
    `xp_conceded`, or the swap would change more than the luck.

    Mutation: `k // 3` (or any other unit) in `_poisson_floor_half`."""
    from fpl_cli.domain.projections import _poisson_pmf  # noqa: PLC0415
    from forecast_prize import _poisson_floor_half  # noqa: PLC0415

    for rate in (0.0, 0.4, 1.3, 2.9):
        expected = sum(_poisson_pmf(k, rate) * (k // 2) for k in range(25))
        assert abs(_poisson_floor_half(rate) - expected) < 1e-12

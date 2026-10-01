# Forecast prize bounds — results

**2026-10-01.** Plan: [forecast-prize-bounds.md](forecast-prize-bounds.md). Harness:
`tools/forecast_prize.py`, which reuses FU-72's state, scoring and settled-only rule.
Pinned GW2–GW5 trios are as in fu-72-results.md. **Every row is an oracle**, and none
is a criterion.

## 1 — Realised points of the default search's plan, against P0 (1.2 as shipped)

| oracle | what it knows | GW2–4 | GW3–5 | share of O1's prize |
|---|---|---|---|---|
| P0 | `component/1.2` as shipped | 231 | 211 | — |
| A | **who plays**: realised minutes, model rates (1.1-price) | +1 | −16 | ~0% |
| B | **prediction size**: 1.2 isotonically recalibrated, in-sample | 0 | +1 | ~0% |
| C | **`ep_next`**, replicated across the window | +5 | −53 | negative |
| **D** | **who hauls**: model appearance term + realised everything else | **+91** | **+103** | **~99%** |
| **E** | **chance quality**: D, with goals and assists → realised xG/xA | **+69** | **+74** | **~73%** |
| O1 | perfect forecast | +91 | +105 | 100% |

A's −16 against P0 is −7 against its own base, `1.1-price` (202 in FU-72 §3).

## 2 — The same forecasts, by the evaluation metrics (first gameweek of each window)

| oracle | `spearman_played` | `spearman_all` |
|---|---|---|
| P0 | 0.39, 0.35 | 0.60, 0.70 |
| A — who plays | **0.56, 0.53** | **0.88, 0.93** |
| B | 0.42, 0.40 | 0.63, 0.73 |
| D — who hauls | 0.91, 0.91 | 0.70, 0.78 |
| E — chance quality | 0.86, 0.80 | 0.76, 0.81 |

B's Spearman moves at all only because isotonic pooling creates ties. It never
reverses an order (`tests/test_forecast_prize.py`).

## 3 — What this says

1. **Every candidate on the 2026-09-23 shortlist is worth about nothing in points.**
   Knowing exactly who plays (A), perfect calibration of size (B) and FPL's own
   `ep_next` (C) each moved the plan by between −53 and +5 points.
2. **The whole prize is in the rate half: who hauls when they play.** D recovers
   99% of the perfect forecast while keeping the model's own uncertainty about
   minutes.
3. **Most of it survives removing finishing luck.** E keeps about 73%, and that is
   chance quality, which a model can in principle predict. It is still a ceiling:
   E knows each match's realised xG, and no pre-match model will.
4. **Spearman cannot see this.** A lifts `spearman_all` from about 0.65 to about
   0.90 and earns no points. Every pre-registration so far (FU-50, FU-60, FU-73,
   FU-74) was judged on a metric that rewards the half of the forecast that does
   not move the plan. `spearman_played` points the right way (D 0.91, A 0.55), but
   A still lifts it substantially for nothing.

`[gap: one starting squad and two windows, as in FU-72. Directions are separated by
about 70 points or more, so the ranking A ≈ B ≈ C ≪ E < D is robust to that; the
exact shares are not.]`

`[gap: why A is worth nothing is inferred, not measured. The planner's targets are
mostly nailed starters already, so knowing who plays changes the bench and the
fringe, not the moves. A per-transfer decomposition would test that.]`

## 4 — Consequences

- **Model work should go to the attacking rate half:** per-match xG and xA
  expectation. That means who gets chances, in which fixture, and on set pieces and
  penalties. The minutes model, calibration and `ep_next` should all be parked.
- **The criterion should be points, not Spearman.** A points criterion needs more
  than FU-72's single squad to be stable: several starting squads and every settled
  window. That is the first thing to design.

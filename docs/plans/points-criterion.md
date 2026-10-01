# A points-based criterion — plan

**Status: plan, 2026-10-01.** Ben's choice: design and pre-register a points-based
criterion **before** any further model work, because the prize bounds
(forecast-prize-results.md) show Spearman cannot see where the points are. The target
is a pre-registration naming GW8 onwards, committed before GW8's deadline of
2026-10-23T17:30Z.

## 1 — What gets measured

**For one model, one window and one starting squad:** the realised points of the
plan that the default search produces from that model's forecast, minus the realised
points of holding the squad. This is FU-72's P − HOLD. The window is three
gameweeks; the state is one free transfer at the start; the scoring is
`apply_transfers` plus best XI and captain under the actuals.

**Across many squads:** one squad is too noisy (FU-72 §2's gap). The harness draws
**N legal starting squads per window, by ownership-weighted sampling** from the
window's pre-deadline capture:
- Positions are filled by sampling players with probability proportional to
  `selected_by_percent`.
- A squad is rejected if it breaks the club limit or the budget.
- Every squad must pass `validate_squad_structure`.
- The seed is fixed.

The squads are realistic managers' teams rather than uniform noise, and they are the
same for every model in a window, so model comparisons are **paired**.

**The statistic:** for candidate X against incumbent Y, the mean over squads of
`(X − HOLD) − (Y − HOLD)`, which is simply `X − Y`, per window.

## 2 — The noise study (development, GW2–GW5, existing variants only)

Run on windows GW2–4 and GW3–5, with `naive/1.0`, `component/1.1-price` and
`component/1.2`:

- **Discrimination:** does it separate naive from 1.2? FU-72 §3 says it should,
  clearly.
- **Noise:** the standard deviation of the paired difference across squads, and how
  the mean's standard error shrinks with N. This chooses N by cost and precision, not
  by any candidate's figure.
- **Stability:** do the two windows agree in sign?

No candidate model exists while this runs, so nothing here can be tuned toward one.

## 3 — Choices left to Ben, informed by §2

- **N** (squads per window), from the noise curve and the cost: about 40 s per plan,
  parallel across 8 cores.
- **Legs:** overlapping windows (GW8–10 and GW9–11, decided after GW11) or disjoint
  ones (GW8–10 and GW11–13, decided after GW13). Overlap is faster but the legs
  share a gameweek, so they are not independent.
- **Threshold:** strictly positive mean in each leg (FU-50 style), or a mean beyond
  some multiple of its standard error. The second would be a chosen constant, so it
  is Ben's to set, not mine.

## 4 — Deliverables

1. `tools/points_criterion.py`: squad sampler, parallel runner, paired statistics.
   It reuses `fu72_plan_oracle.realise` and `path_plan`.
2. Tests for the sampler: legality, determinism under a seed, and the
   ownership-weighted property.
3. `docs/plans/points-criterion-noise.md`: the §2 results.
4. A draft pre-registration, FU-75, with §3's choices marked for Ben.

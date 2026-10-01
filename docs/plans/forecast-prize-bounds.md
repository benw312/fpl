# Bounding the prize for the next forecast direction

**Status: plan, 2026-10-01.** Ben asked to choose the next forecast direction (handoff
2026-09-23 §3) with time to do it properly. **This is measurement only.** It bounds
each candidate's prize before anything is built, following FU-53. Nothing here
changes a model, a default or a criterion. Every run is an oracle that has seen the
results, so it lives in `tools/`.

## The question

FU-72 showed that the search is close to exact and the forecast is the prize: about
+90 to +105 realised points over a three-gameweek window, between the 1.2 forecast
and a perfect one. **How much of that could each candidate direction capture, at
best?**

| | candidate | its oracle (best case) |
|---|---|---|
| A | "Will he play": P(plays) and minutes | `component/1.1-price` with **realised minutes** substituted, rates untouched (`fu53_minutes_oracle.py`'s `full` mode, per event) |
| B | Prediction size: FU-62 compression, FU-63 scale | 1.2's xP **isotonically recalibrated to realised points**, per event, in-sample. The ranking is unchanged by construction, so this is the prize from magnitudes alone |
| C | Blending `ep_next` | FPL's own `ep_next`, **replicated across the window**, because FPL publishes no further horizon. A crude proxy, flagged as such |

**Measures, per window:**
- Realised points of the default search's plan (FU-72's P-runs).
- `spearman_played` and `spearman_all` at the window's first gameweek.

**Windows:** GW2–4 and GW3–5 (same squad and state as FU-72).

**How to read it.** A's and B's numbers are ceilings; a real fix captures some
fraction of them. C's is a proxy for a cheap, real change, not a ceiling. Compare
each against P0 (1.2: 231, 211) and the perfect forecast (O1: 322, 316).
`[gap: one starting squad, two windows; this ranks directions, it does not size
them precisely.]`

## Deliverable

`tools/forecast_prize.py`, reusing `fu72_plan_oracle` (scoring, state) and
`fu53_minutes_oracle` (substitution), with no new expression of the model. Results go
in `docs/plans/forecast-prize-results.md`. Then Ben chooses a direction, and that
choice gets its own pre-registration naming GW8 and GW9.

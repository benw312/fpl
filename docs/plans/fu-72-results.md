# FU-72 — results: where the optimiser's output loses points

**2026-09-22.** Harness `tools/fu72_plan_oracle.py`; plan
[fu-72-plan-scoring.md](fu-72-plan-scoring.md). Pinned inputs are the GW2–GW5 trios
already cited in model-1.3.md §7 and gw5-evaluation.md §1. The harness prints a hash
prefix for each input as it loads them. `component/1.2` is at digest
`4f479b2253cc`. The strength model is the difficulty band throughout.

**Measured, not decided.** Per FU-72's closing gap, nothing here changes a default.

---

## 1 — Realised points over the window

| run | what | GW2–4 | GW3–5 |
|---|---|---|---|
| HOLD | no transfers | 233 | 188 |
| **P0** | **the program as shipped** (1.2 forecast, default search) | **231** | **211** |
| O1 | same search, perfect forecast | 322 | 316 |
| O2 | + decay 1.0, ft_value 0 | 322 | 315 |
| O3 | + hit cap removed | 322 | 315 |
| O4 | + beam 50, first moves 400 | 325 | 316 |
| **M2** | **exact optimum, ≤ 2 transfers a gameweek** | **325** | **316** |
| **M∞** | **exact optimum, full transfer rules** | **389** | **381** |

**The MILP was checked against shipped code, both windows, both caps.** Each plan
was replayed through `apply_transfers`: every event validated, and the replayed score
equalled the MILP's objective exactly. Solve times were 1–4 s.

## 2 — The decomposition, by FU-72 §1's causes

| cause | difference | GW2–4 | GW3–5 |
|---|---|---|---|
| **The forecast** | O1 − P0 | **+91** | **+105** |
| 1 + 5: decay and terminal value | O2 − O1 | 0 | −1 |
| 6: the default hit cap, `max_hit = 4` (new) | O3 − O2 | 0 | 0 |
| 4: the beam | M2 − O3 | +3 | +1 |
| 4, cross-check: wide beam against the optimum | M2 − O4 | 0 | 0 |
| 3: at most two transfers a gameweek | M∞ − M2 | +64 | +65 |
| 2: chips | — | *not measured* | *not measured* |
| **Headline: shipped plan against the best achievable** | M∞ − P0 | **158** | **170** |

### What this says

- **The search is not where points are lost.** Within its own move space, the
  planner fed a perfect forecast came within **3 points** (GW2–4) and **0–1** (GW3–5, O1 and O3) of the exact
  optimum. Decay, the terminal free-transfer value and the hit cap moved nothing
  measurable (0, −1, 0). The −1 is almost certainly beam path dependence:
  changing the decay reorders what the beam keeps. Under a perfect forecast, with
  decay 1.0 and ft_value 0, a path's score *is* its realised total, so an aligned
  objective cannot prefer a worse plan it can see. **FU-72's worry,
  "are we polishing the wrong half?", is answered no.** The optimiser is close to
  exact for what it is given. **Widening the beam closes the rest:** O4 reaches the
  exact optimum in both windows. But each O4 run took **about 4.1 hours** (14,793 s
  and 14,861 s). FU-72 §2 estimated about 54 minutes from `optimizer.py`'s expansion
  formula, so the formula understates wall time at this width by about 4.5×. Beam 4
  is the right default: it costs at most 3 points for about 1/370th of the time.
- **The forecast is where the points are.** A perfect forecast is worth **+91 and
  +105** to the planner as built: about **60%** of the headline gap in each window.
- **The shipped program barely beats doing nothing.** P0 − HOLD is **−2 and +23**.
  Its plans gave up 2 points against holding in one window, and in the other earned
  23 out of the 128 available in its own move space (M2 − HOLD).
- **The two-transfer limit is worth about 65, but only under certainty.** M∞ takes
  7–9 transfers in the first week and pays for them with hits, which is rational
  only with perfect foresight. **This is an upper bound on cause 3, not a case for
  raising `K_ENUM`.** Under a realistic forecast, hits of that size would mostly be
  bets on noise.

`[gap: P0 is scored as a fixed three-gameweek plan. The program is meant to be
re-run every week, committing only the first move. A rolling P0 — re-planning from
each gameweek's own pre-deadline capture — is the faithful measure of the shipped
workflow. It is not run here because the captures carry different prices, and
mixing snapshots needs its own design. Filed below.]`

`[gap: two windows, one starting squad (squad.json), one free transfer at the
start. The shape — forecast ≫ search — is the same in both, and the magnitudes are
consistent. More windows arrive as gameweeks settle.]`

## 3 — The same search, fed each registered forecast

`--forecasts`: the default search with each variant's forecast, scored on realised
points. **A measurement, not a criterion.** One squad and two windows are far too
little to rank models on, and nothing here promotes one. `official-ep/1.0` cannot
project beyond the next gameweek, so it cannot plan a three-gameweek window.

| forecast | GW2–4 | GW3–5 |
|---|---|---|
| HOLD (no transfers) | 233 | 188 |
| `naive/1.0` | **213** | **158** |
| `component/1.1-price` | 231 | 202 |
| `component/1.2` (P0) | 231 | 211 |
| `component/1.2-availability` | 231 | 202 |
| `component/1.3` | 231 | 198 |
| `component/1.4-venue` | 231 | 193 |
| `component/1.4` | 232 | 204 |

- **`naive/1.0` produces much the worst plans, 20 and 30 points below holding.**
  It is also the control that beats the component family on `spearman_all` in
  GW3–5. **Ranking well and planning well are not the same property.** A forecast
  that ranks the population well but gets magnitudes wrong buys the wrong players.
  That is FU-62's and FU-63's territory, and it is the first evidence here that
  magnitudes cost real points.
- **Within the component family the differences are small and inconsistent.** At
  GW2–4 all six component variants make the same GW2 move, and five of the six
  produce the identical three-week plan. At GW3–5 they spread over 193–211.
  Nothing here separates noise from signal.
- **No forecast gets near the perfect-forecast planner** (322, 316). Every component
  variant is 90–123 points short, and naive is further. So the gap does not come down
  to which of the registered models is used.

## 4 — Consequences for the register

- **FU-31** (expose `--beam`, `--first-moves`, `--max-cells`) was promoted by FU-72
  because step A needed it. **That need is gone.** The `tools/` harness calls
  `optimise()` directly, and the beam turns out to cost ≤ 3 points. FU-31 reverts
  to a convenience.
- **FU-5** (chips) remains the one unmeasured cause. It is also the only one left
  that could plausibly rival the forecast.
- **The projection half remains the prize.** Two fitted strength models failed to
  beat the difficulty band (FU-73, FU-74). The minutes term is where the family
  loses to `naive/1.0` on `spearman_all`. The next projection work should be judged
  on points like these, not only on Spearman. §3 is the first cut. It needs more
  windows and more than one starting squad before it can carry a decision, and any
  such decision needs a pre-registration first.

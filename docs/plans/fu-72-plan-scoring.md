# FU-72 — scoring the optimiser's output

**Status: plan, 2026-09-22.** Decisions by Ben, 2026-09-22:

- **Route to the true optimum: MILP**, using scipy's `milp` (HiGHS) as an optional
  `oracle` extra. It is used only by a `tools/` script and never by the CLI.
- **Objective:** realised points over the window: best XI plus captain, minus hits.
  **The terminal squad is reported, not scored**, so `ft_value` is excluded.
- **Strength model: the FPL difficulty band** stays, per the FU-74 outcome.

This is a measurement of our own code against a constructed benchmark. It is not a
decision rule about a model. Per FU-72's closing gap, **no default changes on the
strength of it** without a pre-registration.

---

## 1 — The benchmark

- **Windows:** GW2–4 and GW3–5, horizon 3. Every gameweek involved is settled and
  clean, and has a pinned trio. Two windows give two readings.
- **Prices, membership and rules:** from the window's first pre-deadline capture,
  held fixed for the whole window. The planner makes the same simplification.
  **In-window price changes are therefore excluded from both sides**, and this is
  stated.
- **Starting state:** `squad.json`, replayed and placed at event W−1 with 0 banked
  free transfers, so exactly one is available at W. That avoids the deep-bank trap
  (reference-data traps; `optimiser_scale_probe.py`, trap 1). Bank is £0.0m.
  `[assumption: one free transfer at W is the ordinary state; a deeper bank would
  make every hit-related cause inert, as it does in the probe.]`
- **Perfect forecast:** `Projection.xp_total` equals the player's realised
  `total_points` from the settled live payload. All other fields are 0.
- **Realised score of a plan:** walk the plan's transfers event by event through
  `apply_transfers` (the shipped validator), and at each event take
  `objective_points(best_xi(...))` under the actuals, minus that event's hits.
  Under the actuals, `best_xi` is the best XI and captain in hindsight. **Autosubs
  and the vice-captain are not modelled on either side.**

## 2 — The runs, and what each difference isolates

| id | what | forecast | settings |
|---|---|---|---|
| HOLD | no transfers | — | — |
| P0 | **the program as shipped** | component/1.2 | defaults (decay 0.84, ft_value 1.5, max_hit 4, beam 4, first moves 50) |
| O1 | planner, perfect forecast | actuals | defaults |
| O2 | + objective-aligned | actuals | decay 1.0, ft_value 0 |
| O3 | + hits unbounded | actuals | + max_hit ∞ |
| O4 | + wide beam | actuals | + beam 50, first moves 400 (~81× cost) |
| M2 | **MILP optimum, ≤ 2 transfers a GW** | actuals | the planner's move space, solved exactly |
| M∞ | **MILP optimum, full transfer rules** | actuals | up to `transfers_cap`, −4 each beyond free |

- **O1 − P0:** what a perfect forecast is worth to the planner as built. That is the
  projection half's whole prize.
- **O2 − O1:** causes 1 and 5, the decay and the terminal value.
- **O3 − O2:** the default hit cap, `max_hit = 4`. This is a sixth cause, not listed
  in FU-72 §1. It was found while planning.
- **M2 − O3**, cross-checked by O4: cause 4, the beam. M2 is the exact optimum of
  the planner's own move space.
- **M∞ − M2:** cause 3, the two-transfer limit.
- **Cause 2, chips: not measured.** `[gap: a chip-aware MILP is a further
  formulation. It is deferred and stated, not estimated.]`
- **M∞ − P0 is the headline:** how far the shipped program's plan falls short of the
  best achievable, over three gameweeks.

## 3 — The MILP (`tools/fu72_plan_oracle.py`)

Binaries per player p and event e: `x` (held), `s` (starts), `c` (captain), `b`
(bought), `q` (sold). Integers per event: `n` (transfers), `u` (free transfers used),
`f` (free transfers available). Continuous per event: `bank`.

- **Flow:** `x[p,e] = x[p,e−1] + b[p,e] − q[p,e]`, with `x[p,0]` the starting squad.
- **Composition:** each position's count equals `squad_select`; total 15; at most
  `squad_team_limit` per club. Only `_validator_usable` players may be bought, the
  same gate the planner uses.
- **Money:** `bank[e] = bank[e−1] + Σ q·sell − Σ b·cost ≥ 0`. `sell` is
  `selling_price(purchase, now_cost)` for an original holding, and `now_cost` for a
  player bought inside the window, because one snapshot means purchase equals now.
- **XI:** `s ≤ x`; Σ s = `squad_squadplay`; each position within
  `[squad_min_play, squad_max_play]`; `c ≤ s`; Σ c = 1.
- **Transfers:** `n[e] = Σ b[p,e]`; `u ≤ f`; `u ≤ n`; `f[W] = 1`;
  `f[e+1] ≤ f[e] − u[e] + 1`; `f ≤ cap`. `n ≤ 2` for M2, and
  `n ≤ transfers_cap` for M∞.
- **Objective:** `Σ pts·(s + c) − 4·Σ(n − u)`.
- **The MILP is checked by the shipped code, not trusted.** Its plan is replayed
  through `apply_transfers`, which must validate every event. Its objective must
  equal the realised score computed by §1's scorer to 1e−6. A mismatch fails the
  run. This honours CLAUDE.md's "every optimiser recommendation must pass the same
  validator".

## 4 — Deliverables, in order

1. `pyproject.toml`: an `oracle = ["scipy>=1.11,<2"]` extra. Nothing in `src/`
   imports it.
2. `tools/fu72_plan_oracle.py`: refuses unsettled gameweeks (the
   `fu53_minutes_oracle.py` rule); prints each input's sha256.
3. Tests in `tests/test_fu72_oracle.py`. They skip when scipy is absent. On a
   synthetic league they check that the MILP equals brute force, and that the scorer
   equals `objective_points`. Every test is mutation-demonstrated.
4. Results in `docs/plans/fu-72-results.md`, plus FU-72's Progress or Status line,
   and FU-31's note that it gained a dependant.

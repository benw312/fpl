# Points criterion — noise study (development, GW2–GW5)

**2026-10-01.** Plan: [points-criterion.md](points-criterion.md). Harness:
`tools/points_criterion.py`. For each window it draws 40 squads by ownership-weighted
sampling, with seed `20261001 + window`. Mean bank £4.2–4.4m; one free transfer at
the start. The pinned trios are as in fu-72-results.md. **Existing variants only, so
nothing here can be tuned toward a candidate.** Wall time was 2,972 s for 240 plans
on 8 cores, about 12 s each.

## Results (realised points per squad over the window)

| | GW2–4 | GW3–5 |
|---|---|---|
| HOLD, mean | 211.9 | 187.1 |
| `naive/1.0` − HOLD | −3.4 (sd 12.9) | −10.4 (sd 15.6) |
| `component/1.1-price` − HOLD | +15.0 (sd 10.1) | +11.2 (sd 19.1) |
| `component/1.2` − HOLD | +12.9 (sd 12.7) | +9.2 (sd 15.7) |

**Paired differences:**

| | GW2–4 | GW3–5 |
|---|---|---|
| 1.1-price − naive | **+18.4**, se 2.2 (35 + / 2 = / 3 −) | **+21.6**, se 2.7 (36 / 1 / 3) |
| 1.2 − naive | **+16.3**, se 2.5 (32 / 0 / 8) | **+19.5**, se 2.3 (37 / 0 / 3) |
| 1.2 − 1.1-price | −2.1, se 1.6 (11 / 8 / 21) | −2.0, se 2.4 (16 / 2 / 22) |

## What it says

- **It discriminates.** Naive's weakness, which FU-72 §3 found on one squad, holds
  across 40 squads in both windows, at 7–9 standard errors.
- **It is noisy at the size of differences between component variants.** The paired
  sd per squad is 10–15. Standard error by N:

  | N per window | 40 | 100 | 200 | 400 |
  |---|---|---|---|---|
  | GW2–4 (sd 10.1) | 1.6 | 1.0 | 0.72 | 0.51 |
  | GW3–5 (sd 15.1) | 2.4 | 1.5 | 1.06 | 0.75 |

  Cost scales linearly: about 80 min a window for N = 200 with two models plus HOLD.
- **Development finding, not a criterion:** `1.2` trails `1.1-price` by about 2
  points in both windows, at about one standard error, with more squads losing than
  gaining. It matches GW5's Spearman reversal (S6(a)). Points cannot license acting
  on it without a pre-registration, but it makes `1.1-price` or `1.2-availability`
  an obvious first candidate to test the criterion on.

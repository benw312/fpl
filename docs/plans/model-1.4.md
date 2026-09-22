# component/1.4 — design

**Status: DRAFT, 2026-09-22, awaiting Ben's sign-off with FU-74.** Nothing here is
built. This document is the *what* and *why*; FU-74 is the decision rule. It
supersedes [model-1.3.md](model-1.3.md) as the candidate for GW6 and GW7. It does
not replace 1.3's record: `component/1.3` and `component/1.3-fixtures` stay
registered, and their development check (model-1.3.md §7) is what this responds to.

---

## 1 — Why a revision, and why now

1.3's fitted strength model **lost all six fixture readings** on the development set
(model-1.3.md §7). The worst was GW3, at −0.081. FU-73 was binding and could have
been run as registered, but that would have spent GW6 and GW7 confirming a result the
development set already shows. **FU-73 is withdrawn before its first leg**, before any
GW6 figure exists, which FU-50 §5 permits. The withdrawal is recorded in its Status
line.

**The suspected cause.** 1.3 fits home advantage, unshrunk, from the current season
alone. At GW3 that was 20 matches, and it split home and away by ±19%, larger than
any team's opponent rating (0.92–1.07). **Suspected, not measured:** the loss was
never decomposed. §3 registers the home-advantage fix on its own so that the
decomposition happens at GW6 and GW7 instead.

**Honest about contamination.** This design responds to 1.3's GW2–GW5 figures, so
GW2–GW5 are now *more* contaminated for 1.4 than they were for 1.3. That is why the
development check below is a go/no-go gate only (§5), and why the test is GW6 and
GW7.

---

## 2 — The two changes

Both use **the 2025-26 season** (vaastav archive, `data/2025-26/`), pinned by sha256:

| pin | sha256 | content |
|---|---|---|
| `2025-26-fixtures.csv` | `2d7e3950d346df14ca486cb09e9b9ba406d37d943775244eed06cdc021ffb3a9` | 380 finished |
| `2025-26-teams.csv` | `b29df099cb0ad25413e284e53116099b0e0496874f99743dbc0870d8241b46c5` | 20 clubs |

**Clubs are matched across seasons by FPL `code`, not by id or name.** Ids are
reassigned each season. Measured: 17 clubs carry over, and every one has the same name
under the same code. Relegated: Wolves, Burnley, West Ham. Promoted: Hull City,
Ipswich Town, Coventry City.

### 2.1 — Change A: home advantage from last season

The home and away factors are **2025-26's, fixed**: home goals per match / μ and
away goals per match / μ, over all 380 matches. **Measured: home 1.110, away 0.890.**
Everything else is 1.3's model unchanged: μ and the team ratings are fitted from the
current season, shrunk toward 1.

*Why this is not a chosen constant.* The value is fitted from 380 match results, not
from our metric, and it is fixed here before any 1.4 figure exists. It is the same
estimator 1.3 uses, applied to a sample nineteen times larger than GW3's.

### 2.2 — Change B: team ratings shrunk toward last season, not toward 1

**The prior per club.** Each club's attack and defence multipliers are fitted on
2025-26 by 1.3's own §3.2 machinery (all 380 results, shrunk toward 1; at 38 games
the shrinkage is small). Those become the **prior means** `r_i` for 2026-27.

- **The 17 clubs that carry over** use their own 2025-26 ratings.
- **The 3 promoted clubs** each use the **mean of the three relegated clubs'**
  2025-26 ratings, taken separately for attack and for defence. That is fitted, not
  chosen. It also avoids the known optimism of treating promoted sides as average.

**Current-season shrinkage toward the prior, still with no chosen constant.** This is
method of moments again, measured around the prior instead of around 1:

```
excess = mean_i[(m_i − μ·r_i)²] − μ/n        (m_i: club i's raw goals per match)
σ²     = excess / μ²                         (variance of the multiplier about r_i)
prior  = Gamma(shape r_i²/σ², rate r_i/σ²)   (mean r_i, variance σ²)
rating = (observed + r_i²/σ²) / (exposure + r_i/σ²)
```

This is estimated separately for attack and for defence, with the fixed-point
iteration exactly as in 1.3.

**Fallback, fixed now:** if either excess is ≤ 0, the current season shows no spread
beyond the prior plus noise. **The prior ratings are then used unchanged** for that
capture, not the banded model, and the run records that. It is expected early on,
possibly at GW2.

---

## 3 — Variants, registered together

| variant | home advantage | team ratings | minutes term |
|---|---|---|---|
| `component/1.2` | band (venue built in) | band | S1–S6(a), incumbent default |
| `component/1.2-availability` | band | band | S1–S5 |
| `component/1.3` | current season, unshrunk | current, shrunk → 1 | S1–S5 (existing) |
| **`component/1.4-venue`** | **2025-26, fixed** | current, shrunk → 1 | S1–S5 |
| **`component/1.4`** | **2025-26, fixed** | **current, shrunk → 2025-26** | S1–S5 |

Each comparison changes one thing:

- **`1.4-venue − 1.3`**: change A alone. This tests the suspected cause directly.
- **`1.4 − 1.4-venue`**: change B alone.
- **`1.4 − 1.2-availability`**: the whole fitted strength model against the band,
  with the minutes term held at S1–S5.

The minutes term is 1.2-availability's for every new variant, as decided for 1.3
(model-1.3.md §2). **No `-fixtures` twin carrying S6(a) is registered.** S6(a) has
four readings now, and a fifth tells us nothing about strength.

---

## 4 — The data path

- **`tools/prior_season.py`** reads the two pinned CSVs and fits 2025-26 with
  `fit_team_strength`'s machinery. It writes a generated module,
  **`src/fpl_cli/domain/season_prior.py`**, which holds the ratings by club `code`,
  the relegated means, the home and away factors, and the sha256 of both inputs in
  its header. It is regenerated, never hand-edited.
- **The CLI never touches the network**, and tests never read `~/fpl-pinned`.
  `season_prior.py` is committed data.
- **The variant digest covers the prior.** The strength config names
  `prior_season="2025-26"` and carries a hash of the table. A regenerated table with
  different numbers is a different model, and the digest test says so.
- `Club` gains `code` (parsed, `extra="ignore"` today). CLAUDE.md's Structure block
  gains `season_prior.py` in the same commit (FU-19).

---

## 5 — The development check is a gate, not a tuning loop

Once built, 1.4 and 1.4-venue are scored on GW2–GW5 with **nothing changed after the
figures are seen**. **One revision; no iteration.** If it fails, 1.4 is not revised
against GW2–GW5 again.

The **go/no-go rule is FU-74 §2**, fixed before the build. `[gap: the threshold is a
proposal awaiting Ben's sign-off.]`

---

## 6 — Not in 1.4

Everything model-1.3.md §5 parks stays parked: blending `ep_next`,
rank-ensembling, and splitting P(plays) from E[points | plays]. **Dixon–Coles's
low-score correction is not added either.** It would be a third change.

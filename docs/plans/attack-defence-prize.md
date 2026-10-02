# Attacking ideas, and what to do about defenders — measured

**2026-10-01/02, overnight, for Ben.** This follows forecast-prize-results.md. That
document put the prize in the rate half: who hauls when they play. Ben asked for
three attacking ideas to be measured the same way, and then what could be done
about defenders, including whether "expected clean sheets" exist. **Everything here
is development measurement on GW2–GW5. Nothing changes a model, and nothing is a
criterion.** FU-75 governs any real change.

Tools:
- `tools/attack_prize.py`: prototypes A–C, and `--oracles` for H and I.
- `tools/forecast_prize.py`: oracles D–I.

Pinned inputs are as in fu-72-results.md, plus `~/fpl-pinned/2025-26-players_raw.csv`
(sha256 `412ce017…`).

---

## 1 — The three attacking ideas (40 squads per window, paired against 1.2)

Each prototype changes only the raw xG/xA rate and exposure fed into 1.2's own
shrinkage, so each difference is that idea alone. 1.2 − HOLD reproduces the noise
study exactly (+12.93, +9.18).

| idea | GW2–4 | GW3–5 | squads whose points differ from 1.2's (GW2–4 / GW3–5) |
|---|---|---|---|
| **A** last-season prior (2025-26 xG/xA pooled, w = 1) | −1.1 (se 2.1) | **+5.5** (se 2.4) | 39 of 40 / 37 of 40 |
| **B** penalty takers (+0.15 × 0.76 xG per 90 for first choice) | +0.1 (se 0.3) | −0.6 (se 1.2) | 8 / 16 |
| **C** recency (half-life 2 GWs) | 0.0 (identical by construction: one GW of history) | −1.6 (se 2.1) | 1 / 25 |

**Spearman barely moves for any of them** (±0.004 at either window).

- **A is the only idea with a real effect on the plans:** it changes the outcome
  for nearly every squad. But the two windows disagree in sign, and the mean of the two is
  about +2.2. It is the one worth a proper pre-registration. `[gap: w = 1 is a
  prototype choice; how much weight last season deserves is the judgement 1.4's
  team-level version also left open.]`
- **B does nothing measurable.** Penalty xG is already in the takers' observed
  rates, and the bonus changes few plans. `[assumption: 0.15 penalties per
  team-match; not measured.]`
- **C cannot be tested yet.** With four or fewer gameweeks of history there is
  nothing to weight. Revisit around GW10.

## 2 — Where the prize sits: attack against defence (oracles, one squad)

| oracle | what it knows | GW2–4 | GW3–5 |
|---|---|---|---|
| D | realised rates (who hauls) | +91 | +103 |
| E | D, attacking luck removed (xG/xA for goals) | +69 | +74 |
| F | D, defensive luck removed (xGC for clean sheets) | +78 | +95 |
| G | E and F: chance quality only | +66 | +70 |
| **H** | **1.2 + perfect *defensive* chance quality only** | **+8** | **−35** |
| **I** | **1.2 + perfect *attacking* chance quality only** | **+38** | **+39** |

**The 40-squad check (paired against 1.2) is decisive, and it overturns the
one-squad −35:**

| | GW2–4 | GW3–5 |
|---|---|---|
| **I — perfect attacking chance quality** | **+28.0** (se 2.6; 39 + / 0 = / 1 −) | **+38.6** (se 3.1; 39 / 1 / 0) |
| H — perfect defensive chance quality | +2.0 (se 2.1; 21 / 1 / 18) | +0.6 (se 2.7; 24 / 1 / 15) |

**The forecastable prize is in attack.** Knowing each player's attacking chance
quality is worth about +28 to +39 points per squad over three weeks. Knowing each
team's defensive chance quality is worth about nothing, within noise. The one-squad
−35 was that squad, not defence.

## 3 — Defenders: what exists, and what our data says

**Yes, "expected clean sheets" exist.** The standard construction is Poisson:
P(clean sheet) = exp(−xGC), where xGC is the team's expected goals conceded. That
is exactly the form 1.2 already uses, `exp(-xg_against)`. Two refinements appear in
public work:
- **Calibration.** One open-source FPL project measured that plain exp(−xGC)
  **over-predicts clean sheets: 35% predicted against 29% actual in 2025/26.** It
  fits `P(CS) = exp(−(0.09 + 1.16·xGC))` by maximum likelihood on 2023/24–2025/26,
  using *realised* match xGC. [jacobcharest/fpl-dashboard PR #10, merged
  2026-09-18 — a hobby project, not peer-reviewed.]
- **Team defence from xG conceded, not goals.** It stabilises faster, and is shrunk
  toward the league average or the club's previous season.
  [amanwaseem/fpl-predictor issue #31.] Older analysis reaches the same conclusion
  from the other side: clean sheets and goals conceded are "a lot less predictable"
  than attacking returns. [Overthinking Football, "xFpts: Defenders", 2020.]

**Our own data (GW2–5, 80 team-fixtures):**
- **1.2's clean-sheet predictions have no skill.** Brier 0.2102, against 0.2100 for
  predicting the base rate for everyone. The difficulty band squeezes every
  prediction into 0.18–0.28, ignores the team's own defence, and under-predicts on
  average (24.5% against 30.0%).
- **Unshrunk season-to-date xGC is worse:** skill −0.20 own-only, −0.07 with the
  opponent's xG. After 1–4 matches it is far too confident (predictions span
  0.01–0.97). Shrinkage, ideally toward last season, is not optional. Nothing was
  tuned here.
- **Even perfect knowledge of defensive chance quality does not help the plan** (H:
  +2.0 and +0.6, both within noise, over 40 squads). Defensive points are mostly
  per-match luck, which is consistent with the literature.

`[gap: defensive-contribution (defcon) points were not separated out. H swaps only
clean sheets and goals conceded; defcon stays as 1.2 modelled it. Whether CBIT is
predictable enough to matter is unmeasured.]`

## 4 — Recommendation

1. **Defenders: park clean-sheet modelling for points.** It is worth about nothing
   in plan points even under perfect knowledge. The one cheap fix — 1.2's
   clean-sheet base rate is about 5.5 points too low, and it has no skill — would
   improve calibration, not plans (forecast-prize-results.md's B: calibration is
   worth about 0). Do it only as a correctness fix, if at all. Defcon is the one
   defensive question left open.
2. **Attack is where to build.** The target is per-match attacking chance quality.
   Of the three ideas, **A (last-season prior) is the only one that moves plans**,
   and it is the natural first candidate under FU-75's method. It needs a fresh
   pre-registration with the last-season weight fixed in advance (or set by the
   method of moments, as 1.4 did for teams). To share FU-75's legs, GW8–10 and
   GW11–13, it must land before 2026-10-23T17:30Z.
3. **A bigger design, not yet bounded:** team expected xG per fixture (from
   xG-based team ratings shrunk toward last season, which public work favours over
   goals) × each player's share of the team's xG. It combines A's prior, the
   fixture model that failed on goals (FU-73/74), and the attack-only prize I
   measures. Bound it the same way before building.
4. **B and C:** B (penalty bonus) does nothing measurable. C (recency) cannot be
   tested before about GW10.

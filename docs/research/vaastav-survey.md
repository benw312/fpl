# The vaastav archive: what it can and cannot do for us

**Research only. No `src/` file is touched and no dependency is added.** The archive
was shallow-cloned to a scratch directory outside the repo, deliberately: everything
below is a finding about data, not a decision to depend on it.
[rank-calibration.md](../plans/rank-calibration.md) §4.2(c) records that adding a
third-party dataset is an architecture decision, and this document does not take it.

**Source.** `vaastav/Fantasy-Premier-League`, `master` at
`9779cdbc0c07f6c900c2d0c181ddf6bb9c800f88`, shallow clone 2026-09-12, 363 MB.
**Licence:** MIT covers the *code*; the LICENSE states the data is the property of
fantasy.premierleague.com and understat.com. So we may compute from it and must not
redistribute it — the position
[projections-survey.md](projections-survey.md) already records.

---

## TL;DR

- **The outcome-distribution question Ben asked first is wide open.** Six complete
  seasons carry position and points (2020-21 → 2025-26). Haulers per gameweek is
  **remarkably stable at 63–67, or 22% of players who appeared**, across all six.
- **Our GW2 and GW3 sit inside that norm** (20.5% and 21.2% of played). We are not
  facing an unusual season; the model's haulers problem is not a data problem.
- **Hauler shape is strongly position-dependent and asymmetric.** Defenders haul
  *often and small*; midfielders haul *rarely and huge*. That asymmetry is an
  argument for `per_position` being mandatory in any calibration, not optional.
- **FDR predicts hauling strongly and monotonically** — 32.3% of appearances at
  FDR 1 versus 10.8% at FDR 5 — **and the effect is four times larger for
  goalkeepers and defenders than for midfielders.** But it is confounded and we
  already model most of it; see §5.
- **Running our model historically is impossible, and for a sharper reason than
  [rank-calibration.md](../plans/rank-calibration.md) §4.2(a) guessed.** Not missing
  columns: the availability fields exist only as **one end-of-season snapshot per
  season** and cannot be reconstructed for any past gameweek, in any season,
  including the current one. §2 corrects that gap.

---

## 1 — Structure

Per season: `gws/gwN.csv` and `gws/merged_gw.csv` (a row per player per gameweek),
`players_raw.csv`, `fixtures.csv`, `teams.csv`, and `players/<name>_<id>/` holding
`gw.csv` and `history.csv`. Eleven seasons, 2016-17 → 2026-27.

**The current season lags ours.** 2026-27 holds one gameweek; we have three settled.
Anything wanting current-season data must come from our own archive, not this one.

**The population matches ours in shape.** 2024-25's `merged_gw` carries 27,605 rows
over 38 rounds, 58% of them with zero minutes, and grows from 616 rows in round 1 to
954 late on. Ours grew 616 → 652 over GW1–GW3. So "share of population" is
comparable between the two sources, with the caveat that their denominator drifts
upward more over a full season.

---

## 2 — Field inventory by season, and the verdict on reconstruction

This is the verification
[rank-calibration.md](../plans/rank-calibration.md) §4.2(a) flagged as not done and
possibly fatal. It is done here, and the answer splits cleanly in two.

### 2.1 What appears when

| field (in `merged_gw.csv`) | first season |
|---|---|
| `total_points`, `minutes`, `round`, `was_home`, `opponent_team`, `value`, `selected` | 2016-17 |
| **`position`** | **2020-21** |
| `starts`, `expected_goals`, `expected_assists`, `expected_goals_conceded` | 2022-23 |
| **`defensive_contribution`** | **2025-26** (the rule change) |
| `fixtures.csv` with `team_h_difficulty` / `team_a_difficulty` | 2018-19 |
| `teams.csv` | 2019-20 |

### 2.2 Cumulative stats are reconstructible; point-in-time state is not

`players_raw.csv` carries every field our model consumes —
`chance_of_playing_this_round` and `_next_round`, `selected_by_percent`, `status`,
`news`, `starts`, `expected_goals_per_90`, `saves_per_90`,
`defensive_contribution_per_90`, `now_cost`, `ep_next`. **But it is one row per
player per season — 841 rows for 2025-26's 843 players — a single snapshot, not a
per-gameweek series.** And no per-gameweek file carries any availability field.

So:

| our model's input | reconstructible per gameweek? |
|---|---|
| cumulative `starts`, `minutes`, xG, xA, saves, defcon | **yes**, by summing `gws/gwN.csv` up to the round, from the season the field appears |
| ownership | **approximately** — `selected` is a per-gameweek *count*; converting to `selected_by_percent` needs the total-manager count, which is not in the archive |
| `status`, `chance_of_playing_*`, `news` | **no. One snapshot per season, and the live values are overwritten in place.** |

**The last row is fatal for running our model historically**, and it is fatal for
*every* season including 2025-26, not just the old ones. S1 to S5 are the entire
minutes structure and all of them read availability. FU-51's gap already said this
about `news` — "overwritten in place, so an absence's length is only recoverable
from a dense capture archive" — and it turns out to be true of the whole
availability block.

**So `rank-calibration.md` §4.2(a) is confirmed, with its reasoning corrected.** The
obstacle is not sparse columns in old seasons. It is that the archive records
outcomes densely and *state* only once. A historical run would have to disable
S1–S5, which makes it a different model and defeats the purpose.

`[gap: a partial run is conceivable — our component model with every availability
branch forced to "available" and ownership approximated from `selected`. That is not
`component/1.2` and could not calibrate it, but it might still say something about
the scoring terms, which do not read availability. Not pursued.]`

---

## 3 — Haulers per gameweek: a stable target

Hauler = `total_points >= 5`, which is `evaluation.py`'s own `_category` cut, so
these numbers are directly comparable with ours.

| season | GWs | pop/GW | played/GW | **haulers/GW** | sd | min | max | % of pop | **% of played** |
|---|---|---|---|---|---|---|---|---|---|
| 2020-21 | 38 | 641 | 274 | 65.5 | 15.5 | 26 | 112 | 10.2% | 24.0% |
| 2021-22 | 38 | 670 | 276 | 64.5 | 16.4 | 21 | 117 | 9.6% | 23.4% |
| 2022-23 | 37 | 716 | 307 | 66.9 | 10.9 | 39 | 108 | 9.3% | 21.8% |
| 2023-24 | 38 | 782 | 300 | 62.8 | 11.0 | 20 | 98 | 8.0% | 21.0% |
| 2024-25 | 38 | 726 | 304 | 65.9 | 11.2 | 46 | 94 | 9.1% | 21.6% |
| 2025-26 | 38 | 783 | 303 | 66.6 | 9.2 | 44 | 96 | 8.5% | 22.0% |

**Six seasons, and the mean never leaves 62.8–66.9.** The within-season spread is
wide (20 to 117 in a single gameweek) but the seasonal mean is nearly a constant.

**We are normal.** Our GW2 produced 63 haulers from 308 who played (20.5%); GW3
produced 65 from 307 (21.2%). Against a six-season norm of 22.0%. Whatever is wrong
with the model's haulers, the *supply* of haulers is not unusual.

### Did the 2025-26 defensive-contribution rule move it?

| season | haul% of played | GKP | DEF | MID | FWD | mean hauler pts |
|---|---|---|---|---|---|---|
| 2024-25 | 20.2% | 24.7% | 22.5% | 16.5% | 26.8% | 7.68 |
| **2025-26** | **22.0%** | 27.1% | **25.3%** | **18.6%** | 22.9% | 7.72 |

Defenders +2.8pp and midfielders +2.1pp, which is what a rule rewarding defensive
actions should do — while the **mean hauler score is unchanged at 7.7**. So the rule
made *more* haulers, not *bigger* ones. Pre-2025-26 seasons therefore remain usable
for hauler **shape** and slightly understate hauler **frequency** for DEF and MID.

---

## 4 — Hauler shape by position

Six seasons pooled, 2020-21 → 2025-26.

| pos | share of haulers | haul rate of pop | haul rate **of played** | mean pts | median | p90 | max | 5–8 | 9–12 | 13+ |
|---|---|---|---|---|---|---|---|---|---|---|
| GKP | 8.9% | 7.2% | **28.2%** | 7.43 | 7 | 10 | 16 | 72.1% | 26.2% | **1.8%** |
| DEF | **39.8%** | 10.6% | 26.0% | 7.17 | 6 | 10 | 24 | **82.1%** | 13.4% | 4.5% |
| MID | 37.0% | 7.7% | **17.4%** | **8.16** | 7 | **13** | **26** | 63.4% | 26.2% | **10.4%** |
| FWD | 14.4% | 10.7% | 25.0% | 7.99 | 7 | 13 | 24 | 67.4% | 22.1% | **10.5%** |
| ALL | 100% | 9.0% | 22.0% | 7.68 | 7 | 12 | 26 | | | |

**The asymmetry is the finding.** Defenders are the largest block of haulers (39.8%)
and haul *small*: 82% of their hauls are 5–8 points and only 4.5% reach 13+.
Midfielders are the **least** likely to haul given they played (17.4%, against
GKP's 28.2%) but produce the biggest hauls — 10.4% at 13+, a p90 of 13, a maximum of
26.

**What that implies for calibration.** `rank-calibration.md` §7 lists `per_position`
as row 5, an optional knob. These figures argue it is not optional: a single global
map would have to compromise between a DEF distribution concentrated at 5–8 and a
MID distribution with a fat 13+ tail, and would misprice both. It also sharpens
FU-62's compression finding — the model's ceiling of 5.68 is below the *median*
hauler in every position.

---

## 5 — Does FDR predict hauling? Yes, strongly, and unevenly

Difficulty as faced by the player (`team_h_difficulty` if home, else
`team_a_difficulty`), joined on fixture id. 163,082 of 163,404 rows joined.

| FDR | haul% of played, all pos | mean pts (played) |
|---|---|---|
| 1 | **32.3%** | 3.65 |
| 2 | 27.0% | 3.25 |
| 3 | 21.6% | 2.85 |
| 4 | 16.4% | 2.45 |
| 5 | **10.8%** | 1.96 |

**Monotone, and a 3× swing from easiest to hardest.** It is also stable: the
FDR 2→5 decline holds in every one of the six seasons individually.

### The effect is far larger for defenders and goalkeepers

| FDR | GKP | DEF | MID | FWD |
|---|---|---|---|---|
| 1 | 44.3% | 40.8% | 24.7% | 33.7% |
| 3 | 27.3% | 24.8% | 17.5% | 25.2% |
| 5 | 11.0% | 9.9% | 10.1% | 15.7% |
| **ratio 1:5** | **4.0×** | **4.1×** | **2.4×** | **2.1×** |

That is the expected shape: clean sheets are a binary team outcome and swing hard
with opposition quality, while attacking returns are less fixture-dependent.

### Three caveats, and the third is the important one

1. **FDR 1 is thin and recent.** 1,755 played rows in total, of which only **115 are
   goalkeepers** — so the 44.3% headline rests on 115 observations. FDR 1 does not
   appear at all before 2024-25, so FPL's difficulty scale is not stable across
   seasons and cross-season pooling of *level* is unsafe. The *gradient* is stable;
   the *labels* are not.
2. **FDR is endogenous.** A player facing FDR 1 is usually on a strong team. So this
   measures "good players in good fixtures haul" and does not separate the two.
3. **We already model most of this.** `BandedTeamRates` scales attacking and
   clean-sheet terms by opponent strength drawn from the same underlying ratings FDR
   is built from. **The question that matters is not whether FDR predicts hauling —
   it plainly does — but whether it predicts hauling *beyond what our strength model
   already captures*. This analysis does not answer that**, and it is the only
   version of the question worth acting on.

---

## 6 — How this could fit, in increasing cost

**(a) As a target distribution, computed once, no dependency. — BUILT, 2026-09-12,
`tools/distribution_check.py`.** The norms from §3 and §4 are baked in as measured
constants; nothing reads the archive at runtime. Three findings on first run:

1. **A third of FU-63's scale bias is this season, not the model.** Against this
   season's realised totals `component/1.2` is −13.6% at GW3. Against the six-season
   norm *for the same round number* it is **−6.2%**, because GW3 itself came in
   **+8.5% above** the historical round-3 average. `component/1.1-price` moves the
   other way — +12.3% against realised, **+21.9%** against history. Two settled
   gameweeks could not have told us this, which is the whole point of route (a).
2. **The positional allocation looked skewed, and was not.** Filed as FU-67 and
   **refuted the same day** — see below. The pooled reference spanned the
   defensive-contribution rule change, which is the whole of the apparent gap.
   `component/1.1-price`'s goalkeeper share, 11.7% against a post-rule 7.5%,
   survives the correction and is the one part of that entry still standing.
3. **The compression is starker than FU-62 could show.** History says 22.0% of
   players who appear score ≥ 5. `component/1.1-price` projects **zero** players
   above 5 out of 652; `component/1.2` projects three. Reported explicitly as a
   *dispersion* diagnostic and not a bias measure — see the tool's docstring for why
   the two are not comparable as counts.

**Round-indexed, not season-averaged**, because the element set grows from ~586 in
round 1 to ~780 by round 38; comparing an early gameweek against a season average
would use the wrong denominator.

**A correction to §4 and to the tool, found by chasing finding 2.** Defensive
contribution arrived in 2025-26 and moved the defenders' share of all points from a
five-season pre-rule mean of **31.5% to 35.0%** — a step nearly as large as the
4.3-point gameweek-to-gameweek standard deviation — and lifted points per played
player from 2.864 to 2.994. **So the pooled six-season figures in §3 and §4 are the
wrong reference for any season played under the current rules**, and the tool now
reports 2025-26 alone as the reference with the pooled set kept for contrast. The
cost is stated where it is used: one season means a round-level norm is a single
observation where the pooled table averages six.

This is the trap route (a) exists to avoid, sprung in the other direction: a
six-season reference is not automatically better than a two-gameweek one, and 227
gameweeks of authority made the wrong number look right.

**(b) As a prior for a per-position calibration map.** §4's position shapes are the
target a calibration would map onto. Needs `rank-calibration.md`'s criterion problem
solved first (FU-65), and its §6 sequencing argument still says FU-57 comes before
any of it.

**(c) As a historical evaluation set for our model. Not available** — §2.2. Nothing
makes this reachable short of a dense capture archive of availability state, which
only exists going forward, from our own `~/.fpl-cli/archive/` (which begins
2026-08-25).

**If anything is ever vendored**, the licence position in §0 applies: compute from
it, do not redistribute it. A committed extract of *derived aggregates* — "haulers
per gameweek by position and FDR" — is defensible; a committed copy of the raw CSVs
is not.

---

## 7 — Gaps

`[gap: §5's central question — does FDR add anything beyond `BandedTeamRates` — is
not answered and is the only one that would change the model. Answering it means
scoring our own fixture-scaled projections against outcomes with FDR added as a
second term, on our own captures, and seeing whether it explains residual variance.
That is a real piece of work and it is not this document.]`

`[gap: "hauler" is a 5-point threshold inherited from the survey's OpenFPL
yardstick. FU-61 established that bucketing on the realised total is a
selection-on-outcome cut, so every table in §3 and §4 describes the *outcome*
distribution and none of it is a statement about any model's error. That is the
correct use here — we are characterising the target, not scoring a predictor — but
the figures must not be read back into a model comparison.]`

`[gap: the archive's own provenance is not audited. It is scraped from the same FPL
API we read, so systematic errors in the scrape would be invisible to us and would
propagate into anything calibrated on it. No cross-check was made against our own
2026-27 captures, and one is cheap for the overlapping gameweek.]`

`[gap: 2020-21 was played behind closed doors and 2019-20 was interrupted; home
advantage and scoring rates in those seasons are not necessarily comparable with
2024-26. 2020-21 is included in every pooled figure above without adjustment, and
its haul rate (24.0% of played) is the highest of the six.]`

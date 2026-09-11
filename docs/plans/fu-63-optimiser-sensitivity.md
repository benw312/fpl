# FU-63 — does the xP scale bias change what the optimiser recommends?

**Analysis only. No `src/` file is modified, no constant changed.** This answers the
measurement FU-63's closing gap asked for: *"Nobody has run the optimiser under a
scaled xP and counted how many recommendations change."*

**Pinned inputs, cited per FU-40.** `~/.fpl-cli/archive/2026-09-11/bootstrap-static.json`
(sha256 `4d9cafa5b8b3…`), `fixtures.json` (`85d3ef089f28…`), squad ledger
`squad.json` (`9ff9382ce567…`). Model `component/1.2+banded`, digest `4f479b2253cc`.
Horizon GW4–GW6, `decay = 0.84`, `ft_value = 1.5`, `max_hit` unbounded.

**Method.** The objective is `score(α) = α·XP − H + V`, linear in the xP scale `α`.
So a single `optimise` run at `α = 1` determines every path's score at every `α`
exactly, and the flip points can be read off rather than searched for. The first two
attempts swept `α` over six values and re-ran the optimiser each time; both were
wasted, for the reasons in §1.

---

## 1 — Two null results, and why they were null

**On the actual squad, nothing changes across ±33% of xP scale.** Six values of `α`
from 0.80 to 1.50 return the identical first move, transfer count and hit.

That result is **vacuous, not reassuring.** `squad.json` sits at event 1 with no
transfers recorded, and `apply_transfers` accrues a free transfer per intervening
event, so by GW4 the bank is at the cap. Measured: `hit_points = 0` at every `α`,
and `terminal_value = 0` at every `α`. **Both channels through which `α` could act
were dead**, so the run tested nothing.

Forcing `free_transfers = 1` on the ledger did not fix it either — the ledger is at
event 1, so three events of accrual still bring it to 4 by GW4. The state has to be
placed at event 3 with an empty bank to leave exactly one free transfer at GW4.

`[gap: the ledger being stale at event 1 is a fact about this repo's `squad.json`,
not about the optimiser. If transfers have in fact been made since GW1 and not
recorded, every `plan optimise` run to date has started from the wrong squad. That
is a data-hygiene question, not a modelling one, and it is not pursued here.]`

---

## 2 — The answer: the recommendation is scale-sensitive, and the margin is thin

State placed at event 3 with an empty bank — one free transfer available at GW4, so a
second transfer costs the 4-point charge. 204 paths.

| k | hit | XP | score at α=1 | first move |
|---|---|---|---|---|
| 0 | 0 | 5.123 | 5.123 | HOLD |
| 1 | 0 | 6.114 | 6.114 | Igor Jesus → Barry |
| 2 | **4** | 10.298 | **6.298** | Gabriel → De Cuyper + Igor Jesus → Isak |

Taking the hit wins **by 0.184 points**. Solving `score(α)` for the crossover:

> **The recommendation flips at α = 0.96.** Below it the single free transfer wins;
> at or above it the two-transfer move with a 4-point hit wins.

**So the claim is confirmed: a uniform xP scale does change optimiser
recommendations.** It acts entirely through `_hit_points`, which is denominated in
real points while xP is not.

**But the direction matters, and it is not the one FU-63 asserted.** The measured
bias is `component/1.2` running **13.6% low**, i.e. a correction of `α = 1.157` —
which is *above* the 0.96 boundary, so correcting it reinforces the existing
recommendation rather than changing it. In this instance the bias changes nothing.

**What makes it a live risk is the ratio.** The decision sits 4% from flipping while
the bias is 13.6% — **3.4× the margin**. Any decision whose margin is smaller than
the bias will flip, and this one is close to that. A single observation cannot say
how often that happens.

---

## 3 — A correction to FU-63: `ft_value` is inert, so "over-values holding" is wrong

FU-63 claimed the optimiser *"under-takes hits and over-values holding"*. The first
half is confirmed in direction by §2. **The second half is wrong**, and this run
shows why.

**All 204 paths terminate with zero free transfers**, so `terminal_value` is
identically 0.000 and `DEFAULT_FT_VALUE = 1.5` cannot influence the ranking of any
path against any other. Verified directly: the set of terminal `free_transfers`
values across all 204 paths is `{0}`. `_terminal_value` itself is correct — given a
held state it returns 3.175 — but no path ever reaches it with a bank.

The reason is that the search spends the entire bank on every path. Even the HOLD
path makes **3 transfers** over GW5–GW6; "HOLD" names an empty *first move*, not an
empty plan. With three free transfers available across the horizon and 600+ players
to choose from, some transfer is always worth more than 1.5 points, so banking never
wins.

**That makes `DEFAULT_FT_VALUE` very likely a dead constant in ordinary use** — not
merely inert here. It would bind only when no available transfer is worth 1.5 points
over the remaining horizon, which is a rare state. Filed as **FU-64**.

`[gap: "very likely dead in ordinary use" is an inference from one state, one squad
and one horizon, not a measurement. The honest claim is that it is dead in this
instance and that the mechanism which makes it dead does not look
state-specific. Establishing the general case means sweeping squads and horizons,
which this analysis does not do.]`

---

## 4 — What follows

**Do not fix the scale bias with a multiplier.** FU-63 already says this and §2
strengthens it: the bias changes decisions only where margins are thin, and the
route is FU-57, which addresses the cause. A calibration constant would be a fitted
number of exactly the kind FU-50 §3 forbids.

**FU-63's text needs amending** — the "over-values holding" half is withdrawn, and
the `ft_value` finding is filed separately as FU-64.

`[gap: one squad, one horizon, one gameweek, one constructed free-transfer state.
The flip point of 0.96 is a property of this decision, not of the optimiser. A
distribution of margins across many states would say how often a 13.6% bias matters;
this says only that it can.]`

`[gap: §2 holds the fixture and price inputs fixed and scales only xP. A real
calibration would change the relative ordering of players as well as the scale, since
the bias is not uniform across the prediction range (haulers-decomposition.md §3
measures per-bin biases of +0.08 to −0.76). A uniform α is the conservative test and
understates the effect.]`

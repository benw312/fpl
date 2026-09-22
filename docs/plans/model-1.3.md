# component/1.3 — design

**Status: design only. Nothing here is built, and the pre-registration that governs
it is FU-73, which is not yet signed off.** This document is the *what* and *why*;
FU-73 is the decision rule. The split follows minutes-model.md / FU-60.

---

## 1 — The diagnosis this responds to

Three settled gameweeks of decomposition, plus a split visible only after GW5.

**The minutes work has not paid.** S1–S5: +0.003, −0.006, +0.0003 — never moved the
metric. S6(a): +0.029, +0.0065, −0.033 — mean near zero, spread wider than every
margin any decision here has turned on.

**And the two metrics disagree about where we are weak.** On `spearman_all` —
effectively the *"will he play"* problem, since most of 659 players score zero —
the component family **loses to `naive/1.0` and to `official-ep/1.0`** at GW4 and
GW5. On `spearman_played` — *"how many points given he played"* — it wins GW3 and
GW5.

**So the rate half earns its place and the minutes half is worse than doing almost
nothing. `component/1.2` spent its entire effort on the minutes half.** 1.3 inverts
that: take effort *out* of minutes, and put it into the fixture term that feeds the
rates.

---

## 2 — Change 1: subtract the minutes elaboration

**What.** Revert the availability/minutes term to the simplest form that works,
dropping S6(a)'s ownership-conditioned start prior and the S1–S5 structure with it.

**Why, on evidence rather than taste.** At GW5, `component/1.1-price` (0.414226) and
`component/1.2-availability` (0.414502) are indistinguishable, and both beat
`component/1.2` (0.381725). The elaborate term is not merely failing to help; S6(a)
is actively costing 0.033 on the most recent settled gameweek.

**This is a deletion, not a rewrite**, which is the cheapest change available and the
one the data most directly supports. `component/1.1-price`'s existing availability
scalar is the target shape.

`[gap: "the simplest form that works" is not yet a specification. The two candidates
are 1.1-price's scalar exactly, or S1–S5 retained with only S6(a) removed — which is
`component/1.2-availability`, already registered and already measured. If the second
is chosen, change 1 is *already built* and 1.3 reduces to change 2 applied on top of
1.2-availability. That is a real simplification and it should be decided before any
code is written.]`

---

## 3 — Change 2: a fitted team-strength model

**What is there now.** `attack_scale = rates.xg_for / league_mean_goals`, applied to
the player's shrunk xG and xA rates. `xg_for` and `xg_against` come from
`DifficultyBandRatesModel` — *"v1: `xg_for`/`xg_against` from the opponent's
difficulty band"* — which is the FPL difficulty rating, an integer band, used as a
lookup.

**What to replace it with.** A Poisson team attack/defence model fitted from actual
match results: each team gets an attack rating and a defence rating, with home
advantage, and expected goals for a fixture come from the fitted ratings rather than
a band. Ratings shrunk toward the league mean, using the machinery rate-shrinkage.md
already establishes for player rates.

**Why this and not something else.**

- **The seam already exists and was built for this.** `strength.py` defines a
  `TeamRatesModel` Protocol with `rates(team, opponent, home)`, `league_mean_goals()`
  and `name()`. projections-v1.md Decision 1 calls it the fixture-strength strategy
  seam. A new model is a drop-in, not a refactor.
- **It is fitted, not chosen.** Every parameter comes from match results. This
  matters: FU-50 §3 forbids picking constants on thin data, and a fitted model does
  not ask anyone to pick one.
- **It amplifies the half that works.** The opponent is the largest single swing in
  any gameweek, and it is currently represented by a 1–5 integer.

`[gap: five gameweeks is 50 team-games for 40 free parameters. The shrinkage is what
makes this tractable rather than overfitted, and the shrinkage strength is itself a
constant — which is exactly the trap FU-50 §3 names. It must be set from a principle
(e.g. empirical-Bayes from the between-team variance) or fixed before any evaluation
figure is seen, never tuned against GW2-GW5 Spearman.]`

`[gap: the vaastav archive could supply a prior from previous seasons, which would
ease the thin-data problem. Squads and managers change between seasons, so how much
weight a prior season deserves is a judgement nobody here has made. Not resolved.]`

---

## 4 — Three variants, registered together

Two changes in one variant cannot be attributed. This is the mistake `component/1.2`
made — a bundle whose entire gain turned out to be one unstable part — and FU-60 §6.1
records the further mistake of registering the decomposition variant *late*, so it
could never be scored on GW3.

| variant | fixture model | minutes term |
|---|---|---|
| `component/1.1-price` | difficulty band | scalar (control, existing) |
| `component/1.2` | difficulty band | S1–S6 (incumbent default, existing) |
| **`component/1.3-fixtures`** | **fitted** | unchanged from the incumbent |
| **`component/1.3`** | **fitted** | **simplified** |

`1.3 − 1.3-fixtures` isolates the minutes change. `1.3-fixtures − 1.1-price` isolates
the fixture change. **All four are scored in one run against one capture**, which is
the whole point of `plan evaluate --model` being repeatable.

---

## 5 — Deliberately excluded

Parked so that 1.3 stays attributable, not because they are weak:

- **Blending `ep_next`.** FPL publishes its own expected points; we parse the field
  and ignore it, and `official-ep/1.0` tops `spearman_all` at GW4 and GW5. Strong,
  cheap, and a third change would make the decomposition unreadable.
- **Rank-ensembling** the five or six models already scored every run.
- **Splitting P(plays) from E[points | plays]** into two separately evaluated
  problems. The most principled response to §1's diagnosis and the most work.

**Not FU-62.** Spearman is invariant to monotone transforms, so the compression into
[0, 5.2] cannot hurt either ranking metric. It hurts magnitudes, which only the
optimiser consumes — it belongs behind FU-72, not in a model change.

**Not FU-57 or FU-58.** Their premise is gone and both entries now say so.

---

## 6 — Development, and the line that keeps it honest

**Four gameweeks are backtestable: GW2, GW3, GW4, GW5**, each with a complete pinned
trio in `~/fpl-pinned/`. **GW1 is not and cannot be** — its deadline was
2026-08-21T17:30Z and the capture archive begins 2026-08-28; that route is closed
permanently.

**Fitting team ratings from match results is fitting to data and is fine. Tuning any
constant against our own evaluation metric on four gameweeks is what FU-50 §3
forbids.** That distinction is the difference between a model and a flattering
curve, and it is the first thing that slips under time pressure.

**GW2–GW5 are contaminated as a test set.** Every one has been read in detail and
this design is a response to what they showed. That is what a development set is for.
It is also why FU-73 names GW6 and GW7, and why the criterion must be committed
before GW6's deadline of **2026-10-10**.

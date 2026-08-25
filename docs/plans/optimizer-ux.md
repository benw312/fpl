# Plan: `fpl plan optimise` — the optimiser's user-facing output

## Context

`domain/optimizer.py` is the last unwritten module in the README Agent Plan.
[projections.md](projections.md) deliberately deferred it — *"**Out:** the
optimiser itself — search strategy, horizon defaults, pruning, captaincy
multipliers, chip interaction, and how transfer hits net off against projected
gain. `domain/optimizer.py` gets its own plan"* — and no such plan exists yet.

This document is not that plan. It settles the **output** first, because what
the optimiser must produce determines what it must search over and what each
search state must retain. A search that scores 15-player squad totals cannot
later be asked to explain a captaincy decision. A search that keeps only scalar
objective values cannot later be asked *why* a transfer was recommended. Those
are one-way doors, and they are cheaper to get right before the search exists
than after.

**Scope — in:** the command surface, the shape of the answer, how a
recommendation is explained, how hits are presented against projected gain, how
uncertainty is conveyed, and the CLI gaps this workflow depends on.

**Scope — out:** the search algorithm. No beam width, no pruning rule, no
complexity budget, no terminal-value function. Those belong in the search plan,
written against this document.

---

## 1 — The workflow, end to end

```bash
fpl sync                                            # refresh bootstrap + fixtures
fpl squad create --output squad.json                # build the 15; writes a ledger
fpl squad show squad.json                           # [gap — §8.1] where am I now?
fpl plan optimise squad.json --horizon 5            # the new command
fpl plan optimise squad.json --horizon 5 --output plan.json
fpl plan simulate squad.json plan.json              # re-validate the recommendation
fpl plan evaluate --event 5                         # after the GW: was the model right?
```

The optimiser sits between *"what is my state"* and *"prove this recommendation
validates"*. The `--output` → `simulate` round-trip is what makes the CLAUDE.md
guarantee operational — *"Every optimiser recommendation must pass the same
validator used for manual squad planning."* The two commands must print
identical per-gameweek numbers for the same path; if they diverge, one of them
is wrong, and the divergence is the test.

**The decision the output supports is singular: what to do before the next
deadline.** Everything past GW *t+1* is contingent. The plan will be re-run next
week against a newer snapshot, newer prices, newer injuries and a newer fixture
list. The horizon exists to *justify* the first move — to stop the optimiser
selling a player whose fixtures turn in three weeks — not to be executed as a
script. The output must never imply otherwise.

---

## 2 — Command surface

```
fpl plan optimise SQUAD_LEDGER
  --horizon INT        gameweeks to search (default 5)
  --from-event INT     first gameweek to plan (default: next event with an open deadline)
  --paths INT          full paths to display (default 3)
  --max-hit INT        cap on hit points per gameweek (default: uncapped)
  --model TEXT         component | naive | official-ep  (default component)
  --decay FLOAT        per-gameweek discount on the ranking objective (default 0.84)
  --robustness TEXT    rescore | full | off  (default rescore)
  --explain            per-gameweek, per-player decomposition for the top path
  --output PATH        write the winning path as a transfers-plan JSON
  --json               machine-readable output
```

Positional `SQUAD_LEDGER` follows `fpl plan simulate`'s precedent
(`cli.py:171`).

**`--horizon 5` default.** Beyond roughly GW+5 the fixtures endpoint is
provisional: cup and European rearrangement move fixtures, and `event: null`
marks the unscheduled. A longer horizon therefore buys less certainty than its
length suggests. The command must clamp the horizon to the last scheduled
gameweek and say that it did, rather than silently projecting into an empty
schedule (which `_build_schedule` would render as a blank gameweek —
indistinguishable from a real one).

**`--from-event` respects deadlines.** `apply_transfers`
(`transfers.py:239-243`) refuses a gameweek whose deadline has passed, so a run
after Friday 18:30 must start from the next gameweek. It must *announce* that,
not skip silently — the user who runs the command an hour after the deadline is
precisely the user most likely to misread the output.

**Naming.** The command is `optimise`: CLAUDE.md mandates UK English throughout,
and `plan_app`'s help string at `cli.py:45` already reads "Simulate and optimise
transfer plans." Register `optimize` as a hidden alias so the README's literal
`fpl plan optimize` works. The module stays `domain/optimizer.py` — three
existing plan docs name it that way, and renaming it is churn for no gain.

---

## 3 — The objective

Maximise **the points that actually score**, per gameweek, across the horizon:

```
objective(GW) = Σ xP(starting XI) + xP(captain)
```

The XI is the highest-xP legal formation under `Position.squad_min_play` /
`squad_max_play`; the captain is the highest-xP starter. Bench players
contribute nothing.

This is the correct objective, and it is not the cheap one. Summing xP over all
15 would ship today with no dependencies, but it is wrong in two directions at
once: it counts bench points that never score, and it ignores the captain
armband that roughly doubles one player. It would systematically over-value
bench depth and under-value premium captains — the two things a real manager
trades off most often.

Two consequences follow, and both must reach the output.

### 3.1 — The value of a transfer is not `xP(in) − xP(out)`

If the outgoing player was benched in GW6, selling him costs nothing that week.
If the incoming player becomes captain, he counts double. The raw player delta
and the realised objective delta differ, often substantially, and in a direction
the user cannot guess.

An explanation that shows only the raw delta teaches a wrong mental model. §5's
"why" view therefore shows both rows, and labels which one is the objective.

### 3.2 — This objective is blocked on FU-8

`Position.squad_min_play` and `squad_max_play` (`api/models.py:76-77` — note
FU-8 cites `51-52`, which is now `price_millions`) are parsed from the snapshot
and read by **nothing**. `validate_plan`
(`squad.py:35-42`) checks only that `starters` numbers `squad_squadplay` and is
a subset of `players`, so a starting XI of 1 goalkeeper and 10 forwards
validates clean today.

An optimiser cannot choose an XI before an illegal formation can be rejected,
and CLAUDE.md forbids shipping a recommendation the manual validator does not
back. The sequencing is therefore fixed:

> **FU-8 (formation validity) → a shared `best_xi(player_ids, projections,
> snapshot)` helper in `domain/squad.py` → `domain/optimizer.py`.**

Putting `best_xi` in `domain/squad.py` rather than inside the optimiser is what
satisfies the CLAUDE.md guarantee: the optimiser and manual planning select and
validate an XI through the same code. FU-6 and FU-9 (the per-gameweek lineup has
nowhere to live in the ledger schema — `starters`/`captain`/`vice_captain` are
stored globally) are resolved by the same piece of work; FU-6's own text already
anticipates this, naming *"when the optimiser needs to assign a captain per
simulated gameweek"* as its trigger.

### 3.3 — Discounting

Rank on a decayed sum, `decay_base = 0.84` — the objective convention from
sertalpbilal/FPL-Optimization-Tools, recorded in
[projections-survey.md](../research/projections-survey.md). The justification is
not that later gameweeks matter less to the season; it is that projection error
grows with distance, fixtures beyond GW+3 are provisional, and distant moves are
notional because the plan will be re-run.

But **display undiscounted per-gameweek xP**, so the table adds up, and show the
decayed value only as a separate `Score` column used for sorting. Two numbers
the user must reconcile is a real cost — the alternative, a headline that does
not equal the sum of the row above it, is a worse one.

---

## 4 — The answer

```
Plan · squad.json · GW5–GW9 (horizon 5) · component/1.0+banded
Snapshot GW4 finished, fetched 2026-08-25T09:12Z · fixtures 2026-08-25T09:12Z
Deadline GW5: Fri 29 Aug 18:30 UTC (in 3d 21h)
State at GW5: bank £1.4m · 1 free transfer

! UNVALIDATED — component/1.0 has never been scored against realised points.
  Run `fpl plan evaluate --event 4` before trusting the magnitudes below.
! HIT COST ASSUMED — 4 points per extra transfer is not in bootstrap-static.
  Every net figure below depends on it. See §7.

RECOMMENDED — GW5: Semenyo → Saka (−4)
  break-even +4.0 · gross +17.0 · net +13.0 over GW5–GW9
  robustness: 2 of 3 models rank this first (baseline/flat-ppg ranks it 3rd)

Paths                                       GW5    GW6    GW7    GW8    GW9    Net   Score
───────────────────────────────────────────────────────────────────────────────────────────
1 Semenyo→Saka (−4) · — · Cash→Gvardiol‡   56.7   55.1   58.3   63.8   58.8  +13.0   7.16
2 — · Semenyo→Saka · —                     54.0   55.1   57.1   62.4   57.7  +10.6   6.24
3 Semenyo→Saka (−4) · — · —                56.7   55.1   57.1   62.4   57.7   +9.3   4.94
  HOLD (no transfers)                      54.0   55.1   55.4   56.0   55.2    0.0   0.00

  Net = projected points vs holding, after hits.  Score = decayed (0.84), the sort key.
  ‡ horizon-edge decision — see §5.3.
```

Note what the example shows: taking the −4 immediately (row 1) beats waiting a
week to do it for free (row 2), but only because a second free transfer becomes
affordable at GW7. Row 3 — the same hit without the follow-up — loses to
waiting. That is the kind of interaction the horizon exists to expose, and it is
invisible at a horizon of 1.

### Fixed elements

**HOLD is pinned.** It renders always, regardless of where it ranks, because
every `Net` figure is quoted relative to it. It is the table's origin, not a
competitor. And the recommendation verb must be able to *be* hold —
`RECOMMENDED — GW5: hold (roll to 2 free transfers)` is a first-class answer,
not the absence of one. An optimiser that can only ever say "make this transfer"
is an optimiser that will tell you to burn a free transfer every week.

**`Net` is the only decision-relevant column.** Gross per-gameweek totals differ
between squads for reasons unrelated to the transfer; the delta against hold
does not.

**Hits appear three ways** — break-even (the points the hit must recover before
it is worth anything), gross, and net. "−4" on its own tells the user nothing
about whether to take it; the break-even framing is what makes it a decision
rather than a deterrent.

**The hit cost is banner-level, not footnote-level.** The 4-point deduction is
**[assumed]**: it appears in neither `game_settings` nor `game_config.scoring`
(`transfers.py:22-23`), so unlike squad size, budget or club limits it is *not*
derived from the snapshot — it is the one number in the output that the API
never confirms. Every `Net` figure, every break-even and the `RECOMMENDED` /
`MARGINAL` verdict itself are computed from it. A reader who does not know that
cannot calibrate anything else on screen, which is why it sits in the header
beside the validation banner rather than seventh in a list in §7. If FPL ever
changes the deduction, this output goes wrong silently and nothing in the app
would notice.

**`RECOMMENDED` is a reserved verb.** Below a decision margin the headline reads
`MARGINAL`, and the text says plainly that the models cannot separate the
options. The threshold is one RMSE-per-gameweek from the most recent
`fpl plan evaluate` run, if one exists.
**[assumption: there is no empirical basis for any threshold until the benchmark
has been run. Until then the value is a placeholder and the output must say so
rather than implying the margin is calibrated.]**

### Known weakness of the top-N full-path shape

Rows 1 and 3 above share a first move and differ only in a GW7 tail. Since the
first move is the only actionable output, a raw top-N ranking spends most of the
table restating one decision — and the effect worsens as the horizon grows,
because more distinct tails hang off the same opening.

**Mitigation, recommended:** constrain the displayed paths to have distinct
first-gameweek moves, so `--paths 3` yields three genuinely different decisions,
each shown with its best continuation. This keeps the full-path presentation
while removing the degeneracy. The example above deliberately violates the
constraint to show what it costs.

If raw ranking is preferred, drop the constraint and accept near-duplicate rows;
the rest of this design is unaffected either way.

---

## 5 — Why a transfer is recommended

```
Why — GW5: Semenyo → Saka  (the first move of path 1)

                         GW5    GW6    GW7    GW8    GW9   Total
  out  Semenyo (BOU)     4.1    3.9    4.4    0.0*   4.2    16.6
  in   Saka (ARS)        6.8    5.9    6.1    6.4    6.7    31.9
  ────────────────────────────────────────────────────────────────
  raw player delta      +2.7   +2.0   +1.7   +6.4   +2.5   +15.3
  realised in XI        +2.7   +0.0†  +1.7   +6.4   +2.5   +13.3   ← the objective
  hit                                                       − 4.0
  net                                                        +9.3

  * GW8: Bournemouth blank (0 fixtures)
  † GW6: Semenyo would have been benched anyway — selling him cost nothing that week
  Sale: Semenyo £6.4m (bought £6.2m; +£0.1m kept after the 50% sell-on fee)
  Buy:  Saka £10.1m.  Bank £1.4m → £−2.3m … infeasible alone; path 1 also sells …

  Path 1's remaining +3.7 comes from GW7 Cash→Gvardiol (free). See --explain.
```

The row that earns its place is **`realised in XI`**. It is the objective, and it
diverges from the raw delta wherever the bench or the armband intervened. Two
rows where one would do is the cost of §3.1 being true.

### 5.1 — What the search must retain

The explanation above is what constrains the search state. The right split is:
compute the projection table **once**, share it across every node, and retain in
each node only what cannot be recomputed.

Retain per node:

- parent pointer, the `list[Transfer]` applied, and the event
- the `SquadState` — already `frozen` (`transfers.py:127`), so cheap by
  reference; `docs/plans/transfers.md:112` records that it was made immutable
  for exactly this reason
- scalars: objective value, hit points, bank, free transfers
- the chosen XI (`tuple[int, ...]`) and the captain (`int`)

**Do not retain per-player projections in the node.**
`ProjectionModel.project` is already horizon-shaped
(`projections.py:204-207` — it takes a `Sequence[int]` of events and returns a
`(player, event)`-keyed mapping) and it is deterministic. Build one immutable
`dict[(player, event), Projection]` up front, over **every player** × horizon
events (§9), and let the explanation recompute any detail on demand from that
table plus the retained XI. This keeps nodes to roughly twenty machine words,
which is what makes a wide beam affordable, while leaving every explanatory
number exact rather than reconstructed — for any player, including ones the
search never selected.

The XI and captain are strictly *recomputable* from holdings plus the projection
table — `best_xi` is a deterministic argmax under formation constraints — so
caching them is an optimisation rather than essential state. But they must be
computed anyway to score the node, so caching is free. Say so explicitly in the
implementation, so a later reader does not mistake a cache for a source of truth.

### 5.2 — What this rules out

Retaining only a scalar objective per node would make §5's table unreconstructable:
the per-gameweek breakdown, the bench footnote and the blank-gameweek marker all
require knowing which XI was fielded when. That is the one-way door this document
exists to hold open.

### 5.3 — The horizon edge

A free transfer banked at GW9 is worth zero to a horizon-5 search and non-zero in
reality. The search therefore systematically under-values holding as it
approaches the edge, and over-values spending a transfer that would have been
better rolled into GW10.

Two responses, and both are needed:

1. **Display:** mark the final gameweek's move in each path with `‡` and exclude
   it from the recommendation text. It is an artefact of where the horizon was
   cut, not advice.
2. **Search:** a terminal value for banked free transfers is the real fix. It
   belongs in the search plan, not here — but the display marker is required
   regardless, because no terminal-value function makes the edge disappear
   entirely.

---

## 6 — Uncertainty

[projections.md](projections.md) is explicit: *"Until that has been run, v1 is
unproven regardless of how principled its structure is."* The output must not
launder an unvalidated model into a confident number.

Three mechanisms, in order of prominence.

**1. A validation banner.** If no `fpl plan evaluate` run exists for any
finished gameweek, state plainly that the model has never been scored against
realised points, and name the command that would score it. This is the first
thing on screen after the header, not a footnote.

**2. A decision margin.** `Net` against the break-even, so the user can see how
much slack a recommendation has. A +0.4 net gain and a +13.0 net gain are not
the same recommendation, and a single `RECOMMENDED` label for both would be a
lie of omission — hence the reserved verb in §4.

**3. Model disagreement.** Re-rank under `NaiveProjection` and the flat
points-per-game baseline, and report where the recommended first move lands
under each:

- `ROBUST` — first under all models
- `MARGINAL` — first under a majority
- `UNSTABLE` — the models disagree on the first move

This is computable today, requires no calibration, and answers the question the
user actually has — *should I act on this?* — rather than manufacturing an error
bar. It also targets the right quantity: the optimiser cares about *ordering*,
not absolute xP, and rank stability is exactly what disagreement measures.

`OfficialEpProjection` is excluded automatically whenever `--horizon > 1`: it
raises `ValueError` for any event but `is_next` (`projections.py:383-387`). At
`--horizon 1` it participates, making four models.

### 6.1 — Cost trade-off

`--robustness=rescore` (**default**) re-scores the top-N paths found under the
primary model, using the other models' projection tables. Cheap — a handful of
paths, not a search — but it cannot discover that another model would have
preferred a path the primary model pruned.

`--robustness=full` re-runs the entire search once per model. Honest, N× the
cost. Worth it before a wildcard or a big hit; wasteful weekly.

Recommend `rescore` as the default, and **label the claim precisely in the
output** — "2 of 3 models rank this first *among the paths found*" — so the
weaker statement is not read as the stronger one.

### 6.2 — No fabricated error bars

An RMSE band on a *difference* of two projections assumes independent errors,
and they are not independent: both projections share the same minutes model, the
same team-strength bands, the same scoring table and the same fixture data.
Their errors are strongly correlated, and a naively scaled band would be far too
wide in the direction that matters.

If error bars are ever added they need a paired-error estimate measured across
gameweeks, not `rmse × sqrt(horizon)`. Until then, disagreement and margin are
the honest signals.

---

## 7 — The assumptions block

Rendered every run, aggregated from `Projection.assumptions` (already populated
— `projections.py:295-298`) plus the assumptions the optimiser owns:

- Hit cost of **4 points per extra transfer is [assumed]** — absent from
  `bootstrap-static`, in neither `game_settings` nor `game_config.scoring`
  (`transfers.py:22-23`). Every net figure in the output depends on it, which is
  why it is *also* a header banner (§4) rather than only a line here. It is
  repeated in both places deliberately: the header is what a user reads, this
  block is what a user checks.
- **1 free transfer per gameweek is [inferred]** from the field name
  `max_extra_free_transfers` — the base is never stated by the API
  (`transfers.py:24-26`).
- **Chips are not modelled (FU-5).** If a wildcard, free hit, bench boost or
  triple captain is intended anywhere in the horizon, this plan is wrong for that
  gameweek — and `_fold_event` would additionally decrement free transfers that
  a chip should have preserved.
- **Vice-captain is not modelled**; the captain is assumed to play.
- **Fixtures beyond GW*t+3* are provisional**; blanks and doubles may move.
- Stale bootstrap / stale fixtures / stale live data, whenever applicable (§8.3).

---

## 8 — CLI audit: the gaps this design depends on

Six commands exist today: `sync`, `players list`, `squad create`,
`squad validate`, `plan simulate`, `plan evaluate`. The following gaps block or
degrade the workflow in §1. Findings *not* load-bearing for this design are
filed as FU-12 … FU-20 in [follow-ups.md](follow-ups.md) instead.

**8.1 — `fpl squad show LEDGER` is missing.** There is no way to see bank, free
transfers and holdings without running `plan simulate` against a dummy plan file.
`squad_state_table` (`presentation.py:55`) already exists and is called only from
inside `simulate` (`cli.py:205`). The command is small — replay the ledger, print
the existing table — and it is named in the README Agent Plan. §1's workflow
assumes it.

**8.2 — No projected points appear anywhere in the CLI.** `players list` sorts
by `total_points` (`cli.py:110`) — backward-looking — and shows no xP at all,
despite `domain/projections.py` existing and being the app's most sophisticated
module. A user told "buy Saka" has no way to inspect Saka's projection short of
re-running the optimiser. Needed:

- `--sort xp --horizon N` on `players list`
- `fpl players show ID --horizon N`, rendering the eight-component decomposition

The second is the natural "why this player" drill-down from an optimiser
recommendation, and is named in the README. Note that `presentation.py` contains
**no `Projection` renderer at all**, so this is new surface either way — there is
nothing to extend.

**8.3 — Three staleness channels, no unified header.** Bootstrap staleness
prints a yellow line from `load_snapshot` (`cli.py:59-63`); fixtures staleness is
buried inside a `Projection.assumptions` string (`projections.py:295-298`);
live-event staleness is never surfaced at all. The optimiser depends on all
three, and §4's header block presents them together. This wants one
`data_provenance_panel(...)` renderer in `presentation.py`, retrofittable to the
other commands.

**8.4 — No deadline is ever displayed.** `current_event_id` (`transfers.py:110`)
exists and is unused by the CLI; `sync` reports player and fixture counts but not
where we are in the season. Since `--from-event` silently advances past a closed
deadline (§2), the deadline and the time remaining must be on screen.

**8.5 — `plan simulate` shows hits but no projected gain. This ships *before*
the optimiser, not after.** It answers "is this legal?" and never "is it worth
it?" — `simulation_table` (`presentation.py:38-52`) has Event, Transfers, Hit,
Bank, Free transfers and Valid columns and no points column, because projections
did not exist when it was written.

This is not a nice-to-have that trails the optimiser. §1 makes the
`optimise --output` → `simulate` round-trip the mechanism that satisfies
CLAUDE.md's *"Every optimiser recommendation must pass the same validator used
for manual squad planning"*. A `simulate` that prints no points can only confirm
that a recommendation is **legal** — squad structure, club limits, bank, free
transfers. It cannot confirm the number the recommendation was actually made on.

That is the wrong half. Legality is already enforced inside `apply_transfers`
before the optimiser ever sees a state, so the round-trip would be re-checking
something that cannot fail while leaving the objective — the part with a novel
implementation, a decay factor, an XI selection and a captain multiplier —
entirely unverified. Until `simulate` prints per-gameweek xP, the guarantee is
aspirational: it reads as satisfied and checks nothing that matters.

**Sequencing:** add the xP columns to `simulate` first, so that on the day
`plan optimise` lands there is already an independent implementation to disagree
with it. Building both at once, or `simulate` second, means the first thing the
round-trip ever does is confirm the optimiser agrees with itself.

**8.6 — Nothing writes a transfers-plan file.** `parse_transfers_plan`
(`transfers.py:93-107`) only reads. `--output` needs the writer, and it must
round-trip exactly through the parser.

**8.7 — `_build_schedule` is private.** `projections.py:216-233` is the only
blank/double-gameweek machinery in the repo. Any output that says "GW8 blank" —
as §5's example does — needs it exposed rather than reimplemented. Filed as
FU-20.

### Hard blockers

Each of these must be resolved before `fpl plan optimise` ships. They are not
caveats to be printed; they are defects that make the output wrong.

| Item | Subject | Effect on this design |
|---|---|---|
| **FU-8** | Formation validity never checked | Blocks §3's objective outright |
| **FU-6 / FU-9** | Per-gameweek lineup has nowhere to live | Resolved by the same work as FU-8 |
| **FU-11** | Unavailable players still score | The search may **buy** injured players — see below |
| **FU-5** | Chips not modelled | Plan is wrong for any chip gameweek in the horizon |
| **§8.5** | `simulate` prints no points | The round-trip verifies legality, not the objective |

#### Why FU-11 is a blocker and not an assumption

`_minutes_probabilities` implements `p1 = p_start + (1 - p_start) *
p_sub_appearance`. `_availability` correctly drives `p_start` to 0 for a player
with `status` in `{i, s, u}`, but `p_sub_appearance` is a flat 0.35 applied
regardless of availability. A long-term injury therefore keeps a 0.35
appearance probability and a non-zero `xmins`, and every downstream component
is gated through those.

The consequence is worse than holding a player too long. The optimiser searches
over *every* player as a transfer target, and it ranks them by `xp_total`. A
£4.5m defender who is out for the season still projects a small positive score
— and being cheap, he is affordable in states where better players are not. The
search has no other signal that would reject him: `can_transact` gates
transacting, not projecting, and nothing else in the objective knows he is
unavailable. Under budget pressure a bench slot filled by an injured cheap
player can therefore score *higher* than the same slot filled by a fit one of
the same price, because the injury costs him nothing the model can see.

That is the exact inversion of the README Agent Plan's *"Penalize unavailable or
risky players"*, and it fails in the most visible place: a recommendation to
**buy** a player the user can see is injured on the official site. A user shown
that once will not trust the tool again, and no amount of assumption-block text
recovers it — the caveat arrives after the recommendation has already destroyed
its own credibility.

FU-11's own entry says this needs a decision rather than a silent patch, because
the projections-v1 plan specifies the ungated formula precisely and may have
intended it. That decision now has a forcing function. The candidate fix is
recorded there: gate the substitute term on availability too,
`p1 = p_start + (1 - p_start) * p_sub_appearance * availability`.

---

## 9 — The projection table covers every player, always

This looked like a search-cost question. It is an interface question, so it is
settled here rather than deferred.

**Decision: build the projection table over the full player population × the
horizon. Prune candidates inside the search, never in the table.**

### Why it is not a search-cost decision

Measured on the current snapshot, `ComponentProjection.project` over all 612
players × 5 events builds 3,060 projections in **84 ms**. It is O(players ×
events) with small constants — the Poisson helpers are hand-rolled over bounded
ranges (`projections.py:107-118`) and the minutes model is computed once per
player, not per event (`projections.py:270`). The table is built **once** per
run and shared by every search state. A beam search evaluates orders of
magnitude more states than there are table entries, so pre-filtering optimises
the wrong term.

### Why it is an interface decision

Three surfaces in this document require a projection for a player the search may
have pruned:

1. **§8.2's `fpl players show ID --horizon N`.** The user's natural next move
   after a recommendation is to inspect a player — including one the optimiser
   *didn't* pick, which is precisely the case a candidate filter would have
   dropped. A drill-down that fails on exactly the players the user is most
   curious about is worse than no drill-down.
2. **§5's explanation.** It quotes per-gameweek projections for both sides of a
   transfer. The outgoing player is in the squad and so always in any candidate
   set; the incoming player is only there if the filter kept him. A filter
   tuned for search speed would silently constrain what can be explained.
3. **Negative explanation — "why *not* X?"** With a complete table the CLI can
   answer the second-most-common question a planning tool gets: *"why didn't you
   suggest Haaland?"* — `not considered: £15.0m, unaffordable with £1.4m bank
   and no sale that funds him`. This is only possible because his projection
   exists even though the search rejected him. A pre-filtered table can only say
   nothing, and an optimiser that cannot say why it declined an obvious option
   is one users route around.

The third point generalises: **a filter that runs before the table is invisible;
a filter that runs inside the search is reportable.** That asymmetry, not the
84 ms, is the reason for the decision. The candidate set remains a legitimate
and probably necessary search device — it just belongs to the search, which must
be able to name what it excluded and why.

**Consequence for the search plan:** candidate pruning is in scope for it, with
one constraint inherited from here — exclusions must be attributable to a stated
reason (unaffordable, club limit, position not needed, dominated), not an
anonymous top-*k* cut.

**If this ever does show up in a profile,** the fix is caching the table across
runs keyed by snapshot `fetched_at`, not filtering it. Projections are
deterministic given a snapshot and a fixture list.

---

## 10 — Open questions for the search plan

Recorded here because this document's decisions imply them, not because it
answers them:

- The terminal value of banked free transfers at the horizon edge (§5.3).
- Whether `best_xi` is recomputed per node or incrementally updated after a
  single-player swap.
- The decision-margin threshold in §4, once `fpl plan evaluate` has been run
  against enough finished gameweeks to measure one.
- The candidate-pruning rule itself, subject to §9's attributability constraint.

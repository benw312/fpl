# Plan: `domain/optimizer.py` — the search

## Context

[optimizer-ux.md](optimizer-ux.md) settled what the optimiser must produce. This
document settles how it finds it: the algorithm, the pruning rules, the cost
budget, and the four items left open in that document's §10.

The hard blockers it named have since landed on main — FU-8 (formation validity,
`0d4dc85`), `best_xi`/`objective_points` (`10a95e3`), FU-11 (availability gating,
`a7b86d3`), and §8.5's per-gameweek xP in `plan simulate` (`dd14d9b`). Nothing
structural now blocks the search.

Everything numeric below was **measured against the live cached snapshot**
(612 players, 20 clubs, `squad.json`, Python 3.14.3, single-threaded CPython, no
numpy) rather than estimated. Where a number is an assumption it is flagged
`[assumption: …]`.

**Scope — in:** the search algorithm, candidate pruning, node state, terminal
value, cost budget, determinism, testing.

**Scope — out:** chips (FU-5 — see §9), the decision-margin threshold in
optimizer-ux.md §4 (still blocked on `fpl plan evaluate` runs), and the CLI
rendering, which optimizer-ux.md §4–§7 owns.

---

## 1 — The objective, derived rather than assumed

optimizer-ux.md §3 gives the per-gameweek objective and §3.3 gives the decay, but
never states how the two combine with hits. The worked example in §4 pins it down
exactly, so it can be derived rather than guessed. Reading the per-gameweek totals
off that table and differencing against the pinned `HOLD` row:

| Path | Δ per GW (GW5…GW9) | Gross | Net | Score |
|---|---|---:|---:|---:|
| 1 | 2.7, 0.0, 2.9, 7.8, 3.6 | +17.0 | +13.0 | 7.16 |
| 2 | 0.0, 0.0, 1.7, 6.4, 2.5 | +10.6 | +10.6 | 6.24 |
| 3 | 2.7, 0.0, 1.7, 6.4, 2.5 | +13.3 | +9.3 | 4.94 |

Applying `0.84^(w − w₀)` with the exponent starting at **0** for the first planned
gameweek reproduces all three `Score` values to two decimal places
(row 1: `2.7 + 0 + 2.9(0.7056) + 7.8(0.5927) + 3.6(0.4979) = 11.16`, then `− 4.0`).
Row 3's gross of `+13.3` is also exactly §5's `realised in XI` total, confirming
that the two sections describe one quantity.

So the ranking objective is:

```
objective(path, w) = Σ xP(best_xi(holdings_w), w) + xP(captain_w, w)

Score(path)  = Σ_w  decay^(w − w₀) · [objective(path, w) − objective(HOLD, w)]
             − points_per_extra_transfer · Σ_w paid_transfers(path, w)
             + terminal_value(path)                                    # §6.1

Net(path)    = Σ_w  [objective(path, w) − objective(HOLD, w)]
             − points_per_extra_transfer · Σ_w paid_transfers(path, w)
```

Three properties worth stating explicitly, because none is obvious and all three
are load-bearing for the search:

- **Hits are undiscounted.** They are subtracted at face value regardless of which
  gameweek they fall in. A hit taken in GW9 costs the same 4 points as one taken in
  GW5, while the points it buys are discounted by `0.84⁴ = 0.498`. This is the
  correct behaviour — the deduction is certain and immediate, the gain is neither —
  but it means the search is *structurally* biased against late hits, on top of the
  horizon-edge bias §6.1 addresses.
- **Score is a delta against HOLD, not an absolute.** The search must therefore
  compute the `HOLD` path first and keep it as the origin. It is not a competitor
  in the beam and must never be pruned from it.
- **`objective` is computed against the projection table only.** It does not read
  `SquadState.bank` or `free_transfers`; those constrain feasibility, not value.
  Their only effect on `Score` is through hits and (§6.1) terminal value.

`decay`, `points_per_extra_transfer` and the horizon all come from existing
sources — `--decay` (default 0.84), `TransferRules.points_per_extra_transfer`
(`transfers.py:27`), `--horizon`. Nothing new is hardcoded.

---

## 2 — What the search inherits

The repo already fixes most of the search's shape. Measured costs, all per call:

| Operation | Cost | Source |
|---|---:|---|
| `ComponentProjection.project` — 612 players × 5 events | **87 ms**, once per run | `projections.py:268` |
| `best_xi` + `objective_points` | **136 µs** | `squad.py:93,158` |
| the same, value only, without materialising formation tuples | **17.7 µs** | §6.2 |
| the same, incrementally after a one-player swap | **5.5 µs** | §6.2 |
| `apply_transfers` (one transfer, full validation) | **197 µs** | `transfers.py:229` |
| the same, with `players_by_id` memoised | **69 µs** | §9, FU-23 |

Two of these are defects rather than facts, and both are separate concerns that
should land on their own branches **before** the optimiser (CLAUDE.md: *one concern
per branch*):

- **`BootstrapSnapshot.players_by_id` rebuilds a 612-entry dict on every access**
  (`models.py:174`), and `apply_transfers` reaches it twice per call. Memoising it
  takes `apply_transfers` from 197 µs to **69 µs — a 2.9× win on the search's
  hottest validation path**, and it also speeds up every existing command. The same
  applies to `.clubs` and `.positions`. Filed as **FU-23**.
- **`best_xi` spends most of its time materialising eight sorted 11-tuples** inside
  the formation loop (`squad.py:144-146`), one per candidate formation, when only
  the winner's tuple is ever used. Splitting the value computation from the witness
  takes it from **136 µs to 17.7 µs — 7.7×**. This is the single largest available
  speedup in the whole design, and it is a refactor of existing code rather than new
  work. Filed as **FU-24**; see §6.2 for the exact split.

Both are prerequisites in the sense that §7's cost budget assumes them. The search
is correct without them and roughly 4× slower.

---

## 3 — The size of the problem, measured

From `squad.json`'s state (bank £0.0m, 15 holdings, 571 transactable players):

| Move set | Legal moves from one state |
|---|---:|
| 0 transfers (hold) | 1 |
| 1 transfer | **2,031** |
| 2 transfers | **2,427,098** |

Scoring every 2-transfer child over a 5-gameweek horizon at the *current* `best_xi`
cost would take **~28 minutes for a single node's children**. Exhaustive enumeration
is dead at k = 2, and the numbers make clear it is not close.

Two things follow immediately, and they frame everything else:

1. **The candidate set must be cut, and optimizer-ux.md §9 constrains how** — every
   exclusion must carry a stated reason, never an anonymous top-*k*. §5.2 shows that
   an *exact* rule does most of the work.
2. **`--max-hit` cannot default to uncapped** as optimizer-ux.md §2 specifies. With
   `transfers_cap = 20`, uncapped means the per-gameweek move set is
   `Σₖ C(15,k) · pool^k` — unbounded in any practical sense. **Amendment to §2:
   `--max-hit` defaults to 4** (one paid transfer above the free allowance),
   bounding k at `free_transfers + 1`. Higher values are accepted; above 8 the
   command warns that deeper levels switch to heuristic move generation (§5.4).
   This is the only change this document makes to the settled command surface.

---

## 4 — The central decision: beam search, state-pruned DP, or MILP

The README Agent Plan says *"Start with bounded beam search or state-pruned dynamic
programming."* sertalpbilal/FPL-Optimization-Tools — Apache-2.0, and the source of
this project's `decay_base = 0.84` — uses MILP over HiGHS. The README is not
evidence; it was written before any of this code existed. Each option is argued
below against what is actually in the repo.

### 4.1 — State-pruned DP is not viable standalone, but it contributes

The DP state would be `(event, holdings, bank, free_transfers)`. `holdings` is a
15-subset of 612 players, and there is no sufficient statistic that collapses it:
the club limit (≤3 per club) and the budget couple all fifteen slots, and the
objective couples them again through `best_xi`, which selects across positions
jointly. Unlike knapsack there is no dimension to sweep. "State-pruned DP" at this
scale is either exponential enumeration or — once the pruning is aggressive enough
to be affordable — beam search wearing a different name.

What DP *does* contribute is a **dominance test**, and it is exact:

> Two nodes at the same event with identical `holdings` are comparable. If
> `bank_A ≥ bank_B`, `free_transfers_A ≥ free_transfers_B` and
> `cumulative_score_A ≥ cumulative_score_B`, then B can be discarded: every
> continuation available to B is available to A at no lower value.

This is sound because those quantities are the complete forward-relevant state —
the objective depends only on `holdings` and the projection table, and feasibility
depends only on `bank` and `free_transfers`. It costs one dictionary lookup keyed by
`(event, frozenset(holdings))`, and it also **deduplicates transfer orderings**,
which would otherwise multiply the beam without adding paths. Folded into §5.5.

Note that "dominated" is one of the four reasons optimizer-ux.md §9 names as
acceptable. That is not a coincidence: the UX document already anticipated a
dominance rule.

### 4.2 — MILP: a fair account of what it wins

FPL linearises better than its reputation suggests, and it is worth recording which
parts, so a future reader does not have to re-derive it:

- **Squad composition** (`Σx = 15`, per-position `squad_select`, club limit ≤3) —
  pure linear on binaries.
- **Starting XI and captain** — `y ≤ x`, `Σy = 11`, per-position
  `squad_min_play`/`squad_max_play` on `y`, `c ≤ y`, `Σc = 1`, objective
  `Σ xP·y + Σ xP·c`. This is exactly optimizer-ux.md §3's objective, expressed
  linearly.
- **Transfer accounting** — `t_in − t_out = x_w − x_{w−1}`.
- **Selling prices** — `selling_price` (`transfers.py:160-167`) contains a `floor()`,
  which is nonlinear in general. It is *constant* here: for a held player the
  purchase price is known, and for a player bought and sold inside the horizon the
  app has no price-change model, so `now_cost == purchase_price` and profit is zero.
  Every sale price is therefore a per-player constant. It linearises cleanly today,
  and would stop doing so the moment a price model is added.
- **Hits** — `hits_w ≥ transfers_w − free_w`, `hits_w ≥ 0`, tight at the optimum
  because the objective penalises them.
- **Chips (FU-5)** — a wildcard week is a binary that relaxes the transfer-count
  constraint for one gameweek. This is where MILP is not merely competitive but
  decisively better; see §4.4.

And what it buys: a **proven** optimum rather than a best-found one; no beam-width
knob; optimizer-ux.md §9's attributability constraint satisfied by construction,
since a MILP excludes nobody — all 612 players are in the model; and a *better*
negative explanation than a search can give, since "forcing Haaland in costs 6.2
points over the horizon and requires selling X and Y" is strictly more informative
than "he was pruned".

### 4.3 — Why it loses *here*, specifically

The argument below is about this objective. It is not a claim about MILP in
general; see the end of this section.

**The inner problem has a closed form, and the MILP encoding discards it.**
`best_xi` is not a general combinatorial subproblem. Because the objective is
separable within a position, the optimal XI for any candidate formation is a
*prefix* of that position's xP-sorted list — so the whole nested argmax reduces to
four sorts of ≤5 elements, four prefix-sum arrays, and an enumeration of the **8**
legal formations (`squad_min_play`/`squad_max_play` admit exactly 8 that total 11).
Measured: **17.7 µs**, closed form, no search. In MILP that same subproblem becomes
`y` and `c` binaries at every `(player, event)` — for 612 players × 5 events the
nested argmax alone **triples the binary count**, from ~3,060 to ~9,180 before a
single transfer variable is declared, and hands a polynomially-trivial problem to
branch-and-bound. Paying a solver to rediscover a prefix property we can evaluate in
17 µs is the wrong trade.

**optimizer-ux.md §5 requires the XI and captain of paths that are not the
optimum.** In a direct-evaluation search the XI and captain are computed at every
node because the objective cannot be evaluated without them — §5.1's retained state
is a by-product that costs nothing. In a MILP the `y`/`c` values exist only for the
solution returned. The `†` footnote in §5 ("GW6: Semenyo would have been benched
anyway") needs the *HOLD* path's XI in GW6; §4's table needs three alternative paths
each with per-gameweek totals; §4's mitigation requires those three to have
*distinct first moves*, i.e. three solves with the first move fixed. That is
**≥4 solves for the default display**, plus one per `--explain` counterfactual and
one per "why not X" probe — each a black box of unpredictable duration. The beam
already contains all of them.

**The free-transfer recurrence would be encoded twice.**
`free_w = min(free_{w−1} − transfers_{w−1} + 1, cap)` with `max(0, ·)`
(`transfers.py:184,201-203`) needs indicator binaries or a one-hot encoding of the
free-transfer count per week. That is a second, independent implementation of
`_fold_event`, in a different formalism, including both constants the README flags
as unverifiable against the API (`points_per_extra_transfer`,
`free_transfers_per_event`). CLAUDE.md's *"Every optimiser recommendation must pass
the same validator used for manual squad planning"* is satisfied **structurally** by
a search that calls `apply_transfers` verbatim, and only **testably** by a MILP that
re-encodes it. The round-trip in optimizer-ux.md §1 would then compare two
implementations rather than exercise one — arguably a stronger test, but a doubled
rule surface and a doubled drift risk on constants that change silently.

**Secondary, but real in this environment.** A solver is a compiled dependency
(`highspy`, MIT) in a project whose five runtime dependencies are deliberately
minimal and which already refused scipy for less — *"These are small enough to
hand-roll rather than add the dependency for"* (`projections.py:106`). The venv runs
**Python 3.14.3**, where compiled-wheel availability commonly lags;
`[gap: highspy's 3.14 wheel coverage is unverified — checking it is a prerequisite
of ever revisiting this]`. And a MIP under a time limit returns whatever incumbent it
holds, which sits badly with the README's *"verify known optimizer outcomes"*.

**This is not a claim that MILP is the wrong tool for FPL.** sertalpbilal's solver
optimises a different formulation — externally supplied projections, a longer
horizon, chips, multiple objectives, and no requirement to explain a recommendation
or to reuse a specific validator. Under those constraints MILP's advantages dominate
and beam search would be the wrong choice. The divergence here is driven by three
properties of *this* problem: a closed-form inner argmax, an output specification
that needs non-optimal paths, and an existing rule implementation that must not be
duplicated.

### 4.4 — Decision, and what would change it

**Beam search, over an exactly-pruned candidate set, with the root gameweek
enumerated exhaustively and DP dominance folded in.** `optimise(...)` is a plain
function taking a `SquadState` plus a projection table and returning ranked paths;
**no strategy Protocol and no solver seam** — the input and output are already the
natural interface for any backend, so a later swap is mechanical rather than
speculative.

Revisit this decision if any of the following becomes true:

| Trigger | Why it flips the argument |
|---|---|
| **Chips land (FU-5)** — the most likely trigger | A wildcard gameweek is an unconstrained re-selection of all 15 from 612. Branching is hopeless for search; for MILP it is one relaxed constraint. Free hit additionally breaks the "a node is a squad" assumption, since the squad reverts. |
| Horizon routinely exceeds ~8 gameweeks | Beam continuation error compounds with depth; MILP's cost grows far more slowly than enumeration. |
| The XI rule stops being a per-position prefix | e.g. a "field ≥1 player from a doubling team" constraint. The closed-form inner argmax is the load-bearing half of §4.3. |
| Projections become validated and well-separated | Ranking differences of ~0.5 points are currently inside the model's own error (optimizer-ux.md §6), so exact optimality buys precision, not accuracy. If `fpl plan evaluate` ever shows the model is that good, this changes. |
| numpy or another compiled dependency is accepted anyway | The marginal cost of `highspy` drops to near zero. |

---

## 5 — The search

### 5.1 — The projection table and the node

Unchanged from optimizer-ux.md §5.1 and §9, which settled both. One table per run
over **all** players × horizon events (**87 ms measured**, 3,060 entries), immutable,
shared by every node. The node retains parent pointer, `list[Transfer]`, event, the
frozen `SquadState`, scalars (cumulative score, hit points, bank, free transfers),
and the chosen XI and captain.

One addition the search requires: a node also carries **`exclusions`**, a mapping
from excluded `player_id` to a reason string, populated per §5.2/§5.3 so the
"why not X" surface can answer without re-deriving anything.

### 5.2 — The candidate set: exact dominance, not top-*k*

optimizer-ux.md §9 requires exclusions to be attributable. The primary rule is
**exact**, so it is attributable by construction:

> Within one `(position, club)` bucket, player A dominates player B if
> `now_cost(A) ≤ now_cost(B)` and `xP(A, e) ≥ xP(B, e)` for **every** event e in the
> horizon. B is excluded, with the reason `dominated by <A>: costs £Xm less (or the
> same) and projects at least as many points in every gameweek of the horizon`.

Bucketing by `(position, club)` rather than by position alone is what makes it
sound. A dominator from a different club could be unusable when that club is at the
3-player limit; a same-club, same-position teammate is interchangeable under every
constraint the rules impose — squad quota, club limit, budget and formation all treat
them identically. Per-event comparison (rather than comparison of the decayed sum) is
what makes it exact: a squad holds a player over a contiguous span of gameweeks, so a
player who is better only *on aggregate* may still be worse over the span actually
used.

**Measured on the live snapshot, 5-event horizon:**

| Rule | Buy pool | Reduction |
|---|---:|---:|
| transactable, not held | 556 | — |
| exact `(position, club)` Pareto frontier | **178** | **3.1×** |
| position-global Pareto frontier (unsound — ignores the club limit) | 15 | 37× |

The position-global figure is recorded only to show what is being left on the table
for soundness, and as a warning: it is 15 because at this point in the season
`_appearances` is 1, so the minutes shrinkage collapses to the position prior
(`projections.py:84`, with `_appearances` documented at `:69-76`) and xP is nearly a
monotone function of per-90 rates. **Dominance will prune less as players
differentiate through the season.** That costs speed and never correctness, which is
the right way round — but §7's budget should be re-measured around GW10.

Downstream effect on branching, from the same state as §3:

| Move set | Unpruned | After exact dominance |
|---|---:|---:|
| 1 transfer | 2,031 | **562** |
| 2 transfers | 2,427,098 | **189,147** (12.8×) |

Alongside dominance, three per-node feasibility exclusions, each already carrying its
reason and each one of §9's named four: **unaffordable** (quoting the bank and the
shortfall), **club limit** (naming the three players already held), **already held**.
`can_transact`/`can_select`/`removed` filtering reuses the predicates in `_selectable`
(`squad.py:238`).

**No top-*k* cut is ever applied to the candidate set.** Beam width truncates
*paths*, which is a different object; §5.6 states exactly what that costs, and the
output must not conflate the two.

### 5.3 — Move generation within a gameweek

`k` ranges over `0 … min(free_transfers + ⌊max_hit / 4⌋, transfers_cap)`. With §3's
amended `--max-hit 4` default and one free transfer, that is `k ≤ 2`.

- **k = 0 (hold)** is `apply_transfers(state, [], event, …)`. `apply_transfers` folds
  the intervening idle events itself (`transfers.py:309-310`) and accrues free
  transfers correctly, so hold needs no special case — **one code path, and it is the
  existing validator.**
- **k = 1** — enumerate the pruned candidate set per outgoing player.
- **k = 2** — enumerate out-pairs × in-pairs subject to joint budget and club counts.
- **k ≥ 3** — see §5.4; generated heuristically and labelled as such.

The generator does arithmetic on `bank`, club counts and position counts; it does
**not** call `apply_transfers` per child. `apply_transfers` is called on every child
**retained into the beam**, and is the authority: a child the generator produces and
`apply_transfers` rejects is dropped, and in tests is an assertion failure (§8). This
keeps CLAUDE.md's guarantee intact — every node in a reported path has passed the
manual validator — while not paying 69 µs of validation for 562 children of which a
few dozen survive.

### 5.4 — The root gameweek is enumerated exhaustively

optimizer-ux.md §1: *"The decision the output supports is singular: what to do before
the next deadline."* The search is shaped around that.

At the root (`--from-event`, i.e. the next open deadline), **every legal move with
k ≤ 2 over the pruned candidate set is enumerated and scored exactly** — 562 + 189,147
children measured. Ranking proceeds in two stages, both reportable:

1. **Immediate value.** Score every child at the root event only:
   189,709 × 17.7 µs ≈ **3.4 s**.
2. **Hold-out value.** Take the top 5,000 by stage 1 and score each over the full
   horizon *with no further transfers* — the value of making this move and then doing
   nothing: 5,000 × 5 × 17.7 µs ≈ **0.44 s**. This is what captures optimizer-ux.md
   §1's reason for having a horizon at all ("to stop the optimiser selling a player
   whose fixtures turn in three weeks"); ranking on stage 1 alone would
   systematically discard exactly those moves.

Retain the top **`--first-moves`** (default 50) distinct first moves by hold-out
value, plus `HOLD`, as the roots of the beam.

**k ≥ 3 is not exhaustible** (out-triples × in-triples is ~10⁸) and is generated by
ranking on the sum of the individual single-transfer deltas, then scoring the top
candidates exactly. That estimate is **not admissible**, and this was measured rather
than assumed: over 3,082 sampled cross-position pairs, the true joint delta exceeded
the sum of the two individual deltas in **144 cases (4.7%), by up to 2.21 points**.
So no additive-bound argument can make a k ≥ 3 cut exact, and the output must label
3+ transfer moves as heuristically generated. Under the default `--max-hit 4` this
path is never taken — the k ≤ 2 enumeration is complete — and that is worth saying
plainly in the output.

*(The same measurement is why k = 2 is enumerated rather than generated from ranked
singles: the cheap route is demonstrably not safe, and the exact route is
affordable.)*

### 5.5 — Beam levels

For events after the root:

- Expand each beam node over k = 0…max, generating children per §5.3.
- Score each child at that event only — the path value is cumulative, so earlier
  gameweeks are already accounted for in the parent. This is why the per-level cost
  is `nodes × children × 17.7 µs` and not `× horizon`.
- **Bucket the beam by root first move.** Retain `--beam` (default 4) continuations
  per first move. This does three things at once: it implements optimizer-ux.md §4's
  distinct-first-move display constraint directly rather than as a post-filter; it
  guarantees no first move is dropped before its best continuation has been explored;
  and it keeps `HOLD` exact, since HOLD is its own bucket and is never in competition.
- **Apply the §4.1 dominance test within each bucket**, keyed by
  `(event, frozenset(holdings))`. This is exact, and it collapses the transfer-order
  duplicates that would otherwise fill the beam.
- Tie-break deterministically on `(−score, transfers_made, sorted transfer ids)` so
  two runs against one snapshot give one answer. Projections are deterministic
  (optimizer-ux.md §9) and nothing else in the loop is ordered by a set.

### 5.6 — The guarantee, stated precisely

Beam search cannot promise the globally optimal path. What it *can* promise here is
the thing the output exists for:

> **Under the default `--max-hit 4`, the recommended first move is selected from a
> complete enumeration of every legal move available before the next deadline.**
> No first move is excluded except by an exact dominance rule or a feasibility
> constraint, each of which names itself. What the beam approximates is the
> *continuation value* used to rank those first moves — not which moves were
> considered.

That is the honest statement, and it should appear in the output, because the weaker
reading ("the optimiser found the best plan") is the one a user will otherwise
assume. It also bears directly on §4: the quantity beam search approximates is a
continuation value computed against projections that are themselves unvalidated
(optimizer-ux.md §6) and provisional beyond GW+3 (optimizer-ux.md §7). Exact
optimisation of a noisy objective buys precision, not accuracy.

---

## 6 — Resolving optimizer-ux.md §10

### 6.1 — Terminal value of banked free transfers (§5.3)

A free transfer banked at the horizon edge is worth zero to the search and non-zero
in reality, so the search over-spends near the edge — compounded by §1's finding that
hits are undiscounted while their payoff is not.

```
terminal_value(node) = decay^(H−1) · ft_value · min(free_transfers_H, free_transfer_cap)
```

**`ft_value` is a constant, `--ft-value`, defaulting to 1.5 points.**
`[assumption: 1.5 is the community/FPL-Optimization-Tools convention.
docs/research/projections-survey.md records only that repo's decay_base = 0.84, not
its ft_value — so unlike the decay factor this number has no provenance in this repo
and must be treated as unsourced until verified.]`

**A run-time estimator was considered and rejected on measurement.** The obvious
principled default — estimate a transfer's worth as the best free single-transfer
gain from the current squad — gives **9.96 points** for `squad.json` at the root
event (49.12 over 5 gameweeks). The estimator is dominated by squad *quality*, not by
the marginal worth of a transfer: a poor squad makes a banked transfer look worth ten
points, which would make the search hoard transfers it ought to be spending. A
squad-independent constant is less clever and more honest.

The principled version is a **two-pass self-consistent estimate**: search with
`ft_value = 0`, take the winning path's terminal squad, compute the best free
single-transfer gain at event H *from that squad*, then re-run with it. It costs 2×
the runtime and needs a convergence argument. Filed as **FU-25**, not built now.

**No bank terminal value.** `itb_value` is 0 and is not exposed. Money's value inside
the horizon is already captured through affordability; a non-zero value would be a
hedge against post-horizon price movement, which this app does not model at all.
`[gap: a price-change model would make itb_value meaningful; inventing one now would
be inventing detail.]`

**Display.** Terminal value enters `Score` and never `Net` or the per-gameweek
columns, preserving optimizer-ux.md §3.3's rule that the table adds up. It breaks the
exact identity §1 derives (`Score` = decayed `Net`), so the footnote under §4's table
must change to *"Score = decayed (0.84) net vs hold, plus the terminal value of
banked transfers"*, and `--ft-value 0` recovers the identity exactly. `--explain`
shows the contribution as its own line. *(Alternative considered: a separate `Edge`
column, keeping `Score` reader-verifiable. Rejected as clutter for a term that is
usually 0 or 1.5, but it is a one-line change if preferred.)*

Because `ft_value` is unvalidated, the output additionally reports **whether the
recommendation changes at `ft_value ∈ {0, 2 × default}`**. Rescoring stored paths is
free, and it matches optimizer-ux.md §6's principle: show disagreement, do not
fabricate an error bar.

The `‡` marker of optimizer-ux.md §5.3 is retained regardless. No terminal-value
function makes the edge disappear.

### 6.2 — `best_xi` per node, or incrementally updated (§10)

**Recompute per node — but split value from witness.** Measured, per call:

| | Cost | vs current |
|---|---:|---:|
| `best_xi` + `objective_points` as written today | 136 µs | — |
| value only, winner's tuple materialised once | **17.7 µs** | 7.7× |
| incremental after a single-player swap | 5.5 µs | 25× |

The split, both halves in `domain/squad.py` so the CLAUDE.md guarantee holds:

- **`xi_value(player_ids, projections, snapshot) -> float`** — the hot path. Four
  sorts of ≤5 elements, four prefix-sum arrays, 8 legal formations, plus the captain
  term. Returns the objective and nothing else. Called `nodes × children` times.
- **`best_xi(...) -> BestXI`** — unchanged signature; materialises starters, captain
  and (FU-22) vice-captain. Called only for nodes retained into the beam, and for
  output.

Both share one formation enumeration, so `xi_value` cannot drift from the XI that
`validate_plan` will check.

**Incremental is rejected for now**, on four grounds:

1. The remaining 3.2× is not decisive. §5.2's exact dominance is worth 12.8× on the
   same axis, and §2's `players_by_id` fix another 2.9× on validation. The orders of
   magnitude are in pruning, not in the per-node constant.
2. It only helps k = 1 children. A k = 2 move across two positions perturbs two
   buckets, so the bookkeeping grows in exactly the case that dominates the cost.
3. The incremental state must be invalidated on every event boundary, because the xP
   ranking within a position changes each gameweek. That is the bug most likely to
   produce a plausible wrong answer rather than a crash.
4. It is optional by construction. Revisit only if profiling shows `xi_value` above
   ~30% of runtime, and then behind a property test asserting equality with `best_xi`
   on randomly generated squads.

Recording the third bullet explicitly, per optimizer-ux.md §5.1: the retained XI and
captain are a **cache of a deterministic argmax, not a source of truth** — they must
be reproducible from `holdings` plus the projection table at any time.

### 6.3 — Candidate-set attributability (§9)

Answered by §5.2. Every exclusion carries one of four reasons — `dominated` (exact,
naming the dominator), `unaffordable` (quoting bank and shortfall), `club limit`
(naming the three held players), `already held` — and the pruned set is reachable
from the node, so `fpl players show` and the "why not X" surface can answer without
re-running anything. **No top-*k* cut is applied to candidates at any point.** The one
genuinely heuristic cut in the design is the k ≥ 3 move generator (§5.4), which is a
cut on move *combinations* rather than on players, is unreachable under the default
`--max-hit`, and must be labelled where it is used.

### 6.4 — The decision-margin threshold (§10) — still open

Unchanged. It needs `fpl plan evaluate` run against enough finished gameweeks to
measure an RMSE-per-gameweek, and no such run exists. Until then the
`RECOMMENDED`/`MARGINAL` threshold stays the placeholder optimizer-ux.md §4 already
requires the output to admit to.

---

## 7 — Cost budget

Horizon 5, `--max-hit 4`, `--first-moves 50`, `--beam 4`, assuming §2's FU-23/FU-24
prerequisites:

| Stage | Cost |
|---|---:|
| projection table (612 × 5) | 0.09 s |
| root stage 1 — 189,709 children × 1 event | 3.4 s |
| root stage 2 — top 5,000 × 5 events | 0.44 s |
| beam levels — 200 nodes × 562 children × 4 levels | 8.0 s |
| `apply_transfers` on retained nodes (~1,000) | 0.07 s |
| `--robustness=rescore` over 3 models | < 0.1 s |
| **total** | **≈ 12 s** |

Acceptable for a planning command run once a week before a deadline. Without FU-23
and FU-24 it is roughly 4×, which is not.

Notes: `--robustness=full` multiplies the whole budget by the model count, which is
what optimizer-ux.md §6.1 already says it costs. `--horizon 8` roughly doubles the
beam-level term. §5.2 warns that dominance prunes less as the season progresses, so
**re-measure around GW10**; if the budget breaks, the escape hatch is vectorising
`xi_value` over candidates — which means numpy, and therefore the same dependency
conversation §4.3 declined. Decide it then, on evidence.

---

## 8 — Testing

Per the README's Verification section, on the synthetic dataset in
`tests/conftest.py`:

- **Known outcomes.** On a dataset small enough to brute-force every k ≤ 2 path over
  a 2-gameweek horizon, assert the search's answer equals the enumerated optimum. This
  is the test that actually exercises the beam, so the fixture must be sized such that
  the beam genuinely truncates.
- **The generator is a filter, not a bypass.** Property test: for random states, every
  child the generator emits is accepted by `apply_transfers`. A rejection is a test
  failure, not a silently dropped node.
- **Dominance is exact.** Property test: for random `(position, club)` buckets, no
  excluded player appears in any optimal squad found by brute force over that bucket.
- **`xi_value` ≡ `objective_points(best_xi(...))`** on random 15-player squads. This
  is the guard that keeps the fast path honest, and it is also the precondition for
  ever adding the incremental variant.
- **The round-trip.** `optimise --output` → `plan simulate` must print identical
  per-gameweek xP and identical hits. optimizer-ux.md §1 makes this the operational
  form of CLAUDE.md's guarantee, and since `dd14d9b` it checks the objective rather
  than only legality. Needs FU-22 (vice-captain) and optimizer-ux.md §8.6 (a
  transfers-plan writer) to exist first.
- **Determinism.** The same snapshot, run twice, produces byte-identical `--json`
  output.
- **Horizon clamping** (optimizer-ux.md §2), and **`from_event ≤ state.event`**:
  `apply_transfers` raises `ValueError` when the planning event is not ahead of the
  ledger's last event (`transfers.py:238-239`). The CLI must catch this and say which
  gameweek the ledger already reaches, rather than surfacing the raw exception.

---

## 9 — Assumptions and known limits

Beyond optimizer-ux.md §7, which the output already renders:

- **`ft_value = 1.5` is unsourced in this repo** (§6.1). It is the one number this
  design introduces that cannot be traced to the snapshot, to `TransferRules`, or to
  `docs/research/projections-survey.md`.
- **The beam approximates continuation value, not the candidate set** (§5.6). The
  output must say which.
- **Dominance pruning weakens through the season** (§5.2). Correctness is unaffected;
  §7's budget is.
- **Hits are undiscounted while their payoff is discounted** (§1). Derived from
  optimizer-ux.md §4's own worked example, so it is the intended behaviour — but it
  biases against late hits, and it interacts with §6.1's terminal value.
- **Chips are not modelled (FU-5)**, and §4.4 records that they are the most likely
  reason to revisit the whole approach. A free hit in particular breaks the "a node is
  a squad" assumption, since the squad reverts the following gameweek — the node would
  need a chip field and a saved pre-chip state.
- **Vice-captain is not modelled.** "Captain if he plays, else vice" is a conditional
  on a random event, and is not expressible in either a linear objective or a
  deterministic argmax. FU-22's fix gives `best_xi` a vice-captain for
  `validate_plan`'s benefit; it does not enter the objective.

**New follow-ups this document files:**

- **FU-23** — `BootstrapSnapshot.players_by_id` / `.clubs` / `.positions` rebuild
  their dicts on every access. Memoise. Measured 2.9× on `apply_transfers`; benefits
  every existing command.
- **FU-24** — `best_xi` materialises a sorted 11-tuple per candidate formation when
  only the winner's is used. Split into `xi_value` (value) and `best_xi` (witness).
  Measured 7.7×.
- **FU-25** — two-pass self-consistent `ft_value` estimation (§6.1).

FU-23 and FU-24 are prerequisites of §7's cost budget, and both are separate concerns
from the optimiser — one branch each, before `domain/optimizer.py`.

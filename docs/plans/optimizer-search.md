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
(612 players, 20 clubs, `squad.json`, Python 3.14.3, single-threaded CPython,
numpy 2.5.2) rather than estimated. Where a number is an assumption it is flagged
`[assumption: …]`.

**numpy is a straight runtime dependency of this design**, not an optional
extra. An earlier revision of this document declined it, carrying over the
`projections.py:106` precedent — *"These are small enough to hand-roll rather
than add the dependency for"* — which was a decision about **one distribution
function**. It does not generalise to a search kernel executing ~10⁸ scored
candidates per run. §6.2 vectorises `xi_value` and scores every child of a node
as a batch of array operations; §7 measures what that buys. There is no
pure-Python fallback path and no optional-extra guard: a second implementation
of the hot kernel would be a second place for the objective to drift, which is
exactly what §6.2's shared-formation argument exists to prevent.

**Scope — in:** the search algorithm, candidate pruning, node state, terminal
value, the runtime **and memory** budget and the guard that enforces them,
`--schedule`, determinism, testing.

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
| the same, value only, without materialising formation tuples | **15.6 µs** | §6.2, FU-24 |
| the same, node-amortised across a whole k ≤ 2 expansion (pure Python) | **4.44 µs** | §6.2 |
| **the same, vectorised with numpy** | **357 ns** | §6.2, FU-26 |
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
  takes it from **136 µs to 15.6 µs — 8.7×**. It is a refactor of existing code
  rather than new work. Filed as **FU-24**; see §6.2 for the exact split.

Both are prerequisites in the sense that §7's cost budget assumes them. A third,
**FU-26** — scoring a whole node's children as one vectorised batch against the
parent's prefix sums, **357 ns against 15.6 µs** — is new code rather than a repair,
and §6.2 explains why §5.5's k ≤ 2 beam levels make it the load-bearing one. Without
it the search is correct and **12.4× slower** than §7's budget, which at k ≤ 2 on
every level is not a slower run but a different command: 39 s becomes ≈ 8 min at the
default horizon, and the wide configurations pass half an hour.

Note the ordering that follows. FU-24 splits `best_xi` into value and witness;
**FU-26 then vectorises the value half**, so FU-24 is not merely a speed-up that
FU-26 supersedes — it is the refactor that gives FU-26 something to vectorise, and
the property test tying `xi_value` to `objective_points(best_xi(...))` is what keeps
the vectorised kernel honest afterwards. One branch each, FU-23 → FU-24 → FU-26,
before `domain/optimizer.py`.

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
   `--max-hit` defaults to 4** (one paid transfer above the free allowance).
3. **`--max-hit` is not by itself a bound on k, and an earlier draft of this
   document wrongly assumed it was.** It bounds k at `free_transfers + 1`, and
   `free_transfers` is itself bounded only by `TransferRules.free_transfer_cap` —
   which is `free_transfers_per_event + max_extra_free_transfers`, **measured at 5
   on the live snapshot** (`1 + 4`). So the default `--max-hit 4` admits **k ≤ 6**,
   not k ≤ 2. §5.3 sets out where that is reachable and what actually bounds the
   search.

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
Measured: **15.6 µs**, closed form, no search — and **357 ns** once §6.2 evaluates a
whole batch of candidates at once. In MILP that same subproblem becomes
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

**Secondary — and this argument has since weakened, so it is recorded at its
current strength rather than its original one.** An earlier revision leaned on the
project's minimal dependency set and on `projections.py:106` refusing scipy. That
reasoning no longer transfers: the Context block accepts **numpy** outright, and
numpy 2.5.2 installs cleanly on this venv's **Python 3.14.3** — which also removes
most of the force of the wheel-lag worry that was raised against `highspy`
`[gap: highspy's own 3.14 wheel coverage remains unverified; it is a prerequisite of
ever revisiting this, and it is now the only part of the dependency objection still
standing]`. What survives intact is narrower and is not about dependencies at all: a
MIP under a time limit returns whatever incumbent it holds, which sits badly with
the README's *"verify known optimizer outcomes"*. §4.4 records the accepted
dependency as a **fired** trigger.

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

Revisit this decision if any of the following becomes true. **Two of these have
already fired**, which is why the decision is recorded as re-examined rather than
merely restated:

| Trigger | Status | Why it flips the argument |
|---|---|---|
| **Multi-transfer gameweeks at every level** | **FIRED** — see below | §5.3 raised `k_enum` from 1 to 2 *at every beam level*, not just the root. That is a ~290× increase in branching per node (559 → 162,792 children) and it is what made a compiled kernel compulsory. Chips were assumed to be the first trigger; ordinary FPL play got there first. |
| **numpy accepted as a straight dependency** | **FIRED** — Context, §6.2 | The marginal cost of `highspy` drops to near zero. The dependency half of §4.3's secondary objection is spent; only the time-limited-incumbent half survives. |
| **Chips land (FU-5)** | not yet | A wildcard gameweek is an unconstrained re-selection of all 15 from 612. Branching is hopeless for search; for MILP it is one relaxed constraint. Free hit additionally breaks the "a node is a squad" assumption, since the squad reverts. |
| Horizon routinely exceeds ~8 gameweeks | not yet | Beam continuation error compounds with depth; MILP's cost grows far more slowly than enumeration. §7 measures horizon 8 as still affordable, so this is a live boundary rather than a hypothetical one. |
| The XI rule stops being a per-position prefix | not yet | e.g. a "field ≥1 player from a doubling team" constraint. The closed-form inner argmax is the load-bearing half of §4.3 — and it is also what the §6.2 kernel vectorises, so this trigger would cost both arguments at once. |
| Projections become validated and well-separated | not yet | Ranking differences of ~0.5 points are currently inside the model's own error (optimizer-ux.md §6), so exact optimality buys precision, not accuracy. If `fpl plan evaluate` ever shows the model is that good, this changes. |

**What the first row actually demonstrates, and why it is recorded as a trigger
rather than a footnote.** The original table treated chips as *"the most likely
trigger"* on the reasoning that only a chip produces a gameweek whose move set is
too large to enumerate. That was wrong in a way worth keeping on the record: the
same pressure arrives from **ordinary play**. Holding a free transfer and then
spending two — `hold · hold · (A→B, C→D)` — is standard FPL, not an edge case, and
representing it requires k ≤ 2 at *every* level rather than only at the root.
Enumerating that costs ~10⁸ scored candidates per run (§7), which pure Python
cannot pay for and which forced the numpy dependency — which in turn fired the
second row. One rules-level requirement thus knocked out two of the arguments that
had been holding MILP off.

The decision **does not change today**: §7 measures k ≤ 2 at every level at
**39 s and 53 MB** at the default horizon 5, and the three structural arguments in
§4.3 — closed-form inner argmax, an output specification that needs non-optimal
paths, and an existing rule implementation that must not be duplicated — are
untouched by any of this. But the margin is now thinner than the earlier revision
implied, and the honest reading is that **k ≤ 3 at every level is the point where
this flips.** §5.3 measures that at **201× the scored candidates and ≈ 55× the wall
time** of the whole k ≤ 2 run — ≈ 35 min against 39 s — which no amount of
vectorising recovers, because the growth is combinatorial rather than constant. A
MILP absorbs the same change in a constraint bound. If a future revision
wants k ≤ 3 generally rather than at scheduled gameweeks only (§5.7), it should
reopen §4 rather than optimise §6.2 further.

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
| exact `(position, club)` Pareto frontier | **177** | **3.1×** |
| position-global Pareto frontier (unsound — ignores the club limit) | 18 | 31× |

**The relation is non-strict, so the tie-break is load-bearing.** `≤` on cost and
`≥` on every event make mutual domination possible: two players in one bucket at the
same price with identical projections each dominate the other. Discarding both would
be a correctness bug — the bucket could lose a player who belongs in the optimum — so
ties are broken by **player ID ascending**, matching `best_xi`'s existing rule
(`squad.py:99-102`). This is not cosmetic: keeping every tied player instead yields
**197** survivors rather than 177, a 20-player difference on the live snapshot.

**FU-11 (`a7b86d3`) does not strengthen this rule — measured, not assumed.** The
availability gating drove 55 more pool players to exactly zero xP across the horizon
(3 before, 58 after), so it is natural to expect them to become dominated. They do
not: the survivor set is **byte-identical either side of the commit** (177 both ways,
empty symmetric difference). Dominance is a *within-bucket ordering* test, and FU-11
is a monotone transformation that only lowers already-low values — it cannot promote
any player into being a dominator. The binding half of the test is the price clause:
an unavailable player is typically the **cheapest** in their `(position, club)`
bucket, so no teammate satisfies `now_cost(A) ≤ now_cost(B)`. All five zero-xP
survivors on the live snapshot are the cheapest in their bucket. §7's budget is
therefore unchanged by FU-11.

The position-global figure is recorded only to show what is being left on the table
for soundness, and as a warning: it is 18 because at this point in the season
`_appearances` is 1, so the minutes shrinkage collapses to the position prior
(`projections.py:84`, with `_appearances` documented at `:69-76`) and xP is nearly a
monotone function of per-90 rates. **Dominance will prune less as players
differentiate through the season.** That costs speed and never correctness, which is
the right way round — but §7's budget should be re-measured around GW10.

Downstream effect on branching, from the same state as §3:

| Move set | Unpruned | After exact dominance |
|---|---:|---:|
| 1 transfer | 2,031 | **559** |
| 2 transfers | 1,995,109 | **162,233** (12.3×) |
| 3 transfers | — | **~27,181,734** |

*(Re-measured at the real root — GW2, the next open deadline — with the joint budget
and club-limit filters applied during enumeration, which an earlier draft applied
only partially. The k = 3 row is extrapolated from 40 of the 455 out-triples.)*

Alongside dominance, three per-node feasibility exclusions, each already carrying its
reason and each one of §9's named four: **unaffordable** (quoting the bank and the
shortfall), **club limit** (naming the three players already held), **already held**.
`can_transact`/`can_select`/`removed` filtering reuses the predicates in `_selectable`
(`squad.py:238`).

**No top-*k* cut is ever applied to the candidate set.** Beam width truncates
*paths*, which is a different object; §5.6 states exactly what that costs, and the
output must not conflate the two.

### 5.3 — Move generation within a gameweek: two caps, not one

An earlier draft of this document conflated the rules cap with what the search can
afford to enumerate. They are different numbers and they must be named separately,
because the gap between them is exactly where a silent blind spot lives.

**The rules cap** is `k_rules = min(free_transfers + ⌊max_hit / 4⌋, transfers_cap)`.
It is what FPL permits. `free_transfers` accrues at `min(ft + 1, free_transfer_cap)`
per event (`transfers.py:176`), and `free_transfer_cap` is **5** on the live snapshot
(`free_transfers_per_event 1 + max_extra_free_transfers 4`). Measured, from the
`squad.json` ledger at GW1:

| Where | `free_transfers` | `k_rules` under the default `--max-hit 4` |
|---|---:|---:|
| root at GW2 (next open deadline) | 1 | 2 |
| root at GW4 (ledger three gameweeks behind) | 3 | **4** |
| root at GW6 or later | 5 | **6** |
| beam level 1, after holding at the root | 2 | **3** |
| beam level 4, after holding throughout | 5 | **6** |

**The enumeration cap** is `k_enum = 2`, fixed, at the root and at every beam level.
It is what §7's budget can pay for, and it is a property of the search rather than of
the game.

**k ≤ 2 at every level is the decision this revision exists to record.** An earlier
draft budgeted k ≤ 1 at beam levels and k ≤ 2 only at the root, on the grounds that
it fitted a ~21 s budget. That is not a defensible search: `hold · hold · (A→B,
C→D)` — bank a free transfer, then spend two — is standard FPL play, and a beam that
can only ever apply one transfer per level **cannot represent it at all**. The
failure is invisible in the output, because every path the search prints is legal and
well-scored; what is missing never appears. §5.6's guarantee is written the way it
is precisely so this class of gap has to be stated rather than discovered.

Why 2 and not 3, measured with the §6.2 kernel:

| Enumeration | Scored candidates per node-event | Runtime per node-event | H5, beam 4, first-moves 50 |
|---|---:|---:|---:|
| k ≤ 1 | 574 | 4.9 ms | ≈ 3.2 s |
| **k ≤ 2** (the default) | **226,896** | **58.3 ms** | **39.0 s** |
| k ≤ 3 | 45,641,270 | 3.26 s | **≈ 35 min** |

*(Measured at the root node; the average across all 651 expansions is slightly lower
— 213,955 at k ≤ 2 — because beam nodes hold different players and so filter the pool
differently.)*

k = 3 costs **201× the scored candidates** of k = 2 and roughly **55× the wall time**
of the whole k ≤ 2 run. Vectorising does not rescue it — the kernel is already within
a small factor of memory bandwidth, and the growth is combinatorial, not constant.
Two consequences, and they point in different directions:

- **At the root alone, k = 3 is now affordable.** Five event-passes at 3.26 s is
  **≈ 16 s**, against the 77 s the pure-Python estimate implied. `--max-transfers-per-gw 3`
  stays off by default and stays root-only (§5.4), but it is no longer a
  theoretical offer.
- **At every level it is not, and §4.4 records that as the boundary where the whole
  approach should be reopened** rather than optimised further.

The middle ground — k = 3 at *one chosen gameweek* rather than at all of them — is
what **`--schedule` (§5.7)** buys, and it costs **3.2 s**.

**The two caps disagree, and the output must say so.** With three banked free
transfers the rules permit spending all three in one gameweek — a core FPL play,
banking through a poor run to strike at a fixture swing — and the search does not
enumerate it. That gap is invisible unless it is reported, which is the failure mode
this whole section exists to avoid:

> When `k_rules > k_enum` at any event in the horizon, the output states it plainly:
> *"GW4: you have 3 free transfers; the search planned combinations of up to 2
> transfers per gameweek. Moves spending all 3 at once were not enumerated — run
> `--schedule 0,0,3,0,0` to search that shape directly."*

`--max-hit` therefore does **not** gate this, and raising it does not help. Anyone
reaching for a wider search wants `--max-transfers-per-gw`, a new flag defaulting to
2, whose accepted values are 1, 2 and — at the root only — 3. The `> 8` heuristic
warning the earlier draft attached to `--max-hit` is withdrawn; it described a code
path that does not exist (§5.4).

**The naming of the gap is necessary but not sufficient, and that is why §5.7
exists.** A message telling the user that a shape was not searched is an improvement
on silence, and it is still a dead end: it names something the tool will not do and
offers no way to do it. `--schedule` closes that loop — the same sentence can now
point at the flag that searches the shape it just declined to enumerate.

Given `k_enum`, generation is:

- **k = 0 (hold)** is `apply_transfers(state, [], event, …)`. `apply_transfers` folds
  the intervening idle events itself (`transfers.py:309-310`) and accrues free
  transfers correctly, so hold needs no special case — **one code path, and it is the
  existing validator.**
- **k = 1** — enumerate the pruned candidate set per outgoing player.
- **k = 2** — enumerate out-pairs × in-pairs subject to joint budget and club counts.

One exclusion the generator must apply that §5.2's list omits, and that cost a bug in
the measurement harness for this revision: **a beam node's candidate set is not the
root's.** A player pruned as "already held" at the root may have been transferred out
by depth 2, and a candidate bought at depth 1 is held at depth 2. The `already held`
test is against **the node's** holdings, re-evaluated per node, or the generator emits
squads containing a duplicate and `apply_transfers` rejects them (§8's property test
catches this).

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
k ≤ `k_enum` over the pruned candidate set is enumerated** — 559 + 162,233 = 162,793
children including `HOLD`, measured at GW2.

**All of them are scored over the full horizon.** Each child is evaluated at every
event with no further transfers — the value of making this move and then doing
nothing — which is what captures optimizer-ux.md §1's reason for having a horizon at
all ("to stop the optimiser selling a player whose fixtures turn in three weeks").
Measured with §6.2's kernel: 162,793 children × 5 event-passes at 58 ms each ≈
**0.3 s**, which is under 1% of §7's budget — scoring every child over the whole
horizon is no longer a cost worth optimising against. Retain the top
**`--first-moves`** (default 50) distinct first moves by that value, plus `HOLD`, as
the roots of the beam.

**A two-stage cut was specified here and has been withdrawn.** The earlier draft
ranked all children by immediate value at the root event, kept the top 5,000, and
scored only those over the horizon. That reproduces at 5,000 exactly the failure it
identifies at 1: a move that is poor in the root gameweek but strong across the
horizon is cut before the horizon is ever consulted. Measured against the live
snapshot the cut looked harmless — the true hold-out winner ranks **4th** on
immediate value and no move in the true top 500 falls outside the stage-1 top 5,000.
That measurement is worthless, and recording why matters more than the number: **the
cached schedule contains no blanks and no doubles at any gameweek**, and
`_appearances` is 1, so xP varies across events only through opponent strength. There
is nothing for the two rankings to disagree about.

Injecting the disagreement measures it properly. Blanking the root gameweek for a
club, so its players are worth nothing in GW2 and unchanged afterwards:

| Injected blank | Best first move recovered from the top 5,000? | Top-3 displayed moves correct | Top-50 first-move overlap |
|---|---|---:|---:|
| none (live schedule) | yes | 3/3 | 50/50 |
| one club | yes | 3/3 | **26/50** |
| six clubs (a real blank gameweek) | **no** | **0/3** | **8/50** |

With six clubs blanking — an ordinary GW18/GW29 shape, not a pathological one — the
stage-1 cut loses the best first move outright, and raising the cut to 50,000 does not
recover it. Only scoring every child does. The cut saved 1.5 s against a budget of
minutes (§7) and cost the guarantee §5.6 exists to make, so it goes.

**k ≥ 3 is not exhaustible from a beam node** (~27.2M children, §5.2) but *is*
affordable once, at the root: **≈ 16 s** with §6.2's kernel — five event-passes at the
3.16 s per k = 3 expansion measured in §5.3, against the 77 s the pure-Python estimate
implied. Offered as `--max-transfers-per-gw 3`, off by default, and reported as
covering the root gameweek only. There is no heuristic k ≥ 3 generator in this design.
For k = 3 at a gameweek *other* than the root, `--schedule` (§5.7) is the supported
route and costs 3.2 s.

An earlier draft proposed one — ranking out-triples by the sum of the individual
single-transfer deltas — and the measurement that killed it is worth keeping: over
3,082 sampled cross-position pairs, the true joint delta exceeded the sum of the two
individual deltas in **144 cases (4.7%), by up to 2.21 points**. No additive bound is
admissible here, so a ranked-singles cut cannot be made exact at any k. That draft
also claimed the heuristic path "is never taken under the default `--max-hit 4`",
which §5.3 shows is false — the default admits k ≤ 6. Removing the generator rather
than the claim is the fix: the search is now exact up to `k_enum` and silent about
nothing, because §5.3 requires it to report where `k_rules` exceeds `k_enum`.

*(The same 4.7% measurement is why k = 2 is enumerated rather than generated from
ranked singles: the cheap route is demonstrably not safe, and the exact route is
affordable.)*

### 5.5 — Beam levels

For events after the root:

- Expand each beam node over k = 0…max, generating children per §5.3.
- Score each child at that event only — the path value is cumulative, so earlier
  gameweeks are already accounted for in the parent. This is why the per-level cost
  is `nodes × children × 357 ns` and not `× horizon`.
- **Bucket the beam by root first move.** Retain `--beam` (default 4) continuations
  per first move. This does three things at once: it implements optimizer-ux.md §4's
  distinct-first-move display constraint directly rather than as a post-filter; it
  guarantees no first move is dropped before its best continuation has been explored;
  and it keeps `HOLD` exact, since HOLD is its own bucket and is never in competition.
  Under `--schedule` the bucket key moves to the first gameweek with `k_w > 0`, for
  the reason §5.7 gives.
- **Apply the §4.1 dominance test within each bucket**, keyed by
  `(event, frozenset(holdings))`. This is exact, and it collapses the transfer-order
  duplicates that would otherwise fill the beam.
- Tie-break deterministically on `(−score, transfers_made, sorted transfer ids)` so
  two runs against one snapshot give one answer. Projections are deterministic
  (optimizer-ux.md §9) and nothing else in the loop is ordered by a set.

**`--beam 4` is not a converged width, and the measurements say so plainly.** Scoring
the same root at four widths (§7.1, horizon 5):

| `--beam` | Best score | Recommended first move |
|---:|---:|---|
| 1 | 176.092 | Gabriel→De Cuyper + Le Fée→Hinshelwood |
| 2 | 176.233 | Gabriel→De Cuyper + Le Fée→Hinshelwood |
| 4 | 176.465 | **Calafiori→De Cuyper + Le Fée→Szoboszlai** |
| 8 | 176.974 | **Gabriel→De Cuyper + Le Fée→Alcaraz** |

Score improves monotonically with width, as it must — a wider beam is a superset of a
narrower one's retained continuations. Two things about *how* it improves are worth
recording:

- **The total spread is 0.88 points over five gameweeks**, which is comfortably inside
  the projection model's own unquantified error (optimizer-ux.md §6). By the yardstick
  the output itself uses, none of these four answers is distinguishable from the
  others.
- **The recommended first move changes anyway**, twice, and it is the only actionable
  thing the command prints. A difference too small to be meaningful is still large
  enough to flip the headline.

This is the strongest available demonstration of §5.6's distinction: what the beam
approximates is *continuation value*, and continuation value is exactly what is
unstable here. It is an argument for the display constraint (optimizer-ux.md §4's
distinct first moves, §4's `MARGINAL` verb) and against reading `--beam` as an
accuracy dial. `[gap: whether 4 is the right default is not settled by this table —
it would need the decision-margin threshold of §6.4, which is still blocked on
`fpl plan evaluate`. Until then 4 is chosen on cost, not on convergence.]`

### 5.6 — The guarantee, stated precisely

Beam search cannot promise the globally optimal path. What it *can* promise here is
the thing the output exists for:

> **The recommended first move is selected from a complete enumeration of every
> legal move of up to `k_enum` transfers available before the next deadline, each
> scored exactly over the full horizon.** No first move is excluded except by an
> exact dominance rule or a feasibility constraint, each of which names itself. What
> the beam approximates is the *continuation value* used to rank those first moves —
> not which moves were considered.
>
> **`k_enum` is 2 by default, and the game may permit more.** Where `k_rules`
> exceeds it (§5.3), moves spending more than `k_enum` transfers in one gameweek were
> not enumerated, and the output names the gameweeks where that applies — and names
> `--schedule` (§5.7), which searches such a shape directly.
>
> **The continuation value is not converged at the default `--beam`.** §5.5 measures
> the recommended first move changing between widths 2, 4 and 8 on a score spread of
> 0.88 points. The guarantee covers *which moves were considered*, not that widening
> the beam would leave the ranking alone.

An earlier draft of this claim was broader than the algorithm delivered, in two ways
that are worth recording because both were easy to miss:

- It promised a complete enumeration "of every legal move", while §5.4 scored only
  the top 5,000 children by immediate value. Enumeration was complete; *scoring* was
  not, and a first move dropped at the scoring stage is just as absent from the
  answer. §5.4 now scores every child, which makes the promise true rather than
  narrowing it.
- It was conditioned on "the default `--max-hit 4`", which reads as though the
  default made the enumeration complete. It does not — §5.3 measures the default
  admitting k ≤ 6. The condition that matters is `k_enum`, which is a property of the
  search, so the guarantee now names that instead.

That is the honest statement, and it should appear in the output, because the weaker
reading ("the optimiser found the best plan") is the one a user will otherwise
assume. It also bears directly on §4: the quantity beam search approximates is a
continuation value computed against projections that are themselves unvalidated
(optimizer-ux.md §6) and provisional beyond GW+3 (optimizer-ux.md §7). Exact
optimisation of a noisy objective buys precision, not accuracy.

### 5.7 — `--schedule`: fix the shape, search the players

```
--schedule TEXT   a per-gameweek transfer count, e.g. "0,0,3" — plan this
                  shape and search only over which players
```

`--schedule 0,0,3` says: hold, hold, then make three transfers. The search then
enumerates only *which* three, over the same dominance-pruned candidate set, scored
by the same objective, validated by the same `apply_transfers`. Nothing else about
the search changes.

**Why this is a feature and not a debugging flag.** §5.3 identifies a real blind
spot — the search enumerates up to `k_enum = 2` per gameweek while the rules permit
up to 6 — and answers it by *reporting* the gap. Reporting is honest and it is a
dead end: it names something the tool declines to do and leaves the user with
nowhere to go. Three things make the schedule the right way to close it:

1. **It matches how the decision is actually reasoned about.** "Do I bank two
   transfers and strike at the GW7 fixture swing, or spend as I go?" is a comparison
   of a handful of *shapes*, not a request for a global optimum. Running three
   schedules and comparing their `Score` is the workflow; the flag makes it the
   supported one.
2. **It makes rollover strategy visible instead of emergent.** In the free search,
   banking is something that happens — a by-product of the beam preferring `hold` at
   some level, reported after the fact and easy to miss. Under a schedule it is the
   premise, stated up front and attributable to the user rather than to the beam.
3. **It buys back the enumeration the free search cannot afford.** Fixing the shape
   collapses the branching factor at every `k_w = 0` gameweek to exactly 1, so the
   beam does not widen until the first spending gameweek. That is what makes k = 3
   payable:

| Run | Node expansions | Grid cells | Runtime | Peak RSS |
|---|---:|---:|---:|---:|
| free search, k ≤ 2 (default) | 651 | 140,140,569 | 39.0 s | 53 MB |
| `--schedule 1,1,1,1,1` | 651 | 433,248 | **3.2 s** | 54 MB |
| `--schedule 0,0,2,0,0` | 11 | 226,322 | **0.1 s** | ≤54 MB |
| `--schedule 0,0,3,0,0` | 11 | 45,414,374 | **3.2 s** | 63 MB |
| `--schedule 0,0,0,0,3` | 5 | 45,414,374 | **3.2 s** | 64 MB |

*(Horizon 5, `--beam 4`, `--first-moves 50`, root GW2. Peak RSS is a process
high-water mark; `≤` marks a row whose figure is inherited from an earlier row in the
same process. §7.1 carries the full matrix and the memory caveat.)*

**`0,0,3` costs 3.2 s where k ≤ 3 in the free search costs ≈ 35 min** (§5.3). That
is a factor of ~660, and none of it comes from a weaker guarantee about the shape
being searched: within the shape, the enumeration over players is exactly as
complete as the free search's is within k ≤ 2. What the schedule gives up is the
comparison *across* shapes, which is precisely what the user has taken over by
choosing one.

**Semantics, stated so they are not invented at implementation time.**

- **The schedule sets the horizon.** `--schedule 0,0,3` implies `--horizon 3`.
  Passing both with a mismatched length is an error naming both values, not a
  silent truncation. Horizon clamping (optimizer-ux.md §2) still applies and, if it
  bites, the run is refused rather than the schedule being trimmed — a trimmed
  schedule is a different plan from the one that was asked for.
- **Each `k_w` is bounded by 3**, the same `--max-transfers-per-gw` ceiling as §5.3,
  and for the same reason: `k = 4` from one node is ~10⁹ grid cells. Above 3 the
  run is refused by §7's guard with the projected cost quoted.
- **Feasibility is checked up front, against the rules, before any search runs.**
  Fold the free-transfer recurrence over the schedule and compare against
  `--max-hit`: `0,0,3` from a root with 1 free transfer accrues 1 → 2 → 3 and
  spends 3 for **no hit**, while `3,0,0` from the same root spends 3 against 1 free
  and costs **−8**, which the default `--max-hit 4` refuses. Refuse with the
  arithmetic shown — *"GW2: 3 transfers against 1 free transfer = −8 points, above
  `--max-hit 4`"* — rather than returning an empty beam, which is the same
  information rendered as a bug.
- **`HOLD` remains the origin.** `Net` and `Score` are still quoted against holding
  throughout (§1), unchanged, which is what makes two schedule runs against one
  snapshot directly comparable. This is the property the compare-a-few-shapes
  workflow depends on, so it must not be relaxed into "relative to the schedule's
  own first row".
- **Beam bucketing moves to the first spending gameweek.** §5.5 buckets the beam by
  the root's first move to guarantee distinct displayed decisions. Under a schedule
  beginning `0,…` the root has exactly one move — `hold` — so that bucketing
  degenerates to a single bucket and `--paths 3` would print three variations of one
  plan. Bucket instead by **the move made at the first gameweek with `k_w > 0`**,
  which restores the property: for `0,0,3` the genuinely distinct decisions are the
  distinct GW4 triples, and those are what the table should show.

**What the output must say.** The header states the schedule was imposed and that
the result is the best plan **of that shape** — not the best plan. §5.6's guarantee
takes a schedule variant:

> **Under `--schedule`, the enumeration is complete over players and fixed over
> counts.** Every legal assignment of the scheduled number of transfers is
> enumerated at each gameweek, from the same exactly-pruned candidate set. No claim
> is made that this shape beats any other; comparing shapes is the user's, by
> running more than one.

**What it does not do.** It is not a chip mechanism (FU-5) — a wildcard is an
unconstrained re-selection of 15, not a transfer count — and it does not widen the
candidate set. A player excluded by §5.2's dominance rule is excluded under a
schedule too, with the same stated reason.

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

**Split value from witness, and score a node's children as one vectorised batch.**

> **Re-measured 2026-08-26, after FU-24 landed (`5afd728`). The first two rows of the
> table below were not measured under the same conditions as each other, and their
> 8.7× is an artefact of that.** Both were reproduced exactly, which is how the
> mismatch was identified — see *The two rows, reconciled* immediately below. The
> node-amortised and numpy rows are unaffected, and so is §7: those two were timed
> against each other, and §7's table was measured end to end rather than derived from
> any row here.

| | Cost per child | Conditions | vs row 1 |
|---|---:|---|---:|
| `best_xi` + `objective_points`, as measured originally | 136 µs | whole call, **`players_by_id` rebuilt every call** (pre-FU-23) | — |
| the same, with FU-23's memoisation in place | **71.7 µs** | whole call | 1.9× |
| `best_xi` + `objective_points`, post-FU-24 | **54.5 µs** | whole call | 2.5× |
| `xi_value`, post-FU-24 | **43.8 µs** | whole call | 3.1× |
| value only, winner's tuple materialised once, as measured originally | 15.6 µs | **scoring only, structure build hoisted out** | — |
| the same, re-measured post-FU-24 | **12.4 µs** | scoring only, structure hoisted | — |
| `xi_value`'s scoring step alone | **9.3 µs** | scoring only, structure hoisted | — |
| node-amortised incremental, pure Python, over a full k ≤ 2 expansion | **4.44 µs** | structure amortised per node-event | — |
| **the same, vectorised with numpy** | **357 ns** | structure amortised per node-event | — |

*(The pure-Python row was 2.82 µs in the previous revision and re-measures at 4.44 µs
here; that is the same code on a colder machine, and the 12.4× numpy figure below is
the like-for-like comparison, both timed in one process minutes apart. Per
node-event, over the root's full 162,793-child k ≤ 2 expansion: **722 ms pure Python,
58 ms vectorised**.)*

**The two rows, reconciled.** Measured on the live cached snapshot (612 players,
2026_27) with the real 15-player squad from `squad.json` and a real
`ComponentProjection` table, every figure the median of ≥12,800 timed calls:

- **Row 1's 136 µs is a pre-FU-23 measurement.** Dropping the `players_by_id` memo
  before each call reproduces it at **136.9 µs**; leaving FU-23's memoisation in
  place gives **71.7 µs**. The missing 65 µs is precisely the dict rebuild FU-23
  measured at 63 µs, and it is *not* part of `best_xi`'s own cost any more.
- **Row 2's 15.6 µs excludes the structure build.** Timing the scoring step with the
  per-position sort and prefix sums hoisted out of the loop gives **12.4 µs**;
  timing the whole function gives **43.8 µs**. The 33 µs difference is
  `_xi_structure`, which row 1 pays and row 2 does not.

So the 8.7× divided a whole call carrying 65 µs of since-removed overhead by a
fragment of a call. **Neither number is wrong on its own terms; the ratio between
them never meant anything.** Like for like, whole call, FU-23 in place: FU-24 is
**1.64×** (71.7 → 43.8 µs), and `best_xi` itself is 1.32× (71.7 → 54.5 µs).

**Neither squad composition nor projection-table lookup explains any of it.** The
live squad and the synthetic fixture are both 2/5/5/3 and score within 1.2% of each
other on identical xP (43.8 µs vs 43.3 µs), so the synthetic fixture is a valid
stand-in for this measurement. Reading all 15 `xp_total` values out of the
projection table costs **0.78 µs**, and `players_by_id` access post-FU-23 costs
**0.09 µs**. `_xi_structure` is 75% of `xi_value`, and the sorts and prefix sums
inside it are the cost.

**What this changes downstream.** The like-for-like figure to quote against the numpy
kernel is the **node-amortised** one — 4.44 µs — because FU-26 amortises the
structure build across a node's children, which is exactly the cost row 2 was
excluding. Against that, numpy is **12.4×**, the figure §7 already uses. FU-26's
entry in follow-ups.md quotes **44×** against the 15.6 µs row instead; that
comparison is between a non-amortised fragment and an amortised kernel and should be
read as 12.4×.

**Verified before it was timed.** The vectorised kernel is exact against the repo's
own path: `objective_points(best_xi(...))` agrees to 1e-9 on all **559** k = 1
children and **4,000** sampled k = 2 children of the root node, and 300 sampled
children round-trip through `apply_transfers` with matching validity, hit points and
bank. That check is §8's `xi_value ≡ objective_points(best_xi(...))` property test,
run once by hand before any measurement was believed.

The split, both halves in `domain/squad.py` so the CLAUDE.md guarantee holds:

- **`xi_value(player_ids, projections, snapshot) -> float`** — the hot path. Four
  sorts of ≤5 elements, four prefix-sum arrays, 8 legal formations, plus the captain
  term. Returns the objective and nothing else.
- **`best_xi(...) -> BestXI`** — unchanged signature; materialises starters, captain
  and (FU-22) vice-captain. Called only for nodes retained into the beam, and for
  output.

**One formation enumeration, shared structurally.** The set of legal formations is a
snapshot-level constant: `squad_min_play`/`squad_max_play` and `squad_squadplay`
admit exactly 8 combinations totalling 11, and for any legal 15-player squad the
per-position counts are fixed at `squad_select`, so the enumeration does not vary by
squad. It is extracted as **`legal_formations(snapshot) -> list[tuple[int, ...]]`**
in `domain/squad.py`, computed once and called by `xi_value`, by `best_xi`, and by
the vectorised scorer below. Two call sites iterating the same `product(...)`
expression would be two things to keep in step; §8's property test would catch the
drift after the fact, and one function prevents it. `best_xi`'s existing
"cannot field a legal formation" guard (`squad.py:124-128`) stays where it is — it is
a property of a *particular* squad, not of the formation set.

**Batched scoring is now load-bearing, reversing this document's earlier decision.**
That decision was taken when §7 budgeted beam levels at k ≤ 1; with k ≤ 2 at every
level (§5.5) the per-child constant *is* the whole budget, and three of the four
grounds for rejecting it no longer hold:

1. *"The remaining 3.2× is not decisive."* It is **12.4×** on the real expansion, and
   it is the difference between a **39-second** and an **≈ 8-minute** run at the
   default horizon (§7) — and between 75 s and ≈ 15 min at horizon 8.
2. *"It only helps k = 1 children."* Measured false. The parent's per-position
   prefix sums are computed once per node and reused by every child, and a k = 2
   cross-position child perturbs two of four positions while still costing **357 ns**
   against 15.6 µs. That figure *is* the average over a full k ≤ 2 expansion —
   162,793 children, of which 162,233 are k = 2 — not a k = 1 best case. Vectorising
   helps k = 2 *more* than k = 1, because an out-pair's candidates form a
   two-dimensional grid and the batch gets larger, not smaller.
3. *"The incremental state must be invalidated on every event boundary."* **Still
   true, and still the most dangerous bug in the design** — the xP ranking within a
   position changes every gameweek, so the cached structure is valid only for the
   `(node, event)` pair it was built for. It is built inside the per-event expansion
   and never outlives it. §8's equality property test is what makes this checkable.
4. *"It is optional by construction."* No longer. It is a prerequisite of §7.

The mechanism, so it is not re-derived. Per `(node, event)`, sort each position's
xP descending and build prefix sums `B_p[k]`. For a child that removes some of a
position's players and inserts incoming values, the position's new prefix sums follow
from one identity — *the best k either contains the new player or it does not*:

```
one incoming x:      S'[k] = max( B[k],  x + B[k-1] )
two incoming x,y:    S'[k] = max( B[k],  max(x,y) + B[k-1],  (x+y) + B[k-2] )
three incoming:      the same, with the top-1, top-2 and top-3 partial sums
```

The child's XI value is then `max over the 8 legal formations f of Σ_p S'_p[f_p]`,
and the captain term is `max(others_max, incoming…)` — every position has
`squad_min_play ≥ 1`, so each position's top scorer always starts and the squad's
highest-xP player is always the captain.

**Every term on the right broadcasts over the candidate axis**, which is what makes
the batch form fall out rather than having to be engineered: all ~140 candidates for
one outgoing slot are scored by ~5 array operations, and a k = 2 out-pair becomes an
`[m_a, 1] + [1, m_b]` outer sum evaluated 8 times. Feasibility — joint budget, club
limit, already-held, and the strictly-increasing index that de-duplicates
same-position pairs — is a boolean mask over the same grid, so infeasible children
cost a masked-out cell rather than a branch.

*(This also **simplifies** the design it replaces. The previous revision precomputed,
per position and per position-pair, the best total over the other positions at each
fixed starter count — two auxiliary tables to build and keep in step. With only 8
legal formations there is nothing to amortise: enumerating all 8 directly is both
cheaper and one fewer thing that can drift from `best_xi`. The tables are dropped.)*

Filed as **FU-26**.

Recording ground 3 explicitly, per optimizer-ux.md §5.1: the retained XI and
captain are a **cache of a deterministic argmax, not a source of truth** — they must
be reproducible from `holdings` plus the projection table at any time.

### 6.3 — Candidate-set attributability (§9)

Answered by §5.2. Every exclusion carries one of four reasons — `dominated` (exact,
naming the dominator), `unaffordable` (quoting bank and shortfall), `club limit`
(naming the three held players), `already held` — and the pruned set is reachable
from the node, so `fpl players show` and the "why not X" surface can answer without
re-running anything. **No top-*k* cut is applied to candidates at any point**, and
since §5.4's two-stage cut was withdrawn, none is applied to scored *moves* either.

What remains is not a cut but a **cap**: `k_enum` (§5.3) bounds how many transfers a
single gameweek's move may contain. That is a different kind of exclusion from the
four §9 names — it excludes no player, and no reason can be attached to an individual
— so it is reported as a scope statement on the run rather than as a per-player
exclusion, and §5.3 fixes its wording. The earlier draft's heuristic k ≥ 3 generator,
which *would* have needed labelling, no longer exists.

**`--schedule` (§5.7) is what makes that scope statement actionable rather than
merely honest.** optimizer-ux.md §9's principle is that a filter inside the search is
*reportable* where a filter before it is invisible. `k_enum` satisfies the letter of
that — it is reported — while leaving the user with nothing to do about it. A scope
statement that names the flag which searches the declined shape closes the loop the
principle was reaching for.

One thing `--schedule` does **not** relax: the candidate set. A player excluded by
§5.2's dominance rule stays excluded under any schedule, with the same stated reason,
so the four exclusion reasons remain exhaustive.

### 6.4 — The decision-margin threshold (§10) — still open

Unchanged. It needs `fpl plan evaluate` run against enough finished gameweeks to
measure an RMSE-per-gameweek, and no such run exists. Until then the
`RECOMMENDED`/`MARGINAL` threshold stays the placeholder optimizer-ux.md §4 already
requires the output to admit to.

---

## 7 — Cost and memory budget

**Two budgets, not one.** The previous revision of this section budgeted runtime and
never mentioned memory. That omission is not a documentation gap — it is the reason a
12 GB machine had to be power-cycled during the measurement of this very plan. A
budget that constrains only the axis you happened to think of does not constrain the
run; it just picks which way it fails.

### 7.1 — Measured

Root GW2, `--max-hit 4`, `--first-moves 50`, k ≤ 2 at every level, §2's
FU-23/FU-24/FU-26 prerequisites in place. Peak RSS is the process high-water mark
(`ru_maxrss`); runtime is wall clock. Every row was capped at 120 s and 3 GB
(`RLIMIT_AS`) — no unbounded run was performed.

| Horizon | `--beam` | Node expansions | Scored candidates | Runtime | Peak RSS | Best score |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 4 | 251 | 54,756,355 | 14.9 s | 52 MB | — |
| **5** | **1** | 201 | 43,514,091 | **9.6 s** | 52 MB | 176.092 |
| **5** | **2** | 351 | 75,752,308 | **18.3 s** | 53 MB | 176.233 |
| **5** | **4** *(default)* | 651 | 140,140,569 | **39.0 s** | **53 MB** | 176.465 |
| **5** | **8** | 1,251 | 267,658,647 | **94.7 s** | 57 MB | 176.974 |
| 8 | 1 | 351 | 74,454,753 | 16.8 s | 52 MB | 248.627 |
| 8 | 2 | 651 | 137,691,096 | 33.8 s | 54 MB | 248.768 |
| 8 | 4 | 1,251 | 264,048,842 | **74.6 s** | 54 MB | 249.797 |

Schedules (§5.7), horizon 5, `--beam 4`:

| `--schedule` | Node expansions | Scored candidates | Runtime | Peak RSS | Best score |
|---|---:|---:|---:|---:|---:|
| `1,1,1,1,1` | 651 | 433,248 | 3.2 s | 54 MB | 169.246 |
| `2,0,0,0,0` | 201 | 226,322 | 0.2 s | ≤54 MB | 157.269 |
| `0,1,0,1,0` | 14 | 3,056 | 0.0 s | ≤54 MB | 148.498 |
| `0,0,2,0,0` | 11 | 226,322 | 0.1 s | ≤54 MB | 142.706 |
| `0,0,3,0,0` | 11 | 45,414,374 | 3.2 s | **63 MB** | 151.178 |
| `0,0,0,3,0` | 8 | 45,414,374 | 3.2 s | **67 MB** | 134.864 |
| `0,0,0,0,3` | 5 | 45,414,374 | 3.2 s | **64 MB** | 125.224 |

*(`≤` marks rows measured after a k = 3 row in the same process, so their figure is
that process's inherited high-water mark rather than their own. The k = 3 rows are
the first of their kind in each process and their **≈ 10 MB over the k ≤ 2 baseline**
is genuine — it reproduced in two independent processes, 54 → 63 MB and 57 → 67 MB.)*

**Answering the question this revision was rebuilt around: k ≤ 2 at every beam level
is viable, and it holds to horizon 8 — but only with FU-26.** 39 s at the default
horizon 5, 75 s at horizon 8, both at `--beam 4`. The 12.4× is entirely §6.2's
kernel.

**Re-derived 2026-08-26 against the per-child costs actually measured (§6.2).** The
table above was measured end to end with a numpy prototype, not derived from any
per-child figure, so §6.2's correction does not move it. What the correction does
move is the fallback: the implied cost of the measured rows is **221–354 ns per
scored candidate**, consistent with §6.2's 357 ns, while the two pure-Python columns
below are the same candidate counts at the two pure-Python costs.

| Horizon | `--beam` | Scored candidates | Measured (numpy) | Node-amortised @ 4.44 µs | Today's `xi_value` @ 43.8 µs |
|---:|---:|---:|---:|---:|---:|
| 3 | 4 | 54,756,355 | 14.9 s | ~4 min | ~40 min |
| 5 | 1 | 43,514,091 | 9.6 s | ~3 min | ~32 min |
| 5 | 2 | 75,752,308 | 18.3 s | ~6 min | ~55 min |
| **5** | **4** *(default)* | 140,140,569 | **39.0 s** | ~10 min | **~1.7 h** |
| 5 | 8 | 267,658,647 | 94.7 s | ~20 min | ~3.3 h |
| 8 | 1 | 74,454,753 | 16.8 s | ~6 min | ~54 min |
| 8 | 2 | 137,691,096 | 33.8 s | ~10 min | ~1.7 h |
| **8** | **4** | 264,048,842 | **74.6 s** | ~20 min | **~3.2 h** |

**The "≈ 8 min pure Python" this section previously quoted was the 4.44 µs column,
and that variant does not exist in the repo either.** The only pure-Python scorer
that does exist is `xi_value` as landed in `5afd728`, which is not node-amortised
and costs 43.8 µs per child — putting the default run at **~1.7 hours**, not 8
minutes. Both pure-Python columns are unusable, so the conclusion is unchanged in
direction and stronger in degree: **FU-26 is load-bearing for this budget, not an
optimisation of it**, and the gap it closes on the default row is **~157×** against what
is implemented today (1.7 h → 39 s) rather than the 12.4× against a variant that is
also still to be written.

**[Unverifiable from the repo: every figure in the "Measured (numpy)" column.** They
were taken against a prototype of `domain/optimizer.py` and FU-26's kernel, neither
of which is in the repo — `git log` has no commit adding either. Nothing in this
re-derivation confirms or refutes them; the per-candidate rate they imply is at
least internally consistent with §6.2's 357 ns. They should be re-run and re-recorded
as part of FU-26, and treated as a design estimate until then.]**

Extrapolating the same rate — expansions grow as
`1 + first_moves + first_moves · beam · (H − 2)` and the run costs ~3.5 M scored
candidates per second — `--beam 4` crosses two minutes at about **horizon 11**. The
runtime wall is therefore *not* what limits the horizon in practice: optimizer-ux.md
§2 clamps to the last scheduled gameweek and records that fixtures beyond GW+5 are
provisional, and §4.4 flags ~8 as where beam continuation error becomes the argument
against the whole approach. **Both of those bind well before the clock does.**

### 7.2 — Memory is flat by construction, and that is a design property

Peak RSS varies between 52 MB and 57 MB across a 6× range of runtime and a 6× range
of node count. That is not luck. **A node's children are never materialised.** Each
out-combination produces one numpy value grid, is reduced to its top-`w` immediately
by `argpartition`, and the grid is released; only the surviving `w` children per node
are ever built as Python objects. Peak memory is therefore

```
projection table (612 × H)  +  one grid chunk  +  first_moves × beam retained nodes
```

— and the middle term is a **fixed constant**, because grids are chunked at 2²¹
cells (16 MB) regardless of how large the out-combination's candidate product is. No
term grows with the size of the search.

**What the crash was, recorded because the arithmetic is the whole lesson.** The
implementation that exhausted the box accumulated every child of every node at a
level into one Python list before bucketing. At horizon 5, `--beam 4`, that is
200 nodes × 162,792 children = **32.6 M child tuples**; at roughly 400 bytes each
(a 6-tuple, a 15-element id list, a nested move tuple) that is **≈ 13 GB** — on a
12 GB machine, with `--beam 8` doubling it to 26 GB. The run did not fail, it took
the machine with it, which is the worst available outcome and the one a ceiling
exists to convert into an error message.

The lesson generalises past this bug: **the level-materialising design and the
streaming design have identical outputs and identical asymptotic runtime.** Nothing
in a runtime budget distinguishes them. Only a memory budget does.

### 7.3 — The guard: refuse before starting, never discover the limit by hitting it

Both quantities the guard needs are computable **before any scoring happens**, from
the flags and the dominance-pruned pool:

```
expansions      = 1 + first_moves + first_moves · beam · max(0, H − 2)
cells_per_node  = Σ over out-combinations of Π (candidates per incoming slot)
projected_cells = cells_per_node · (H + expansions − 1)
```

**`cells_per_node` is exact, not a model.** It runs the generator's own out-combination
enumeration and multiplies the per-slot candidate counts, skipping only the scoring —
so it does not approximate the number of candidates the run will score, it *is* that
number. Verified against the expander at the root node:

| | Projected | Actually scored | Error | Cost of projecting |
|---|---:|---:|---:|---:|
| k ≤ 1 | 574 | 574 | 0.0% | 0.24 ms |
| k ≤ 2 | 226,896 | 226,896 | 0.0% | 1.10 ms |
| k ≤ 3 | 45,641,270 | 45,641,270 | 0.0% | 6.18 ms |

That exactness matters more than the speed. A guard whose projection drifts fires on
the wrong runs in both directions — refusing affordable ones and admitting the run
that takes the machine down — and a guard that is only approximately right is one
users learn to raise reflexively.

> **`--max-cells`, default 400,000,000** (≈ 115 s at the measured 3.5 M/s). A run
> whose `projected_cells` exceeds it is **refused before the first grid is
> allocated**, with the projection, the ceiling, the implied runtime and the flags
> that reduce it:
>
> ```
> Refusing to start: this search projects 2.1e9 scored candidates
>   (9,801 node expansions, ~10 min, ~55 MB) against --max-cells 400,000,000.
> Reduce --horizon 8, --beam 8 or --first-moves 200, or raise --max-cells.
> ```

Three things about that ceiling are deliberate:

- **It is a cap on projected work, not a timeout.** A timeout tells the user a run
  was too expensive after they have paid for it, and leaves a partial beam whose
  guarantee (§5.6) no longer holds. A refusal costs nothing and is actionable.
- **It also bounds `--schedule`.** `k_w ≥ 4` puts a single out-combination past 10⁹
  cells and is refused by the same arithmetic rather than by a special case — which
  is why §5.7 can state its ceiling of 3 as a consequence rather than a rule.
- **The memory ceiling is separate and is a constant, not a projection.** §7.2 makes
  peak memory independent of the search size, so it is enforced structurally by the
  2²¹-cell chunk rather than by a flag the user has to reason about. The
  implementation should nonetheless set `RLIMIT_AS` for the process, as the
  measurement harness did: a design that guarantees bounded memory should fail loudly
  if that guarantee is ever broken, rather than swapping.

### 7.4 — What still moves these numbers

- `--robustness=full` multiplies the whole budget by the model count, which is what
  optimizer-ux.md §6.1 already says it costs. `rescore`, the default, is free.
- **§5.2 warns that dominance prunes less as the season progresses, so re-measure
  around GW10.** The pool is 177 today; `projected_cells` grows roughly as its
  square at k = 2, so a pool of 250 would put the default configuration near 80 s.
  The guard makes this visible as a refusal rather than as a hang, which is the
  behaviour change that matters — but the budget above is a GW2 measurement and
  should be read as one.
- The escape hatch the previous revision reserved — vectorising `xi_value` — **has
  been taken**, and there is no second one of comparable size held in reserve. The
  next lever is algorithmic (§4.4), not implementational.

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
- **`xi_value` ≡ `objective_points(best_xi(...))`** on random 15-player squads, **and
  the vectorised batch ≡ `xi_value` child by child.** This is the guard that keeps the
  fast path honest, and with FU-26 it is no longer optional: the numpy kernel is a
  second expression of the objective, and this test is the only thing tying it to the
  one `validate_plan` uses. It has already been run by hand against the live snapshot
  — exact to 1e-9 on all 559 k = 1 and 4,000 sampled k = 2 children of the root — and
  that run is what §7's measurements are permitted to mean anything.
- **Peak memory does not grow with the search.** Run the same root at `--beam 1` and
  `--beam 8` and assert peak RSS differs by less than a fixed margin. This is a
  regression test for a specific defect that cost a machine (§7.2), and it is the
  only kind of test that would have caught it: both designs produce identical output
  and identical asymptotic runtime, so nothing else distinguishes them.
- **The guard refuses before allocating.** Assert that a configuration whose
  `projected_cells` exceeds `--max-cells` raises before the first grid is built, that
  the message names the flags that reduce it, and — separately — that
  `cells_per_node` agrees with the number of candidates actually scored, since a
  projection that drifts from reality is a guard that fires on the wrong runs.
- **`--schedule` is a constraint, never a widening.** For any schedule whose counts
  all fall within `k_enum`, its best score must be **≤** the free search's over the
  same snapshot and horizon — the free search can choose that shape. `--schedule 1,1`
  against a free k ≤ 2 run is the cheap instance. A schedule scoring *higher* means
  the free search has a bug, not that the schedule found something.
- **Schedule feasibility is refused up front**, with the hit arithmetic shown, rather
  than producing an empty beam (§5.7).
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
- **Chips are not modelled (FU-5)**, and §4.4 records them as a live reason to
  revisit the whole approach — no longer the *first* such reason, since k ≤ 2 at every
  level got there first. A free hit in particular breaks the "a node is a squad"
  assumption, since the squad reverts the following gameweek — the node would need a
  chip field and a saved pre-chip state.
- **numpy is a hard runtime dependency** (Context, §6.2). The search does not degrade
  gracefully without it; there is no pure-Python path, by choice. This is a real
  reduction in the project's portability, taken deliberately in exchange for k ≤ 2 at
  every beam level, and it is the assumption most likely to be questioned by someone
  reading §4.3's earlier argument rather than its current one.
- **The beam is not converged at `--beam 4`** (§5.5). The recommended first move
  changes between widths on a score spread well inside the projection model's own
  error. `--beam` is a cost knob presented as one, not an accuracy dial.
- **`--schedule` did not beat the free search on the snapshot it was measured
  against** (§7.1) — every fixed shape scored below the free k ≤ 2 run, including
  `0,0,3`. That is not evidence the roll-then-spend shape is worthless, and it must
  not be read as such: §5.4 records that **the cached schedule contains no blanks and
  no doubles at any gameweek** and that `_appearances` is 1, so there is no fixture
  swing to bank *for*. The case `--schedule` exists to express is precisely the case
  this snapshot cannot exhibit. `[gap: the flag's value should be re-measured against
  a snapshot containing a real blank or double gameweek — the same condition §5.4's
  injected-blank experiment had to manufacture.]`
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
  Measured 8.7×.
- **FU-25** — two-pass self-consistent `ft_value` estimation (§6.1).
- **FU-26** — vectorise `xi_value` and score a node's whole child batch as array
  operations (§6.2). Measured **357 ns per child against 15.6 µs**, and 12.4× against
  the pure-Python node-amortised form on the same machine. Adds numpy as a straight
  dependency. **This is the prerequisite §7's budget rests on**, not an optimisation:
  without it k ≤ 2 at every beam level is an ≈ 8-minute command.

FU-23, FU-24 and FU-26 are prerequisites of §7's budget, and all three are separate
concerns from the optimiser — one branch each, in that order, before
`domain/optimizer.py`. The ordering is not arbitrary: FU-24 creates the `xi_value`
seam that FU-26 vectorises, and FU-26's correctness rests on FU-24's property test.

**Not filed as a follow-up, because it belongs to the optimiser branch itself:**
adding `numpy` to `pyproject.toml`'s `dependencies`. It is listed here so it is not
forgotten — §7's measurements were taken against numpy 2.5.2 installed into the venv
by hand, and the declaration does not yet exist in the repo.

# FU-28 — dominance pruning is unsound: reproduction, options, recommendation

**Status:** **implemented** — `task/fu-28-dominance`, 2026-08-27 (`e69bb3d`,
`b9706c6`). §§1–7 are the design as written on `task/fu-28-plan` and are left
unedited; §8 settles the one question §7 left open, and §9 records what landed against
what was predicted. Where they disagree, §§8–9 win.
**Answers:** `docs/plans/follow-ups.md` FU-28; `optimizer-search.md` §5.2's
2026-08-26 correction and §6.3.
**Measured against:** `main` at `8ba4ccf` (post FU-33), 2026-08-27.

## 1 — The guarantee §6.3 claims, and the exact condition under which it is false

### 1.1 What is claimed

§6.3, first paragraph:

> Every exclusion carries one of four reasons — `dominated` (exact, naming the
> dominator), `unaffordable` (quoting bank and shortfall), `club limit` (naming the
> three held players), `already held` — and the pruned set is reachable from the node

and, closing:

> A player excluded by §5.2's dominance rule stays excluded under any schedule, with
> the same stated reason, so the four exclusion reasons remain exhaustive.

Read against optimizer-ux.md §9, that is two claims, not one:

- **(G1) Completeness of the reason set.** Every player absent from a node's candidate
  set is absent for one of exactly four reasons, each nameable to the user.
- **(G2) Costlessness of `dominated`.** The `dominated` reason is *exact*: substituting
  the named dominator costs nothing in legality or in value, so the exclusion removes
  no value from the search. This is what "(exact, naming the dominator)" asserts, and
  what §5.2's "interchangeable under every constraint" argument is offered to prove.

G2 is the load-bearing one. Without it G1 is honest but empty — `dominated` would name
a reason that does not justify the exclusion.

### 1.2 The exact condition under which G2 is false

Let `dom(p)` be the set of players who **effectively dominate** `p` under
`_dominance_pool`'s own relation: same `(position, club)` bucket, `now_cost <=`,
`xP >=` at every event of the horizon, and either strictly better on some coordinate or
lower player ID (`optimizer.py:196-208`). Let

```
m(position) = min(squad_team_limit, position.squad_select)
```

be the most players a legal squad can ever hold simultaneously from one
`(position, club)` bucket — 2 for GKP, 3 for DEF/MID/FWD on the live snapshot.

> **G2 holds for `p` if `|dom(p)| >= m(position(p))`.** It fails exactly when the
> optimal squad holds `p` **and** every member of `dom(p)`, so that no dominator is
> free to substitute for `p`. Since the squad may hold at most `m` from the bucket,
> `|dom(p)| >= m` makes that impossible.

`_dominance_pool` excludes `p` as soon as it finds **one** dominator
(`optimizer.py:209-210`, `break`). So the condition fails whenever a bucket contributes
two or more players to the optimal squad and one of them is dominance-excluded. Two
shapes reach this, and only the first is recorded anywhere today:

- **(i) Same-bucket double-buy.** Both in-slots of a same-position k = 2 move drawn
  from one bucket — the shape `_mask_k2`'s `i < j` dedup exists to support
  (`optimizer.py:334-339`). This is §5.2's recorded correction and FU-28's subject.
- **(ii) Held dominator.** `p`'s only dominator is **already in the squad**.
  `_dominance_pool` ranges over all transactable players with no reference to
  holdings; `_candidates_for` (`optimizer.py:231-241`) then filters held players out of
  the pool. The dominator therefore cannot be bought, and `p` was already discarded, so
  the search can reach neither. **This fires on a single transfer.**

Shape (ii) is not in FU-28, not in §5.2, and is explicitly denied by
`tests/test_optimizer.py:408`'s docstring ("Scoped to picking **one** player from the
bucket … §5.2's own argument for exactness is pairwise substitution") and by FU-28's
"`tests/test_optimizer.py`'s dominance test is scoped to k = 1 (provably exact)".
**k = 1 is not exact in the search.** It is exact only in the bucket-in-isolation
setting the property test actually constructs, where the squad holds nothing.

### 1.3 Unsound-but-bounded, or unbounded?

**Unbounded.** The value lost is

```
xP(p) − xP(best substitute the pruned pool can still reach)
```

The dominance rule constrains the first term only relative to `dom(p)`, and constrains
the second term not at all — `p` was never compared against any non-dominator, so the
best surviving alternative may sit arbitrarily far below `p`. Nothing in §5.2's
construction, in the pool size, or in `k_enum`, `beam` or `first_moves` places a floor
under it.

Measured (§2.3): holding the fixture shape, the pool size and the rule fixed and
varying only the xP values, the gap moves from **1.00 to 98.00 points**. It is bounded
only by the objective's own range, which is not a bound in any useful sense.

This matters for the recommendation. A bounded error could be traded against runtime —
"we lose at most ε, and ε is small". An unbounded one cannot: there is no ε to quote,
so the only honest choices are to restore exactness or to keep telling the user the
answer may be arbitrarily wrong, which is what `presentation.py:274-280` does today.

## 2 — The reproduced counterexamples

Both reproduce against current `main` (`8ba4ccf`, i.e. **after** FU-33 reformulated
`_mask_k2`). The club-mask rewrite changed neither, as expected: FU-33 replaced a
tensor with an equivalent 1-D formulation and is covered by its own equivalence tests.

**Method for the correct answer.** Exhaustive enumeration of every legal k <= 2 move
over the **full transactable player set** (no dominance pruning), each applied with
`apply_transfers` and scored with `xi_value` — the same independent-oracle construction
`tests/test_optimizer.py::_brute_force_best_score` already uses, and deliberately not a
call into `optimizer.py`'s own candidate generator. Both fixtures use `horizon=1` and
`first_moves=500`, so the root expansion is exhaustive over the pruned pool and no beam
or `first_moves` cut can be confused for the effect being measured: the *only*
difference between search and oracle is the candidate pool.

### 2.1 C1 — same-bucket k = 2 double-buy (FU-28's shape, minimised)

Minimised to **four held players and three pool players**. `squad_squadsize=4`,
`squad_squadplay=4`, `squad_team_limit=3`; positions GKP (select 1, play 1–1), DEF
(select 2, play 2–2), FWD (select 1, play 1–1) — so exactly two defenders start and a
same-bucket pair is forced into the XI. One event (GW2), `decay=0.84`, `ft_value=1.5`,
`max_hit=4`, `bank=10`, `free_transfers=1` (accrues to 2, so k = 2 takes no hit and the
hit arithmetic cannot confound the comparison).

| id | pos | club | cost | xP(GW2) | role |
|---:|---|---:|---:|---:|---|
| 1 | GKP | 1 | £4.0m | 1.0 | held |
| 2 | FWD | 2 | £4.0m | 20.0 | held — fixed captain, so the armband never moves |
| 3 | DEF | 3 | £4.0m | 0.5 | held, sold |
| 4 | DEF | 4 | £4.0m | 0.5 | held, sold |
| 6 | DEF | **9** | £4.5m | 10.0 | pool — **dominator** |
| 7 | DEF | **9** | £4.5m | 8.0 | pool — **excluded**, dominated by 6 |
| 8 | DEF | **9** | £4.0m | 7.0 | pool — survivor, incomparable with 7 (cheaper *and* worse) |

`_dominance_pool` returns survivors `[1, 2, 3, 4, 6, 8]`, excluding 7 with
`dominated by 6: costs £0.0m less (or the same) and projects at least as many points in
every gameweek of the horizon`.

```
optimise = 16.000   move = [(3→6), (4→8)]
oracle   = 17.000   move = [(3→6), (4→7)]
gap      =  1.000
```

Selling 3 and 4 frees £9.0m. `6+7` costs exactly £9.0m and scores 18.0; `6+8` costs
£8.5m and scores 17.0. Player 7 is stripped before the search sees it, so `6+8` is the
best pair reachable. Player 8 does not rescue it — 8 and 7 are mutually non-dominated,
so 7's exclusion says nothing about how 7 relates to 8.

### 2.2 C2 — held dominator, k = 1 (**not** recorded in FU-28)

Same rules and shape; the dominator is **held** rather than bought, and only one
transfer is made.

| id | pos | club | cost | xP(GW2) | role |
|---:|---|---:|---:|---:|---|
| 1 | GKP | 1 | £4.0m | 1.0 | held |
| 2 | FWD | 2 | £4.0m | 20.0 | held — fixed captain |
| 6 | DEF | **9** | £4.5m | 10.0 | **held** — the dominator |
| 3 | DEF | 3 | £4.0m | 0.5 | held, sold |
| 7 | DEF | **9** | £4.5m | 8.0 | pool — **excluded**, dominated by held 6 |
| 8 | DEF | **9** | £4.0m | 7.0 | pool — survivor |

```
optimise = 8.000   move = [(3→8)]
oracle   = 9.000   move = [(3→7)]
gap      = 1.000
```

The buyable DEF pool is `[8]`: 6 is filtered as already held, 7 was pruned against 6.
**One transfer, no `_mask_k2` involvement, unsound.**

### 2.3 The error has no floor

C1 with everything fixed but the xP column:

| xP(6) | xP(7) | xP(8) | `optimise` | oracle | gap |
|---:|---:|---:|---:|---:|---:|
| 10.0 | 8.0 | 7.0 | 16.00 | 17.00 | 1.00 |
| 10.0 | 8.0 | 4.0 | 13.00 | 17.00 | 4.00 |
| 10.0 | 8.0 | 0.5 | 11.00 | 17.00 | 6.00 |
| 22.0 | 20.0 | 0.5 | 23.00 | 41.00 | 18.00 |
| 52.0 | 50.0 | 0.5 | 53.00 | 101.00 | 48.00 |
| 102.0 | 100.0 | 0.5 | 103.00 | 201.00 | **98.00** |

### 2.4 Shape (ii) is live, not only synthetic

Cached snapshot 2026-08-27T13:33Z (614 players), root GW2, `squad.json`, `component`
model, horizon 5. Of **425** dominance exclusions, **14 name a dominator the squad
already holds** — every one of them unbuyable, with an exclusion reason the user cannot
act on:

| Excluded | Held dominator | xP over horizon (excluded vs dominator) |
|---|---|---|
| Gabriel (4, £8.0m) | Calafiori (8, £5.6m) | 7.38 vs 11.32 |
| Saliba (6, £6.0m) | Calafiori (8, £5.6m) | 0.00 vs 11.32 |
| Drameh (281), Giles (282), McNair (285), Coyle (280), McCarthy (284), Targett (556), Herrington (585), Hughes (278), Jacob (283) | Egan (277, £4.0m) | 0.00–11.85 vs 18.43 |
| O'Reilly (387, £6.5m) | Guéhi (388, £6.0m) | 17.19 vs 31.69 |
| Matheus N. (389, £6.0m) | Guéhi (388, £6.0m) | 4.34 vs 31.69 |
| Wood (490, £6.0m) | Igor Jesus (491, £6.0m) | 8.80 vs 9.80 |

None of them would improve *this* squad — the best score is 70.066 with or without the
fix (§3). The mechanism is live; on this snapshot it happens not to bind.

## 3 — Options

Measurement conditions, identical for every row: `domain.optimizer.optimise()` driven
directly (the CLI exposes neither `--beam` nor `--max-cells`, FU-31), snapshot and
fixtures **loaded from the on-disk cache** rather than through `SnapshotService` so all
rows see byte-identical input — §7.1c/7.1e's live re-fetch drifted the pool between
runs and this comparison cannot afford that. `squad.json`'s real 15-player squad, root
GW2, `component` model, horizon 5, `--beam 4`, `--first-moves 50`, `--max-hit 4`, decay
and `ft_value` default. Each row in its own subprocess, `RLIMIT_AS` 3 GB, 120 s
wall-clock cap. `max_cells` raised to 10^12 for measurement so the pre-flight guard does
not truncate the comparison (see §3.5 — it would otherwise refuse two of these rows).

**Harness calibration.** The baseline row reproduces §7.1e's published figure: 62.3 s
vs 63.1 s, with `projected_cells` (112,969,160) and best score (70.066) *identical*.
The 0.8 s is inside the 1.4 s run-to-run spread §7.1e's own repeat shows.

| Option | Pool | `projected_cells` | Runtime | Δ | Peak RSS | Best score | Restores soundness? |
|---|---:|---:|---:|---:|---:|---:|---|
| baseline `8ba4ccf` | 189 | 112,969,160 | **62.3 s** | — | 68.8 MB | 70.066 | — |
| **A** ban same-club pairs | 189 | 112,402,585 | 62.6 s | +0.3 s | 68.4 MB | 70.066 | **no** |
| **B** top-`m` Pareto layers | 405 | 597,027,915 | 99.0 s | +36.7 s | 74.4 MB | 70.066 | yes |
| **C** report only | 189 | 112,969,160 | 62.3 s | 0 | 68.8 MB | 70.066 | no (bounds nothing) |
| **D** exclude at >= `m` dominators | 373 | 511,454,785 | **90.4 s** | +28.1 s | 73.2 MB | 70.066 | yes |

Every option was also run against C1 and C2:

| | C1 (`optimise` / gap) | C2 (`optimise` / gap) |
|---|---|---|
| baseline | 16.000 / **1.000** | 8.000 / **1.000** |
| A | 11.000 / **6.000** | 8.000 / **1.000** |
| B | 17.000 / 0.000 ✓ | 9.000 / 0.000 ✓ |
| D | 17.000 / 0.000 ✓ | 9.000 / 0.000 ✓ |

### 3.1 Option A — restrict `_mask_k2` so a same-position pair never shares a club

**Changes:** one extra term in `_mask_k2`'s `club_ok`, ANDing
`club_a[:, None] != club_b[None, :]` when `same_position`. No pool change.

**Soundness: no — measured.** FU-28 and §5.2 both call A "exact by construction". It is
not. It cannot address shape (ii) at all (a k = 1 move never enters `_mask_k2`), so C2
fails identically to baseline. And on C1 it makes the answer **worse**: removing the
shape drops the search to a single transfer and the gap grows from 1.000 to **6.000**.
Removing a move shape does not recover the value the pruning discarded; it discards
more.

It also costs a real capability — stacking one club's defence for a fixture swing —
and does so silently, against §5.3's own standard for unenumerated shapes.

**Runtime: 62.6 s (+0.3 s, inside noise).** The mask is applied *after* `score_children`
fills the grid (`optimizer.py:625-627`), so masked cells are still scored; only
`_materialize` calls are saved. `projected_cells` falls 0.5%.

**Ruled out.** Not a soundness fix, a capability loss, and no runtime win.

### 3.2 Option B — widen the pool to the top `m` Pareto layers

**Changes:** `_dominance_pool` computes Pareto *layers* per bucket (peel the frontier,
repeat) and retains layers `1..m`, `m = min(squad_team_limit, position.squad_select)`.

**Soundness: yes, for every k.** If the optimum uses `j <= m` players from a bucket
including a `p` in layer > `m`, then `p` has a chain of `m` dominators above it, of
which at most `m − 1` can be in use, so one is free; each swap moves strictly up a
finite strict partial order, so iterating terminates on a fully-retained set. Note this
is stronger than FU-28's "exact for every k <= 2 shape" — the argument never mentions
`k_enum`.

**Runtime: 99.0 s (+36.7 s).** Pool 189 → 405; `projected_cells` 5.3×.

**Viable, but strictly worse than D** on pool size, runtime and diff size.

### 3.3 Option C — leave the pruning, name the gap in the output

**This is what ships today.** `cli.py:679` passes `dominance_unsound=True`
unconditionally and `presentation.py:274-280` prints the red banner.

**Runtime: 62.3 s (+0).** **Soundness: no.** It does not bound the error either — §1.3
shows there is no bound to quote, so the banner can only say "arbitrarily wrong", which
is what it says. It was the right holding position while the fix was unpriced; it is
not an answer.

### 3.4 Option D (new) — exclude a player only once `m` distinct dominators exist

**Changes:** `_dominance_pool`'s inner loop counts effective dominators instead of
`break`ing on the first, and excludes only at `count >= m(position)`. The relation and
its ID tie-break are unchanged. The `dominated` reason string gains the count.

**Soundness: yes, for every k** — the same exchange argument as B, one step shorter.
`p` excluded ⇒ `|dom(p)| >= m`; the optimum holds at most `m` from the bucket, so at
most `m − 1` of `dom(p)` besides `p` itself, so some dominator is free to substitute;
each swap moves strictly up a finite strict partial order, so the iteration terminates
on a set the pool retains.

**Strictly stronger pruning than B.** Anyone D retains has `< m` dominators, hence layer
`<= m`, so `D ⊆ B` — verified on the live snapshot (373 vs 405 survivors, subset holds).

**Runtime: 90.4 s (+28.1 s), peak RSS 73.2 MB.** Pool 189 → 373; `projected_cells` 4.5×
for a 1.45× runtime, because per-node fixed costs amortise over larger grids (1.81 M
projected cells/s at 189 survivors, 5.66 M/s at 373).

**Bonus:** exactness for every k also removes one blocker from FU-29's `--schedule` at
k = 3, which B shares and A actively worsens.

### 3.5 What every exact option needs: raise `DEFAULT_MAX_CELLS`

B (597 M) and D (511 M) both exceed `DEFAULT_MAX_CELLS = 400_000_000`
(`optimizer.py:53`), so **without raising it the pre-flight guard refuses the default
configuration** with `SearchTooExpensive` before scoring a single grid. Raise to
**800,000,000**: it clears D's 511 M with room for the pool growth §5.2 predicts as
players differentiate through the season, and D's measured 90.4 s at 511 M leaves the
120 s cap intact.

`[gap: §7.3's ceiling is glossed as "≈ 115 s at the measured 3.5 M/s". Measured
throughput is 1.81 M/s at the current pool and 5.66 M/s at D's — the rate is not a
constant, so cells are a poor proxy for seconds and the gloss is wrong in both
directions. Not fixed here; file separately.]`

### 3.6 Nothing was estimated

Every runtime, pool size and cell count above is a measurement. No option in this
document is priced by extrapolation.

## 4 — Recommendation

**Option D, plus `DEFAULT_MAX_CELLS` 400 M → 800 M.**

1. **B and D are the only options that restore soundness at all,** and the error is
   unbounded (§1.3), so there is no error-bound trade to make. A restores nothing and
   makes C1 worse; C bounds nothing.
2. **The cost is 28.1 s against a self-set cap.** 62.3 s → 90.4 s, inside 120 s. That
   cap is this project's own (§7.1c), not an external requirement, and §7.1f's own
   ordering already says accuracy outranks it: "FU-28 is unsound pruning … Land FU-28
   first" (optimizer-search.md:1752-1758).
3. **D beats B on every axis measured** — 8.6 s faster, 32 fewer pool players, a smaller
   diff (a counter, not a layer decomposition), and the same exactness.
4. **It is exact for every k**, so it does not have to be revisited when `--schedule`
   (FU-29) raises the per-gameweek transfer count.

Once it lands: delete `cli.py:679`'s `dominance_unsound=True` and the
`presentation.py:274-280` banner it feeds, and drop the `dominance_unsound` parameter —
its whole purpose was to admit to the defect this closes. `tests/test_cli_optimise.py`
asserts `"FU-28" in out` and must be inverted to assert the banner is **absent**.

**What is deliberately not done here.** The 28.1 s is not clawed back on this branch.
FU-34's `_materialize` restructuring is filed and independent, and bundling a
performance change with a correctness fix would make both harder to verify — one
concern per branch. If the default run's cost becomes a problem, that is FU-34's
ground, not this one's.

## 5 — The regression test

Two new tests in `tests/test_optimizer.py`, plus one strengthened. All three fail on
`8ba4ccf` and pass after Option D. Fixtures are given in full so no counterexample has
to be re-derived.

### 5.1 Shared fixture helper

```python
_FU28_POSITIONS = [
    Position(id=1, singular_name_short="GKP", squad_select=1, squad_min_play=1, squad_max_play=1),
    Position(id=2, singular_name_short="DEF", squad_select=2, squad_min_play=2, squad_max_play=2),
    Position(id=4, singular_name_short="FWD", squad_select=1, squad_min_play=1, squad_max_play=1),
]
```

`GameSettings(squad_squadsize=4, squad_squadplay=4, squad_team_limit=3,
squad_total_spend=300)`; gameweeks 1 and 2 with deadlines after `NOW`
(`datetime(2025, 8, 1, tzinfo=UTC)`, as the module already defines); nine clubs;
`raw={"game_config": {"scoring": {}}}`. The XI is forced to GKP + FWD + exactly two DEF,
so a same-bucket defensive pair lands in the XI and the FWD (xP 20.0) is the captain in
every branch — the armband never moves, so the gap reads as a plain xP difference.

Holdings all at `purchase_price == now_cost`, `bought_event=0`; `bank=10`, `event=1`,
`free_transfers=1` (accrues to 2, so a k = 2 move takes no hit).

Call: `optimise(..., from_event=2, horizon=1, decay=0.84, ft_value=1.5, max_hit=4,
beam=4, first_moves=500, max_cells=10**9, now=NOW)`. **`horizon=1` and
`first_moves=500` are load-bearing**: they make the root expansion exhaustive over the
pruned pool, so a failure can only be the candidate pool and never the beam.

### 5.2 The oracle

Reuse the existing independent enumeration. `_same_position_swaps(snapshot, held,
k_max=2)` (`tests/test_optimizer.py:110`) already enumerates every k <= 2 same-position
move over **every player in the snapshot**, which is exactly the unpruned move set
needed. Score each with `apply_transfers` + `xi_value` at the single event:

```python
score = (xi_value(result.state.player_ids, projections_by_event[2], snapshot)
         - hold_objective) - result.hit_points \
        + ft_value * min(result.state.free_transfers, rules.free_transfer_cap)
```

Do **not** call `_dominance_pool` or any other `optimizer.py` generator from the oracle.
Assert `result.paths[0].score == pytest.approx(oracle_best, abs=1e-9)`.

### 5.3 `test_dominance_survives_a_same_bucket_double_buy`

Players and xP exactly as §2.1's table; held `(1, 2, 3, 4)`.
Today: `optimise` 16.0, oracle 17.0. After the fix both are 17.0 and the winning move is
`[(3→6), (4→7)]`.

Two sizing assertions, so the test cannot go vacuous the way FU-36's did:

```python
# Player 7 must be reachable on the pruned pool, or the fixture proves nothing.
survivors, reasons = _dominance_pool(snapshot, projections_by_event, [2])
assert 7 in survivors      # on 8ba4ccf this read `7 in reasons`
# The winning pair must be exactly affordable, so the budget genuinely binds.
assert (snapshot.players_by_id[6].now_cost + snapshot.players_by_id[7].now_cost
        == state.bank + sum(snapshot.players_by_id[p].now_cost for p in (3, 4)))
```

The first assertion is the one that flips with the fix; the docstring should record that
it read `7 in reasons` before.

### 5.4 `test_dominance_never_excludes_against_a_held_dominator`

Players and xP exactly as §2.2's table; held `(1, 2, 6, 3)`.
Today: `optimise` 8.0, oracle 9.0. After the fix both are 9.0, move `[(3→7)]`.

Sizing assertion — the point of the test is that the buyable pool is starved:

```python
buyable = [p for p in survivors
           if snapshot.players_by_id[p].element_type == 2 and p not in state.holdings]
assert buyable == [7, 8]   # on 8ba4ccf it is [8]
```

The docstring must record that this is a **k = 1** failure, contradicting FU-28's and
`test_dominance_excludes_only_players_a_survivor_can_always_replace`'s claim that k = 1
is provably exact.

### 5.5 Strengthen the existing property test

`test_dominance_excludes_only_players_a_survivor_can_always_replace`
(`tests/test_optimizer.py:408`) asserts exactness for the best **single** pick. Raise it
to the best pick of **up to `m`** players under a joint budget, and delete the
`[gap: ...]` paragraph in its docstring — after the fix that gap is closed, and leaving
the disclaimer would misdescribe what the test now proves. Same seed
(`"fu-optimizer-dominance-is-exact"`), same 8 trials;
`m = min(squad_team_limit, position.squad_select)`. This is the test that would have
caught the defect originally.

### 5.6 What must keep passing

`pytest -q` — 235 tests on `8ba4ccf`. `tests/test_cli_optimise.py:117`'s
`assert "FU-28" in out` must be **inverted**, not deleted: the banner's absence is part
of what the fix delivers.

## 6 — Corrected §6.3, diff-ready

§6.3 is false as written, independently of whether the code is fixed. Two blocks follow:
the first is true **today**, on `8ba4ccf`, and should land with this document. The
second is the edit that replaces part of it **when Option D lands**.

### 6.1 Land now — §6.3 as it must read while the defect stands

Replace `docs/plans/optimizer-search.md` lines 1129-1155 (`### 6.3` through
`…remain exhaustive.`) with:

```markdown
### 6.3 — Candidate-set attributability (§9)

Answered by §5.2 **for three of the four reasons, and not yet for the fourth.**
`unaffordable` (quoting bank and shortfall), `club limit` (naming the three held
players) and `already held` are exact and attributable by construction. `dominated`
names a dominator, and the pruned set is reachable from the node, so `fpl players
show` and the "why not X" surface can answer without re-running anything — **but the
reason it gives is not always a true justification for the exclusion, and the value
lost is not bounded.** See FU-28 and `docs/plans/fu-28-dominance.md`.

**What is false, precisely.** §5.2's "interchangeable under every constraint" argument
proves that a dominator can substitute for a dominated player *when the squad wants
one player from the bucket*. `_dominance_pool` excludes on the **first** dominator
found, so the argument fails whenever an optimal squad wants a dominance-excluded
player together with every one of its dominators. Two shapes reach that, both
reproduced in `fu-28-dominance.md` §2 against `8ba4ccf`: a same-position k = 2 pair
drawn from one bucket (`_mask_k2`'s `i < j` dedup exists for it), and — on a **single**
transfer — an excluded player whose dominator the squad already holds, so that
`_candidates_for`'s already-held filter and the dominance exclusion between them make
both unreachable. The second shape fires 14 times on the live snapshot at GW2, and is
not covered by §5.2's correction, which scopes the defect to k = 2.

**The loss is unbounded, not bounded.** It is `xP(excluded) − xP(best reachable
substitute)`, and dominance never compared those two, so no quantity this design
controls places a floor under the second term. Measured: 1.0 to 98.0 points on one
fixture by varying only the xP column.

Until FU-28 lands, the four reasons are therefore **not exhaustive**: value lost to
unsound pruning is a fifth exclusion, attributable to no individual player, and
`fpl plan optimise` says so on every run (`presentation.py`'s
`DOMINANCE PRUNING IS UNSOUND` banner) rather than claiming an exactness the algorithm
does not have.

**No top-*k* cut is applied to candidates at any point**, and since §5.4's two-stage
cut was withdrawn, none is applied to scored *moves* either. That claim is unaffected
by the above — dominance is not a top-*k* cut, it is a rule that is currently applied
too aggressively.

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
§5.2's dominance rule stays excluded under any schedule, with the same stated reason —
including the cases above where that reason does not justify the exclusion.
```

### 6.2 Land with the fix — the replacement for three of those paragraphs

When Option D is implemented, replace the "**What is false, precisely.**", "**The loss
is unbounded**" and "Until FU-28 lands…" paragraphs with:

```markdown
**What makes `dominated` exact is a count, not a single comparison.** A player is
excluded only once `m = min(squad_team_limit, position.squad_select)` distinct players
in their `(position, club)` bucket dominate them — the most a legal squad could ever
hold from that bucket simultaneously. An optimal squad holding an excluded player
therefore always leaves at least one dominator free to substitute, whether the other
bucket members were bought in the same move or were already in the squad. This is
exact for **every** k, not only for `k_enum = 2`, so `--schedule` (§5.7) inherits it
without a further argument. FU-28 records the earlier first-dominator rule, which was
unsound in both those shapes, and `docs/plans/fu-28-dominance.md` records the
reproduction, the measurement and the four options considered.
```

…and restore the closing sentence to its original form:

```markdown
One thing `--schedule` does **not** relax: the candidate set. A player excluded by
§5.2's dominance rule stays excluded under any schedule, with the same stated reason,
so the four exclusion reasons remain exhaustive.
```

## 7 — What this document does not settle

- `[gap: whether Option D's 28.1 s can be recovered is not established here. FU-34's
  `_materialize` restructuring is the obvious candidate and is independent of this
  change, but it was not measured on top of D.]`
- `[gap: §7.3's "≈ 115 s at the measured 3.5 M/s" gloss on `--max-cells` is wrong —
  measured throughput is 1.81 M/s at the current pool and 5.66 M/s at D's. Cells are a
  poor proxy for seconds. Not fixed here.]`
- ~~`[gap: FU-35's note that `_dominance_pool` does not filter `can_select` is
  untouched by this change and neither confirmed nor refuted by it.]`~~ **Closed
  2026-08-27, before implementation, as variant (c) — see §8.**
- Whether the live best score ever changes under the fix is unknown beyond this one
  squad and snapshot, where it does not (70.066 before and after). The case for the fix
  is the unbounded error, not an improvement on today's recommendation.

## 8 — §7's `can_select` gap, closed: variant (c)

§7's third bullet left open whether the dominator count should include players
`_dominance_pool` admits but `validate_squad_structure` rejects. It has to be settled
before implementation, because it decides whether §3.4's exactness argument is true or
merely nearly true. **Decided: count only dominators the validator would accept** —
`can_select and not removed`. Pool *admission* is unchanged and stays on
`can_transact`; FU-35 owns that.

**Why the question is not cosmetic.** §3.4's exchange argument needs a dominator that
can *legally replace* the excluded player. `_dominance_pool` admits on `can_transact
and not removed` (`optimizer.py:184`) while `validate_squad_structure` rejects
`not can_select or removed` (`rules.py:57`), and **42 of the 614 players** on the
cached snapshot sit in the gap. Counting one of those towards `m` reintroduces exactly
the defect this document exists to fix, one level up: the player is excluded, and the
substitute the exclusion promises cannot legally be bought.

**Measured exposure**, horizon 5, root GW2:

| Counting rule | Excluded |
|---|---:|
| all transactable dominators (Option D as §3.4 writes it) | 241 |
| only validator-usable dominators (variant (c)) | 240 |

One player differs — **276 Lo-Tutala, 2 dominators, only 1 usable, `m` = 2** — and he
is himself `can_select=False`, so nothing legitimate is lost on this snapshot. That is
luck, not construction, and it is the same "true today, not true by design" shape FU-35
already records for 299 Burstow under the old rule.

**Why not simply fix admission instead (the obvious alternative).** Filtering
admission on `can_select` would make both predicates agree and the argument trivially
true. It is rejected here because it is FU-35's change, not FU-28's: it takes the pool
from 189 to 185 on the pre-FU-28 code, moves the search's output on its own, and
requires answering FU-35's open question of which flag is authoritative — which FU-35
records as unanswered. Bundling it would put two concerns and an undecided question on
one branch, and would make FU-28's before/after unreadable.

**What this costs:** one extra pool player on the cached snapshot, and one comment in
`_dominance_pool` explaining why two predicates that look like they should agree do
not. The comment is load-bearing — without it this reads as an inconsistency and gets
tidied into agreement, which would silently re-open the defect.

**Falsifiable, and demonstrated.** `tests/test_optimizer.py::
test_dominance_counts_only_dominators_the_validator_would_accept` fails under Option D
as §3.4 writes it and passes under variant (c) — confirmed by mutation, removing the
`_validator_usable` check and watching that test alone fail. The fixture is synthetic
because it has to be: the cached snapshot's only affected player is unselectable
himself.

## 9 — Landed

`task/fu-28-dominance`, 2026-08-27. `e69bb3d` (the counting change, three regressions,
the strengthened property test, and the removal of the `DOMINANCE PRUNING IS UNSOUND`
banner from both the console header and `--json`), `b9706c6` (`DEFAULT_MAX_CELLS`
400M → 800M).

Predicted against measured, on the live cached snapshot at GW2:

| | Predicted (§3) | Landed (variant (c)) |
|---|---:|---:|
| pool | 373 | **374** |
| exclusions | 241 | **240** |
| runtime, horizon 5 / beam 4 | 90.4 s | ~~**90.8 s**~~ |
| `projected_cells` | 511,454,785 | **513,191,190** |
| peak RSS | 73.2 MB | **73.7 MB** |
| best score | 70.066 | **70.066** |

**The runtime figure is superseded (FU-41).** ~~90.8 s~~ is not a baseline anything can
be compared against, for three reasons at once: it was measured by driving
`domain.optimizer.optimise()` directly rather than through the CLI; under
`--max-hit 4 --beam 4 --first-moves 50` rather than the CLI's defaults; and against a
2026-08-27T13:33Z capture with **614** players that no longer exists — `SnapshotService`
overwrote it, and FU-39's reproducibility note records its loss. Every other figure in
the row is reproducible from `projected_cells` and stands; only the seconds do not.

**Replacement baseline:** **93.05 s** (median of 5; min 92.91, max 93.37, spread 0.5%),
`fpl plan optimise squad.json` at CLI defaults, pinned to
`~/fpl-pinned/gw2-pre-deadline.json` (616 players, captured
2026-08-28T07:26:38.797492+00:00), 3 GB `RLIMIT_AS`, 120 s cap, all five runs
byte-identical. The flag differences were checked rather than assumed: `--robustness
off` measured 94.01 s and `--robustness off --max-hit 4` 93.21 s, so neither accounts
for the ~2 s gap — at GW2 one free transfer accrues to two, and `k_max` is 2 either
way. A directory capture of the same inputs (FU-41) reproduces it exactly: net
96.02285, 238 exclusions, three runs byte-identical at 93.20-93.91 s.

The single-player differences are variant (c) and nothing else, exactly as §8 predicts.
`D ⊆ B` still holds (374 ⊆ 408).

**One reported number needs restating rather than ticking off.** §2.4 counts "14
exclusions naming a dominator the squad already holds", and that was the right
diagnostic for a rule that named exactly one dominator: naming a held one meant no
substitute existed. Under the counting rule an exclusion names `m` dominators, so the
metric no longer means what it did — 15 exclusions name *a* held dominator, which is
harmless. The defect-free measurements are:

- exclusions naming fewer than `m` dominators: **0**
- exclusions where **every** named dominator is held — no buyable substitute: **0**
  (this is the defect; it was 14)
- every exclusion leaves at least one buyable dominator: **yes**

Of §2.4's 14 named players, 2 are now in the pool and 12 remain excluded — but each of
the 12 now names 3 dominators of which only 1 is held, leaving 2 buyable substitutes.
They are excluded legitimately, which is the whole point.

**§7's other gaps remain open**: FU-34 was not re-measured on top of this change, and
`--max-cells` is still expressed in cells but justified in seconds with no constant
converting the two. Both are filed — FU-34 and the new FU-39.

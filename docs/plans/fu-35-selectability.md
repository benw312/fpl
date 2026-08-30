# FU-35 — should pool admission follow dominance counting?

**Status:** design, not implemented. No change to `src/` on this branch.
**Answers:** `docs/plans/follow-ups.md` FU-35, as narrowed by its 2026-08-28
re-check; `fu-28-dominance.md` §7 (third bullet) and §8.
**Measured against:** `main` at `7d9fb36`, 2026-08-28. Every figure below was
re-measured on this branch. **None of FU-35's recorded figures were inherited** —
the entry marks them indicative and they were taken against a snapshot that no longer
exists. Where a re-measured figure contradicts the entry, §9 says so.
**Provenance for every number:** §8. **Method, including how the "after" runs were
produced without editing `src/`:** §8.2.

---

## 1 — The question

FU-28 settled *counting*: a dominator counts towards `m` only if
`_validator_usable(other)` (`optimizer.py:180-188, 258`), which mirrors
`rules.py:57`. So for "may this player be counted as a dominator", the validator's
`can_select` is authoritative.

Admission was deliberately left alone (`optimizer.py:231`, and the source note at
`:219-223` that names FU-35 as its owner). The question is therefore **not** which flag
is authoritative in general. It is:

> **Should admission follow counting — `can_select and not removed`, the same predicate
> the count already uses — or stay on `can_transact and not removed`?**

The recommendation is **yes, admission should follow counting**, and it is grounded in
what the two flags mean (§2), not in what it does to the search. What it does to the
search (§4) is a consequence, and a small one.

---

## 2 — What the two flags mean, and who sits in the gap

### 2.1 Population on the pinned capture

`~/fpl-pinned/gw2-pre-deadline.json`, 616 elements. Counted directly off the raw
`elements` array, so these are API values and not model defaults:

| `can_transact` | `can_select` | `removed` | `status` | count |
|---|---|---|---|---:|
| True | True | False | `a` | 492 |
| True | True | False | `i` | 61 |
| True | True | False | `d` | 17 |
| True | True | False | `s` | 1 |
| **True** | **False** | **False** | **`u`** | **45** |

Derived populations:

| Predicate | Where | Count |
|---|---|---:|
| `can_transact and not removed` — admission today | `optimizer.py:231` | **616** |
| `can_select and not removed` — the validator, and the count | `rules.py:57`, `optimizer.py:188` | **571** |
| the gap: `can_transact and not removed and not can_select` | — | **45** |
| the reverse gap: `can_select and not removed and not can_transact` | — | **0** |

**`can_transact` is `True` for every player and `removed` is `False` for every player.**
Admission is therefore not a filter at all on this capture: it admits the entire
element list. That holds on every capture on this machine, not just this one — five
distinct captures spanning four days:

| Capture | elements | `can_transact ∧ ¬removed` | gap |
|---|---:|---:|---:|
| `archive/bootstrap-2026-08-25.json` | 612 | 612 | 41 |
| `archive/bootstrap-2026-08-26.json` | 614 | 614 | 42 |
| `archive/bootstrap-2026-08-27.json` | 614 | 614 | 42 |
| `archive/bootstrap-2026-08-28.json` | 616 | 616 | 45 |
| `~/fpl-pinned/gw2-pre-deadline.json` | 616 | 616 | **45** |

FU-35's "42 of 614" is reproduced exactly by the 08-26 and 08-27 captures, which is
where it came from. Today it is **45 of 616**.

### 2.2 Who sits in the gap

All 45 have `status='u'`, and on this capture `can_select == (status != 'u')` exactly.
Every one of them has news saying they have left the club: *"Has joined Paris
Saint-Germain permanently"* (30 Digne), *"Has joined Colchester United on loan for the
rest of the season"* (276 Lo-Tutala), and 43 more of the same shape. `now_cost` runs
40–65 against a snapshot maximum of 155, and `chance_of_playing_next_round` is 0 for
all 45. By position: 9 GKP, 15 DEF, 12 MID, 9 FWD.

So the gap is not an edge case in the flags. It is one coherent population: **players
who have left the Premier League**, priced at the bottom of the list.

### 2.3 What the flags mean, read off the code that already uses them

The repo already encodes an answer, in two places, and they agree with each other:

- **`can_select` governs whether a squad may *contain* a player.**
  `validate_squad_structure` rejects any squad holding one that fails it
  (`rules.py:57`), and `squad.py:404-405` uses the same test when choosing an XI.
- **`can_transact` governs whether a transfer may *touch* a player, in either
  direction.** `apply_transfers` rejects a transfer whose out- or in-side is not
  transactable (`transfers.py:299`).

That pairing is what the 45 are for. A manager holding Digne on 2026-08-25 must still
be able to **sell** him — that is `can_transact=True` — while nobody, that manager
included, may **hold** him past the deadline — that is `can_select=False`. The
combination is a *sell-only* state, and it is the only combination the API actually
uses here.

### 2.4 Why that settles admission

`_dominance_pool` feeds exactly one thing: `_candidates_for` (`optimizer.py:292-299`),
the **buy** side. The sell side never touches the pool — `_out_combinations`
(`:401-408`) ranges over `node.state.player_ids`, the squad's own holdings, and
`_expand_node` takes `held = set(node.state.holdings)` (`:653`).

So the pool is, by construction, a set of players the search proposes to **hold**.
Holding is governed by `can_select`. `can_transact` is necessary for the transfer that
buys them and is not sufficient for the squad that results — which is precisely why
`validate_squad_structure` throws every one of them out again downstream (§4.3).

Admitting on `can_transact` asks the wrong question of the wrong flag: it asks "may
this player be transferred?" of a list whose only use is "may this player be held?".
**Admission should follow counting: `can_select and not removed`.**

Two properties of this reading are worth stating because the tests in §7 depend on
them:

- **It does not make a held unselectable player unsellable.** Outs come from holdings,
  not the pool, and `apply_transfers` still consults `can_transact` at
  `transfers.py:299`. A squad holding Digne can still sell him after this change, at
  every `k`.
- **The safe direction is asymmetric.** Admission *narrower* than the validator can
  only lose optimality (a legal player the search never considers). Admission *wider*
  than the validator produces candidates that cannot legally exist — which is today's
  behaviour, and the shape FU-28 had to defend against one level up. §7's invariant
  test asserts the subset relation in that direction and not equality, for this reason.

---

## 3 — Recommendation

**Change `optimizer.py:231` to admit on the validator's predicate, expressed as the
same function the count uses:**

```python
transactable = [player for player in snapshot.elements if _validator_usable(player)]
```

Not a second textual copy of `can_select and not removed`. One function call, so the
two predicates cannot drift apart by editing one of them — which is the failure mode
the source note at `:219-223` was written to prevent by prose. The local name
`transactable` becomes wrong and should go with it (`admissible`, or fold the
comprehension into the bucket loop).

§5 says what then happens to the count-side call at `:258`, and §7 says what replaces
the guarantee the source note currently carries.

---

## 4 — The measured before/after

Default CLI configuration throughout: `fpl plan optimise squad.json --snapshot
~/fpl-pinned/gw2-pre-deadline.json --json` (horizon 5, root GW2, `--beam 4`,
`--first-moves 50`, `--model component`, `--robustness rescore`, uncapped hits), 3 GB
`RLIMIT_AS`, 120 s cap. Full provenance in §8.

### 4.1 Pool

| | before | after |
|---|---:|---:|
| admitted | 616 | **571** |
| pool (survivors) | 378 | **358** |
| exclusions | 238 | **213** |
| `projected_cells` | 522,125,390 | **466,526,370** (−10.6%) |
| node expansions | 651 | 651 |

The pool loses **exactly 20** players and gains none. Those 20 are exactly the
unselectable members of the old pool; the other 25 of the 45 were excluded by dominance
anyway. **No selectable player changes status** — not one is admitted that was
excluded, and not one is excluded that was admitted (238 = 213 + 25, 378 = 358 + 20,
and the set difference was checked member by member).

That is not luck. FU-28's counting change already made a selectable player's fate
independent of unselectable players, so filtering admission on the same predicate can
only remove the unselectable ones themselves. It is worth stating plainly because it
is the strongest argument that this change is *safe*: **the pool difference is the 45,
and nothing else.**

The 20 dropped from the pool: 39 Nedeljkovic, 59 Dennis, 80 Enes Ünal, 132 Howell,
197 Bassette, 225 Uche, 275 Cartwright, 276 Lo-Tutala, 298 Destan, 299 Burstow,
317 Hirst, 322 Al-Hamadi, 348 Piroe, 365 Ramsay, 394 Alleyne, 425 Fredricson,
451 A.Murphy, 530 Patterson, 538 Hjelde, 540 Masuaku.

### 4.2 Wall-clock and memory

Median of 5 runs each, process wall clock (`/usr/bin/time`), alternating before/after:

| | before | after |
|---|---:|---:|
| median | **93.21 s** | **89.87 s** |
| min / max | 92.63 / 94.71 | 89.17 / 90.33 |
| spread | 2.2% | 1.3% |
| peak RSS (median) | 93,788 kB | 93,692 kB |

**−3.34 s, −3.6%.** The before-median reproduces FU-28 §9's replacement baseline of
93.05 s to within its own spread, on the same capture and the same flags, which is the
check that this harness measures the same thing that baseline did.

Note the asymmetry: cells fall 10.6% but runtime falls 3.6%. That is expected and is
the same fact §6 turns on — the pool sets the *width of the scored grid*, but not the
number of candidates materialised, and materialisation is roughly half the run
(FU-34).

### 4.3 Rejections and the discard ratio

Instrumented runs (counters on `_materialize` and `_expand_level`; the timings above
come from the uninstrumented runs):

| | before | after |
|---|---:|---:|
| `_materialize` calls | 318,954 | **318,954** |
| rejected by `apply_transfers` | **498** | **0** |
| distinct pool members causing them | 12 | — |
| distinct rejection causes | 1 (`"<player> is not selectable."`) | — |
| `_expand_level` calls | 204 | 204 |
| retained after `_dp_prune` + `[:beam]` | 816 | 816 |

Every rejection, before, is one of 12 unselectable pool members being bought:
131 Cartwright, 114 Lo-Tutala, 74 Bassette, 30 Dennis, 29 Enes Ünal, 28 Destan,
27 Patterson, 19 Burstow, 16 Piroe, 11 Uche, 10 Hirst, 9 Al-Hamadi. After the change,
**zero rejections**, and `_materialize`'s `return None` branch is never taken.

### 4.4 The output diff, and the GW2 recommendation

**On the pinned capture, the `--json` payload differs in exactly one line:**

```diff
-    "dominance_exclusions": 238,
+    "dominance_exclusions": 213,
```

Everything else is byte-identical: verdict, description, break-even, gross, net,
robustness verdict, and all four paths with all their per-gameweek points. All seven
"before" runs produced one identical payload; all seven "after" runs produced another;
the two differ only in that line.

**Does the GW2 recommendation change? No — and this was checked on the exact input that
produced today's live run**, not only on the pre-deadline pin.

`~/fpl-pinned/gw2-recommendation.json` is a **live** run (`provenance.snapshot.source`
= `live`, 2026-08-28T13:25:28Z), so under FU-40 it is not citable as it stands. It is
made citable here by pinning the bootstrap cache file that produced it — the same
bytes, sha256 `3aac6dff…` (§8.1) — and re-running against that. The result:

- The pinned "before" run reproduces `gw2-recommendation.json` **byte-for-byte apart
  from the `provenance` block**: same 239 exclusions, same *Gabriel→De Cuyper +
  E.Le Fée→Alcaraz (−4)*, same net 92.91735970546681, same four paths. So the pin is
  the right input.
- The "after" run on that capture differs from it in one line, again:
  `"dominance_exclusions": 239 → 214`. Pool 377 → 357. Recommendation, net, paths,
  robustness: **identical**.

| Capture | pool before → after | exclusions before → after | recommendation |
|---|---|---|---|
| `gw2-pre-deadline.json` (07:26Z) | 378 → 358 | 238 → 213 | unchanged (net 96.02285022404398) |
| bootstrap cache (13:25Z), = the live run | 377 → 357 | 239 → 214 | unchanged (net 92.91735970546681) |

**The two captures disagree with each other about the recommendation** — 07:26Z says
*Tzolis→Hinshelwood* first and nets 96.023, 13:25Z says *Tzolis→Rogers* and nets
92.917 — and that difference is entirely capture drift across six hours, present
before and after the change alike. It is a clean small illustration of why FU-40
exists: quoting "the GW2 recommendation" without naming the capture would have made
this look like FU-35's doing.

### 4.5 Is the search better, or only cheaper?

Better, weakly, and cheaper, measurably.

`_expand_node` retains `local_retain=beam` candidates **per out-combination**
(`optimizer.py:639-712`) before `_dp_prune` sees them. Every one of the 498 rejected
candidates occupied one of those retained slots and was then discarded by the
validator, so 498 slots per run went to candidates that could not legally exist. After
the change the same slots go to the next-best legal candidates, so the candidate set
reaching `_dp_prune` is a superset of today's legal one.

**On both captures measured, none of those extra candidates wins** — the output is
unchanged. The case for the change is therefore not "it finds a better plan today". It
is that the pool stops containing players the search is not allowed to keep, which is
§2.4's argument, and the cost is negative (−3.34 s).

**What this change is *not*, and FU-35's entry should be corrected on the point:** it is
no longer a soundness fix. FU-35 records the "second-order effect" — an unusable player
dominating and excluding a usable one — as "the real reason to do it". **FU-28 closed
that path**, at `optimizer.py:258`. §4.1's measurement confirms it: no selectable
player's exclusion status changes. What is left is coherence (§2.4), 498 wasted
materialisations, 20 unbuyable players out of a buy-side pool, and −3.6% runtime.

---

## 5 — What happens to FU-28's usable-dominator filter

Once admission is `_validator_usable`, the count-side test at `optimizer.py:258`
(`if not _validator_usable(other): continue`) can never fire: every member of every
bucket satisfies it by construction. It is exactly redundant — the same predicate, one
level down.

**Recommendation: delete it, and move the guarantee into a test at the admission
boundary (§7, T1 and T2).**

The trade-off, stated rather than assumed, because FU-28 §8 explicitly calls the
comment guarding this "load-bearing":

- **Keeping it** costs one branch per bucket member per candidate and leaves FU-28's
  exchange argument true regardless of what admission does later. That is real
  protection against someone relaxing admission again.
- **But it is protection that can never be observed to work.** A guard that cannot
  execute is the same pathology FU-36 was filed for one level up: a test that cannot
  fail. Nobody maintaining `_dominance_pool` after this change can tell whether the
  guard still does anything, because it provably does not, and its own regression test
  (`test_dominance_counts_only_dominators_the_validator_would_accept`) becomes vacuous
  at the same moment — the fixture player it depends on can no longer enter the pool.
  Verified: that test fails under the change, at `tests/test_optimizer.py:794`, with
  *"7 must be admitted to the pool, or FU-35's admission predicate has changed here"*.
- **The comment at `:219-223` cannot survive either way.** Its premise is
  *"Admission — `can_transact and not removed`. Unchanged"*, which this change
  falsifies. So the choice is not "keep the comment or lose the guarantee". It is
  between a **rewritten comment guarding dead code** and **a test guarding live
  behaviour**. This repo has already made that choice once, in FU-19: the CLAUDE.md
  structure block stopped being trusted prose and became
  `tests/test_claude_md_structure.py`. Same argument, same answer.

**What stops the exchange argument silently losing its guarantee when someone later
relaxes admission**: T2 in §7 — an invariant test asserting that no player the
validator would reject is ever admitted to the pool. Relax admission and T2 fails by
construction, naming FU-35 and FU-28 in its message. That is a stronger guard than the
`continue` it replaces, because it fails on the *cause* (a widened admission predicate)
rather than on a downstream symptom that may or may not be reachable from whatever
fixture happens to exist.

**Also required, in the same commit:** replace the "Two predicates, deliberately
different, and they must not be tidied into agreement here" block
(`optimizer.py:215-229`) with a note saying there is now one predicate, why the
direction matters (§2.4), and that T2 is what holds it. And add a marked note to
`fu-28-dominance.md` §8 — the file already uses that convention — recording that
variant (c)'s filter was subsumed by FU-35 and where its guarantee now lives. §8's
reasoning is not wrong and should not be rewritten; it is superseded in one particular.

---

## 6 — FU-34, and the 390 : 1 discard ratio

**The ratio does not change.** Measured, before and after, on the pinned capture:

| | before | after | FU-34 records |
|---|---:|---:|---:|
| `_materialize` calls | 318,954 | 318,954 | 318,954 `apply_transfers` calls |
| retained after `_dp_prune` + `[:beam]` | 816 | 816 | 816 |
| ratio | 390.9 : 1 | **390.9 : 1** | 390 : 1 |

The reason is structural, not incidental: `_expand_node` materialises
`local_retain=beam` per out-combination, and out-combinations come from the 15
holdings, not from the pool. Pool size sets the *width of the scored grid* — hence
`projected_cells` falling 10.6% and the run getting 3.34 s cheaper — but not how many
of those cells are materialised. **FU-34's justification is untouched, and its headline
number needs no restatement.**

What FU-35 does change is one supporting clause, and it changes it in FU-34's favour.
FU-34 records:

> All 335 rejections per default run have one cause: `"<player> is not selectable"`,
> from four pool members that are `can_transact=True, removed=False, can_select=False`
> (FU-35).

Re-measured on the pinned capture, that is **498 rejections from 12 pool members** —
same single cause, larger numbers, because the capture is different (45 unselectable
players, not 42) and the pool is post-FU-28. **After FU-35 it is 0 from 0.**

Consequences for FU-34, which should be written into its entry when it is picked up:

1. **FU-34's "Implementation shape" step is no longer needed.** It requires applying
   selectability *"to the retained tuples, after the per-combination top-k — not inside
   the mask"*, with a careful argument about why filtering earlier would change which
   candidates reach `_dp_prune`. If FU-35 lands first, there is nothing to filter: no
   pool member is unselectable, and `_materialize`'s `return None` becomes a pure
   backstop against causes FU-34 already argues are structurally impossible. That
   removes the most delicate step in FU-34's plan.
2. **FU-34's byte-exactness baseline must be re-taken after FU-35 lands.** Its whole
   claim is that the restructure reproduces today's candidate set exactly. Today's
   candidate set includes 498 candidates that FU-35 removes, so a byte-exactness claim
   made against a pre-FU-35 payload would be measuring the wrong thing.
3. **Order: FU-35 first.** It is one line plus tests, it removes work from FU-34, and
   the reverse order means FU-34 implements and then immediately deletes the
   selectability step. `[gap: the two changes were not measured together. FU-34
   projects ~29 s of saving from a term this change does not touch (materialisation
   count is identical), and this change's 3.34 s comes from a term FU-34 does not touch
   (grid width), so they should compose to ~35 s → ~32 s. That is arithmetic, not a
   measurement, and is not claimed as one.]`

---

## 7 — The regression tests

All in `tests/test_optimizer.py`, synthetic fixtures only, no live API. Existing
helpers to reuse: `_fu28_snapshot(layout)` (`:549`, layout entries
`(id, element_type, club, now_cost, can_select)`), `_fu28_projections`, `_fu28_state`,
`_fu28_m`, `_bucket_snapshot` (`:396`).

**Two existing tests fail under the change and must be dealt with explicitly, not
patched into passing.** Both failures were reproduced on this branch by applying the
one-line change at runtime and running the full suite: `329 passed, 2 failed`.

### T1 (new) — `test_pool_never_admits_a_player_the_validator_would_reject`

The direct statement of §2.4. Build an `_fu28_snapshot` bucket in which an
unselectable player is *cheap and dominant* — the exact shape that gets him admitted
today:

- layout: a held GKP and FWD to make a legal XI, one held DEF to sell, and in one club
  a DEF bucket containing a `can_select=False` player who costs no more than the
  others and projects highest.
- assert he is **not** in `survivors` from `_dominance_pool(snapshot,
  projections_by_event, [2])`.
- **Sizing assertions, per FU-36's standard**, so the test cannot pass vacuously.
  Assert all of: he is `can_transact and not removed` (so the *old* admission predicate
  would have admitted him); he is `not can_select`; his `now_cost` is ≤ that of the
  bucket members he would dominate; his `xp_total` at every event of the horizon is ≥
  theirs. Drop any one and the test proves nothing.
- Message on the main assertion must name FU-35 and say the pool is a **buy-side** set
  whose members will be held.

### T2 (new) — `test_pool_admission_never_widens_past_the_validator`

The invariant the user asked for: **fails if admission and FU-28's count are ever
brought back into disagreement in the wrong direction.**

- Take a snapshot with a mixed population — several unselectable players across
  different `(position, club)` buckets, at least one of whom is dominant and at least
  one of whom is dominated — and assert:

```python
usable = {p.id for p in snapshot.elements if p.can_select and not p.removed}
assert set(survivors) <= usable
```

- **A subset assertion, deliberately, not equality.** Admission narrower than the
  validator is a legality-safe direction (it can only cost optimality); admission wider
  is the defect. Equality would fail spuriously the first time dominance excludes
  anyone — which it does on every realistic fixture — and would also fail if a future
  change narrowed admission for an unrelated reason. The docstring must say this, in
  those terms.
- Message: naming FU-35 and FU-28 §8, and stating the consequence — *"a player the
  validator will reject entered the buy-side pool; FU-28's exchange argument assumes
  every pool member can legally replace another"*.
- Assert also that the fixture actually contains at least one player outside `usable`,
  otherwise the subset check is trivially true.

### T3 — retire `test_dominance_counts_only_dominators_the_validator_would_accept` (`:754`)

Currently fails at `:794` (`assert 7 in survivors`) because player 7 is no longer
admitted. Its own message anticipates this: *"or FU-35's admission predicate has
changed here"*.

**Delete it, in the same commit that deletes the `_validator_usable` call at `:258`,
and only with §5's note added to `fu-28-dominance.md` §8.** Do not keep it alive by
constructing the bucket below the admission line — that would be a test of a branch
that cannot execute in production, which is what §5 rejects. The property it defended
is now defended by T1 and T2 at the boundary where it is actually decidable.

If the reviewer prefers to keep `:258` (§5's rejected option), then T3 stays and must
instead be reworked to call the counting logic with a hand-built bucket that bypasses
admission — and the plan should say so, because a kept-but-unreachable guard with a
vacuous test is the one outcome worse than either alternative.

### T4 — rework `test_generator_children_are_all_accepted_by_apply_transfers` (`:252`)

Currently fails at `:387` — `assert rejections, "the can_select guard was never
exercised…"` — with `assert []`. This is FU-36's sizing check doing its job: the
fixture forces rejections by offering an unselectable player as a **buy** candidate
(`:322-333`), and after FU-35 no such candidate can be offered.

The property under test — *rejects get dropped, not smuggled through* — is still worth
holding. The rejection must now come from the **held** side:

- Deal the unselectable player into the *starting squad* rather than adding him to the
  buy pool. Every candidate that does not sell him still contains him, so
  `validate_squad_structure` rejects it and `_materialize` returns `None`; candidates
  that do sell him pass.
- **This directly contradicts the comment at `:323-327`**, which says a
  `can_select=False` player in the starting squad *"would just make the fixture illegal
  from the outset, testing nothing about the generator"*. That judgement was correct
  while the buy side could produce the rejection; it is not correct once the buy side
  cannot. Replace the comment, do not leave it standing next to code that contradicts
  it, and say why it changed.
- Keep `assert rejections` and add `assert result.paths`, so a fixture that rejects
  *everything* — leaving nothing to check — fails loudly rather than passing vacuously.
- The implementer must **record the observed rejection count** in the commit message.
  `[gap: not verified on this branch that the held-side route produces rejections at
  the fixture's `beam=2, first_moves=5, horizon=2` settings. It follows from
  `_materialize` validating the post-transfer squad (`optimizer.py:510-512`), and k=0
  hold nodes must reject, but it was not run. If it turns out unreachable, convert the
  sizing assertion to an explicit `pytest.xfail` naming the reason — do not delete it.
  FU-36 exists because that assertion was deleted-by-omission once already.]`

### T5 — must keep passing, unchanged

`test_dominance_excludes_only_players_a_survivor_can_always_replace` (`:412`),
`test_dominance_m_is_the_tighter_of_club_limit_and_squad_select` (`:488`),
`test_dominance_never_excludes_against_a_held_dominator` (`:663`),
`test_dominance_survives_a_same_bucket_double_buy` (`:709`), and the whole of the rest
of the suite. Measured: with the change applied and nothing else touched, **329 of 331
pass**; the two failures are T3 and T4 and there are no others.

---

## 8 — Provenance (FU-40)

### 8.1 Captures

Primary, for every figure in §§2, 4.1–4.3, 4.4 (first row), 6 and 7:

```
snapshot  ~/fpl-pinned/gw2-pre-deadline.json   source=pinned (bare file)
          captured 2026-08-28T07:26:38.797492+00:00   616 elements
          sha256 593f60c2e356c4e94205f10248dfd834f4797ad6c736ea73b239da610d84ffcf
fixtures  ~/.fpl-cli/fixtures.json             source=cache
          captured 2026-08-28T13:25:28.384582+00:00
          sha256 fbd4457e5c819f38cb34228453596f8c6eb3ae345bc64a11996682187bdf09a8
```

*[**Model version, added 2026-08-29** under FU-40's extension
(`task/model-versioning`): every figure in this document was produced by
**`component/1.0+banded`**, which is now a registered variant with its constants pinned
by digest in `tests/test_variants.py`. At the time these were measured that string was
a literal that four different models could report, so the citation is completed
retrospectively here rather than claimed to have been complete. The figures themselves
are unaffected — `component/1.0` was registered with exactly the constants in force
when they were taken, and projections were verified byte-identical across that change.]*

`provenance.fixtures.source` reads `cache`, which under FU-40 is the signal that the
fixtures were **not** pinned and may have moved. Here they demonstrably have not: that
sha256 is identical to `~/fpl-pinned/gw2-fixtures.json`, the read-only 08:08Z copy.
The `captured_at` is 13:25Z only because the live run that produced
`gw2-recommendation.json` rewrote the file with the same bytes. Every before/after pair
in this document was additionally run back-to-back against the same file, so no figure
straddles a fixtures change.

Secondary, for §4.4's second row only — the input that produced today's live run:

```
snapshot  ~/.fpl-cli/bootstrap-static.json (copied and pinned)   616 elements
          mtime 2026-08-28T13:25:28Z
          sha256 3aac6dffaa7509f255e60c14eecd3bc002fe0c942d228e54b7983e2fb6511c85
fixtures  as above (unchanged between the two runs)
```

`[gap: this second capture is not archived. It was pinned from
`~/.fpl-cli/bootstrap-static.json`, which `SnapshotService` rewrites on any unpinned
run, so the sha256 above is its only durable identity — the file itself will not
survive the next `fpl sync`. If §4.4's second row is to stay re-checkable, copy that
file into `~/fpl-pinned/` before the next sync. Not done here: writing into
`~/fpl-pinned/` was not part of this task.]`

Capture used for §2.1's cross-capture table: the four bare files under
`~/.fpl-cli/archive/`, listed there by name.

### 8.2 Method

`src/` was not modified on this branch. The "after" runs were produced by a harness in
the session scratchpad that re-executes `_dominance_pool`'s own source with a single
substring replaced, then rebinds the module attribute:

```python
OLD = "if player.can_transact and not player.removed]"
NEW = "if player.can_select and not player.removed]"
src = textwrap.dedent(inspect.getsource(optimizer._dominance_pool))
assert src.count(OLD) == 1
exec(compile(src.replace(OLD, NEW), "<fu35-patched>", "exec"), optimizer.__dict__, ns)
optimizer._dominance_pool = ns["_dominance_pool"]
```

The `assert` is what makes this equivalent to the source change rather than merely
similar: exactly one occurrence, replaced, with the function's globals unchanged. The
CLI was then driven in-process at its own defaults through `fpl_cli.cli.app`, with
`RLIMIT_AS` set to 3 GB, so the measured path is the real command and not a direct call
to `optimise()` — the flaw FU-28 §9 records in its own superseded 90.8 s figure.

Counters (`_dominance_pool`, `_materialize`, `_expand_level`, `project_cost`) were
attached as wrappers in the same harness. **Timings in §4.2 come from runs with the
counters off**; §4.3's counts come from separate instrumented runs. The suite result in
§7 came from the same substitution applied as a pytest plugin.

The harness is in the session scratchpad and will not survive it. The three code blocks
above are enough to rebuild it; nothing else about it is load-bearing.

---

## 9 — Where this contradicts what is already written

| Recorded | Where | Re-measured |
|---|---|---|
| pool 189 → 185 | FU-35 entry | **378 → 358** (189 predates FU-28, which took the pool to ~374) |
| four unselectable pool members | FU-35 entry | **20** in the pool; **12** actually reach `apply_transfers` |
| 335 rejections per run | FU-35 entry, FU-34 entry | **498** |
| 42 of 614 snapshot-wide | FU-35 entry | **45 of 616** (42 of 614 reproduces exactly on the 08-26/08-27 captures) |
| "the false-exclusion path … is the real reason to do it" | FU-35 entry, **Unblocks** | **Closed by FU-28 already.** No selectable player's exclusion status changes (§4.1). The reasons that survive are §2.4, 498 wasted materialisations and −3.34 s |
| "it changes the output" | FU-35 entry | **True but trivial**: one line of the payload, `dominance_exclusions`. The recommendation is unchanged on both captures measured (§4.4) |
| "Also decide which flag is authoritative" | FU-35 entry | Superseded by the entry's own 2026-08-28 re-check, and answered here: `can_select` for the pool, because the pool is a buy-side set of players who will be *held*; `can_transact` keeps its own job at `transfers.py:299` |

FU-35's entry should be updated with these when the change lands, in the same style the
file already uses for corrections.

---

## 10 — What this document does not settle

- `[gap: the composed effect of FU-34 and FU-35 is not measured (§6, item 3). The
  ~32 s figure there is arithmetic on two independent terms and is not claimed as a
  measurement.]`
- `[gap: whether the recommendation ever changes under this fix is unknown beyond the
  two captures measured, where it does not. As with FU-28 §7's equivalent gap, the case
  for the change is §2.4, not an improvement in today's output.]`
- `[gap: `dominance_exclusions` is the one user-visible number that moves, and its
  meaning shifts slightly — it now counts exclusions among selectable players only.
  Nothing in the payload reports pool size, so a future before/after of this kind again
  needs instrumentation to say anything about the pool. Proposed as a follow-up rather
  than bundled here; text in the appendix.]`
- `[gap: `cli.py:312`'s `players list` filter uses `can_select and not removed and
  status == "a"` — a *third*, stricter predicate. Not examined here. It is a display
  filter with no bearing on the search, and folding it in would be a second concern on
  this branch.]`
- `[gap: the 45 are all `status='u'` on every capture available, so `can_select` and
  `status != 'u'` are indistinguishable in this data. If the API ever sets
  `can_select=False` on a player with another status, nothing here would notice. The
  code depends on `can_select`, not on `status`, so this is an observation about the
  evidence, not a defect.]`

---

## Appendix — proposed follow-up, not filed on this branch

Filing it would mean editing `docs/plans/follow-ups.md`, a second concern on a
plan-only branch. Text, ready to lift, as **FU-44** (FU-43 is the highest number in
use, and FU-38 is recorded as never having existed):

> ## FU-44 — `plan optimise --json` reports exclusions but not pool size
>
> **Deferred from:** `task/fu-35-plan` (`fu-35-selectability.md` §10).
>
> The payload carries `dominance_exclusions` but not the size of the pool that
> produced it, so any measurement of a pruning change — FU-28's, FU-35's, and whatever
> comes next — needs a wrapper around `_dominance_pool` to say anything about the pool
> itself. Both of those branches wrote one. `dominance_exclusions` alone is also
> ambiguous: it moved 238 → 213 under FU-35 while the number of *admitted* players
> moved 616 → 571, and the payload cannot distinguish "pruned harder" from "admitted
> fewer".
>
> **Proposal:** add `dominance_pool` (survivor count) and `dominance_admitted`
> alongside `dominance_exclusions`. Three integers already computed inside `optimise`;
> the cost is the payload contract and its test.
>
> **Unblocks:** pool measurements citable straight from `--json` under FU-40, with no
> instrumentation and no risk that the harness measured something other than the
> command.

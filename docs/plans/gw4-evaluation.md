# GW4 — leg 2 of FU-60's pair

**Pre-settle record. Written 2026-09-12, before GW4's first kick-off and before any
result exists.** Nothing in this document is a result. It exists so that the two
things FU-50 requires to be settled *in advance* — the inputs, and whether the
gameweek counts — are on record with a timestamp that precedes the figure they will
be used to read.

The result sections are deliberately absent and are filled in when GW4 settles
(~2026-09-15). [gw3-evaluation.md](gw3-evaluation.md) is the template; FU-60 §1,
§5 and §6.2 fix every reading in advance and are not restated here.

---

## 1 — Pinned inputs, cited per FU-40

Two of the three legs are final and are now pinned. The third cannot exist yet.

| pin | sha256 | state |
|---|---|---|
| `~/fpl-pinned/gw4-pre-deadline.json` | `de9d7d3573b27d28c3d43d8ac0932b290d5f0785903d1e07d031099d8eb49f7e` | **pinned 2026-09-12** |
| `~/fpl-pinned/gw4-fixtures.json` | `85d3ef089f28bc22a1d168204ea9d1982dac6ba0af72fd28379e370fbf3eff23` | **pinned 2026-09-12** |
| `~/fpl-pinned/gw4-live.json` | — | **not yet — GW4 has not settled** |

Both are byte copies of `~/.fpl-cli/archive/2026-09-12/`, and **both hashes match
that capture's own `manifest.json`**, which is the check that makes the pin a pin
rather than a copy.

**The capture is leak-free, and the manifest says so itself.** `captured_at`
2026-09-12T00:03:59.326002+00:00, `role` `canonical`, and `next_event` records
`{id: 4, deadline_time: 2026-09-12T12:30:00+00:00, captured_before_deadline: true}`
— **12h 26m 01s before the deadline**. No team news published after 00:03:59Z can
have reached the projection inputs.

**`select_archived_snapshot` resolves it unprompted**, verified rather than assumed:
for GW4's deadline it returns `~/.fpl-cli/archive/2026-09-12/bootstrap-static.json`,
and the same call at GW3's deadline returns the `2026-09-04` capture — which is the
pin [gw3-evaluation.md](gw3-evaluation.md) cites, so the selection reproduces a known
answer as well as producing the wanted one.

Model digests are not restated here; they are pinned in `tests/test_variants.py` and
quoted in [gw3-evaluation.md](gw3-evaluation.md), and `component/1.2` is frozen
unchanged between the two legs by FU-60 §7.

---

## 2 — GW4 is clean in FU-50 §2's sense

Measured on `gw4-fixtures.json`, the pin above — **not** on the week-old GW3 list,
which is the caveat [gw3-evaluation.md](gw3-evaluation.md) §7 left open.

**10 fixtures. 20 teams. Every team exactly once. No blanks, no doubles.**

| kick-off (UTC) | fixture |
|---|---|
| 2026-09-12 14:00 | AVL v NFO |
| 2026-09-12 14:00 | BOU v BRE |
| 2026-09-12 14:00 | CHE v HUL |
| 2026-09-12 14:00 | CRY v IPS |
| 2026-09-12 14:00 | LIV v FUL |
| 2026-09-12 16:30 | TOT v EVE |
| 2026-09-12 19:00 | SUN v ARS |
| 2026-09-13 13:00 | COV v BHA |
| 2026-09-13 15:30 | MUN v MCI |
| 2026-09-14 19:00 | LEE v NEW |

**There are no unscheduled fixtures anywhere in the payload** — zero entries with
`event: null` across all 38 gameweeks. That is the check that matters for a *double*:
a double arrives when a previously postponed fixture is assigned into a gameweek, and
there is currently nothing in the pool to assign.

GW4 therefore counts, and it was established that it counts before it was played.

**Settle expected ~2026-09-15.** The last fixture kicks off 2026-09-14T19:00Z. At
capture time GW3 reads `finished: true, data_checked: true` and GW4 reads
`false, false`.

---

## 3 — Population

656 players in the pinned bootstrap. For continuity with the same figure elsewhere:
GW2 projected 616 and GW3 projected 652 against 654 live. The population has grown at
every evaluation, so **no absolute figure will be like-for-like with its GW3
counterpart** — the same limitation [gw3-evaluation.md](gw3-evaluation.md) §8 records.
FU-60 §1's criterion is a within-gameweek pairwise comparison and is unaffected.

---

## 4 — What to run when it settles

Unchanged from [handoff-2026-09-12.md](handoff-2026-09-12.md) §1, with step 1 now
two-thirds done:

1. Pin `gw4-live.json` — the settled GW4 event-live payload — and record its sha256
   above. Confirm `finished: true` **and** `data_checked: true` before scoring
   (FU-43, FU-49).
2. Re-confirm §2 against the settled payload. See the gap below: this section
   establishes the list was clean before kick-off, which is the half that has to
   precede the result; it cannot rule out a postponement during the gameweek.
3. `fpl plan evaluate --event 4`, then `tools/calibration_report.py` and
   `tools/distribution_check.py` for the same event.
4. Report against FU-60 §1 and §6.2 **as written**, and against FU-50 §4's control
   clause. Do not re-read either against the figure — FU-60 §8, FU-50 §5.

---

## 5 — Gaps

`[gap: §2 is measured on a pre-deadline capture, so it establishes that GW4's list
was clean before the gameweek was played — not that it stayed clean. A fixture
postponed mid-gameweek would turn two teams' GW4 into a blank retroactively, and
nothing here can see that. The value of recording it now is that the cleanliness
judgement cannot later be made selectively against a visible result; the
re-confirmation at step 2 is still required.]`

`[gap: no result, no digest of the live payload, and therefore nothing in this
document is citable as a measurement. It is a record of inputs and preconditions
only.]`

# GW5 — the control clause, and a reversal

**Result. No model changed, no constant touched, no criterion re-read.**

**GW5 is not a leg of FU-60's pair.** The pair was GW3 and GW4, it completed on
2026-09-19, and its verdict is fixed. Nothing in this document revisits it, and §4
below says explicitly what GW5 can and cannot be used for. The pre-registered rule
this gameweek *does* settle is **FU-50 §4**, the control clause.

---

## 1 — Pinned inputs, cited per FU-40

| pin | sha256 |
|---|---|
| `~/fpl-pinned/gw5-pre-deadline.json` | `52d5c54e9304a3a13a79cdb84a656beaff30298d28f3b0997083f0c8d987d67c` |
| `~/fpl-pinned/gw5-fixtures.json` | `34c4a8f38ac8cd0d3293ce642237478e8d5c89793a24cc4e068d181f85e8cfab` |
| `~/fpl-pinned/gw5-live.json` | `c02280fc938f5f7d80056f5cef0272bc5c5c021db4199a2226e881b7e249bb86` |

First two are byte copies of `~/.fpl-cli/archive/2026-09-18/`, hashes matching that
capture's own manifest. `captured_at` 2026-09-18T00:01:59Z, canonical,
`captured_before_deadline: true` against a 17:30Z deadline — **17h28m of clearance**.
Live payload `finished: true, data_checked: true`.

**GW5 is clean**, and this is now a post-settle confirmation rather than the
after-kick-off check the 2026-09-19 handoff flagged as weaker: ten fixtures, twenty
teams, all finished, **fixture set identical to the pre-deadline pin**. No
postponement. That gap is closed.

Population 659 projected, 301 played, 220 started. `a = 4`.

---

## 2 — FU-50 §4: the component family clears its control

**§4: if the best component variant fails to beat `naive/1.0` on `spearman_played`
across two clean gameweeks, `naive/1.0` becomes the default.**

| | best component variant | `naive/1.0` | clears? |
|---|---|---|---|
| GW2 | `component/1.1-price` 0.359 | 0.330 | yes, +0.029 |
| GW3 | `component/1.2` 0.348 | 0.229 | yes, +0.119 |
| GW4 | `component/1.2` 0.329666 | 0.342232 | **no, −0.012567** |
| **GW5** | **`component/1.2-availability` 0.414502** | **0.336305** | **yes, +0.078196** |

**The clause does not fire.** One failure in four, and it is not the most recent.
The component family survives, by its widest margin yet.

`official-ep/1.0`, which topped GW4, falls to 0.380525 — behind both `1.1-price` and
`1.2-availability`.

---

## 3 — The reversal: `component/1.2` lost, and lost heavily

| variant | `spearman_played` | `spearman_all` |
|---|---|---|
| baseline/flat-ppg | 0.331694 | 0.654299 |
| naive/1.0 | 0.336305 | 0.726431 |
| **component/1.2-availability** | **0.414502** | 0.684139 |
| component/1.1-price | 0.414226 | 0.699608 |
| component/1.2 | 0.381725 | 0.683752 |
| official-ep/1.0 | 0.380525 | 0.740813 |

**`component/1.2` finished −0.032501 behind `component/1.1-price`** — the variant it
was promoted over. For scale, its *winning* margin at GW4 was +0.000517. **The GW5
reversal is 63 times larger than the GW4 win, in the opposite direction.**

### The decomposition is the finding

| | S6(a) = 1.2 − 1.2-avail | S1–S5 = 1.2-avail − 1.1-price |
|---|---|---|
| GW3 | **+0.029** | +0.003 |
| GW4 | +0.0065 | −0.006 |
| **GW5** | **−0.032776** | +0.000275 |

Two things, and the second is the more important:

**S1–S5 has never done anything measurable.** +0.003, −0.006, +0.0003 across three
gameweeks. It is indistinguishable from zero and has been since it was built.
minutes-model.md §9 predicted exactly this in advance — *"The claim made here is that
they fix category errors … not that they will move Spearman. They may not."*

**S6(a) is not a small positive effect; it is a large and unstable one.** +0.029,
+0.0065, −0.033. Its mean over three gameweeks is roughly zero and its spread dwarfs
every margin any decision here has turned on. **`component/1.2`'s entire measured
advantage over `component/1.1-price` was S6(a), and S6(a) now looks like noise.**

`component/1.2-availability` — which is 1.2 *without* S6(a) — is the best variant in
this gameweek, and sits 0.000276 from `component/1.1-price`, i.e. identical. That is
S1–S5 being nothing, measured a third time.

---

## 4 — What GW5 may and may not be used for

**It may not be used to revisit FU-60's verdict.** The criterion was fixed on
2026-09-02, the pair was GW3 and GW4, both legs were won, and §8 forbids re-reading a
criterion against a later figure. *Declining* to promote because a subsequent
gameweek looks bad is the same error as promoting on a figure the rule did not
license — the result choosing the rule, with the sign flipped. **FU-60 says promote,
and FU-60 is not wrong about what it says.**

**It may be used as evidence for a new decision, which needs its own
pre-registration.** FU-60 §6.2 already fixed the shape: *"any later attempt requires
a fresh pre-registration naming its gameweeks before they are settled."* That clause
was written for a failed leg, and it applies with equal force here.

**What this changes in practice.** The promotion is prepared on
`task/promote-component-1.2` and **not merged**. Merging it is no longer a
book-keeping step — it installs as default a variant that has now been beaten by its
predecessor on the most recent settled gameweek, by 63 times the margin it won on.
That is a judgement for Ben, and this document deliberately does not make it. Both
available positions are defensible and both must be taken deliberately:

- **Honour FU-60 and promote**, then pre-register a revert test naming GW6 and GW7
  before they settle. This keeps the rule's authority intact, which is the thing that
  makes every other figure in this repo trustworthy.
- **Hold the promotion** and pre-register a three-way test instead. This is the
  better decision on the evidence and the worse one for the discipline, and choosing
  it means saying plainly that the rule was outrun by data it did not anticipate —
  which is a legitimate thing to say, once, in writing, with the reason.

**`component/1.2-availability` still cannot be promoted under any existing entry.**
FU-60 §6.2: it *"has no criterion of its own and cannot become default under this
entry"*. It has now been best or joint-best twice. That is an argument for writing it
a pre-registration, not for skipping one.

---

## 5 — Diagnostics (not criteria)

`tools/minutes_diagnostics.py`:

| variant | Brier | log loss | Σ `p_start` | actual starters |
|---|---|---|---|---|
| component/1.1-price | 0.1092 | **0.3481** | 248.6 | 220 |
| component/1.2 | **0.1080** | 0.4344 | 191.6 | 220 |
| component/1.2-availability | 0.1136 | 0.4566 | 248.7 | 220 |

**FU-60 §5's disagreement signature is back**: 1.2 wins Brier and loses log loss,
which §5 reads as better aggregate calibration with confident errors concentrated on
a subgroup.

**The tracked FU-57 residual: −0.0238 → +0.0848 → +0.0452 → −0.0863.** It has now
been negative twice and positive twice, and the GW5 value is the largest in
magnitude. Recorded as §5 requires; it is a measurement and not a gate.

**FU-57's suppression count has gone.** At `a = 4`, 144 players have `starts = 4` and
1.2 rates just **4** of them ≤ 0.5 (1 started), against 59 at GW3. FU-60 §4's
recession is complete. **But S6(a) is doing more damage than ever** — so whatever is
now wrong with the ownership prior is not the thing FU-57 described, and FU-57 can no
longer be treated as the explanation for S6(a)'s behaviour.

**FU-63's "stable" scale bias is not stable.** Against the post-rule norm: −7.5%
(GW3), −8.0% (GW4), **+4.9%** (GW5). It has changed sign. GW5 was an unusually
high-scoring week — realised +30.4% against the post-rule norm — so part of this is
the gameweek, not the model. Against realised, 1.2 is −19.6%.

---

## 6 — Gaps

`[gap: GW5 is one gameweek and so is GW4. A −0.033 reversal following a +0.0005 win
is not proof that the GW3 win was noise; it is a third reading of a quantity with no
error bar, and three readings whose spread exceeds their mean is exactly the pattern
that means "we cannot yet tell", not "we now know it is zero".]`

`[gap: GW5 scored +30.4% against the post-rule norm — a high-scoring week. No check
was made of whether high-scoring gameweeks systematically favour models that predict
higher totals, which `component/1.1-price` does (+25.2% against the norm) and
`component/1.2` does not (+4.9%). If they do, part of GW5's ordering is an artefact
of the week rather than of the models, and the same mechanism would have penalised
1.1-price in a low-scoring week. This is checkable across the four settled gameweeks
and was not done.]`

`[gap: the S6(a) figures are differences between two variants scored on one capture,
so they are paired and the pairing removes some noise — but nothing here quantifies
how much remains. "Its spread dwarfs every margin" is an observation about three
numbers, not a variance estimate.]`

`[gap: this document scores five registered variants on a gameweek nobody
pre-registered anything about. That is legitimate for a measurement and would not be
for a decision, and §4 is the whole of what keeps those apart. A reader who takes
§3's table as licence to pick a default has misread it.]`

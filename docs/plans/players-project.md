# `fpl players project` — per-player xP, ranked

**Status:** implemented, `task/fu-44-project`, 2026-08-29.
**Purpose:** a diagnostic. The projections are unvalidated (README, Known
limitations), and the fastest available check on them is whether a human who
watches football recognises the names at the top. This command exists to make
that check cheap, not to recommend transfers — `plan optimise` does that.

**On the entry number.** The task naming this work called it FU-44. There is no
FU-44 in [follow-ups.md](follow-ups.md): the highest filed entry is FU-43, and
**FU-44 is already reserved** — [fu-35-selectability.md](fu-35-selectability.md)
§Appendix holds ready-to-lift text for it, on a different subject (`plan optimise
--json` reporting pool size alongside `dominance_exclusions`). That file states
the reservation explicitly, and the header of `follow-ups.md` forbids shifting
numbering. So this document does not claim a number. Nothing filed here is
deferred work in the first place — it is work done — and the two things this
branch *does* defer are filed as **FU-45** and **FU-46**.

---

## 1 — Established before building

Three questions the task asked to be settled first. All three were answered by
reading `domain/projections.py`, not by assumption.

### 1.1 `p_start` is already on the `Projection` shape — nothing to widen

`Projection.p_start` exists (`projections.py:200`) and is populated by all three
models. The cost of surfacing it is zero: no new field, no change to the
dataclass, no change to any model. The task's contingency ("say what surfacing it
costs before doing it") does not arise.

**But it does not mean the same thing in all three models**, and that is the real
finding:

| Model | What `p_start` holds | Start% column |
|---|---|---|
| `component` | The minutes model's actual `p_start` = `availability × shrunk_start_rate` (`projections.py:88`) | Meaningful |
| `naive` | `_availability(player)` — the availability scalar, **not** a start rate | Misleading if unlabelled |
| `official-ep` | Hardcoded `0.0`; its own `assumptions` tuple says *"p_start and xmins are not modelled"* | Meaningless |

Rendering `0.0%` for every row under `--model official-ep` would be a fabricated
number presented as a measurement. The column therefore renders `—` for
`official-ep`, and the table footer says what the column holds under whichever
model is in use. The decision is keyed off the `--model` string in `cli.py`
rather than sniffed from the model object, because `Projection` has no way to
say "this field is not modelled" — see **FU-45**.

`p_start` is also **event-independent**: `ComponentProjection.project` computes
the minutes probabilities once per player, outside the event loop
(`projections.py:270`), so every event's `Projection` carries the same value.
Start% is one number per player, and no aggregation question arises. It is *not*
zeroed by a blank gameweek — a player whose team does not play still reports the
start rate they would have had.

### 1.2 The columns show xP **per gameweek**, not per fixture

`_project_one` accumulates the eight components over every leg the player's team
has in that event (`projections.py:284-300`), so `Projection.xp_total` is the
whole gameweek's expected points. In a double gameweek it is the sum of both
fixtures; in a blank it is exactly `0.0`, since the loop does not execute and
`fixtures = 0` yields all-zero components rather than a silent single-fixture
assumption.

So:

- **Next GW** is `xp_total` at the first event of the horizon — per gameweek.
- **Next 5** is the arithmetic **mean of `xp_total` across the horizon's
  events** — a per-gameweek mean, not a per-fixture one. A double gameweek
  raises it; a blank drags it toward zero.
- The bracketed count is the **total fixtures across the whole horizon**
  (`sum(p.fixtures)`), not a per-gameweek figure. Over a horizon of 5 a normal
  player reads `(5)`; `(4)` is a blank somewhere and `(6)` a double. This is
  the number that says what the mean means, which is why the task required it
  visible.

### 1.3 Unavailable players are excluded by default — recommended and implemented

**Recommendation: exclude, on `can_select and not removed`, with a flag to
include and a count printed so nothing vanishes silently.**

The predicate is the one FU-35 and FU-28 settled on for the optimiser's own pool
(`_validator_usable` = `can_select and not removed`), and the reasoning carries
over unchanged: a player the validator will not accept cannot be bought, so in a
ranking meant for transfer thinking they are noise. Sell-only players are a
different question that `squad validate` already answers.

**Deliberately *not* `players list`'s predicate.** That command filters on
`can_select and not removed and status == "a"` (`cli.py:312`) — a third, stricter
form, noted as unexamined in fu-35-selectability.md §10. Adopting it here would
drop every `status="d"` doubtful player, and a doubtful premium is precisely the
row a human sense-checking the minutes model most wants to see: it is where
availability, `chance_of_playing_next_round` and the start rate visibly interact.
Doubtful players stay in.

**Why a flag rather than a silent filter.** Post-FU-11 an unavailable player has
`availability = 0`, hence `p_start = 0`, hence every term gated to zero, so they
sink to the bottom of a descending sort and would rarely reach the top 30 anyway.
That is an argument that the filter changes little, not that it should be
invisible — and it fails under `--model official-ep`, which never consults
availability at all and will happily rank an injured player on a stale `ep_next`.
A diagnostic that hides rows is worse than one that says how many it hid, so the
count is always printed and `--include-unavailable` always available.

---

## 2 — The sort order: implemented as specified, but the mean is the better default

**Implemented: next-gameweek xP, descending**, as the task specifies. The
argument that it is the wrong default is recorded here rather than acted on,
because the choice is the task-setter's.

**The case for sorting on the 5-gameweek mean instead:**

1. **It disagrees with the tool it exists to sense-check.** `plan optimise`
   defaults to `--horizon 5` and ranks on a decayed multi-gameweek total
   (`decay = 0.84`), not on the next gameweek. A diagnostic sorted by a
   different objective than the optimiser's answers a different question — a
   captaincy pick, not a transfer.
2. **One gameweek is where fixture noise is largest.** A single easy fixture
   floats a mediocre player above a better one; the mean over five is much
   closer to what the search actually optimises, and much closer to what a
   human would call "is this player good".
3. **A blank gameweek breaks it outright.** A player whose team blanks at the
   first event of the horizon projects exactly `0.0` there and sorts to the
   bottom of the table, however good they are over the other four gameweeks —
   which is the single most misleading thing this command could do, since the
   fixture-count column would be sitting right there explaining why. This is
   not hypothetical for the general case, though it is not reachable in the
   data available today (§4).

**The case for next gameweek**, which is not nothing: it matches the decision
actually in front of the user at a deadline, and the transfer being contemplated
plays its first match next gameweek.

**If this is changed, change only the sort key** — both columns are already
displayed, so the table needs no other edit. A `--sort` option was considered and
rejected as premature: the right response to "the default is wrong" is a better
default, not a flag that makes every reader choose.

---

## 3 — Shape

**`cli.py`** — `fpl players project`, on `players_app` beside `list`. Reuses
`_build_model`, `_projections_by_event`, `_next_open_event`, `resolve_snapshot_path`
and `snapshot_service` unchanged; adds no helper the other commands could have
wanted. Horizon clamping to the last scheduled gameweek mirrors `plan optimise`
verbatim.

An unrecognised `--position` raises `typer.BadParameter` naming the value and the
four valid ones. This follows `--position` on `players list` rather than
`--club` on it, which is FU-17's open silent-empty-result defect; the new command
must not add a third instance of it.

`--model official-ep` is refused above `--horizon 1`, and refused when the
planning event is not the snapshot's own next event, because
`OfficialEpProjection.project` raises `ValueError` for any other event
(`projections.py:383-387`). The guard is `_alt_models`' guard, stated as an error
rather than a silent skip since here the user asked for that model by name.

**`presentation.py`** — one renderer, `projection_table`, plus a
`ProjectionRow` dataclass carrying the four already-formatted values. Same shape
as `PathRow`: the CLI decides what a row says, presentation decides how it looks.
The file goes from 393 to ~440 lines, still under FU-18's 600-line split
threshold.

**No `--json`.** FU-13 scopes machine-readable output to `plan evaluate` and
`plan simulate`, and explicitly argues against it on `players list` — *"a script
wanting player data has the snapshot cache and the capture directory, both
already JSON on disk and both richer than any table"*. That argument applies to
this command with one difference worth recording: the xP values here are **not**
on disk in any form, so a future consumer would have something real to want. Not
now, and not on this branch.

---

## 4 — Verification, and what could not be verified

Verified against `~/fpl-pinned/gw2-pre-deadline.json` at horizon 5 (GW2–GW6).

`[gap: the fixture-count column cannot be exercised against real data. Every one
of the 20 clubs plays exactly once in each of GW2–GW6 in the cached fixtures
list, and no fixture has a null event, so every real row reads (5). The blank and
double cases are covered only by constructed fixtures in
tests/test_players_project.py. This is a property of the fixture list this early
in the season, not of the command — but it does mean the real run cannot
distinguish a correct total from one that hardcodes the horizon.]`

`[gap: Start% is displayed but nothing checks it against realised starts. It is
the dominant source of uncertainty in these projections and it is exactly as
unvalidated as everything else on the table; the column makes the model legible,
not correct.]`

The header is "Start%" and not "confidence" deliberately. It is a modelled
probability that a player starts, carrying no interval and no calibration; a
column called confidence would imply a statistical statement the number cannot
support.

---

## 5 — Follow-ups filed

- **FU-45** — `Projection` cannot say which of its fields a model does not
  model. Consumers special-case by model name; this branch does it for Start%.
- **FU-46** — the fixture-count total is displayed but never checked against
  real blank or double data, for want of any in the current fixture list.

# FPL CLI

**Last updated: 2026-08-30.**

A local, read-only Fantasy Premier League planning tool. It talks to the official
(undocumented) FPL API, holds no credentials and submits nothing — it cannot
change your team. It projects points per player per gameweek from an
eight-component model, and searches transfer plans over a horizon of gameweeks to
rank the paths that follow from them.

## What this is, and what it isn't

It produces a recommendation together with the reasoning that led to it: the
paths considered, the per-gameweek numbers behind each, the hits paid, and
whether other projection models agree with the ranking. That last part matters
more than the recommendation. `fpl plan optimise` prints a robustness line
grading the winning move ROBUST, MARGINAL or UNSTABLE by how many of three
projection models rank it first, and names where the dissenters placed it. On the
run pasted below it says UNSTABLE — one model of three, the other two ranking that
move 18th and 16th. That is the tool working, not failing.

It is not an autopilot, and the projections underneath it have never been
validated against realised points. The search is exact about what it is given;
what it is given is a model whose every constant was chosen by hand rather than
fitted to data. Optimising precisely over an unvalidated objective produces a
precise answer to the wrong question, which is why the run prints an UNVALIDATED
banner above every result and why [Known limitations](#known-limitations) is near
the top of this file rather than the bottom.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

fpl sync
fpl plan optimise squad.json
```

`fpl sync` fetches `bootstrap-static` and `fixtures`, refreshes the caches, and
writes a dated capture to `~/.fpl-cli/archive/`. `fpl plan optimise` takes a
squad ledger — `fpl squad create` writes one — and searches from the next open
deadline.

Below is the middle of one real run, pinned to a capture so it can be re-measured:

```
$ fpl plan optimise squad.json --snapshot ~/.fpl-cli/archive/2026-08-28/

! UNVALIDATED — component/1.0+banded has never been scored against realised points.
  Run `fpl plan evaluate --event 1` before trusting the magnitudes below.
! GW2–GW6 allow up to 20 transfers under the rules; this search considers ≤2 per gameweek (FU-29,
--schedule).
MARGINAL — GW2: Gabriel→De Cuyper + E.Le Fée→Alcaraz (−4)
  break-even +4.0 · gross +100.0 · net +96.0 over GW2–GW6
  robustness: UNSTABLE — 1 of 3 models rank this first (naive ranks it 18th; baseline/flat-ppg ranks
it 16th)

                                               Paths
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━┳━━━━━━━┳━━━━━━━┓
┃   ┃ Path                                      ┃  GW2 ┃  GW3 ┃  GW4 ┃  GW5 ┃  GW6 ┃   Net ┃ Score ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━╇━━━━━━━╇━━━━━━━┩
│ 1 │ Gabriel→De Cuyper + E.Le Fée→Alcaraz (−4) │ 56.5 │ 63.9 │ 65.5 │ 64.3 │ 68.0 │ +96.0 │ 65.49 │
│   │ · Tzolis→Hinshelwood · Igor Jesus→Nketiah │      │      │      │      │      │       │       │
│   │ · Calafiori→Ajayi · Palmer→Rogers‡        │      │      │      │      │      │       │       │
│ 2 │ Calafiori→De Cuyper + E.Le Fée→Alcaraz    │ 56.5 │ 63.9 │ 65.5 │ 64.3 │ 68.0 │ +96.0 │ 65.49 │
│   │ (−4) · Tzolis→Hinshelwood · Igor          │      │      │      │      │      │       │       │
│   │ Jesus→Nketiah · Gabriel→Ajayi ·           │      │      │      │      │      │       │       │
│   │ Palmer→Rogers‡                            │      │      │      │      │      │       │       │
│ 3 │ Gabriel→De Cuyper + Tzolis→Alcaraz (−4) · │ 56.5 │ 63.9 │ 65.5 │ 64.3 │ 68.0 │ +96.0 │ 65.49 │
│   │ E.Le Fée→Hinshelwood · Igor Jesus→Nketiah │      │      │      │      │      │       │       │
│   │ · Calafiori→Ajayi · Palmer→Rogers‡        │      │      │      │      │      │       │       │
│   │ HOLD (no transfers)                       │ 43.9 │ 44.5 │ 41.7 │ 45.3 │ 42.7 │  +0.0 │  3.73 │
└───┴───────────────────────────────────────────┴──────┴──────┴──────┴──────┴──────┴───────┴───────┘
  Net = projected points vs holding, after hits.  Score = decayed (0.84), the sort key.
  ‡ horizon-edge decision — see optimizer-ux.md §5.3.

  Path 1's remaining +26.6 comes from GW3 Tzolis→Hinshelwood (free). See --explain.
```

**Illustrative only.** Run on 2026-08-28 against the capture
`~/.fpl-cli/archive/2026-08-28/` (`captured_at` 09:01:35Z), with the header and
provenance lines trimmed. Pasted output is not checked by anything and will drift
from what the code prints — the same failure mode that produced FU-15 (this file
went stale across four merges) and FU-19 (`CLAUDE.md`'s module list went stale
twice). Treat every block here as a description, not a specification, and trust
`--help` and the source over both.

## Commands

Eight commands. Detail lives in `--help`, which is generated from the code; this
table is hand-maintained and nothing checks it.

| Command | What it does |
|---|---|
| `fpl sync` | Fetch and cache `bootstrap-static` and `fixtures`, and write a dated capture. |
| `fpl players list` | List and filter players from the latest available snapshot. |
| `fpl players project` | Rank players by projected points over a horizon. A diagnostic on the model, not a recommendation. |
| `fpl squad create` | Interactively build a 15-player squad and write it as a transfer ledger. |
| `fpl squad validate` | Validate a squad plan or ledger against the rules in the current snapshot. |
| `fpl plan simulate` | Apply a transfers plan to a ledger gameweek by gameweek, with hits and selling prices. |
| `fpl plan optimise` | Search transfer paths over a horizon and rank them. `optimize` is a hidden alias. |
| `fpl plan evaluate` | Score the projection models against a finished gameweek's actual points. |

Every command that reads a snapshot takes `--snapshot PATH` (or reads
`$FPL_SNAPSHOT`; the flag wins) to pin the run to a capture.

`fpl players show`, `fpl squad show` and `fpl squad import`/`export` are named in
the Agent Plan below and do not exist (FU-14).

## How it works

### Projections

`ComponentProjection` decomposes expected points into eight independently
testable terms — appearance, attack, clean sheet, goals conceded, saves,
defensive contribution, bonus and cards — each priced from
`game_config.scoring` in the live snapshot rather than from a hardcoded scoring
table, and summed over every fixture a player's team has in that gameweek
(`domain/projections.py`). Everything multiplies through expected minutes, so the
minutes model dominates the error: availability maps `status` and
`chance_of_playing_next_round` to a scalar, a shrunk start rate collapses to a
positional prior early in the season and converges on realised behaviour by
around GW6, and clean-sheet points are gated on `p60` rather than on appearance
probability, because getting that wrong over-rates rotation-risk defenders
silently. The fixture-strength seam
(`domain/strength.py`) deliberately returns `MatchRates(xg_for, xg_against)`
rather than a scalar difficulty multiplier, because a scalar cannot express a
clean sheet — P(CS) is `exp(-xg_against)`, and squashing the pair into one number
would force any better team model to rewrite the clean-sheet, conceded and saves
terms rather than slot in beside `BandedTeamRates`. That class is the v2
injection point. See [docs/plans/projections-v1.md](docs/plans/projections-v1.md)
Decisions 1, 4 and 5.

### The optimiser

Beam search over an exactly-pruned candidate set, with the root gameweek
enumerated exhaustively, up to two transfers enumerated at every beam level, and
a dynamic-programming dominance test folded into the beam
(`domain/optimizer.py`). The Agent Plan below asked for beam search or
state-pruned DP, which is not evidence of anything — it was written before this
code existed — so MILP was argued properly first, since the reference
implementation this project borrows its 0.84 decay from solves FPL that way. It
was rejected on three properties of *this* objective, not on any general claim
about MILP: the inner argmax has a closed form, since the optimal XI
for a formation is a per-position prefix of an xP-sorted list, so eight formations
and four prefix sums replace what MILP would encode as `y`/`c` binaries at every
player-event and hand to branch-and-bound; the output specification needs the XI
and captain of paths that are *not* the optimum, which a search computes as a
by-product and a solver would need one solve each to produce; and the
free-transfer recurrence and hit arithmetic already exist in
`domain/transfers.py`, so a MILP would re-encode both — including the two
constants under [Season checks](#season-checks) that nothing can verify — where a
search calls `apply_transfers` verbatim and satisfies CLAUDE.md's validator
guarantee structurally. That decision has a recorded reopening condition: k ≤ 3 at
every level is measured as the point where it flips.
[optimizer-search.md §4](docs/plans/optimizer-search.md).

### Dominance pruning

The search drops a player from the candidate pool when a same-position,
same-club rival costs no more and projects at least as many points in every
gameweek of the horizon. That rule was claimed exact, and it was not: excluding on
the *first* dominator found is unsound whenever the optimal squad wants the
excluded player *and* all of its dominators at once, which happens both on a
same-bucket double-buy and — the shape nobody had noticed — on a single transfer
whose only dominator is already in the squad. The error is unbounded, not merely
present: the pruning never compares the discarded player against any
non-dominator, so nothing floors the gap, and varying only the xP values in a
fixed reproduction moved it from 1.0 to 98.0 points. It was found by attempting
to prove the guarantee rather than by a failing test — the property test that
existed asserted a k = 1 exactness that holds only in the bucket-in-isolation
setting it constructed — then characterised with a minimised seven-player
counterexample, and fixed exactly for every k by excluding only once
`m = min(squad_team_limit, position.squad_select)` selectable dominators exist,
`m` being the most a legal squad can hold from one bucket. On the live snapshot
the pool went 189 → 374 and exclusions 425 → 240, for an unchanged best score of
70.066. [fu-28-dominance.md](docs/plans/fu-28-dominance.md).

### Captures and provenance

A projection is a function of the snapshot it was computed from, so a figure
quoted without naming its inputs cannot be re-measured — and fixtures feed
opponent and venue into every projected cell, which means a `plan evaluate` run
against a rewritten `fixtures.json` is not measuring what it reports. `fpl sync`
therefore writes a **capture**: a directory under `~/.fpl-cli/archive/` holding
`bootstrap-static.json`, `fixtures.json` and a `manifest.json` recording the
capture instant, the gameweek current at the time, and a sha256 per file, checked
before use. `--snapshot` pins a run to one, never fetching and never writing the
cache, and `plan optimise --json` — the only command with a payload — reports the
provenance of both files so a quoted number names what produced it (FU-40, and
FU-13 for the command that most needs this and has none). The first capture of a
UK date claims that day's
**canonical** slot if it is empty; later ones the same day are filed as **ad-hoc**
under a timestamped directory and stay pinnable, but automatic selection considers
canonical captures only — which is why `fpl sync --archive-dir` exists, so a
verification run does not spend the day's canonical slot. A capture is never
deleted or overwritten; one that cannot be read is renamed aside and reported.
`storage/capture.py`, and
[snapshot-pinning.md](docs/plans/snapshot-pinning.md) §5 for what a pinned run
still does not pin.

## Known limitations

- **The projections have never been validated against realised points.** This is
  the limitation the others are downstream of. Everything the optimiser prints is
  conditional on a model that has not been shown to beat a flat baseline.
- **Every constant in the minutes model was chosen, not fitted.** Seven settings
  — the shrinkage constant, the start priors (one per position), minutes per
  start, substitute appearance probability, minutes per substitute, the
  doubtful-status chance and the bonus shrinkage window — carry an explicit
  `[assumption: no empirical basis for any constant in this block]` above them in
  `domain/projections.py`. The fixture band multipliers and the league mean goal
  rate in `domain/strength.py` are flagged the same way. All are constructor
  arguments rather than baked-in behaviour, so they are falsifiable once there is
  data to falsify them against; none has been.
- **The one measurement that exists is not evidence.** At GW1,
  `ComponentProjection` scores Spearman **0.707** against the baseline's 1.000 and
  RMSE 2.938 against its 0.000 (pinned to `~/.fpl-cli/archive/2026-08-28/`,
  measured 2026-08-28). The baseline wins because it leaks: `points_per_game`
  after one played gameweek *is* that gameweek's score, so a perfect 0.000 RMSE is
  the leak being visible rather than a good model. Nothing was archived before
  GW1's deadline, so GW1 can only ever be evaluated this way. The number also
  moves with the snapshot it is computed from — the same command against the live
  cache the same day gives 0.700 — which is a second reason not to read anything
  into it. The first honest run is the first gameweek whose deadline post-dates a
  capture.
- **At this stage of the season the model ranks largely on start probability.**
  This is the most useful thing to know about the output, and it is sharper than
  "unvalidated". Until FU-47 the per-90 rates were consumed exactly as the API
  publishes them, so a single strong match produced ratings like 1.72 xG90 from
  77 minutes, or 270 defensive actions per 90 from **one minute**. Those are now
  shrunk toward a prior pooled from the snapshot — and the measured consequence
  is that the table gets *less* discriminating, not more: goalkeepers in the top
  30 rise from 1 to 8, because once single-match noise is removed the component
  model has very little left with which to separate outfielders, and keepers
  have the highest start probability of anyone. The noise was doing the work of
  discrimination and was never measuring player quality. Read a projection this
  early as "is this player likely to play", not "is this player good".
  `docs/plans/rate-shrinkage.md` §5.3 and §9.
- **The search considers at most two transfers per gameweek.** The rules allow far
  more — 20 in the run above, taken from the snapshot's `transfers_cap` — and the
  run says so per gameweek rather than leaving it implicit. Three or more at every
  level is measured at roughly 201× the scored candidates, which is why
  `--schedule` (a per-gameweek transfer count fixed by the user, searched by
  complete enumeration) is specified and unimplemented. FU-29.
- **No chips.** Wildcard, free hit, bench boost and triple captain are unmodelled;
  the ledger schema reserves a `chips_played` field that nothing reads. FU-5.
- **No price-change model.** A player bought and sold inside the horizon is
  assumed to sell for what it cost.

## Season checks

### Rules that are hardcoded, and need checking each season

Squad size, position quotas, budget, club limits and deadlines are all derived
from `bootstrap-static` at runtime, so a mid-season rule change is picked up by
`fpl sync`. **Two transfer rules are not, because the API never publishes them:**

| Constant | Value | Status | Source |
|---|---|---|---|
| Points deducted per extra transfer | `4` | Confirmed correct for 2026/27 | `domain/transfers.py` — `points_per_extra_transfer` |
| Free transfers accrued per gameweek | `1` | Inferred, never stated by the API | `domain/transfers.py` — `free_transfers_per_event` |

Neither appears in `game_settings` or `game_config.scoring`. The hit cost is a
known-correct value that simply cannot be re-derived; the free-transfer base was
reasoned from the field name `max_extra_free_transfers` ("extra" relative to an
unstated base), so it is the weaker of the two.

Both are load-bearing for `fpl plan simulate` and `fpl plan optimise`, since every
points-hit calculation and every net-gain figure depends on them. If FPL changes
either rule between seasons, the output goes wrong **silently**: nothing in the
app can detect the drift, because there is no API field to compare against.

**Check both at the start of each season** against the official rules page, and
update `domain/transfers.py` if they have moved.

## Architecture

All paths under `src/fpl_cli/`:

| Module | |
|---|---|
| `cli.py` | Typer commands, snapshot loading, provenance blocks and `--json` payloads. |
| `transport.py` | HTTPX client, timeouts, retries and the 429 policy below. |
| `builder.py` | The interactive squad builder behind `fpl squad create`. |
| `presentation.py` | Every Rich renderer, one flat module by decision (FU-18). |
| `api/official.py` | The three endpoints used: `bootstrap-static`, `fixtures`, `event/{n}/live`. |
| `api/models.py` | Pydantic models over the raw payloads. |
| `api/snapshots.py` | `SnapshotService`: the live/cache/pinned decision and stale fallback. |
| `domain/rules.py` | Rules read out of the snapshot — squad size, quotas, budget, club limit. |
| `domain/squad.py` | Squad and formation validation, `best_xi` and `xi_value`. |
| `domain/transfers.py` | The ledger, transfer application, rollover, hits and selling prices. |
| `domain/projections.py` | The eight-component xP model and its two controls. |
| `domain/strength.py` | The fixture-strength seam: `MatchRates`, `BandedTeamRates`. |
| `domain/variants.py` | Named model variants, the registry, and the derived version string. |
| `domain/optimizer.py` | The beam search, the numpy scoring kernel and dominance pruning. |
| `domain/evaluation.py` | RMSE, MAE, Spearman, return categories and per-component error. |
| `storage/cache.py` | The raw JSON snapshot cache. |
| `storage/capture.py` | The capture directory format, manifests, roles and quarantine. |

**This table is checked against the tree.** `tests/test_claude_md_structure.py`
walks `src/fpl_cli/` and fails naming the document, the package and every module
the table omits, every module it names that does not exist, and every package it
never mentions (FU-19). `CLAUDE.md` carries an equivalent Structure block checked
by the same test — one comparison, two readers, because the formats differ.

The guard was written for `CLAUDE.md`, whose block went stale twice by the same
mechanism: the commit adding a module did not update the list naming it as
missing. This table then went stale within two days of being written, by that
same mechanism, which made it three instances and the second document.

Transient failures (timeouts, connection errors, 5xx) are retried with
exponential backoff. A 429 is deliberately **not** retried aggressively: the API
is unauthenticated and rate-limited by IP, so hammering a 429 risks turning a
short block into a longer one. A retry is attempted only when `Retry-After` is
present and short (≤5s); otherwise the CLI falls back to the cached snapshot
immediately. Prices are integer units throughout — `1000` means £100.0m, never a
float.

## Development

```bash
pip install -e ".[dev]"
pytest -q          # 331 tests at the time of writing, no network
```

**One concern per branch, and never a commit to `main`.** Work happens on
`task/<short-name>` branches off `main`; merging is a separate, manual step.

**Plans are the handoff mechanism, not documentation.** Anything non-trivial is
designed in a file under [docs/plans/](docs/plans/) before it is built, because a
plan on disk survives a context clear and a conversation does not. Those files are
written to be argued with: they record what was measured, what was assumed, and
what was decided against and why, and later sections openly supersede earlier ones
rather than being edited into false coherence — see fu-28-dominance.md, whose §§8–9
overrule §§1–7. Deferred work is filed in
[docs/plans/follow-ups.md](docs/plans/follow-ups.md) as a numbered FU entry;
numbering never shifts, closed entries stay in place with a Status line naming what
was checked *in the code* rather than what the commit claimed, and the file is
periodically reconciled against `main` — which is how FU-19 was caught having
regressed after being closed.

**Tests use a synthetic dataset and mocked responses. No live API, ever.** Two
disciplines beyond that are load-bearing:

- **Mutation-test every new assertion.** A test is kept only once it has been
  demonstrated *failing* against the defect it claims to catch — the pre-fix
  code, or a deliberate mutation of the line under test. Two guard tests in this
  repo were found to be vacuous (FU-36, FU-37), which is what a test that was
  never seen to fail is by default.
- **Prefer a check to a correction.** Where the same defect recurs by the same
  mechanism, the fix is a test that names the drift, not a third hand-edit:
  `tests/test_claude_md_structure.py` for the module list (FU-19), and an AST scan
  for `typer.Exit` given a message instead of an exit code (FU-3), a mistake that
  had been copied to nine call sites while its follow-up entry sat open.

`presentation.py` is 393 lines and splits into a package at 600 — a threshold
recorded in FU-18 precisely so the question is settled by a line count rather than
re-litigated as a judgement call, which it had already been twice.

## Roadmap

Intent, not commitment.

- **Dixon-Coles team strength (v2).** Fit attack, defence and home-advantage
  parameters on raw scorelines from the fixtures endpoint, behind the existing
  `TeamRatesModel` protocol. This is the change the `MatchRates` seam was designed
  for: it replaces one class and touches no component.
- **xGI by differencing daily captures.** The API publishes cumulative
  `expected_goals`/`expected_assists` only. Two captures a day apart differ by one
  gameweek's worth, so the archive can yield per-gameweek underlying numbers that
  the API never exposes directly — a use for the capture format beyond
  reproducibility.
- **`--schedule`, and what k = 3 costs.** FU-29. Fixing the per-gameweek transfer
  count and enumerating players completely at that count is the affordable way to
  reach three transfers in a gameweek; making the free search do it everywhere is
  the measured point at which the MILP decision reopens.
- **ML projections.** The longer-term direction, and the one that needs the
  evaluation harness to mean something first. Fitting anything requires a run of
  leak-free gameweeks to fit against, which the archive is only now starting to
  accumulate.

---

## Appendix — the original Agent Plan

Kept verbatim as a historical statement of intent, not as a live specification.
It is wrong in places — it specifies `src/fpl_cli/presentation/` as a package,
which FU-18 decided against, and names commands that do not exist (FU-14) — and
it is left unedited because it is referenced by name from
[docs/plans/](docs/plans/) as the record of what was originally planned, and
correcting it would make it a worse record. Where it and the sections above
disagree, the sections above are current.

Plan: FPL CLI Planner
Build a local, read-only Python CLI that uses the official FPL API to browse players, create valid squads, simulate transfers, and optimize transfer paths across multiple gameweeks.

Steps

Scaffold a Python project using:

Typer for CLI commands
Rich for tables, prompts, colours, and panels
HTTPX for API access
Pydantic for typed API models
SQLite plus raw JSON snapshots for caching
Pytest with mocked API responses
Integrate the official FPL endpoints:

bootstrap-static
fixtures
element-summary/{player_id}
event/{gameweek}/live
The primary snapshot provides player names, clubs, positions, prices, points, form, availability, injuries, gameweek deadlines, and rule configuration.

Derive rules dynamically from the API rather than hardcoding them:

15-player squad
2 goalkeepers, 5 defenders, 5 midfielders, 3 forwards
£100m budget
Maximum three players per club
Valid starting XI and formations
Captain and vice-captain rules
Free-transfer rollover and transfer deductions
Selling fees and chip availability
Add an interactive squad builder:

Search players by name
Filter by position, club, price, points, form, and availability
Show remaining budget and club counts
Warn about injuries, suspensions, loans, and unavailable players
Save named local squads
Import/export plans as JSON
Implement deterministic transfer simulation:

Apply transfers gameweek by gameweek
Track free transfers and rollover limits
Calculate selling prices and points hits
Validate every resulting squad
Use official UTC deadlines
Model wildcard and free-hit behaviour separately
Implement multi-week optimization:

Search valid squad states over a configurable horizon
Maximize projected points minus transfer hits
Penalize unavailable or risky players
Preserve budget and club constraints
Start with bounded beam search or state-pruned dynamic programming
Display recommended transfers, projected gains, hits, assumptions, and alternative paths
Provide initial commands such as:

fpl sync
fpl players list
fpl players show
fpl squad create
fpl squad validate
fpl squad show
fpl squad import/export
fpl plan simulate
fpl plan optimize
Add documentation covering:

Setup and Linux usage
Official API dependency and lack of formal API guarantees
Cache and stale-data behaviour
Currency units
Rule-source handling
Optimizer assumptions and limitations

Relevant files

pyproject.toml — dependencies, packaging, CLI entry point, and test configuration
src/fpl_cli/cli.py — Typer commands
src/fpl_cli/api/official.py — API requests
src/fpl_cli/api/models.py — Pydantic models
src/fpl_cli/transport.py — HTTP errors, timeouts, and retries
src/fpl_cli/storage/cache.py — SQLite and raw snapshot storage
src/fpl_cli/domain/rules.py — runtime FPL rules
src/fpl_cli/domain/squad.py — squad and formation validation
src/fpl_cli/domain/transfers.py — transfer simulation
src/fpl_cli/domain/optimizer.py — multi-week optimization
src/fpl_cli/presentation/ — Rich output
tests/ — API, domain, CLI, and optimizer tests
README.md — setup, usage, caveats, and roadmap

Verification

Test valid and invalid squads, budgets, positions, formations, club limits, captaincy, and player availability.
Test transfer rollover, selling prices, transfer hits, deadlines, chips, and multi-week transitions.
Mock API failures including timeouts, 403, 429, 5xx, malformed data, and stale-cache fallback.
Use a tiny synthetic player dataset to verify known optimizer outcomes.
Run Linux CLI smoke tests for syncing, filtering, squad creation, validation, simulation, and optimization.
Confirm every optimizer recommendation passes the same validator used for manual squad planning.

Decisions

The MVP is read-only and does not require FPL credentials.
No account login or submission of real teams initially.
Squad selection is interactive, with JSON import/export.
Multi-week optimization is the main planning feature.
Manual transfer simulation is required first as the optimizer's correctness baseline.
The official FPL API is the primary free data source.
Rules and deadlines come from the live API snapshot rather than hardcoded values.
External injury, lineup, or prediction APIs are deferred.
The workspace is currently empty, so this plan can be implemented as a clean project from scratch.

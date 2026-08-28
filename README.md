# FPL CLI

A local, read-only Fantasy Premier League planning tool.

## Status

The first slice supports:

- Fetching and caching the official FPL `bootstrap-static` snapshot
- Listing and filtering players
- Rule-aware squad validation from a JSON plan

The official endpoints are undocumented and may change. Cached snapshots are retained locally so the app can remain useful during temporary API failures. Prices are stored in FPL integer units, where `1000` means GBP 100.0m.

Transient failures (timeouts, connection errors, 5xx responses) are retried automatically with exponential backoff. A 429 (rate limited) is deliberately **not** retried aggressively: the FPL API is unauthenticated and rate-limited by IP, so hammering a 429 risks turning a short-lived block into a longer one. A retry is attempted only when the server's `Retry-After` header is present and short (≤5s); otherwise the CLI falls back to the cached snapshot immediately.

### Rules that are hardcoded, and need checking each season

Squad size, position quotas, budget, club limits and deadlines are all derived from `bootstrap-static` at runtime, so a mid-season rule change is picked up by `fpl sync`. **Two transfer rules are not, because the API never publishes them:**

| Constant | Value | Status | Source |
|---|---|---|---|
| Points deducted per extra transfer | `4` | Confirmed correct for 2026/27 | `domain/transfers.py` — `points_per_extra_transfer` |
| Free transfers accrued per gameweek | `1` | Inferred, never stated by the API | `domain/transfers.py` — `free_transfers_per_event` |

Neither appears in `game_settings` or `game_config.scoring`. The hit cost is a known-correct value that simply cannot be re-derived; the free-transfer base was reasoned from the field name `max_extra_free_transfers` ("extra" relative to an unstated base), so it is the weaker of the two.

Both are load-bearing for `fpl plan simulate` — and will be for `fpl plan optimise` — since every points-hit calculation and every net-gain figure depends on them. If FPL changes either rule between seasons, the output goes wrong **silently**: nothing in the app can detect the drift, because there is no API field to compare against.

**Check both at the start of each season** against the official rules page, and update `domain/transfers.py` if they have moved.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Commands

```bash
fpl sync
fpl players list --position MID --available-only
fpl squad validate squad.json
```

A squad plan is a JSON object containing a `players` array of player IDs. The validator reports the exact rule failures and the snapshot metadata used.

### Pinning a run to a capture

Every command that reads a snapshot takes `--snapshot PATH` (or reads
`$FPL_SNAPSHOT`; the flag wins). A pinned run reads bootstrap-static from
`PATH`, never fetches, and never writes the cache, so a figure measured under
it can be re-measured later against the same inputs:

```bash
fpl plan optimise squad.json --snapshot ~/fpl-pinned/gw2-pre-deadline.json --json
```

`--snapshot` takes either shape:

- **A capture directory** (`~/.fpl-cli/archive/YYYY-MM-DD/`, written by `fpl
  sync`) holding `bootstrap-static.json`, `fixtures.json` and a
  `manifest.json`. Both files are pinned, and each is checked against the
  manifest's sha256 before use. The first capture of a UK date claims that
  day's canonical slot; later ones the same day are filed as ad-hoc under
  `YYYY-MM-DDTHHMMSSZ/` and stay pinnable, but `plan evaluate` selects only
  canonical captures.
- **A bare bootstrap-static file**, as before: the snapshot is pinned and
  fixtures still come from the cache, which `provenance` reports as `cache`.

A missing or unparseable path, a directory with no manifest, or a file that
does not match its recorded digest is an error naming it — there is no fallback
to cache or live. See [docs/plans/snapshot-pinning.md](docs/plans/snapshot-pinning.md),
including §5 on what a pinned run still does not pin.

## Agent Plan

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
Manual transfer simulation is required first as the optimizer’s correctness baseline.
The official FPL API is the primary free data source.
Rules and deadlines come from the live API snapshot rather than hardcoded values.
External injury, lineup, or prediction APIs are deferred.
The workspace is currently empty, so this plan can be implemented as a clean project from scratch.
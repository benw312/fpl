# FPL CLI

Local, read-only Fantasy Premier League planning tool. Python CLI over the
official (undocumented) FPL API. No credentials, no team submission.

## Stack
Typer (CLI) · Rich (output) · HTTPX (API) · Pydantic (models) · numpy (optimiser kernel)
SQLite + raw JSON snapshots (cache) · pytest (mocked API)

## Platform
Developed and run on Linux.

## Structure
All paths under `src/fpl_cli/`:
`api/` — official.py, models.py, snapshots.py
`domain/` — rules.py, squad.py, transfers.py, projections.py, strength.py,
evaluation.py, optimizer.py, variants.py
`storage/` — cache.py, capture.py
Top level — cli.py, transport.py, builder.py, presentation.py (one file by
decision, not by drift — see FU-18, which sets 600 lines as the threshold to
split it into a package)

This block is checked against the tree by
`tests/test_claude_md_structure.py`: add a module here in the same commit that
adds the file, or the suite fails naming it (FU-19).
See `docs/plans/` for written plans and `docs/plans/follow-ups.md` for
filed follow-ups. The repo is still the source of truth — this block is now
checked, the prose around it is not.


## Rules
- Derive FPL rules from the live API snapshot. Never hardcode squad limits,
  budgets or deadlines — they come from bootstrap-static.
- Prices are integer units: 1000 = £100.0m. Never store as float.
- The API is undocumented and may change. Cached snapshots must keep the
  app usable during failures — preserve stale-cache fallback behaviour.
- Every optimiser recommendation must pass the same validator used for
  manual squad planning.

## Conventions
- UK English.
- Task branch per change: `git checkout -b task/<short-name>`. Never commit
  to main.
- Tests use a synthetic dataset and mocked responses. No live API in tests.
- Flag gaps and assumptions in [square brackets] rather than inventing detail.

## Commands
- Install: `pip install -e ".[dev]"`
- Test: `pytest -q`
- Run: `fpl sync` / `fpl players list` / `fpl squad validate squad.json`

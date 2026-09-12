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

## Follow-ups
`docs/plans/follow-ups.md` is the register, and it is only worth what its
entries say about the code *now*. Working on an FU means updating its entry
**in the same commit as the work** — not afterwards, not in a tidy-up pass.

- **Partial progress:** add a dated `**Progress: YYYY-MM-DD**` line saying what
  changed and what is left. The entry stays open.
- **Closed:** add the `**Status: closed**` line, naming the commit or branch.
  Say what was checked **in the source**, not what the commit message claimed,
  and where the fix diverged from the entry, say how. The file's header
  specifies the format; follow it there rather than restating it here.
- **Update the entry *and* the header's open-entry table.** They are two
  records of the same fact and they drift apart silently.
- Numbering never shifts, so closed entries stay in place.

**This is the file's recurring failure, not a hypothetical.** FU-15 and FU-21
each sat closed-in-code and unmarked for fifteen and ten days, while the
header's own findings list claimed no entry was in that state. Both were found
by accident on 2026-09-12. An entry that overstates what is still broken costs
a future session the work of rediscovering it is already done.

**Deliberately not machine-checked, unlike the Structure block above.** The
obvious check — a hook rejecting a commit whose message names FU-N without
touching follow-ups.md — was considered and declined on 2026-09-12. It would
have caught FU-15, whose commit message *does* name the entry, and missed
FU-21, whose does not: that close was a side effect of implementing
`component/1.2` and nobody was thinking about FU-21 at all. So it catches the
case where the author already has the entry in mind and misses the case where
they do not, which is the one that actually fails. It also cannot check the
thing that gives a Status line its value — whether what it says about the
source is *true*. That is a prose judgement, and prose judgement is the whole
job here.

## Commands
- Install: `pip install -e ".[dev]"`
- Test: `pytest -q`
- Run: `fpl sync` / `fpl players list` / `fpl squad validate squad.json`

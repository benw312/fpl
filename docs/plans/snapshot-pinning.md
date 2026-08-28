# Pinning a run to a capture (`--snapshot` / `FPL_SNAPSHOT`)

## 1. The defect

Verification and benchmark runs fetch live data and write it to the cache. A
figure measured "against the cached snapshot" is therefore reproducible only
until the next `fpl` command runs — including the next verification run.

This has bitten twice, both in [fu-28-dominance.md](fu-28-dominance.md):

- **§7.1e** — figures re-measured against a cache that had moved under them.
- **§7.1g** — the 2026-08-27T13:33Z capture (614 players) was overwritten by
  this branch's own verification runs. The replacement figures come from a
  22:18Z capture (616 players), which invalidated the numbers quoted in three
  commit messages. `~/.fpl-cli/archive` held nothing between 2026-08-27T00:30
  and the overwrite, so the original capture is simply gone.

`SnapshotService.load()` saves on every successful live fetch
(`api/snapshots.py:91`). That behaviour is right for ordinary use and is
deliberately **not** changed here — see §6.

## 2. The design

`--snapshot PATH` loads bootstrap-static from `PATH`.

- **It never fetches.** Not bootstrap-static, not fixtures, not event-live.
- **It never writes the cache.** Not the bootstrap cache, not the fixtures
  cache, not the event-live cache, not the archive.

Both properties are the point. A run that touches the network or the cache is
not a pinned run, and a figure measured under it is not citable.

`FPL_SNAPSHOT` is an equivalent environment variable. The flag wins if both
are set, so a pinned shell can still be overridden for one command.

A missing or unparseable file is a **hard error naming the path**. There is no
fallback to cache or to live: silent fallback would recreate the exact defect
this fixes — a run that quietly measured something other than what it was told
to measure.

Applies to every command that reads a snapshot: `players list`,
`squad create`, `squad validate`, `plan simulate`, `plan evaluate`,
`plan optimise`. Not `sync`, whose entire job is to fetch and write.

## 3. Shape

`api/snapshots.py` gains `PinnedSnapshotService`: `SnapshotService`'s
read-only twin. Same `load` / `load_fixtures` / `load_event_live` / `close`
surface, no `refresh*` and no `archive` (a pinned run has no business writing).
`SnapshotService` itself is untouched.

`cli.py` gains `resolve_snapshot_path` (flag beats environment) and
`snapshot_service` (the one place that chooses between the two services). Both
are module-level so a test can exercise the precedence rule without a CLI
invocation.

The pinned snapshot's `fetched_at` is the file's mtime, matching
`JsonDocumentCache.load_typed`. That makes it a property of the capture rather
than of the run, which is what lets two pinned runs produce identical `--json`.

## 4. Provenance in `--json`

`plan optimise --json` gains a `provenance` block:

```json
"provenance": {
  "snapshot": {"source": "pinned", "captured_at": "...", "path": "..."},
  "fixtures": {"source": "cache", "captured_at": "..."}
}
```

`source` is `pinned` / `cache` / `live`. A recorded figure now carries the
capture it came from, which is what makes a plan measurement citable — the
missing half of the fix. Quoting a figure without it is what FU-40 forbids.

`captured_at` is the snapshot's `fetched_at`: the file's mtime for a pinned
capture and for a cache read, the moment of the fetch for a live one. Taking it
from the clock instead would be honest about when a figure was produced and
useless for finding what produced it — and would differ between two runs of the
same pinned command.

Two stdout defects had to go with it, because `--json` that cannot be parsed
carries no provenance at all:

- The stale-cache warning went to stdout via `rich.print`, so a stale run
  printed a non-JSON line in front of the payload — in exactly the run whose
  provenance says `cache`. It now goes to `error_console`, like the pinned-run
  notice.
- The payload itself went through `rich.print`, which word-wraps at the console
  width and *folds* an over-long token. An absolute path — which `provenance`
  now always may carry — came out split across two lines, i.e. invalid JSON. It
  is written with `sys.stdout.write` instead.

## 5. What a pinned run still does not pin

`[gap: the capture format is bootstrap-static only — it is what the FPL API
serves at that URL and what `~/fpl-pinned/gw2-pre-deadline.json` contains.
Fixtures and event-live have no pinned equivalent, so a pinned run reads them
from their ordinary caches, read-only. That honours both stated properties (no
fetch, no cache write) but means a pinned run is reproducible only for as long
as those caches are also unchanged. Pinning them wants either a bundle format
or a second flag; neither is in this design. Filed as part of FU-40.]`

`[gap: `PinnedSnapshotService.load_event_live` serves whatever the event-live
cache holds, bypassing `SnapshotService`'s `finished and data_checked` gate
(Decision 6) — under pinning there is no live fetch to prefer, so the gate has
nothing to choose between. A cache written before that gate existed would be
served as if final.]`

## 6. Explicitly not changed

`SnapshotService.load()`'s save-on-fetch. It is the right behaviour for
ordinary use — the cache exists so the tool survives an API failure, and a
cache that is only written by `sync` would go stale for anyone who does not run
`sync`. The defect is not that it saves; it is that nothing could opt out.
`--snapshot` is the opt-out.

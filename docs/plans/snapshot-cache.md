# Plan: FU-2 (+ FU-1) — snapshot caching

Implements [FU-2](follow-ups.md) — `load_snapshot` never writes the cache on a
successful fetch — and [FU-1](follow-ups.md) — extract the stale-cache decision into
a `SnapshotService` — from the transport follow-ups. FU-3 (`typer.Exit` misuse) and
FU-4 (SQLite) stay out of scope and untouched. No code written yet.

## Branch base

`task/transport` is not yet merged into `main`. This branch (`task/snapshot-cache`)
is cut from `task/transport`, not `main`, because the code this follow-up touches —
`FplError`, `cli.py`'s `except FplError` handling, `tests/test_stale_cache.py` —
only exists there. **The eventual PR should target `task/transport`, not `main`.**

## Do FU-1 and FU-2 conflict?

No — they compose. FU-2's fix ("save after every successful fetch") has to live
inside whatever function performs the fetch-with-fallback. Today that's
`cli.load_snapshot` (`cli.py:22-34`); after FU-1 it's `SnapshotService.load()`. Doing
FU-1 first just relocates the function FU-2's one-line fix lands in — it doesn't
change what the fix is. The task's own framing ("if it lands in the same function")
is satisfied: it's the same function, new home.

The only interaction worth naming: `fpl sync` (`cli.py:38-48`) already does
fetch-then-save, unconditionally, with no fallback. FU-1 gives `load_snapshot` and
`sync` a shared home (`SnapshotService`), so the "save on success" line ends up
written twice — once in a `load()` method (fetch, fall back to cache on failure) and
once in a `refresh()` method (fetch, no fallback, used by `sync`). That's one
duplicated line, not a real conflict, and not worth abstracting away (see Decision
3).

---

## Current state (`cli.py`, on `task/transport`)

```python
def load_snapshot() -> BootstrapSnapshot:
    cache = SnapshotCache()
    cached = cache.load()
    api = OfficialFplApi()
    try:
        return api.bootstrap_static()          # <-- never saved on success (FU-2)
    except FplError:
        if cached is not None:
            print(f"[yellow]Using cached snapshot from {cached.fetched_at.isoformat()}.[/yellow]")
            return cached
        raise typer.Exit("No live snapshot or cached snapshot is available.")
    finally:
        api.close()


@app.command()
def sync() -> None:
    api = OfficialFplApi()
    try:
        snapshot = api.bootstrap_static()
        SnapshotCache().save(snapshot)
    except FplError as exc:
        raise typer.Exit(str(exc)) from exc
    finally:
        api.close()
    console.print(f"[green]Synced {len(snapshot.elements)} players for {snapshot.season}.[/green]")
```

Both functions construct their own `OfficialFplApi` and `SnapshotCache` — the
duplication FU-1 also names.

---

## Design

New module `src/fpl_cli/api/snapshots.py`, matching the existing layering
(`cli.py` → `api/` → `transport.py`).

```python
@dataclass(frozen=True)
class SnapshotResult:
    snapshot: BootstrapSnapshot
    stale: bool
    reason: str | None = None   # why we fell back, when stale


class SnapshotService:
    def __init__(self, api: OfficialFplApi | None = None, cache: SnapshotCache | None = None) -> None:
        self._api = api or OfficialFplApi()
        self._owns_api = api is None
        self._cache = cache or SnapshotCache()

    def close(self) -> None:
        if self._owns_api:
            self._api.close()

    def load(self) -> SnapshotResult:
        """Fetch live; fall back to cache on any FplError. Saves on success."""
        try:
            snapshot = self._api.bootstrap_static()
        except FplError as exc:
            cached = self._cache.load()
            if cached is None:
                raise
            return SnapshotResult(snapshot=cached, stale=True, reason=str(exc))
        self._cache.save(snapshot)
        return SnapshotResult(snapshot=snapshot, stale=False)

    def refresh(self) -> BootstrapSnapshot:
        """Force a live fetch for `fpl sync`. No fallback; raises FplError on failure."""
        snapshot = self._api.bootstrap_static()
        self._cache.save(snapshot)
        return snapshot
```

`cli.py` becomes:

```python
def load_snapshot() -> BootstrapSnapshot:
    service = SnapshotService()
    try:
        result = service.load()
    except FplError as exc:
        raise typer.Exit("No live snapshot or cached snapshot is available.") from exc
    finally:
        service.close()
    if result.stale:
        print(f"[yellow]Using cached snapshot from {result.snapshot.fetched_at.isoformat()} — live fetch failed: {result.reason}[/yellow]")
    return result.snapshot


@app.command()
def sync() -> None:
    service = SnapshotService()
    try:
        snapshot = service.refresh()
    except FplError as exc:
        raise typer.Exit(str(exc)) from exc
    finally:
        service.close()
    console.print(f"[green]Synced {len(snapshot.elements)} players for {snapshot.season}.[/green]")
```

`list_players` and `validate_squad` are unaffected — both call `load_snapshot()`,
whose signature and return type (`BootstrapSnapshot`) don't change.

`raise` with no argument inside the `except FplError as exc` block re-raises the
original exception object, not a copy — `cli.py` still gets `exc.status_code`,
`RateLimited.retry_after`, etc. if it ever wants them.

### Decision 1 — ownership pattern for `api`/`cache`

Mirrors `OfficialFplApi`'s existing `transport`/`_owns_transport` split
(`api/official.py:37-40`): an injected `api` is not closed by `SnapshotService`, a
self-constructed one is. Same idiom, no new pattern introduced. `cache` has no
close() method (it's just a path wrapper), so it needs no ownership tracking.

### Decision 2 — what happens when there's no cache to fall back to

`SnapshotService.load()` re-raises the original `FplError` rather than inventing its
own "no snapshot available" error. This keeps error *construction* in `cli.py`
(consistent with the layer boundary already stated in `docs/plans/transport.md`:
"cli.py: user-facing messages, exit codes, stale-cache decision" — the decision of
what to load moves to the service, but messaging stays put) and preserves the
original exception's type and attributes for anything downstream that wants them.

### Decision 3 — don't extract the shared `self._cache.save(snapshot)` line

`load()` and `refresh()` each call `self._cache.save(snapshot)` once. Pulling that
into a private helper (`_fetch_and_cache`) would save one line at the cost of an
extra indirection for a reader — not worth it per repo convention ("Three similar
lines is better than a premature abstraction"). Revisit only if a third caller shows
up.

### Decision 4 — include the fallback reason in the printed message, kept to one line

`SnapshotResult.reason` (the stringified original error) is threaded into the
existing yellow warning as a single `print` call, one line:
`Using cached snapshot from {ts} — live fetch failed: {reason}`. This is new
information for the user (currently they just see "using cached snapshot" with no
indication of *why* live failed — a 429 vs. a timeout vs. FPL being down all look the
same). Costs nothing beyond what FU-1 already proposed (`SnapshotResult(..., reason)`
is named in the follow-up itself), so this is using the field for what it was
specified for rather than adding scope. Deliberately one `print`, not a second line
or a Rich panel — the reason is a supplement to the existing warning, not a new UI
element.

### Decision 5 — cache-write failures on the success path are not specially handled

If a live fetch succeeds but `cache.save()` then raises (disk full, permissions),
that exception propagates uncaught and the command fails despite having good data in
hand. This is pre-existing behaviour — `sync` already has this exact gap today
(`cli.py:42-43`) — so `load()` inherits it rather than diverging in how the two
methods handle a save failure. Not fixing it here; it's a new, smaller follow-up if
it turns out to matter (disk-full is the realistic case, and the existing behaviour —
loud failure — is arguably the safer default for the `sync` case rather than a bug in
its own right, so this isn't being filed as FU-5 unless requested).

### Message text: "no cache" case stays static, on purpose

The "no cache" `typer.Exit` message is constructed explicitly —
`typer.Exit("No live snapshot or cached snapshot is available.")` — rather than
interpolating the underlying exception (`f"...: {exc}"`). Letting the exception text
flow straight into the exit-code slot would tangle this change with FU-3 (`typer.Exit`
being passed a message where it expects a code): if the wording started depending on
`str(exc)`, fixing FU-3 later — printing to stderr and passing a real exit code — would
mean re-deriving that wording rather than just relocating a literal string. Keeping it
a plain string now keeps FU-3 a clean, independent fix later. `exc` is still chained
via `from exc` for anyone inspecting the traceback; it's just not in the user-facing
text.

---

## Implementation steps

1. **`src/fpl_cli/api/snapshots.py`** (new) — `SnapshotResult`, `SnapshotService` as
   above.
2. **`src/fpl_cli/cli.py`** — replace `load_snapshot` and `sync` bodies as above.
   Drop the now-unused direct `OfficialFplApi`/`SnapshotCache` imports if nothing
   else in the file uses them (check `squad_app`/`players_app` commands — they don't
   construct either directly, so both imports should go).
3. **`tests/test_snapshots.py`** (new) — the substantive coverage, replacing
   `tests/test_stale_cache.py`'s current monkeypatch-heavy approach with direct
   construction (`SnapshotService(api=stub, cache=SnapshotCache(path=tmp_path/...))`),
   the same pattern `test_official.py`'s `StubTransport` already uses:
   - `load()`, live fetch succeeds → `stale is False`, and the cache file now exists
     and round-trips via `SnapshotCache(path=...).load()`. **This is the restored
     test case.**
   - `load()`, live fetch fails (`RequestTimeout`), cache present → returns cached
     snapshot, `stale is True`, `reason` contains the timeout message.
   - `load()`, live fetch fails, no cache → the original `FplError` propagates
     unchanged (assert `is` the same exception type raised by the stub, e.g.
     `RateLimited` stays `RateLimited`, not wrapped).
   - `load()`, live fetch fails, cache file corrupt → same as no-cache (relies on
     `SnapshotCache.load()`'s existing `None`-on-corruption behaviour,
     `storage/cache.py:20-24`).
   - `refresh()`, live fetch succeeds → cache written, snapshot returned.
   - `refresh()`, live fetch fails → `FplError` propagates, cache is **not**
     modified (assert any pre-existing cache file is untouched — `refresh()` has no
     fallback path to accidentally trigger).
   - `close()` — injected `api` is not closed; self-constructed one is (mirrors
     `test_official.py`'s / `test_transport.py`'s existing "injected client not
     closed" tests).

   Uses a `StubApi` with the same shape as `test_official.py`'s `StubTransport`:
   constructed with either a `BootstrapSnapshot` to return or an exception to raise,
   tracks whether `close()` was called.

4. **`tests/test_stale_cache.py`** — repurposed, not deleted. Once the fallback
   logic itself is covered in `test_snapshots.py`, this file's only remaining job is
   confirming `cli.py` correctly delegates to `SnapshotService` and turns `FplError`
   into `typer.Exit`. Slimmed to monkeypatch `cli.SnapshotService` (one class) instead
   of `cli.OfficialFplApi` and `cli.SnapshotCache` (two) — this is the "patching goes
   away" outcome FU-1 named, though it thins rather than fully removes it:
   Four tests, one per branch (this file goes from 3 tests to 4, not a 1:1 swap):
   - `load_snapshot()`: stub service `.load()` returns a stale `SnapshotResult` →
     function returns `.snapshot`, no exception.
   - `load_snapshot()`: stub service `.load()` raises `FplError` → `typer.Exit`.
   - `sync()`: stub service `.refresh()` succeeds → prints the synced-players message.
   - `sync()`: stub service `.refresh()` raises `FplError` → `typer.Exit`.

5. **No change** to `tests/test_rules.py`, `tests/test_official.py`,
   `tests/test_transport.py`, `tests/conftest.py`.

Run `pytest -q` at the end; expect all prior tests plus the new ones green.

---

## Scope boundary

In scope: `api/snapshots.py` (new), `cli.py` (`load_snapshot`, `sync`),
`tests/test_snapshots.py` (new), `tests/test_stale_cache.py` (slimmed).

Out of scope, left filed: FU-3 (`typer.Exit` misuse — still present, unchanged
call pattern), FU-4 (SQLite).

# Plan: `src/fpl_cli/transport.py`

Extract HTTP concerns out of `api/official.py` into a dedicated transport layer that
owns timeouts, error classification and retries. No code in this document is written
yet; this is the implementation order plus the decisions that have a real choice in
them.

## Why now

`api/official.py:26-31` does the whole job in one `try`: request, status check, JSON
decode, and a single blanket `except (httpx.HTTPError, ValueError)` that flattens
every failure into one `FplApiError` string. Consequences:

- A 403 (Cloudflare / blocked User-Agent), a 429 (rate limit), a 503 and a read
  timeout are indistinguishable to the caller, so the CLI cannot say anything useful
  and cannot make different decisions.
- There are no retries at all. A single transient 502 drops the user to stale cache.
- `except ... ValueError` catches JSON decode errors, but the schema mismatch is
  caught separately at line 40 by a bare `except Exception`. The two failure kinds
  ("we did not get well-formed bytes" vs "the bytes did not mean what we expect")
  are split across the wrong boundary.
- The `httpx.Client` is constructed inside the API class, so timeout policy is a
  literal (`timeout=15`) with no way to tune it and no separation of connect vs read.

---

## Layer boundary

```
cli.py            user-facing messages, exit codes, stale-cache decision
  └─ api/official.py   FPL endpoints, URL shapes, JSON -> Pydantic, season derivation
       └─ transport.py  httpx client, timeouts, retries, status classification
```

**transport.py owns:**
- The `httpx.Client` lifecycle and its timeout/limit configuration.
- Base URL joining and the `User-Agent` header.
- Turning every HTTP outcome into either decoded JSON or one typed exception.
- The retry loop and backoff, including `Retry-After` handling.
- Debug logging of retries via stdlib `logging` (no Rich import — transport must not
  depend on presentation).

**transport.py does not own:**
- Which endpoints exist, or what their payloads mean.
- Pydantic validation.
- Caching or stale-fallback policy.

### Decision 1 — file location

The README's Relevant files list says `src/fpl_cli/transport.py` (flat), not
`api/transport.py`. Flat is also correct on the merits: the module is generic HTTP
with no FPL knowledge beyond a default base URL, and `domain/` code should never
reach through `api/` to get at it.

**Decided:** follow the plan, `src/fpl_cli/transport.py`.

Note: `CLAUDE.md` already records one plan/reality divergence (`presentation/`
package vs flat module). Adding a second divergence for no reason is not worth it.

### Decision 2 — what `get_json` returns

| Option | Consequence |
| --- | --- |
| Return `httpx.Response` | `official.py` stays coupled to httpx; JSON decode errors leak back up into the API layer; transport becomes a thin wrapper that does not actually own "malformed data". |
| **Return decoded JSON (`Any`)** | Transport owns decode failure, so a truncated or HTML body (very common when FPL serves a Cloudflare interstitial with a 200) is classified as a transport fault. `official.py` never imports httpx. |
| Return `bytes` | Caller decodes; splits the same concern again for no gain. |

**Decided:** `get_json(path) -> Any`.

This gives the clean split the current code lacks:
transport raises on *malformed transport-level data*, `official.py` raises on
*schema mismatch*. Both are in the README's required test list and they are now
testable independently.

---

## Decision 3 — the exception hierarchy

This is the decision that most affects `cli.py`, so it is worth stating the options.

**Option A — one error class with a `status_code` attribute.** Smallest change;
callers branch on `exc.status_code`. But `Retry-After` has nowhere natural to live,
and every consumer re-implements the same status-to-meaning mapping that transport
just performed and threw away.

**Option B — a small typed hierarchy.** Consumers catch what they care about; the
mapping is done once. Costs about 25 lines of class definitions.

**Decided: Option B**, kept deliberately small:

```
FplError(RuntimeError)                 # common base, defined in transport.py
├── TransportError(FplError)           # carries url, status_code, attempts
│   ├── RequestTimeout                 # connect/read timeout, connect error
│   ├── RateLimited                    # 429, carries retry_after: float | None
│   ├── ServerError                    # 5xx
│   ├── AccessDenied                   # 401/403
│   ├── NotFound                       # 404
│   └── MalformedResponse              # body is not JSON / not the expected container
└── FplApiError(FplError)              # stays in api/official.py: schema mismatch
```

### The base-class placement sub-decision

`cli.py:27` currently catches `FplApiError`. Three ways to keep a single catch site:

1. Transport errors subclass `FplApiError`. Rejected — makes the generic HTTP module
   import from the FPL API package, inverting the dependency direction.
2. `cli.py` catches `(TransportError, FplApiError)`. Works, but every new call site
   must remember the tuple.
3. **A shared `FplError` base defined in `transport.py`**, which `FplApiError`
   subclasses. `cli.py` catches `FplError` and gets everything.

**Decided: 3.** `api/official.py` keeps `FplApiError` as its public name and
re-exports the transport errors, so existing imports still read naturally.

**This forces one mandatory change in `cli.py`.** `FplApiError` narrows to mean
"schema mismatch" only, so the two existing handlers at `cli.py:27` and `cli.py:43`
would stop catching HTTP failures — the stale-cache fallback would break outright for
exactly the errors it exists to handle. Both `except FplApiError` clauses must become
`except FplError`. This is a required consequence of the change, not one of the
deferred `cli.py` bugs below, and it is in scope for this task.

`TransportError.__str__` should produce a user-ready sentence — the CLI prints it
directly, so message quality belongs here, not at the call site. `AccessDenied` in
particular should say what a 403 from FPL usually means (blocked User-Agent,
region/Cloudflare challenge) rather than "HTTP 403".

---

## Decision 4 — retry policy, and why 429 is not 5xx

The README lists 429 and 5xx as separate test cases. They need genuinely different
handling, not just different messages.

**5xx / timeouts / connect errors** are transient and uncorrelated with our
behaviour. Retrying is the correct response and usually succeeds.

**429 from FPL is a statement about us.** The endpoint is unauthenticated and rate
limited by IP; a 429 means our IP is already over the line. Retrying quickly extends
the block rather than clearing it, and repeated hammering is what escalates a soft
rate limit into a longer IP ban. Backing off to the cache is strictly better for the
user than burning the IP for a snapshot that is at most a few hours stale.

Proposed classification table:

| Outcome | Retry? | Notes |
| --- | --- | --- |
| `httpx.ConnectError`, `ConnectTimeout`, `ReadTimeout`, `ReadError` | yes, full backoff | `RequestTimeout` once attempts are exhausted |
| 5xx | yes, full backoff | `ServerError` on exhaustion |
| 429 | conditional — see below | `RateLimited`, `retry_after` populated |
| 401 / 403 | **no** | `AccessDenied`. Retrying a block looks like abuse and never succeeds |
| 404 | **no** | `NotFound`. Signals a wrong endpoint / removed player ID |
| other 4xx | no | `TransportError` |
| 2xx, body not JSON | **no** | `MalformedResponse`. A retry returns the same bad body |

All FPL calls in scope are `GET`, so retries are unconditionally safe. If a write
endpoint is ever added this table must be revisited.

### The 429 sub-decision

| Option | Trade-off |
| --- | --- |
| Never retry 429 | Simplest and safest for the IP. Loses the case where FPL says `Retry-After: 1` and one short wait would have worked. |
| **Retry once, only when `Retry-After` is present and ≤ `max_retry_after` (5s)** | Recovers the genuinely transient case, and treats an absent or long header — which is what a real rate-limit block looks like — as terminal. |
| Retry with normal backoff, ignoring the header | Worst option. Ignores the server's explicit instruction and is the pattern that turns a rate limit into a ban. |

**Decided:** the middle row. Concretely: honour `Retry-After` exactly when
present and small; otherwise raise `RateLimited` immediately with `retry_after` set
so the CLI can tell the user when to try again.

`Retry-After` is legally either delta-seconds or an HTTP-date. Parse both
(`email.utils.parsedate_to_datetime` for the date form), and treat an unparseable
header as absent rather than as an error.

### Backoff shape

Exponential with full jitter, since several `fpl` invocations could easily be
running against the same IP:

```
delay = min(max_delay, base_delay * 2 ** (attempt - 1))
delay = delay * (1 - jitter + random() * 2 * jitter)
```

Defaults: `attempts=3`, `base_delay=0.5`, `max_delay=4.0`, `jitter=0.25`. Worst case
added latency is around 3s, which is acceptable for an interactive CLI. Do not sleep
after the final attempt.

### Decision 5 — how tests avoid real sleeping

| Option | Trade-off |
| --- | --- |
| Monkeypatch `time.sleep` | Zero production code, but patches a global and hides the dependency. |
| `base_delay=0` in tests | No wall-clock cost, but the backoff *sequence* then cannot be asserted — a bug in the delay calculation would pass. |
| **Inject a `sleep` callable, defaulting to `time.sleep`** | One extra constructor keyword. Tests pass a recorder and assert the exact delay sequence, including that `Retry-After` was honoured. |

**Decided:** inject `sleep`. The 429 tests need to assert *what* delay was
used, not merely that a retry happened, and that is only observable this way.

### Decision 6 — timeout granularity

`httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)` instead of the current
flat `timeout=15`. Connect failures mean offline or blocked and should fail fast into
the cache path; read needs more slack because `bootstrap-static` is a large payload.
Marginal complexity, and it makes the two failure modes separately tunable.

Also set `follow_redirects=True` on the client. The current code happens to use the
trailing-slash URL that FPL does not redirect; a caller that omits it would get an
unhandled 301 with httpx's default of `False`.

---

## Implementation steps

### Step 1 — `src/fpl_cli/transport.py`

Public surface:

```python
BASE_URL = "https://fantasy.premierleague.com/api"
DEFAULT_TIMEOUT: httpx.Timeout
DEFAULT_USER_AGENT = "fpl-cli/0.1"

class FplError(RuntimeError): ...
class TransportError(FplError):
    url: str
    status_code: int | None
    attempts: int
# + RequestTimeout, RateLimited(retry_after), ServerError,
#   AccessDenied, NotFound, MalformedResponse

@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 4.0
    jitter: float = 0.25
    max_retry_after: float = 5.0

class FplTransport:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        base_url: str = BASE_URL,
        policy: RetryPolicy = RetryPolicy(),
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None: ...
    def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any: ...
    def close(self) -> None: ...
    def __enter__(self) -> FplTransport: ...
    def __exit__(self, *exc: object) -> None: ...
```

Notes:
- An injected `client` is not closed by `close()` — the injector owns it. Only a
  self-constructed client is closed. Getting this wrong makes tests that share a
  mock client fail confusingly on the second call.
- Do **not** also set `httpx.HTTPTransport(retries=n)`. That retries connect errors
  only, invisibly, and would multiply with our loop, making the observed attempt
  count wrong. Keep all retry behaviour in one place.
- `get_json` treats a body that decodes to something other than `dict | list` as
  `MalformedResponse`. An HTML challenge page served with a 200 is the realistic
  case and it must not reach Pydantic.
- Log each retry at `logging.DEBUG` with url, status and the chosen delay.

### Step 2 — rewrite `api/official.py`

```python
class FplApiError(FplError):
    """The payload did not match the expected FPL schema."""

class OfficialFplApi:
    def __init__(self, transport: FplTransport | None = None) -> None:
        self._transport = transport or FplTransport()
        self._owns_transport = transport is None

    def bootstrap_static(self) -> BootstrapSnapshot: ...
    def close(self) -> None: ...
```

Changes from the current file:
- Drop the `client` and `base_url` constructor parameters; both now belong to
  `FplTransport`. Two call sites use this class (`cli.py:24`, `cli.py:39`), so a
  clean break is cheaper than a compatibility shim.
- `bootstrap_static` becomes: call `self._transport.get_json("/bootstrap-static/")`,
  let transport errors propagate untouched, then wrap only the Pydantic construction
  in `try/except ValidationError -> FplApiError`. Catch `ValidationError` explicitly
  rather than the current bare `except Exception` at line 40, which would also
  swallow a `KeyboardInterrupt` or a genuine bug in `_season_from_payload`.
- Keep `_season_from_payload` here. It is FPL-specific and has no business in
  transport.

Follow-on cleanup, worth doing in the same change: `_season_from_payload` is
duplicated verbatim in `storage/cache.py:33-35`. Move it to `api/models.py` as a
`BootstrapSnapshot.from_payload(payload, fetched_at)` classmethod and have both call
sites use it. Both files also repeat the same four-field construction.

### Step 3 — `cli.py`: the minimum, and nothing else

**Decided: no `SnapshotService` extraction in this task.** The stale-cache decision
stays in `cli.py:21-33`. Filed as [FU-1](follow-ups.md).

The only change to `cli.py` is the mandatory one from Decision 3: both
`except FplApiError` clauses (`cli.py:27`, `cli.py:43`) become `except FplError`.
Without it the fallback stops catching HTTP failures entirely.

The two constructor call sites (`cli.py:24`, `cli.py:39`) are `OfficialFplApi()` with
no arguments, so dropping the `client`/`base_url` parameters in Step 2 needs no edit
here.

Explicitly **not** fixed in this task, both filed as follow-ups:

- [FU-2](follow-ups.md) — `load_snapshot` never writes the cache on a successful
  fetch (`cli.py:26`).
- [FU-3](follow-ups.md) — `typer.Exit` is passed a message where it expects an exit
  code (`cli.py:31`, `cli.py:44`, `cli.py:87`).

FU-2 constrains Step 4: the "live fetch populates the cache" assertion cannot be
written yet, because the behaviour it asserts does not exist. It is listed in FU-2 as
part of that fix rather than added here as a known-failing test.

### Step 4 — tests

Add `tests/conftest.py`:
- `bootstrap_payload` — a minimal but valid synthetic `bootstrap-static` dict,
  reusing the shape already built in `tests/test_rules.py:7-24`. Extract that
  builder into the fixture so there is one synthetic dataset, not two.
- `recording_sleep` — a callable that appends delays to a list instead of sleeping.

`tests/test_transport.py` (respx; already a dev dependency in `pyproject.toml:22`):

| Test | Asserts |
| --- | --- |
| timeout then success | `httpx.ReadTimeout` side effect, then 200; one result, two requests |
| timeout exhausted | `RequestTimeout` raised, `attempts == 3`, `len(sleeps) == 2` |
| connect error retried | same path as timeout, via `httpx.ConnectError` |
| 503 then success | retried, returns payload |
| 5xx exhausted | `ServerError`, `status_code == 503` |
| **429 with `Retry-After: 1`** | exactly one retry, `sleeps == [1.0]` — header honoured, not backoff |
| **429 with `Retry-After: 3600`** | **no** retry, one request, `RateLimited.retry_after == 3600` |
| **429 with no header** | no retry, `RateLimited.retry_after is None` |
| 429 with unparseable header | treated as absent, no retry, no exception from parsing |
| 403 | `AccessDenied`, exactly one request, message mentions blocking |
| 404 | `NotFound`, exactly one request |
| malformed body (`"<html>…"`, 200) | `MalformedResponse`, exactly one request |
| JSON scalar body (`200`, `"null"`) | `MalformedResponse` |
| backoff sequence | recorded delays are increasing and within the jitter band of `[0.5, 1.0]`; no sleep after the last attempt |
| injected client not closed | `close()` leaves an injected client usable |

`tests/test_official.py`:
- Valid payload via a stub transport → `BootstrapSnapshot`, season parsed correctly.
- Season derivation falls back to `"unknown"` when `static_content_url` is absent.
- Schema mismatch (`elements` is a string) → `FplApiError`, and it is *not* a
  `TransportError`.
- A `RateLimited` raised by the transport propagates as `RateLimited`, not
  re-wrapped as `FplApiError`. This is the regression guard for the current
  behaviour of collapsing everything into one error type.

`tests/test_stale_cache.py` (stale-cache fallback, `tmp_path` for the cache file):

With FU-1 deferred, this tests `cli.load_snapshot` directly. It is a module-level
function, so `CliRunner` is not needed — but `load_snapshot` constructs both its
collaborators internally (`cli.py:22-24`), so the test must monkeypatch
`fpl_cli.cli.OfficialFplApi` and `fpl_cli.cli.SnapshotCache`. That patching of module
globals is the accepted inelegance; FU-1 removes it.

- Transport raises, cache present → returns the cached snapshot, `fetched_at` matches
  the cached file's mtime.
- Transport raises, no cache → raises `typer.Exit`. Assert the type only, not the
  message — the message is currently smuggled through the exit-code slot (FU-3).
- Transport raises, cache file corrupt → raises `typer.Exit`, not a crash
  (`cache.load` already returns `None` here, `storage/cache.py:29`).
- A `RateLimited` and a `MalformedResponse` both trigger the fallback, not just a
  timeout. This is the test that would have caught the `except FplError` change being
  missed.

Not covered here: that a successful fetch populates the cache. See FU-2.

Run with `pytest -q`. No live API calls; respx fails the test if an unmocked request
escapes.

### Step 5 — docs

- README: replace "Setup and Windows usage" in the Agent Plan's documentation
  section — the repo is Linux-only per `CLAUDE.md`, and the same stale Windows
  reference survives at line 130 ("Run Windows CLI smoke tests").
- README Status section: add a short paragraph on retry behaviour, specifically that
  429 is deliberately not retried aggressively.

---

## Decisions taken

1. **429 retry policy** — one retry only when `Retry-After` is present and ≤ 5s;
   otherwise fail immediately with `retry_after` surfaced.
2. **Error hierarchy** — typed subclasses under a shared `FplError` base defined in
   `transport.py`.
3. **`get_json` return type** — decoded JSON, so transport owns malformed bodies.
4. **Scope** — no `SnapshotService` extraction; the stale-cache decision stays in
   `cli.py` and its test monkeypatches module globals. See
   [follow-ups.md](follow-ups.md).

## Scope boundary

In scope: `transport.py` (new), `api/official.py` (rewrite), the `except FplError`
change in `cli.py`, `_season_from_payload` de-duplication, the four test modules,
README wording.

Out of scope, filed: FU-1 (`SnapshotService`), FU-2 (cache not written on fetch),
FU-3 (`typer.Exit` misuse), FU-4 (SQLite cache backend).

## Assumptions

- [Only `bootstrap-static` is in scope. `fixtures`, `element-summary/{id}` and
  `event/{gw}/live` will reuse `get_json` unchanged when they are added; the
  per-player endpoint is the one likely to trip the rate limit, which is another
  reason to get 429 handling right now.]
- [No SQLite work here. `storage/cache.py` is raw-JSON only today despite the plan
  naming SQLite; filed as FU-4.]
- [The current `User-Agent` (`fpl-cli/0.1`) is kept. If 403s turn out to be
  UA-driven in practice, the constructor keyword makes it a one-line change.]

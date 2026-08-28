"""FU-3: `typer.Exit` takes an exit code, not a message.

Nine call sites passed a string, so the intended exit code was discarded and
the message reached the user only through `sys.exit(str)` semantics. The count
grew three -> eight -> nine because each new command copied the idiom from the
last, which is why this file guards the *shape* as well as the behaviour:
`test_no_typer_exit_is_passed_a_message` fails on a tenth string site the day
it is written, rather than at the next audit.

Every failure path asserts the same two things: the process exits 1, and the
message lands on stderr (never stdout) so redirecting stdout does not swallow
it — the behaviour `sys.exit(str)` gave by accident and `error_console`
now gives on purpose.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.api.snapshots import FixturesResult, SnapshotResult
from fpl_cli.transport import RequestTimeout

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "fpl_cli"


class _Service:
    """A `SnapshotService` stub whose every method can be made to fail.

    Installed through `lambda **_:` so it absorbs the constructor arguments the
    CLI passes — `sync` now forwards `--archive-dir`. These tests are about exit
    codes, so where a capture is filed is not their business; that routing is
    covered in `test_archive_dir.py`.
    """

    def __init__(
        self,
        snapshot: BootstrapSnapshot | None = None,
        *,
        load_error: Exception | None = None,
        refresh_error: Exception | None = None,
        fixtures_error: Exception | None = None,
        live_error: Exception | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._load_error = load_error
        self._refresh_error = refresh_error
        self._fixtures_error = fixtures_error
        self._live_error = live_error
        self.closed = False

    def load(self) -> SnapshotResult:
        if self._load_error is not None:
            raise self._load_error
        assert self._snapshot is not None
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def refresh(self) -> BootstrapSnapshot:
        if self._refresh_error is not None:
            raise self._refresh_error
        assert self._snapshot is not None
        return self._snapshot

    def refresh_fixtures(self) -> list[Fixture]:
        return []

    def archive(self, snapshot: BootstrapSnapshot) -> Path:
        return Path("/dev/null")

    def load_fixtures(self) -> FixturesResult:
        if self._fixtures_error is not None:
            raise self._fixtures_error
        return FixturesResult(fixtures=[], fetched_at=datetime.now(UTC), stale=False)

    def load_event_live(self, event: int, snapshot: BootstrapSnapshot) -> object:
        if self._live_error is not None:
            raise self._live_error
        raise AssertionError("not reached in these tests")

    def close(self) -> None:
        self.closed = True


def _timeout() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


def _write_ledger(path: Path, player_ids: list[int], *, event: int = 1) -> None:
    log = ", ".join(f'{{"event": {event}, "type": "buy", "player": {pid}, "price": 50}}' for pid in player_ids)
    path.write_text(f'{{"version": 1, "genesis_event": {event}, "log": [{log}]}}', encoding="utf-8")


def _assert_failed_cleanly(
    capsys: pytest.CaptureFixture[str], info: pytest.ExceptionInfo[typer.Exit], fragment: str
) -> None:
    """The two guarantees FU-3 restores: a real exit code, and stderr."""
    assert info.value.exit_code == 1
    captured = capsys.readouterr()
    # Rich wraps to the console width, so compare on collapsed whitespace.
    err = " ".join(captured.err.split())
    out = " ".join(captured.out.split())
    needle = " ".join(fragment.split())
    assert needle in err, f"expected {needle!r} on stderr, got {err!r}"
    assert needle not in out, f"{needle!r} leaked to stdout: {out!r}"


# --- load_snapshot / sync -------------------------------------------------


def test_load_snapshot_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(load_error=_timeout()))

    with pytest.raises(typer.Exit) as info:
        cli.load_snapshot()

    _assert_failed_cleanly(capsys, info, "No live snapshot or cached snapshot is available.")


def test_sync_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(refresh_error=_timeout()))

    with pytest.raises(typer.Exit) as info:
        cli.sync()

    _assert_failed_cleanly(capsys, info, "timed out")


# --- squad validate -------------------------------------------------------


def test_validate_squad_unreadable_file_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))
    path = tmp_path / "notasquad.json"
    path.write_text('{"nonsense": [1, 2]}', encoding="utf-8")

    with pytest.raises(typer.Exit) as info:
        cli.validate_squad(path)

    _assert_failed_cleanly(capsys, info, "Could not read squad plan")


# --- plan simulate --------------------------------------------------------


def test_simulate_unreadable_ledger_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    squad_path.write_text("{ this is not json", encoding="utf-8")
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text("[]", encoding="utf-8")

    with pytest.raises(typer.Exit) as info:
        cli.simulate_plan(squad_path, transfers_path)

    _assert_failed_cleanly(capsys, info, "Could not read squad ledger")


def test_simulate_unreadable_transfers_plan_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    _write_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text("{ also not json", encoding="utf-8")

    with pytest.raises(typer.Exit) as info:
        cli.simulate_plan(squad_path, transfers_path)

    _assert_failed_cleanly(capsys, info, "Could not read transfers plan")


def test_simulate_invalid_transfers_plan_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """A plan for a gameweek the squad has already moved past — `simulate`
    raises `ValueError`, a different except block from the parse failures."""
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))
    squad_path = tmp_path / "squad.json"
    _write_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text('[{"event": 1, "transfers": []}]', encoding="utf-8")

    with pytest.raises(typer.Exit) as info:
        cli.simulate_plan(squad_path, transfers_path)

    _assert_failed_cleanly(capsys, info, "Invalid transfers plan")


def test_simulate_fixtures_failure_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(
        cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot, fixtures_error=_timeout())
    )
    squad_path = tmp_path / "squad.json"
    _write_ledger(squad_path, list(range(1, 16)))
    transfers_path = tmp_path / "transfers.json"
    transfers_path.write_text("[]", encoding="utf-8")

    with pytest.raises(typer.Exit) as info:
        cli.simulate_plan(squad_path, transfers_path)

    _assert_failed_cleanly(capsys, info, "Could not load fixtures")


# --- plan evaluate --------------------------------------------------------


def test_evaluate_unknown_gameweek_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))

    with pytest.raises(typer.Exit) as info:
        cli.evaluate_plan(event=99)

    _assert_failed_cleanly(capsys, info, "No gameweek 99 in the current snapshot.")


def test_evaluate_fixtures_failure_exits_1_with_message_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    monkeypatch.setattr(
        cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot, fixtures_error=_timeout())
    )

    with pytest.raises(typer.Exit) as info:
        cli.evaluate_plan(event=1)

    _assert_failed_cleanly(capsys, info, "timed out")


# --- the guard against a tenth site ---------------------------------------


def _typer_exit_calls(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == "Exit":
            calls.append(node)
    return calls


def test_no_typer_exit_is_passed_a_message() -> None:
    """`typer.Exit.__init__` is `(self, code: int = 0)`.

    Passing a string discards the exit code and prints via `sys.exit(str)`.
    This scans the source rather than the behaviour so that a new command
    copying the old idiom fails here immediately — the growth from three sites
    to nine happened one copied line at a time, with nothing to catch it.
    """
    offenders = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _typer_exit_calls(tree):
            if not call.args:
                continue
            first = call.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, int)):
                offenders.append(f"{path.relative_to(SRC_ROOT.parents[1])}:{call.lineno}")

    assert not offenders, (
        "typer.Exit must be given an integer exit code, not a message. "
        f"Print the message to `presentation.error_console` first. Offending sites: {offenders}"
    )


def test_guard_catches_a_string_exit() -> None:
    """The guard above is only worth having if it actually fails — check it
    rejects the exact idiom FU-3 is about."""
    tree = ast.parse('import typer\nraise typer.Exit("a message")\n')
    calls = _typer_exit_calls(tree)

    assert len(calls) == 1
    first = calls[0].args[0]
    assert not (isinstance(first, ast.Constant) and isinstance(first.value, int))

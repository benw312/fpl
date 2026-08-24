from __future__ import annotations

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import SnapshotResult
from fpl_cli.transport import RequestTimeout


class StubService:
    def __init__(
        self,
        *,
        load_result: SnapshotResult | None = None,
        load_error: Exception | None = None,
        refresh_result: BootstrapSnapshot | None = None,
        refresh_error: Exception | None = None,
    ) -> None:
        self._load_result = load_result
        self._load_error = load_error
        self._refresh_result = refresh_result
        self._refresh_error = refresh_error
        self.closed = False

    def load(self) -> SnapshotResult:
        if self._load_error is not None:
            raise self._load_error
        assert self._load_result is not None
        return self._load_result

    def refresh(self) -> BootstrapSnapshot:
        if self._refresh_error is not None:
            raise self._refresh_error
        assert self._refresh_result is not None
        return self._refresh_result

    def close(self) -> None:
        self.closed = True


def _timeout_error() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


def test_load_snapshot_returns_stale_result_without_raising(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    result = SnapshotResult(snapshot=bootstrap_snapshot, stale=True, reason="timed out")
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(load_result=result))

    snapshot = cli.load_snapshot()

    assert snapshot is bootstrap_snapshot


def test_load_snapshot_raises_typer_exit_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(load_error=_timeout_error()))

    with pytest.raises(typer.Exit):
        cli.load_snapshot()


def test_sync_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(refresh_result=bootstrap_snapshot))

    cli.sync()

    assert "Synced 15 players" in capsys.readouterr().out


def test_sync_raises_typer_exit_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(refresh_error=_timeout_error()))

    with pytest.raises(typer.Exit):
        cli.sync()

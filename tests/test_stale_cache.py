from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.storage.cache import SnapshotCache
from fpl_cli.transport import MalformedResponse, RateLimited, RequestTimeout


class FailingApi:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def bootstrap_static(self) -> BootstrapSnapshot:
        raise self._error

    def close(self) -> None:
        pass


def _install_failing_api(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    monkeypatch.setattr(cli, "OfficialFplApi", lambda: FailingApi(error))


def _install_cache(monkeypatch: pytest.MonkeyPatch, cache: SnapshotCache) -> None:
    monkeypatch.setattr(cli, "SnapshotCache", lambda: cache)


def _timeout_error() -> RequestTimeout:
    return RequestTimeout("timed out", url="https://fpl.test", status_code=None, attempts=3)


@pytest.mark.parametrize(
    "error",
    [
        _timeout_error(),
        RateLimited("rate limited", url="https://fpl.test", status_code=429, attempts=1, retry_after=None),
        MalformedResponse("bad body", url="https://fpl.test", status_code=200, attempts=1),
    ],
    ids=["timeout", "rate_limited", "malformed"],
)
def test_falls_back_to_cache_on_any_fpl_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bootstrap_payload: dict[str, Any], error: Exception
) -> None:
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_text(json.dumps(bootstrap_payload), encoding="utf-8")

    _install_failing_api(monkeypatch, error)
    _install_cache(monkeypatch, cache)

    result = cli.load_snapshot()

    expected_mtime = cache.path.stat().st_mtime
    assert result.fetched_at.timestamp() == pytest.approx(expected_mtime)
    assert len(result.elements) == 15


def test_raises_when_no_cache_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    _install_failing_api(monkeypatch, _timeout_error())
    _install_cache(monkeypatch, cache)

    with pytest.raises(typer.Exit):
        cli.load_snapshot()


def test_raises_when_cache_file_is_corrupt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cache = SnapshotCache(path=tmp_path / "bootstrap-static.json")
    cache.path.parent.mkdir(parents=True, exist_ok=True)
    cache.path.write_text("not json", encoding="utf-8")

    _install_failing_api(monkeypatch, _timeout_error())
    _install_cache(monkeypatch, cache)

    with pytest.raises(typer.Exit):
        cli.load_snapshot()

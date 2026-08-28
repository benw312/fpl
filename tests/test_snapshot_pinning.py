"""`--snapshot` / `FPL_SNAPSHOT` (docs/plans/snapshot-pinning.md).

Every test here demonstrates its property rather than asserting it: the
no-network test proves the network *would* have been reached unpinned, the
cache test proves the cache *would* have moved unpinned, and the no-fallback
tests leave a perfectly usable cache and a perfectly usable live API in place
so that falling back would visibly succeed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api import snapshots


class NetworkTouched(RuntimeError):
    """Raised by the stub transport when a run reaches for the network.

    Not an `FplError`, so nothing in the CLI's `except FplError:` handlers can
    swallow it into a stale-cache fallback and hide the very thing under test.
    """


@pytest.fixture
def fpl_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect every path the CLI would otherwise touch under `~/.fpl-cli`.

    The fixtures and event-live defaults are module globals read inside
    `__init__`, so patching them here is enough. `SnapshotCache`'s default is
    built inline in its own `__init__`, so that one is redirected by wrapping
    the class where `SnapshotService` looks it up.
    """
    home = tmp_path / "fpl-home"
    home.mkdir()
    monkeypatch.setattr(snapshots, "_DEFAULT_FIXTURES_PATH", home / "fixtures.json")
    monkeypatch.setattr(snapshots, "_DEFAULT_EVENT_LIVE_DIR", home / "events")
    monkeypatch.setattr(snapshots, "DEFAULT_ARCHIVE_DIR", home / "archive")
    real_cache = snapshots.SnapshotCache
    monkeypatch.setattr(
        snapshots,
        "SnapshotCache",
        lambda path=None: real_cache(path or home / "bootstrap-static.json"),
    )
    monkeypatch.delenv(cli.SNAPSHOT_ENV_VAR, raising=False)
    return home


def _events() -> list[dict[str, Any]]:
    """GW1 long past, GW2 and GW3 far enough ahead never to expire.

    Deadlines in 2099 keep `now` out of the result: two pinned runs seconds
    apart must agree, and a deadline that could pass mid-suite would make free
    transfer accrual a function of the clock.
    """
    return [
        {"id": 1, "name": "Gameweek 1", "deadline_time": "2020-08-14T17:30:00Z", "finished": True, "is_previous": True},
        {"id": 2, "name": "Gameweek 2", "deadline_time": "2099-01-01T17:30:00Z", "is_next": True},
        {"id": 3, "name": "Gameweek 3", "deadline_time": "2099-01-08T17:30:00Z"},
    ]


def _capture_payload(bootstrap_payload: dict[str, Any], *, star_name: str) -> dict[str, Any]:
    """A bootstrap-static payload rigged so `optimise --model naive` has one winner.

    The squad is ids 1-15 at 50 each; DEF ids 4-7 score 1.0 a game, DEF id 3
    scores nothing, and `star_name` (id 101, club 6, otherwise unheld) scores
    20.0. Selling 3 for 101 strictly beats every other swap, so the search has
    a winner rather than a tie. `star_name` doubles as the marker that says
    which capture a run actually read.
    """
    payload = copy.deepcopy(bootstrap_payload)
    payload["events"] = _events()
    payload["teams"].append({"id": 6, "name": "Club 6", "short_name": "C6"})
    for element in payload["elements"]:
        if element["id"] in (4, 5, 6, 7):
            element["points_per_game"] = "1.0"
    payload["elements"].append(
        {
            "id": 101,
            "web_name": star_name,
            "team": 6,
            "element_type": 2,
            "now_cost": 50,
            "points_per_game": "20.0",
        }
    )
    return payload


def _write_capture(path: Path, bootstrap_payload: dict[str, Any], *, star_name: str = "Star") -> Path:
    path.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name=star_name)), encoding="utf-8")
    return path


def _write_fixtures_cache(home: Path) -> Path:
    """One GW2 fixture per club, so every player in the capture has a game."""
    path = home / "fixtures.json"
    path.write_text(
        json.dumps(
            [
                {"id": 1, "event": 2, "team_h": 1, "team_a": 2},
                {"id": 2, "event": 2, "team_h": 3, "team_a": 4},
                {"id": 3, "event": 2, "team_h": 5, "team_a": 6},
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_squad_ledger(path: Path) -> Path:
    log = ", ".join(f'{{"event": 1, "type": "buy", "player": {pid}, "price": 50}}' for pid in range(1, 16))
    path.write_text(f'{{"version": 1, "genesis_event": 1, "log": [{log}]}}', encoding="utf-8")
    return path


def _optimise(squad_path: Path, *, snapshot_path: Path | None, json_output: bool = True) -> None:
    cli.optimise_plan(
        squad_path,
        horizon=1,
        from_event=2,
        paths=3,
        max_hit=None,
        model="naive",
        decay=0.84,
        robustness="off",
        explain=False,
        output=None,
        json_output=json_output,
        snapshot_path=snapshot_path,
    )


def _fingerprint(path: Path) -> tuple[bytes, int]:
    """Contents and mtime. A rewrite with identical bytes still moves mtime."""
    return path.read_bytes(), path.stat().st_mtime_ns


# --- resolution: the flag, the environment, and their precedence -------------


def test_resolve_snapshot_path_returns_none_when_neither_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.SNAPSHOT_ENV_VAR, raising=False)

    assert cli.resolve_snapshot_path(None) is None


def test_resolve_snapshot_path_reads_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, "/captures/from-env.json")

    assert cli.resolve_snapshot_path(None) == Path("/captures/from-env.json")


def test_resolve_snapshot_path_prefers_the_flag_over_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, "/captures/from-env.json")

    assert cli.resolve_snapshot_path(Path("/captures/from-flag.json")) == Path("/captures/from-flag.json")


def test_resolve_snapshot_path_treats_a_blank_env_var_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """`FPL_SNAPSHOT=` must not resolve to `Path("")`, which is the cwd."""
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, "   ")

    assert cli.resolve_snapshot_path(None) is None


def test_snapshot_service_is_read_only_only_when_pinned(tmp_path: Path) -> None:
    assert isinstance(cli.snapshot_service(tmp_path / "capture.json"), snapshots.PinnedSnapshotService)
    assert isinstance(cli.snapshot_service(None), snapshots.SnapshotService)


# --- the two properties that make a run pinned ------------------------------


def test_a_pinned_run_makes_no_network_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    """Pinned, the transport is never reached; unpinned, the same call hits it.

    The control matters: without it, a passing test would be equally consistent
    with `plan optimise` having quietly stopped needing the network at all.
    """
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)
    capture = _write_capture(tmp_path / "capture.json", bootstrap_payload)
    _write_fixtures_cache(fpl_home)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=capture)
    payload = json.loads(capsys.readouterr().out)

    assert payload["recommendation"]["description"].startswith("P3→Star")

    with pytest.raises(NetworkTouched):
        _optimise(squad_path, snapshot_path=None)


def test_a_pinned_run_leaves_the_cache_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    """Pinned, neither cache file moves; unpinned, both are rewritten.

    The live payloads differ from the cached ones, so the control shows a
    changed file rather than only a changed mtime.
    """
    live_bootstrap = _capture_payload(bootstrap_payload, star_name="Live")
    live_fixtures = [{"id": 9, "event": 2, "team_h": 1, "team_a": 2}]

    def serve(self: object, path: str, **kwargs: object) -> object:
        return live_fixtures if "fixtures" in path else live_bootstrap

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", serve)
    capture = _write_capture(tmp_path / "capture.json", bootstrap_payload)
    fixtures_cache = _write_fixtures_cache(fpl_home)
    bootstrap_cache = fpl_home / "bootstrap-static.json"
    bootstrap_cache.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name="Cached")), encoding="utf-8")
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    before = (_fingerprint(bootstrap_cache), _fingerprint(fixtures_cache))

    _optimise(squad_path, snapshot_path=capture)
    capsys.readouterr()

    assert (_fingerprint(bootstrap_cache), _fingerprint(fixtures_cache)) == before

    _optimise(squad_path, snapshot_path=None)
    capsys.readouterr()

    assert (_fingerprint(bootstrap_cache), _fingerprint(fixtures_cache)) != before
    assert b"Live" in bootstrap_cache.read_bytes()


def test_two_pinned_runs_against_one_capture_produce_identical_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)
    capture = _write_capture(tmp_path / "capture.json", bootstrap_payload)
    _write_fixtures_cache(fpl_home)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    _optimise(squad_path, snapshot_path=capture)
    first = capsys.readouterr().out
    _optimise(squad_path, snapshot_path=capture)
    second = capsys.readouterr().out

    assert first == second
    assert json.loads(first)["recommendation"]["description"]  # not identically empty


# --- no fallback, ever ------------------------------------------------------


def _usable_cache_and_api(
    monkeypatch: pytest.MonkeyPatch, fpl_home: Path, bootstrap_payload: dict[str, Any]
) -> Path:
    """Leave a working cache *and* a working live API in place.

    Both are deliberately usable, so a fallback of either kind would succeed
    and print a player table. A test that only checked for a non-zero exit
    could not tell "refused to fall back" from "fell back and then failed".
    """
    def serve(self: object, path: str, **kwargs: object) -> object:
        return [] if "fixtures" in path else _capture_payload(bootstrap_payload, star_name="Live")

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", serve)
    cache = fpl_home / "bootstrap-static.json"
    cache.write_text(json.dumps(_capture_payload(bootstrap_payload, star_name="Cached")), encoding="utf-8")
    return cache


def test_a_missing_pinned_path_is_a_hard_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    cache = _usable_cache_and_api(monkeypatch, fpl_home, bootstrap_payload)
    before = _fingerprint(cache)
    missing = tmp_path / "no-such-capture.json"

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=missing
        )

    assert exit_info.value.exit_code == 1
    captured = capsys.readouterr()
    assert str(missing) in captured.err
    # Names the pinning, not just the path: an `OSError` already carries the
    # path in its own text, so "the path appears somewhere on stderr" would
    # also hold for the generic "no snapshot available" handler.
    assert "pinned" in captured.err.lower()
    # Neither fallback ran: the live star and the cached star are both absent,
    # and the cache the live path would have rewritten has not moved.
    assert "Live" not in captured.out
    assert "Cached" not in captured.out
    assert _fingerprint(cache) == before


def test_an_unparseable_pinned_file_is_a_hard_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    cache = _usable_cache_and_api(monkeypatch, fpl_home, bootstrap_payload)
    before = _fingerprint(cache)
    corrupt = tmp_path / "truncated.json"
    corrupt.write_text('{"elements": [', encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=corrupt
        )

    assert exit_info.value.exit_code == 1
    captured = capsys.readouterr()
    assert str(corrupt) in captured.err
    assert "pinned" in captured.err.lower()
    assert "Live" not in captured.out
    assert "Cached" not in captured.out
    assert _fingerprint(cache) == before


def test_a_pinned_file_of_the_wrong_shape_is_a_hard_error_naming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    """Valid JSON, wrong document — a fixtures capture pinned by mistake."""
    _usable_cache_and_api(monkeypatch, fpl_home, bootstrap_payload)
    wrong = tmp_path / "fixtures-not-bootstrap.json"
    wrong.write_text(json.dumps([{"id": 1, "event": 2, "team_h": 1, "team_a": 2}]), encoding="utf-8")

    with pytest.raises(typer.Exit) as exit_info:
        cli.list_players(
            position=None, club=None, name=None, available_only=False, limit=25, snapshot_path=wrong
        )

    assert exit_info.value.exit_code == 1
    captured = capsys.readouterr()
    assert str(wrong) in captured.err
    assert "pinned" in captured.err.lower()
    assert "Cached" not in captured.out


def test_a_pinned_run_without_a_fixtures_cache_says_so_rather_than_fetching(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    """The capture format is bootstrap-static only (snapshot-pinning.md §5)."""
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)
    capture = _write_capture(tmp_path / "capture.json", bootstrap_payload)
    squad_path = _write_squad_ledger(tmp_path / "squad.json")

    with pytest.raises(typer.Exit) as exit_info:
        _optimise(squad_path, snapshot_path=capture)

    assert exit_info.value.exit_code == 1
    assert str(fpl_home / "fixtures.json") in capsys.readouterr().err


# --- flag over environment, end to end --------------------------------------


def _list_players(snapshot_path: Path | None) -> None:
    cli.list_players(
        position=None, club=None, name=None, available_only=False, limit=200, snapshot_path=snapshot_path
    )


def test_the_env_var_pins_a_run_on_its_own(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    """Without this, "the flag wins" would be true of a variable nothing reads."""
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)
    from_env = _write_capture(tmp_path / "env.json", bootstrap_payload, star_name="FromEnv")
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, str(from_env))

    _list_players(None)

    assert "FromEnv" in capsys.readouterr().out


def test_the_flag_overrides_the_env_var(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fpl_home: Path,
    bootstrap_payload: dict[str, Any],
) -> None:
    def refuse(self: object, path: str, **kwargs: object) -> object:
        raise NetworkTouched(path)

    monkeypatch.setattr("fpl_cli.transport.FplTransport.get_json", refuse)
    from_env = _write_capture(tmp_path / "env.json", bootstrap_payload, star_name="FromEnv")
    from_flag = _write_capture(tmp_path / "flag.json", bootstrap_payload, star_name="FromFlag")
    monkeypatch.setenv(cli.SNAPSHOT_ENV_VAR, str(from_env))

    _list_players(from_flag)

    out = capsys.readouterr().out
    assert "FromFlag" in out
    assert "FromEnv" not in out

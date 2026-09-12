"""FU-17: `players list --club` failed silently on an unknown club.

`clubs.get(club.lower())` returned `None`, and the filter turned that into an
empty result with no message — the same output a real club with no matching
players produces. Four lines above, `--position` already raised
`typer.BadParameter` for exactly this class of error, so the defect was an
inconsistency inside one function rather than a missing convention.

Each test below names the mutation it must fail against, and each mutation was
demonstrated failing before the test was kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import SnapshotResult


class _Service:
    """Minimal `SnapshotService` stub — these tests never reach the network."""

    def __init__(self, snapshot: BootstrapSnapshot) -> None:
        self._snapshot = snapshot

    def load(self) -> SnapshotResult:
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def close(self) -> None:
        return None


def _list(club: str | None, *, snapshot_path: Path | None = None) -> None:
    """Every option passed explicitly: calling a Typer command directly leaves
    unpassed parameters as `OptionInfo` objects, not their defaults."""
    cli.list_players(
        position=None, club=club, name=None, available_only=False, limit=200, snapshot_path=snapshot_path
    )


@pytest.fixture(autouse=True)
def _stub_service(monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda **_: _Service(bootstrap_snapshot))


def test_unknown_club_raises_bad_parameter() -> None:
    """The defect itself.

    Mutation it must fail against: restoring the original
    `... if club_id else []`, which returns an empty list and raises nothing.
    """
    with pytest.raises(typer.BadParameter) as info:
        _list("Not A Club")

    assert "Not A Club" in str(info.value)


def test_the_message_lists_the_clubs_that_would_have_worked() -> None:
    """Naming the bad value is not enough on its own.

    `--club` matches `Club.name` only, so a user typing a short name ("LIV")
    gets an error that looks like a typo in a name they believe is correct.
    The valid set is in hand at the point of failure, so it is printed.

    Mutation it must fail against: dropping `known` from the message and
    raising `BadParameter(f"Unknown club {club!r}.")` alone.
    """
    with pytest.raises(typer.BadParameter) as info:
        _list("LIV")

    message = str(info.value)
    assert "Club 1" in message
    assert "Club 5" in message


def test_a_known_club_still_filters_and_does_not_raise(
    capsys: pytest.CaptureFixture[str], bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """The regression guard on the fix.

    Mutation it must fail against: raising unconditionally, i.e. dropping the
    `if club_id is None` test. That turns a working filter into a hard error
    for every club, which no other test here would catch.
    """
    _list("Club 1")

    out = capsys.readouterr().out
    assert out.strip(), "a known club should still print a table"


def test_club_matching_stays_case_insensitive() -> None:
    """`clubs` is keyed on `item.name.lower()` and the lookup lowercases too.

    Mutation it must fail against: dropping the case-folding from *both* the
    keys and the lookup, so exact-case matching still works and only the wrong
    case breaks. That is the mutation this test uniquely catches — it leaves
    the other three here passing.

    Dropping `.lower()` from the lookup alone also fails this test, but it
    fails `test_a_known_club_still_filters_and_does_not_raise` as well, so it
    does not isolate the assertion. Both were demonstrated failing.

    The stake: without this, FU-17's fix converts a silent empty result into a
    loud rejection of a correctly-spelled club, which is worse than the defect.
    """
    _list("cLuB 1")

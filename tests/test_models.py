from __future__ import annotations

from fpl_cli.api.models import BootstrapSnapshot


def test_snapshot_lookups_are_built_once(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """FU-23: the lookups are memoised, not rebuilt on every access."""
    assert bootstrap_snapshot.players_by_id is bootstrap_snapshot.players_by_id
    assert bootstrap_snapshot.clubs is bootstrap_snapshot.clubs
    assert bootstrap_snapshot.positions is bootstrap_snapshot.positions


def test_snapshot_lookups_match_their_source_lists(bootstrap_snapshot: BootstrapSnapshot) -> None:
    assert bootstrap_snapshot.players_by_id == {player.id: player for player in bootstrap_snapshot.elements}
    assert bootstrap_snapshot.clubs == {club.id: club for club in bootstrap_snapshot.teams}
    assert bootstrap_snapshot.positions == {position.id: position for position in bootstrap_snapshot.element_types}


def test_memoised_lookups_are_not_serialised(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """The cached values live in the model's `__dict__`; they must stay out of dumps."""
    _ = bootstrap_snapshot.players_by_id, bootstrap_snapshot.clubs, bootstrap_snapshot.positions

    dumped = bootstrap_snapshot.model_dump()

    assert not {"players_by_id", "clubs", "positions"} & dumped.keys()

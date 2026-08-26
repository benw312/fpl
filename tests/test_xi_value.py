"""FU-24: `xi_value` is the value half of `best_xi`, and must not drift from it.

optimizer-search.md §8 names one property test as the guard that keeps the
fast path honest: `xi_value` ≡ `objective_points(best_xi(...))` on random
15-player squads. It matters more than a normal equality test because the two
functions are two expressions of the objective, and CLAUDE.md requires that
the optimiser and manual planning select an XI by one rule. FU-26's numpy
kernel becomes a third expression and inherits this same contract.

The comparison is `pytest.approx(rel=1e-9)` rather than `==`: both sides add
the same per-position totals, but `objective_points` sums the winning XI
player by player in ID order while `xi_value` sums four prefix totals, and
float addition is not associative. 1e-9 is the tolerance §6.2's by-hand run
against the live snapshot used.
"""

from __future__ import annotations

import random

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.squad import best_xi, legal_formations, objective_points, xi_value

from conftest import add_players

# `bootstrap_snapshot` holds one player per required slot: GKP 1-2, DEF 3-7,
# MID 8-12, FWD 13-15. A property test needs a choice of squad, so the pool is
# widened below and squads are drawn from it.
_POSITION_OF = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
_SQUAD_SELECT = {1: 2, 2: 5, 3: 5, 4: 3}
_EXTRA_PER_POSITION = 6


def _projection(player_id: int, xp: float) -> Projection:
    return Projection(
        player=player_id,
        event=1,
        xp_total=xp,
        xp_appearance=0.0,
        xp_attack=0.0,
        xp_clean_sheet=0.0,
        xp_conceded=0.0,
        xp_saves=0.0,
        xp_defcon=0.0,
        xp_bonus=0.0,
        xp_cards=0.0,
        p_start=1.0,
        xmins=90.0,
        fixtures=1,
        model_version="test",
    )


def _widen(snapshot: BootstrapSnapshot) -> dict[int, list[int]]:
    """Add spare players in every position; return the pool by position id."""
    next_id = max(player.id for player in snapshot.elements) + 1
    extras = []
    for position_id in _SQUAD_SELECT:
        for _ in range(_EXTRA_PER_POSITION):
            extras.append(
                Player(
                    id=next_id,
                    web_name=f"P{next_id}",
                    team=(next_id % 5) + 1,
                    element_type=position_id,
                    now_cost=50,
                )
            )
            next_id += 1
    add_players(snapshot, *extras)

    pool: dict[int, list[int]] = {position_id: [] for position_id in _SQUAD_SELECT}
    for player in snapshot.elements:
        pool[player.element_type].append(player.id)
    return pool


def _random_squad(pool: dict[int, list[int]], rng: random.Random) -> list[int]:
    """A legal 15: exactly `squad_select` players in each position."""
    return [
        player_id
        for position_id, count in _SQUAD_SELECT.items()
        for player_id in rng.sample(pool[position_id], count)
    ]


@pytest.mark.parametrize(
    ("label", "draw_xp"),
    [
        # Distinct values: one formation wins outright, no tie-break involved.
        ("distinct", lambda rng: rng.uniform(0.0, 15.0)),
        # Coarse values: deliberate collisions, so formations tie on total and
        # `best_xi` has to choose a witness among equals.
        ("colliding", lambda rng: float(rng.randint(0, 3))),
        # Negative xP is reachable (cards, own goals) and must not tempt the
        # value half into fielding fewer than `squad_squadplay` starters.
        ("with-negatives", lambda rng: rng.uniform(-4.0, 8.0)),
        # All equal: every legal formation ties, the widest tie-break case.
        ("all-equal", lambda rng: 2.0),
    ],
)
def test_xi_value_equals_objective_points_of_best_xi(
    bootstrap_snapshot: BootstrapSnapshot, label: str, draw_xp
) -> None:
    pool = _widen(bootstrap_snapshot)
    rng = random.Random(f"fu-24-{label}")

    for _ in range(200):
        squad = _random_squad(pool, rng)
        projections = {player_id: _projection(player_id, draw_xp(rng)) for player_id in squad}

        value = xi_value(squad, projections, bootstrap_snapshot)
        witness = best_xi(squad, projections, bootstrap_snapshot)

        assert value == pytest.approx(objective_points(witness, projections), rel=1e-9, abs=1e-9), (
            f"squad={sorted(squad)} xp={{{', '.join(f'{p}: {projections[p].xp_total:.4f}' for p in sorted(squad))}}}"
        )


def test_best_xi_starters_are_a_legal_formation(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """The witness must be one of the formations `legal_formations` admits —
    otherwise the two halves could agree on a number that no XI can field."""
    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-24-legality")
    formations = legal_formations(bootstrap_snapshot)
    position_order = [position.id for position in bootstrap_snapshot.element_types]

    for _ in range(200):
        squad = _random_squad(pool, rng)
        projections = {player_id: _projection(player_id, rng.uniform(0.0, 15.0)) for player_id in squad}

        witness = best_xi(squad, projections, bootstrap_snapshot)

        counts = dict.fromkeys(position_order, 0)
        for player_id in witness.starters:
            counts[bootstrap_snapshot.players_by_id[player_id].element_type] += 1
        assert tuple(counts[position_id] for position_id in position_order) in formations
        assert len(witness.starters) == bootstrap_snapshot.game_settings.squad_squadplay
        assert set(witness.starters) <= set(squad)
        assert witness.captain in witness.starters


def test_xi_value_picks_the_true_optimum_against_brute_force(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """Both halves share a formation enumeration, so a bug in it would be
    invisible to the equality test above — they would agree on the same wrong
    number. Brute-force every 11-subset of a 15-squad instead, score the legal
    ones directly from the definition, and require the maximum to match."""
    from itertools import combinations

    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-24-bruteforce")
    limits = {
        position.id: (position.squad_min_play, position.squad_max_play)
        for position in bootstrap_snapshot.element_types
    }
    target = bootstrap_snapshot.game_settings.squad_squadplay

    # Enough trials that every legal formation is the unique optimum in some
    # of them: with 10, dropping a formation from the enumeration slipped
    # through here and was caught only by the count assertion below.
    seen_winners: set[tuple[int, ...]] = set()
    for _ in range(120):
        squad = _random_squad(pool, rng)
        projections = {player_id: _projection(player_id, rng.uniform(0.0, 15.0)) for player_id in squad}

        best = None
        for starters in combinations(sorted(squad), target):
            counts = dict.fromkeys(limits, 0)
            for player_id in starters:
                counts[bootstrap_snapshot.players_by_id[player_id].element_type] += 1
            if any(not low <= counts[pid] <= high for pid, (low, high) in limits.items()):
                continue
            total = sum(projections[player_id].xp_total for player_id in starters)
            total += max(projections[player_id].xp_total for player_id in starters)
            best = total if best is None else max(best, total)

        assert best is not None
        assert xi_value(squad, projections, bootstrap_snapshot) == pytest.approx(best, rel=1e-9)

        counts = dict.fromkeys(limits, 0)
        for player_id in best_xi(squad, projections, bootstrap_snapshot).starters:
            counts[bootstrap_snapshot.players_by_id[player_id].element_type] += 1
        seen_winners.add(tuple(counts[position_id] for position_id in limits))

    # The trials must actually exercise the whole formation set, or this test
    # would pass against an enumeration missing the formations it never hit.
    assert seen_winners == set(legal_formations(bootstrap_snapshot))


def test_legal_formations_is_derived_from_the_snapshot(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """Not hardcoded (CLAUDE.md): the set follows the snapshot's own limits."""
    formations = legal_formations(bootstrap_snapshot)

    # GKP 1/1, DEF 3/5, MID 2/5, FWD 1/3, totalling 11 -> 8 combinations.
    assert len(formations) == 8
    assert all(sum(combo) == bootstrap_snapshot.game_settings.squad_squadplay for combo in formations)
    for combo in formations:
        for count, position in zip(combo, bootstrap_snapshot.element_types):
            assert position.squad_min_play <= count <= position.squad_max_play

    # Move the goalposts and the set moves with them.
    bootstrap_snapshot.game_settings.squad_squadplay = 10
    moved = legal_formations(bootstrap_snapshot)
    assert all(sum(combo) == 10 for combo in moved)
    assert moved != formations
    bootstrap_snapshot.game_settings.squad_squadplay = 11


def test_legal_formations_result_is_immutable(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """The value is cached and shared between `xi_value`, `best_xi` and later
    FU-26, so a caller must not be able to mutate it out from under them."""
    assert isinstance(legal_formations(bootstrap_snapshot), tuple)
    with pytest.raises(TypeError):
        legal_formations(bootstrap_snapshot)[0] = (9, 9, 9, 9)  # type: ignore[index]


def test_xi_value_rejects_a_squad_that_cannot_field_a_legal_xi(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """Both halves apply the per-squad feasibility guard, not just `best_xi`
    (optimizer-search.md §6.2 keeps it with the squad, not the formation set)."""
    # Only 2 defenders; DEF requires at least 3 starters.
    player_ids = [1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15]
    projections = {player_id: _projection(player_id, 1.0) for player_id in player_ids}

    with pytest.raises(ValueError, match="DEF"):
        xi_value(player_ids, projections, bootstrap_snapshot)
    with pytest.raises(ValueError, match="DEF"):
        best_xi(player_ids, projections, bootstrap_snapshot)

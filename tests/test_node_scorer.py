"""FU-26: the vectorised kernel must agree with the pure-Python reference.

optimizer-search.md §8 makes this the guard that keeps the fast path honest,
and with a numpy kernel it stops being optional: `NodeScorer` is a *third*
expression of the objective, after `best_xi` and `xi_value`, and this file is
the only thing tying it to the rule `validate_plan` uses (CLAUDE.md).

The chain asserted here is the whole contract:

    NodeScorer.score_children(...)[i]
      == xi_value(child_squad, ...)
      == objective_points(best_xi(child_squad, ...), ...)

`xi_value` is the reference implementation, not a fallback — nothing in the
runtime chooses between them. Tolerance is 1e-9, matching §6.2.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.squad import (
    NodeScorer,
    best_xi,
    legal_formations,
    objective_points,
    xi_value,
)

from conftest import add_players

_SQUAD_SELECT = {1: 2, 2: 5, 3: 5, 4: 3}
_EXTRA_PER_POSITION = 8
TOL = 1e-9


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
    return [
        player_id
        for position_id, count in _SQUAD_SELECT.items()
        for player_id in rng.sample(pool[position_id], count)
    ]


def _reference(squad, projections, snapshot) -> float:
    """The pure-Python path, asserted self-consistent as it goes."""
    value = xi_value(squad, projections, snapshot)
    witness = objective_points(best_xi(squad, projections, snapshot), projections)
    assert value == pytest.approx(witness, rel=TOL, abs=TOL)
    return value


def _position_of(snapshot: BootstrapSnapshot, player_id: int) -> int:
    return snapshot.players_by_id[player_id].element_type


def test_node_value_matches_xi_value(bootstrap_snapshot: BootstrapSnapshot) -> None:
    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-26-node")

    for _ in range(50):
        squad = _random_squad(pool, rng)
        projections = {pid: _projection(pid, rng.uniform(0.0, 15.0)) for pid in squad}
        scorer = NodeScorer(squad, projections, bootstrap_snapshot)

        assert scorer.value() == pytest.approx(
            _reference(squad, projections, bootstrap_snapshot), rel=TOL, abs=TOL
        )


@pytest.mark.parametrize(
    ("label", "draw_xp"),
    [
        ("distinct", lambda rng: rng.uniform(0.0, 15.0)),
        ("colliding", lambda rng: float(rng.randint(0, 3))),
        ("with-negatives", lambda rng: rng.uniform(-4.0, 8.0)),
        ("all-equal", lambda rng: 2.0),
    ],
)
def test_k1_batch_matches_reference_child_by_child(
    bootstrap_snapshot: BootstrapSnapshot, label: str, draw_xp
) -> None:
    """One out, many in — the whole candidate axis in one array operation."""
    pool = _widen(bootstrap_snapshot)
    rng = random.Random(f"fu-26-k1-{label}")

    for _ in range(40):
        squad = _random_squad(pool, rng)
        projections = {pid: _projection(pid, draw_xp(rng)) for pid in squad}
        out_id = rng.choice(squad)
        position = _position_of(bootstrap_snapshot, out_id)
        candidates = [pid for pid in pool[position] if pid not in squad]
        rng.shuffle(candidates)
        candidates = candidates[:6]
        for pid in candidates:
            projections[pid] = _projection(pid, draw_xp(rng))

        scorer = NodeScorer(squad, projections, bootstrap_snapshot)
        batch = scorer.score_children(
            [out_id], [np.array([projections[pid].xp_total for pid in candidates])]
        )

        assert batch.shape == (len(candidates),)
        for index, incoming in enumerate(candidates):
            child = [pid for pid in squad if pid != out_id] + [incoming]
            expected = _reference(child, projections, bootstrap_snapshot)
            assert batch[index] == pytest.approx(expected, rel=TOL, abs=TOL), (
                f"{label}: out={out_id} in={incoming}"
            )


def test_k2_cross_position_batch_matches_reference(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """Two out in different positions — the result is an outer grid."""
    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-26-k2-cross")

    for _ in range(25):
        squad = _random_squad(pool, rng)
        projections = {pid: _projection(pid, rng.uniform(0.0, 15.0)) for pid in squad}
        first_pos, second_pos = rng.sample(sorted(_SQUAD_SELECT), 2)
        out_a = rng.choice([pid for pid in squad if _position_of(bootstrap_snapshot, pid) == first_pos])
        out_b = rng.choice([pid for pid in squad if _position_of(bootstrap_snapshot, pid) == second_pos])

        cands_a = [pid for pid in pool[first_pos] if pid not in squad][:4]
        cands_b = [pid for pid in pool[second_pos] if pid not in squad][:5]
        for pid in cands_a + cands_b:
            projections[pid] = _projection(pid, rng.uniform(0.0, 15.0))

        scorer = NodeScorer(squad, projections, bootstrap_snapshot)
        batch = scorer.score_children(
            [out_a, out_b],
            [
                np.array([projections[pid].xp_total for pid in cands_a]),
                np.array([projections[pid].xp_total for pid in cands_b]),
            ],
        )

        assert batch.shape == (len(cands_a), len(cands_b))
        for i, in_a in enumerate(cands_a):
            for j, in_b in enumerate(cands_b):
                child = [pid for pid in squad if pid not in (out_a, out_b)] + [in_a, in_b]
                expected = _reference(child, projections, bootstrap_snapshot)
                assert batch[i, j] == pytest.approx(expected, rel=TOL, abs=TOL)


def test_k2_same_position_batch_matches_reference(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """Two out of one position — the three-way identity, not the two-way one."""
    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-26-k2-same")

    for _ in range(25):
        squad = _random_squad(pool, rng)
        projections = {pid: _projection(pid, rng.uniform(0.0, 15.0)) for pid in squad}
        position = rng.choice([pid for pid, count in _SQUAD_SELECT.items() if count >= 2])
        held = [pid for pid in squad if _position_of(bootstrap_snapshot, pid) == position]
        out_a, out_b = rng.sample(held, 2)

        candidates = [pid for pid in pool[position] if pid not in squad][:5]
        for pid in candidates:
            projections[pid] = _projection(pid, rng.uniform(0.0, 15.0))
        values = np.array([projections[pid].xp_total for pid in candidates])

        scorer = NodeScorer(squad, projections, bootstrap_snapshot)
        batch = scorer.score_children([out_a, out_b], [values, values])

        for i, in_a in enumerate(candidates):
            for j, in_b in enumerate(candidates):
                if in_a == in_b:
                    continue  # the caller masks the diagonal; two of one player is not a squad
                child = [pid for pid in squad if pid not in (out_a, out_b)] + [in_a, in_b]
                expected = _reference(child, projections, bootstrap_snapshot)
                assert batch[i, j] == pytest.approx(expected, rel=TOL, abs=TOL), (
                    f"out=({out_a},{out_b}) in=({in_a},{in_b})"
                )


def test_batch_exercises_the_full_prefix_range(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """An incoming player good enough to push its position to its maximum
    starter count reads the right-hand `-inf` pad — the case where the position
    can only field that many starters *by including the new player*."""
    pool = _widen(bootstrap_snapshot)
    rng = random.Random("fu-26-pad")
    squad = _random_squad(pool, rng)
    # Defenders weak, so 5-DEF formations are only reachable via a strong signing.
    projections = {}
    for pid in squad:
        position = _position_of(bootstrap_snapshot, pid)
        projections[pid] = _projection(pid, 0.1 if position == 2 else 9.0)
    out_id = next(pid for pid in squad if _position_of(bootstrap_snapshot, pid) == 2)
    candidates = [pid for pid in pool[2] if pid not in squad][:3]
    for pid in candidates:
        projections[pid] = _projection(pid, 30.0)

    scorer = NodeScorer(squad, projections, bootstrap_snapshot)
    batch = scorer.score_children(
        [out_id], [np.array([projections[pid].xp_total for pid in candidates])]
    )

    for index, incoming in enumerate(candidates):
        child = [pid for pid in squad if pid != out_id] + [incoming]
        assert batch[index] == pytest.approx(
            _reference(child, projections, bootstrap_snapshot), rel=TOL, abs=TOL
        )


def test_scorer_refuses_a_foreign_event(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """§6.2 calls reusing a scorer across gameweeks the most dangerous bug in
    the design: the xP ranking changes, so the cached structure silently scores
    against the wrong one. The scorer can be asked to prove its event."""
    pool = _widen(bootstrap_snapshot)
    squad = _random_squad(pool, random.Random("fu-26-event"))
    projections = {pid: _projection(pid, 5.0) for pid in squad}

    scorer = NodeScorer(squad, projections, bootstrap_snapshot, event=3)
    scorer.assert_event(3)
    with pytest.raises(ValueError, match="gameweek 3"):
        scorer.assert_event(4)


def test_scorer_rejects_a_player_outside_the_node(bootstrap_snapshot: BootstrapSnapshot) -> None:
    pool = _widen(bootstrap_snapshot)
    squad = _random_squad(pool, random.Random("fu-26-foreign"))
    projections = {pid: _projection(pid, 5.0) for pid in squad}
    scorer = NodeScorer(squad, projections, bootstrap_snapshot)

    outsider = next(pid for pid in pool[2] if pid not in squad)
    with pytest.raises(ValueError, match="not in this node's squad"):
        scorer.score_children([outsider], [np.array([1.0])])


def test_scorer_rejects_mismatched_arguments(bootstrap_snapshot: BootstrapSnapshot) -> None:
    pool = _widen(bootstrap_snapshot)
    squad = _random_squad(pool, random.Random("fu-26-args"))
    projections = {pid: _projection(pid, 5.0) for pid in squad}
    scorer = NodeScorer(squad, projections, bootstrap_snapshot)

    with pytest.raises(ValueError, match="candidate arrays"):
        scorer.score_children([squad[0], squad[1]], [np.array([1.0])])
    with pytest.raises(ValueError, match="at least one outgoing"):
        scorer.score_children([], [])
    with pytest.raises(ValueError, match="1-D"):
        scorer.score_children([squad[0]], [np.array([[1.0, 2.0]])])


def test_scorer_uses_the_shared_formation_set(bootstrap_snapshot: BootstrapSnapshot) -> None:
    """The kernel must not carry its own formation enumeration — that is the
    drift FU-24's `legal_formations` exists to prevent."""
    pool = _widen(bootstrap_snapshot)
    squad = _random_squad(pool, random.Random("fu-26-formations"))
    projections = {pid: _projection(pid, 5.0) for pid in squad}
    scorer = NodeScorer(squad, projections, bootstrap_snapshot)

    assert {tuple(row) for row in scorer._formations} == set(legal_formations(bootstrap_snapshot))

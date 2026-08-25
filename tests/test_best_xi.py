from __future__ import annotations

import pytest

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.projections import Projection
from fpl_cli.domain.squad import best_xi

# `bootstrap_snapshot`'s 15 players: GKP 1-2, DEF 3-7, MID 8-12, FWD 13-15.
# Position limits: GKP min/max 1/1, DEF 3/5, MID 2/5, FWD 1/3. squad_squadplay=11.


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


def test_best_xi_selects_highest_value_legal_formation(bootstrap_snapshot: BootstrapSnapshot) -> None:
    xp = {
        1: 10.0, 2: 1.0,  # GKP
        3: 8.0, 4: 7.0, 5: 6.0, 6: 0.1, 7: 0.1,  # DEF
        8: 9.0, 9: 8.0, 10: 7.0, 11: 6.0, 12: 5.0,  # MID
        13: 12.0, 14: 11.0, 15: 0.1,  # FWD
    }
    projections = {player_id: _projection(player_id, value) for player_id, value in xp.items()}

    result = best_xi(list(range(1, 16)), projections, bootstrap_snapshot)

    # Best is 1 GKP + 3 DEF + 5 MID + 2 FWD: MID's 3rd-5th picks (+7, +6, +5)
    # and FWD's 2nd pick (+11) outscore DEF's 4th/5th picks (+0.1 each).
    assert result.starters == [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    assert result.captain == 13


def test_best_xi_breaks_formation_and_player_ties_by_id_ascending(bootstrap_snapshot: BootstrapSnapshot) -> None:
    projections = {player_id: _projection(player_id, 1.0) for player_id in range(1, 16)}

    result = best_xi(list(range(1, 16)), projections, bootstrap_snapshot)

    # Every legal formation scores the same total (11 x 1.0), so the
    # tie-break must pick deterministically: maximise DEF (lowest IDs) before
    # MID, then MID before FWD, since all-equal xP makes id-ascending both
    # the player- and formation-level tie-break.
    assert result.starters == [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13]
    assert result.captain == 1


def test_best_xi_raises_when_a_position_cannot_meet_its_minimum(bootstrap_snapshot: BootstrapSnapshot) -> None:
    # Only 2 defenders available; DEF requires at least 3 starters.
    player_ids = [1, 2, 3, 4, 8, 9, 10, 11, 12, 13, 14, 15]
    projections = {player_id: _projection(player_id, 1.0) for player_id in player_ids}

    with pytest.raises(ValueError, match="DEF"):
        best_xi(player_ids, projections, bootstrap_snapshot)

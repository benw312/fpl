"""`tools/points_criterion.py`'s squad sampler and paired statistics.

The criterion is only as good as its squads. They must be legal under the shipped
validator, reproducible from a seed (a pre-registration names the seed), and
weighted towards owned players (realistic managers, not uniform noise). Every test
was run against its named mutation first.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from conftest import _bootstrap_snapshot

from fpl_cli.api.models import Player
from fpl_cli.domain.rules import validate_squad_structure

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import points_criterion as pc  # noqa: E402


def _market():
    """63 extra players, enough per position that necessity does not decide
    who is picked. Prices average ~£7.5m, so a squad drawn without the budget
    look-ahead would usually overspend. The first player of each position (101, 109,
    129, 149) is heavily owned."""
    snapshot = _bootstrap_snapshot()
    extras = []
    pid = 100
    for position, count in ((1, 8), (2, 20), (3, 20), (4, 15)):
        for k in range(count):
            pid += 1
            extras.append(
                Player(
                    id=pid, web_name=f"X{pid}", team=(k % 5) + 1, element_type=position,
                    now_cost=55 + (k * 7) % 40, selected_by_percent="60.0" if k == 0 else "0.5",
                )
            )
    snapshot = snapshot.model_copy(update={"elements": [*snapshot.elements, *extras]})
    for cached in ("players_by_id", "clubs", "positions"):
        snapshot.__dict__.pop(cached, None)
    return snapshot


def test_every_sampled_squad_is_legal_and_within_budget() -> None:
    """Mutations: dropping the club-limit condition; dropping the budget
    look-ahead (`cheapest_fill`), which lets late slots overspend."""
    snapshot = _market()
    for squad in pc.sample_squads(snapshot, 60, seed=7):
        assert validate_squad_structure(list(squad.player_ids), snapshot).valid
        assert squad.bank >= 0
        cost = sum(snapshot.players_by_id[p].now_cost for p in squad.player_ids)
        assert cost + squad.bank == snapshot.game_settings.squad_total_spend


def test_the_same_seed_gives_the_same_squads() -> None:
    """A pre-registration names the seed, so it must pin the squads.

    Mutation: seeding from the clock (`random.Random()`)."""
    snapshot = _market()
    assert pc.sample_squads(snapshot, 10, seed=3) == pc.sample_squads(snapshot, 10, seed=3)
    assert pc.sample_squads(snapshot, 10, seed=3) != pc.sample_squads(snapshot, 10, seed=4)


def test_owned_players_are_drawn_far_more_often() -> None:
    """Mutation: uniform weights."""
    snapshot = _market()
    squads = pc.sample_squads(snapshot, 60, seed=11)
    owned = {101, 109, 129, 149}  # the k == 0 player of each position
    others = [p for p in range(101, 164) if p not in owned]
    rate_owned = sum(p in s.player_ids for s in squads for p in owned) / (60 * len(owned))
    rate_other = sum(p in s.player_ids for s in squads for p in others) / (60 * len(others))
    assert rate_owned > 2 * rate_other


def test_paired_statistics() -> None:
    """Mutation: an unpaired difference of means with the wrong sign
    convention (incumbent minus candidate)."""
    rows = [{"a": 10, "b": 12}, {"a": 5, "b": 4}, {"a": 7, "b": 9}]
    stats = pc.paired(rows, "b", "a")
    assert stats["mean"] == 1.0
    assert (stats["positive"], stats["zero"], stats["negative"]) == (2, 0, 1)

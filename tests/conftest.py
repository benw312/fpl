from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings, Player, Position


def _bootstrap_snapshot() -> BootstrapSnapshot:
    players = []
    for player_id in range(1, 16):
        element_type = 1 if player_id <= 2 else 2 if player_id <= 7 else 3 if player_id <= 12 else 4
        players.append(Player(id=player_id, web_name=f"P{player_id}", team=(player_id % 5) + 1, element_type=element_type, now_cost=50))
    return BootstrapSnapshot(
        teams=[Club(id=index, name=f"Club {index}") for index in range(1, 6)],
        element_types=[
            Position(id=1, singular_name_short="GKP", squad_select=2, squad_min_play=1, squad_max_play=1),
            Position(id=2, singular_name_short="DEF", squad_select=5, squad_min_play=3, squad_max_play=5),
            Position(id=3, singular_name_short="MID", squad_select=5, squad_min_play=2, squad_max_play=5),
            Position(id=4, singular_name_short="FWD", squad_select=3, squad_min_play=1, squad_max_play=3),
        ],
        elements=players,
        game_settings=GameSettings(),
        fetched_at=datetime.now(UTC),
        season="test",
    )


@pytest.fixture
def bootstrap_snapshot() -> BootstrapSnapshot:
    return _bootstrap_snapshot()


@pytest.fixture
def bootstrap_payload() -> dict[str, Any]:
    """A minimal but valid synthetic bootstrap-static payload, as raw JSON."""
    return {
        "events": [],
        "teams": [{"id": index, "name": f"Club {index}", "short_name": f"C{index}"} for index in range(1, 6)],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP", "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
            {"id": 2, "singular_name_short": "DEF", "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
            {"id": 3, "singular_name_short": "MID", "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
            {"id": 4, "singular_name_short": "FWD", "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
        ],
        "elements": [
            {
                "id": player_id,
                "web_name": f"P{player_id}",
                "team": (player_id % 5) + 1,
                "element_type": 1 if player_id <= 2 else 2 if player_id <= 7 else 3 if player_id <= 12 else 4,
                "now_cost": 50,
            }
            for player_id in range(1, 16)
        ],
        "game_config": {"settings": {"static_content_url": "https://example.com/static/2025-26_a1b2c3/"}},
    }


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def recording_sleep() -> RecordingSleep:
    return RecordingSleep()

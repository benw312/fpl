from datetime import UTC, datetime

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings, Player, Position
from fpl_cli.domain.rules import validate_squad


def snapshot() -> BootstrapSnapshot:
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


def test_valid_squad_passes() -> None:
    result = validate_squad(list(range(1, 16)), snapshot())
    assert result.valid


def test_budget_failure_is_actionable() -> None:
    data = snapshot()
    data.elements[0].now_cost = 1001
    result = validate_squad(list(range(1, 16)), data)
    assert any("budget" in error.lower() for error in result.errors)


def test_duplicate_and_size_failures() -> None:
    result = validate_squad([1] * 15, snapshot())
    assert any("duplicate" in error.lower() for error in result.errors)
    assert any("GKP" in error for error in result.errors)

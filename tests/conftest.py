from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Club, GameSettings, Gameweek, Player, Position

_GAMEWEEK_DEADLINES = {
    1: datetime(2025, 8, 15, 17, 30, tzinfo=UTC),
    2: datetime(2025, 8, 22, 17, 30, tzinfo=UTC),
    3: datetime(2025, 8, 29, 17, 30, tzinfo=UTC),
    4: datetime(2025, 9, 5, 17, 30, tzinfo=UTC),
    5: datetime(2025, 9, 12, 17, 30, tzinfo=UTC),
}


def _synthetic_gameweeks() -> list[Gameweek]:
    return [
        Gameweek(
            id=event_id,
            name=f"Gameweek {event_id}",
            deadline_time=deadline,
            is_current=event_id == 2,
            is_next=event_id == 3,
            is_previous=event_id == 1,
            finished=event_id <= 1,
        )
        for event_id, deadline in _GAMEWEEK_DEADLINES.items()
    ]


# Real FPL scoring shape, needed by ComponentProjection (snapshot.raw["game_config"]["scoring"]).
_SCORING: dict[str, Any] = {
    "short_play": 1,
    "long_play": 2,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    "bonus": 1,
    "yellow_cards": -1,
    "red_cards": -3,
}


def _bootstrap_snapshot() -> BootstrapSnapshot:
    players = []
    for player_id in range(1, 16):
        element_type = 1 if player_id <= 2 else 2 if player_id <= 7 else 3 if player_id <= 12 else 4
        players.append(Player(id=player_id, web_name=f"P{player_id}", team=(player_id % 5) + 1, element_type=element_type, now_cost=50))
    return BootstrapSnapshot(
        events=_synthetic_gameweeks(),
        teams=[Club(id=index, name=f"Club {index}") for index in range(1, 6)],
        element_types=[
            Position(id=1, singular_name_short="GKP", squad_select=2, squad_min_play=1, squad_max_play=1),
            Position(id=2, singular_name_short="DEF", squad_select=5, squad_min_play=3, squad_max_play=5),
            Position(id=3, singular_name_short="MID", squad_select=5, squad_min_play=2, squad_max_play=5),
            Position(id=4, singular_name_short="FWD", squad_select=3, squad_min_play=1, squad_max_play=3),
        ],
        elements=players,
        game_settings=GameSettings(),
        raw={"game_config": {"scoring": _SCORING}},
        fetched_at=datetime.now(UTC),
        season="test",
    )


@pytest.fixture
def bootstrap_snapshot() -> BootstrapSnapshot:
    return _bootstrap_snapshot()


def add_players(snapshot: BootstrapSnapshot, *players: Player) -> None:
    """Append players to a snapshot, dropping the memoised `players_by_id`.

    `BootstrapSnapshot`'s lookups are `cached_property` (FU-23), so appending
    to `elements` directly leaves a snapshot that has already been read from
    denying the new players exist.
    """
    snapshot.elements.extend(players)
    snapshot.__dict__.pop("players_by_id", None)


def _builder_players() -> list[Player]:
    """~45 players across 8 clubs, varied prices and points.

    Unlike `_bootstrap_snapshot`'s 15 players (one per required slot, all
    priced identically, exactly `squad_team_limit` per club), this gives the
    squad builder's filtering logic something real to filter: several
    candidates per slot, a club with more defenders than the team limit
    allows, price spread wide enough to exercise the budget reserve, and one
    unselectable and one removed player.
    """
    players: list[Player] = []
    next_id = 1

    def add(
        *,
        position: int,
        team: int,
        price: int,
        points: int,
        can_select: bool = True,
        removed: bool = False,
        status: str = "a",
    ) -> int:
        nonlocal next_id
        player_id = next_id
        next_id += 1
        players.append(
            Player(
                id=player_id,
                web_name=f"P{player_id}",
                team=team,
                element_type=position,
                now_cost=price,
                total_points=points,
                can_select=can_select,
                removed=removed,
                status=status,
            )
        )
        return player_id

    for team, price, points in [(1, 45, 120), (2, 50, 100), (3, 40, 60), (4, 55, 140)]:
        add(position=1, team=team, price=price, points=points)  # GKP

    # DEF: club 1 has 4 — one more than squad_team_limit (3) — the rest spread thin.
    for team, price, points in [
        (1, 45, 90), (1, 50, 80), (1, 60, 70), (1, 70, 130),
        (2, 40, 40), (2, 55, 95), (3, 45, 60), (3, 65, 110),
        (4, 50, 55), (4, 75, 150), (5, 42, 45), (5, 58, 85),
        (8, 48, 65), (8, 66, 100),
    ]:
        add(position=2, team=team, price=price, points=points)

    for team, price, points in [
        (1, 60, 100), (2, 145, 260), (2, 95, 200), (3, 55, 70),
        (3, 80, 150), (4, 100, 190), (4, 65, 85), (5, 120, 210),
        (5, 45, 40), (6, 90, 160), (6, 70, 95), (7, 110, 180),
        (7, 50, 60), (8, 130, 230),
    ]:
        add(position=3, team=team, price=price, points=points)  # MID
    add(position=3, team=6, price=75, points=100, can_select=False)
    add(position=3, team=7, price=48, points=30, removed=True)

    for team, price, points in [
        (1, 150, 250), (2, 55, 60), (2, 90, 170), (3, 65, 100),
        (4, 130, 220), (5, 45, 50), (6, 105, 190), (7, 75, 130),
        (8, 60, 90), (1, 40, 45),
    ]:
        add(position=4, team=team, price=price, points=points)  # FWD

    return players


def _builder_snapshot() -> BootstrapSnapshot:
    return BootstrapSnapshot(
        events=_synthetic_gameweeks(),
        teams=[Club(id=index, name=f"Club {index}", short_name=f"C{index}") for index in range(1, 9)],
        element_types=[
            Position(id=1, singular_name_short="GKP", squad_select=2, squad_min_play=1, squad_max_play=1),
            Position(id=2, singular_name_short="DEF", squad_select=5, squad_min_play=3, squad_max_play=5),
            Position(id=3, singular_name_short="MID", squad_select=5, squad_min_play=2, squad_max_play=5),
            Position(id=4, singular_name_short="FWD", squad_select=3, squad_min_play=1, squad_max_play=3),
        ],
        elements=_builder_players(),
        game_settings=GameSettings(),
        fetched_at=datetime.now(UTC),
        season="test",
    )


@pytest.fixture
def builder_snapshot() -> BootstrapSnapshot:
    return _builder_snapshot()


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


@pytest.fixture
def fixtures_payload() -> list[dict[str, Any]]:
    """A minimal but valid synthetic fixtures payload, as raw JSON.

    Fixture 2 is unscheduled (event=None), covering the postponement case.
    """
    return [
        {
            "id": 1,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "team_h_score": 2,
            "team_a_score": 1,
            "kickoff_time": "2025-08-15T19:00:00Z",
            "finished": True,
        },
        {
            "id": 2,
            "event": None,
            "team_h": 3,
            "team_a": 4,
            "team_h_score": None,
            "team_a_score": None,
            "kickoff_time": None,
            "finished": False,
        },
    ]


@pytest.fixture
def live_event_payload() -> dict[str, Any]:
    """A minimal but valid synthetic event/{gw}/live/ payload, as raw JSON.

    Element 2 has a double gameweek's worth of `explain` entries (two
    fixtures), covering that shape.
    """
    return {
        "elements": [
            {
                "id": 1,
                "stats": {"minutes": 90, "goals_scored": 0, "total_points": 6, "played": True},
                "explain": [
                    {
                        "fixture": 1,
                        "stats": [
                            {"identifier": "minutes", "points": 2, "value": 90, "points_modification": 0},
                            {"identifier": "clean_sheets", "points": 4, "value": 1, "points_modification": 0},
                        ],
                    }
                ],
                "modified": False,
            },
            {
                "id": 2,
                "stats": {"minutes": 180, "goals_scored": 1, "total_points": 11, "played": True},
                "explain": [
                    {
                        "fixture": 2,
                        "stats": [{"identifier": "minutes", "points": 2, "value": 90, "points_modification": 0}],
                    },
                    {
                        "fixture": 3,
                        "stats": [
                            {"identifier": "minutes", "points": 2, "value": 90, "points_modification": 0},
                            {"identifier": "goals_scored", "points": 5, "value": 1, "points_modification": 0},
                        ],
                    },
                ],
                "modified": False,
            },
        ]
    }


class RecordingSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def recording_sleep() -> RecordingSleep:
    return RecordingSleep()

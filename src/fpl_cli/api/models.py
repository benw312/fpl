from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Player(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    web_name: str
    first_name: str = ""
    second_name: str = ""
    team: int
    element_type: int
    now_cost: int
    total_points: int = 0
    form: str = "0"
    status: str = "a"
    news: str = ""
    can_select: bool = True
    can_transact: bool = True
    removed: bool = False
    chance_of_playing_next_round: int | None = None

    @property
    def display_name(self) -> str:
        return self.web_name or f"{self.first_name} {self.second_name}".strip()

    @property
    def price_millions(self) -> float:
        return self.now_cost / 10


class Club(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    short_name: str = ""


class Position(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    singular_name_short: str
    squad_select: int
    squad_min_play: int
    squad_max_play: int


class Gameweek(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    deadline_time: datetime | None = None
    is_current: bool = False
    is_next: bool = False


class GameSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    squad_squadsize: int = 15
    squad_squadplay: int = 11
    squad_team_limit: int = 3
    squad_total_spend: int = 1000
    ui_currency_multiplier: int = 10
    transfers_sell_on_fee: float = 0.5
    max_extra_free_transfers: int = 4


class BootstrapSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[Gameweek] = Field(default_factory=list)
    teams: list[Club] = Field(default_factory=list)
    element_types: list[Position] = Field(default_factory=list)
    elements: list[Player] = Field(default_factory=list)
    game_settings: GameSettings = Field(default_factory=GameSettings)
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
    fetched_at: datetime
    season: str = "unknown"

    @property
    def clubs(self) -> dict[int, Club]:
        return {club.id: club for club in self.teams}

    @property
    def positions(self) -> dict[int, Position]:
        return {position.id: position for position in self.element_types}

    @property
    def players_by_id(self) -> dict[int, Player]:
        return {player.id: player for player in self.elements}

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, fetched_at: datetime) -> BootstrapSnapshot:
        return cls(
            **payload,
            fetched_at=fetched_at,
            season=_season_from_payload(payload),
            raw=payload,
        )


def _season_from_payload(payload: dict[str, Any]) -> str:
    static_content_url = payload.get("game_config", {}).get("settings", {}).get("static_content_url", "")
    parts = str(static_content_url).rstrip("/").split("/")
    return next((part for part in reversed(parts) if "_" in part), "unknown")

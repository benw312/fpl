from __future__ import annotations

from datetime import datetime
from functools import cached_property
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

    # Projection inputs (docs/plans/projections-v1.md). Previously dropped
    # silently by extra="ignore" above.
    expected_goals_per_90: float = 0.0
    expected_assists_per_90: float = 0.0
    expected_goals_conceded_per_90: float = 0.0
    saves_per_90: float = 0.0
    # The cumulative counts behind the per-90 rates above, needed to pool a
    # prior by exposure rather than by averaging ratios (rate-shrinkage.md
    # §3.1). `per_90 == cumulative / (minutes/90)` holds exactly in the payload,
    # so these carry no new information per player — but summing published
    # counts across players avoids compounding the payload's two-decimal
    # rounding, which reconstructing each count from its rate would not.
    # xG and xA are numeric-as-string in the API, like `form` and
    # `points_per_game`; Pydantic coerces them.
    expected_goals: float = 0.0
    expected_assists: float = 0.0
    defensive_contribution: int = 0
    saves: int = 0
    starts: int = 0
    starts_per_90: float = 0.0
    minutes: int = 0
    bonus: int = 0
    defensive_contribution_per_90: float = 0.0
    yellow_cards: int = 0
    red_cards: int = 0
    # Numeric-as-string in the API, matching the existing `form` field.
    points_per_game: str = "0.0"
    ep_next: str | None = None

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
    # Despite the field names, `strength_overall_home` is the difficulty
    # rating an OPPONENT faces when playing at home against this club, and
    # `strength_overall_away` the rating faced playing away — confirmed
    # empirically against team_h_difficulty/team_a_difficulty in the live
    # fixtures payload (docs/plans/projections-v1.md Finding 5), 0 mismatches
    # across 380 fixtures. Scale is 1 (easy) to 5 (hard).
    strength_overall_home: int = 3
    strength_overall_away: int = 3


class Position(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    singular_name_short: str
    squad_select: int
    squad_min_play: int
    squad_max_play: int


class Fixture(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    event: int | None = None
    team_h: int
    team_a: int
    team_h_score: int | None = None
    team_a_score: int | None = None
    kickoff_time: datetime | None = None
    finished: bool = False


class ExplainStat(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identifier: str
    points: int = 0
    value: int = 0
    points_modification: int = 0


class ExplainEntry(BaseModel):
    """One fixture's worth of scoring within a `LiveElement.explain` list —
    a double gameweek yields two entries for the same player."""

    model_config = ConfigDict(extra="ignore")

    fixture: int
    stats: list[ExplainStat] = Field(default_factory=list)


class LiveElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    stats: dict[str, Any] = Field(default_factory=dict)
    explain: list[ExplainEntry] = Field(default_factory=list)


class LiveEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    elements: list[LiveElement] = Field(default_factory=list)


class Gameweek(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    deadline_time: datetime | None = None
    is_current: bool = False
    is_next: bool = False
    is_previous: bool = False
    finished: bool = False
    data_checked: bool = False


class GameSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    squad_squadsize: int = 15
    squad_squadplay: int = 11
    squad_team_limit: int = 3
    squad_total_spend: int = 1000
    ui_currency_multiplier: int = 10
    transfers_sell_on_fee: float = 0.5
    max_extra_free_transfers: int = 4
    transfers_cap: int = 20
    element_sell_at_purchase_price: bool = False


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

    # Memoised (FU-23): these otherwise rebuild a dict on every access, and
    # every command reaches for them repeatedly — `apply_transfers` alone hits
    # `players_by_id` twice per call. A snapshot is a fixed read of the API, so
    # the mappings are built once, on first access. Nothing here mutates
    # `teams`, `element_types` or `elements` after construction; anything that
    # does must drop the memo it invalidates (`del snapshot.players_by_id`).

    @cached_property
    def clubs(self) -> dict[int, Club]:
        return {club.id: club for club in self.teams}

    @cached_property
    def positions(self) -> dict[int, Position]:
        return {position.id: position for position in self.element_types}

    @cached_property
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

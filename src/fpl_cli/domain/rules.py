from __future__ import annotations

from dataclasses import dataclass

from fpl_cli.api.models import BootstrapSnapshot, Player


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    season: str
    fetched_at: str

    @property
    def valid(self) -> bool:
        return not self.errors


def validate_squad_structure(player_ids: list[int], snapshot: BootstrapSnapshot) -> ValidationResult:
    """Validate squad size, positions, club limits and selectability.

    Deliberately excludes the budget check: that check only holds against
    `now_cost` at genesis (see domain/transfers.py Decision 3) — post-genesis
    the real budget constraint is the transfer ledger's bank, not a sum over
    current prices.
    """
    settings = snapshot.game_settings
    errors: list[str] = []
    warnings: list[str] = []
    players_by_id = snapshot.players_by_id

    if len(player_ids) != len(set(player_ids)):
        errors.append("The squad contains duplicate player IDs.")
    if len(player_ids) != settings.squad_squadsize:
        errors.append(f"The squad must contain exactly {settings.squad_squadsize} players; found {len(player_ids)}.")

    selected = [players_by_id[player_id] for player_id in player_ids if player_id in players_by_id]
    missing = sorted(set(player_ids) - players_by_id.keys())
    if missing:
        errors.append(f"Unknown player IDs: {', '.join(map(str, missing))}.")

    counts = _count_by_position(selected)
    for position in snapshot.element_types:
        actual = counts.get(position.id, 0)
        if actual != position.squad_select:
            errors.append(f"{position.singular_name_short} requires {position.squad_select} players; found {actual}.")

    clubs = _count_by_club(selected)
    for club_id, count in clubs.items():
        if count > settings.squad_team_limit:
            club = snapshot.clubs.get(club_id)
            club_name = club.name if club else str(club_id)
            errors.append(f"{club_name} has {count} players; the limit is {settings.squad_team_limit}.")

    for player in selected:
        if not player.can_select or player.removed:
            errors.append(f"{player.display_name} is not selectable.")
        if player.status != "a" or player.chance_of_playing_next_round == 0:
            warnings.append(f"{player.display_name} is flagged as unavailable: {player.news or player.status}.")

    return ValidationResult(errors, warnings, snapshot.season, snapshot.fetched_at.isoformat())


def validate_squad(player_ids: list[int], snapshot: BootstrapSnapshot) -> ValidationResult:
    settings = snapshot.game_settings
    result = validate_squad_structure(player_ids, snapshot)
    errors = list(result.errors)

    players_by_id = snapshot.players_by_id
    selected = [players_by_id[player_id] for player_id in player_ids if player_id in players_by_id]
    total_cost = sum(player.now_cost for player in selected)
    if total_cost > settings.squad_total_spend:
        errors.append(f"Squad cost is £{total_cost / 10:.1f}m; budget is £{settings.squad_total_spend / 10:.1f}m.")

    return ValidationResult(errors, result.warnings, result.season, result.fetched_at)


def _count_by_position(players: list[Player]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for player in players:
        counts[player.element_type] = counts.get(player.element_type, 0) + 1
    return counts


def _count_by_club(players: list[Player]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for player in players:
        counts[player.team] = counts.get(player.team, 0) + 1
    return counts

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.transfers import SquadState, Transfer, TransferResult

console = Console()


def player_table(players: list[Player], snapshot: BootstrapSnapshot) -> Table:
    table = Table(title=f"FPL players | {snapshot.season}")
    table.add_column("ID", justify="right")
    table.add_column("Player")
    table.add_column("Club")
    table.add_column("Pos")
    table.add_column("Price", justify="right")
    table.add_column("Points", justify="right")
    table.add_column("Status")
    clubs = snapshot.clubs
    positions = snapshot.positions
    for player in players:
        club = clubs.get(player.team)
        position = positions.get(player.element_type)
        table.add_row(
            str(player.id), player.display_name, club.short_name if club else str(player.team),
            position.singular_name_short if position else str(player.element_type),
            f"£{player.price_millions:.1f}m", str(player.total_points), player.status,
        )
    return table


def simulation_table(transfers_by_event: dict[int, list[Transfer]], results: list[TransferResult]) -> Table:
    table = Table(title="Transfer simulation")
    table.add_column("Event", justify="right")
    table.add_column("Transfers", justify="right")
    table.add_column("Hit", justify="right")
    table.add_column("Bank", justify="right")
    table.add_column("Free transfers", justify="right")
    table.add_column("Valid")
    for event, result in zip(sorted(transfers_by_event), results):
        table.add_row(
            str(event), str(result.transfers_made), str(result.hit_points),
            f"£{result.state.bank / 10:.1f}m", str(result.free_transfers_remaining),
            "[green]✓[/green]" if result.validation.valid else "[red]✗[/red]",
        )
    return table


def squad_state_table(state: SquadState, snapshot: BootstrapSnapshot) -> Table:
    table = Table(title=f"Squad as of gameweek {state.event}")
    table.add_column("ID", justify="right")
    table.add_column("Player")
    table.add_column("Club")
    table.add_column("Pos")
    table.add_column("Purchase price", justify="right")
    table.add_column("Now cost", justify="right")
    players_by_id = snapshot.players_by_id
    clubs = snapshot.clubs
    positions = snapshot.positions
    for player_id in state.player_ids:
        holding = state.holdings[player_id]
        player = players_by_id.get(player_id)
        club = clubs.get(player.team) if player else None
        position = positions.get(player.element_type) if player else None
        table.add_row(
            str(player_id), player.display_name if player else str(player_id),
            club.short_name if club else "?",
            position.singular_name_short if position else "?",
            f"£{holding.purchase_price / 10:.1f}m",
            f"£{player.price_millions:.1f}m" if player else "?",
        )
    return table

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from fpl_cli.api.models import BootstrapSnapshot, Player

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

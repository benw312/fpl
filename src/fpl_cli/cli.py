from __future__ import annotations

from pathlib import Path

import typer
from rich import print

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import SnapshotService
from fpl_cli.domain.squad import SquadPlan, validate_plan
from fpl_cli.presentation import console, player_table
from fpl_cli.transport import FplError

app = typer.Typer(help="A local Fantasy Premier League planning CLI.")
players_app = typer.Typer(help="Browse FPL players.")
squad_app = typer.Typer(help="Create and validate local squad plans.")
app.add_typer(players_app, name="players")
app.add_typer(squad_app, name="squad")


def load_snapshot() -> BootstrapSnapshot:
    service = SnapshotService()
    try:
        result = service.load()
    except FplError as exc:
        raise typer.Exit("No live snapshot or cached snapshot is available.") from exc
    finally:
        service.close()
    if result.stale:
        print(
            f"[yellow]Using cached snapshot from {result.snapshot.fetched_at.isoformat()} "
            f"— live fetch failed: {result.reason}[/yellow]"
        )
    return result.snapshot


@app.command()
def sync() -> None:
    """Fetch and cache the current official FPL snapshot."""
    service = SnapshotService()
    try:
        snapshot = service.refresh()
    except FplError as exc:
        raise typer.Exit(str(exc)) from exc
    finally:
        service.close()
    console.print(f"[green]Synced {len(snapshot.elements)} players for {snapshot.season}.[/green]")


@players_app.command("list")
def list_players(
    position: str | None = typer.Option(None, "--position", help="GKP, DEF, MID, or FWD."),
    club: str | None = typer.Option(None, "--club"),
    name: str | None = typer.Option(None, "--name"),
    available_only: bool = typer.Option(False, "--available-only"),
    limit: int = typer.Option(25, min=1, max=200),
) -> None:
    """List players from the latest available snapshot."""
    snapshot = load_snapshot()
    positions = {item.singular_name_short.upper(): item.id for item in snapshot.element_types}
    clubs = {item.name.lower(): item.id for item in snapshot.teams}
    players = snapshot.elements
    if position:
        position_id = positions.get(position.upper())
        if position_id is None:
            raise typer.BadParameter("Use GKP, DEF, MID, or FWD.")
        players = [player for player in players if player.element_type == position_id]
    if club:
        club_id = clubs.get(club.lower())
        players = [player for player in players if player.team == club_id] if club_id else []
    if name:
        query = name.lower()
        players = [player for player in players if query in player.display_name.lower()]
    if available_only:
        players = [player for player in players if player.can_select and not player.removed and player.status == "a"]
    players = sorted(players, key=lambda player: (-player.total_points, player.display_name))[:limit]
    console.print(player_table(players, snapshot))


@squad_app.command("validate")
def validate_squad(path: Path) -> None:
    """Validate a JSON squad plan against the current FPL rules."""
    snapshot = load_snapshot()
    try:
        plan = SquadPlan.from_file(path)
    except (OSError, ValueError, TypeError) as exc:
        raise typer.Exit(f"Could not read squad plan: {exc}") from exc
    result = validate_plan(plan, snapshot)
    for error in result.errors:
        print(f"[red]✗ {error}[/red]")
    for warning in result.warnings:
        print(f"[yellow]! {warning}[/yellow]")
    if result.valid:
        print(f"[green]Valid squad for {result.season}.[/green]")
    else:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

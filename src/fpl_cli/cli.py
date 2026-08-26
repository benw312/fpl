from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich import print

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import DEFAULT_ARCHIVE_DIR, SnapshotService
from fpl_cli.builder import BuilderCancelled, SquadBuilder, TerminalTooSmall
from fpl_cli.domain.evaluation import (
    actuals_from_live_event,
    evaluate_model,
    flat_points_per_game_projections,
    select_archived_snapshot,
)
from fpl_cli.domain.projections import (
    ComponentProjection,
    NaiveProjection,
    OfficialEpProjection,
    Projection,
    ProjectionModel,
)
from fpl_cli.domain.rules import validate_squad as validate_squad_players
from fpl_cli.domain.squad import best_xi, objective_points, to_ledger_payload, validate_squad_file
from fpl_cli.domain.strength import BandedTeamRates
from fpl_cli.domain.transfers import Ledger, TransferRules, parse_transfers_plan, replay, simulate
from fpl_cli.presentation import (
    console,
    error_console,
    evaluation_category_table,
    evaluation_component_table,
    evaluation_table,
    player_table,
    simulation_table,
    squad_state_table,
)
from fpl_cli.transport import FplError

app = typer.Typer(help="A local Fantasy Premier League planning CLI.")
players_app = typer.Typer(help="Browse FPL players.")
squad_app = typer.Typer(help="Create and validate local squad plans.")
plan_app = typer.Typer(help="Simulate and optimise transfer plans.")
app.add_typer(players_app, name="players")
app.add_typer(squad_app, name="squad")
app.add_typer(plan_app, name="plan")


def load_snapshot() -> BootstrapSnapshot:
    service = SnapshotService()
    try:
        result = service.load()
    except FplError as exc:
        error_console.print("No live snapshot or cached snapshot is available.")
        raise typer.Exit(1) from exc
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
    """Fetch and cache the current official FPL snapshot and fixtures list."""
    service = SnapshotService()
    try:
        snapshot = service.refresh()
        fixtures = service.refresh_fixtures()
        archive_path = service.archive(snapshot)
    except FplError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc
    finally:
        service.close()
    console.print(f"[green]Synced {len(snapshot.elements)} players for {snapshot.season}.[/green]")
    console.print(f"[green]Synced {len(fixtures)} fixtures.[/green]")
    console.print(f"[green]Archived to {archive_path}.[/green]")


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


@squad_app.command("create")
def create_squad(
    output: Path = typer.Option(Path("squad.json"), "--output", help="Where to write the squad ledger."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing output file."),
) -> None:
    """Interactively build a 15-player squad and write it as a transfer ledger."""
    if not sys.stdin.isatty():
        console.print("[red]fpl squad create requires an interactive terminal.[/red]")
        raise typer.Exit(1)
    if output.exists() and not force:
        console.print(f"[red]{output} already exists. Use --force to overwrite.[/red]")
        raise typer.Exit(1)

    snapshot = load_snapshot()
    builder = SquadBuilder(snapshot)
    try:
        slots = builder.run()
    except TerminalTooSmall as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    except BuilderCancelled:
        console.print("[yellow]Cancelled; nothing written.[/yellow]")
        raise typer.Exit(1) from None

    result = validate_squad_players(slots.player_ids, snapshot)
    for error in result.errors:
        print(f"[red]✗ {error}[/red]")
    for warning in result.warnings:
        print(f"[yellow]! {warning}[/yellow]")
    if not result.valid:
        console.print("[red]Squad failed validation; not written.[/red]")
        raise typer.Exit(1)

    payload = to_ledger_payload(slots, snapshot)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    console.print(f"[green]Wrote {output} ({len(payload['log'])} players).[/green]")


@squad_app.command("validate")
def validate_squad(path: Path) -> None:
    """Validate a JSON squad plan or transfer ledger against the current FPL rules."""
    snapshot = load_snapshot()
    try:
        result = validate_squad_file(path, snapshot)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error_console.print(f"Could not read squad plan: {exc}")
        raise typer.Exit(1) from exc
    for error in result.errors:
        print(f"[red]✗ {error}[/red]")
    for warning in result.warnings:
        print(f"[yellow]! {warning}[/yellow]")
    if result.valid:
        print(f"[green]Valid squad for {result.season}.[/green]")
    else:
        raise typer.Exit(1)


def _project_single_event(model: ProjectionModel, player_ids: list[int], event: int) -> dict[int, Projection]:
    return {
        player_id: projection
        for (player_id, projected_event), projection in model.project(player_ids, [event]).items()
        if projected_event == event
    }


@plan_app.command("simulate")
def simulate_plan(squad_path: Path, transfers_path: Path) -> None:
    """Simulate transfers from a squad ledger against a transfers plan file."""
    snapshot = load_snapshot()

    try:
        ledger = Ledger.from_file(squad_path, snapshot)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error_console.print(f"Could not read squad ledger: {exc}")
        raise typer.Exit(1) from exc
    if ledger.legacy:
        print(
            "[yellow]Legacy squad file: selling prices are estimated from current "
            "prices, not real purchase history.[/yellow]"
        )

    try:
        transfers_by_event = parse_transfers_plan(transfers_path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error_console.print(f"Could not read transfers plan: {exc}")
        raise typer.Exit(1) from exc

    rules = TransferRules.from_snapshot(snapshot)
    state = replay(ledger, snapshot)
    try:
        results = simulate(state, transfers_by_event, snapshot, rules)
    except ValueError as exc:
        error_console.print(f"Invalid transfers plan: {exc}")
        raise typer.Exit(1) from exc

    service = SnapshotService()
    try:
        fixtures_result = service.load_fixtures()
    except FplError as exc:
        error_console.print(f"Could not load fixtures: {exc}")
        raise typer.Exit(1) from exc
    finally:
        service.close()
    model = ComponentProjection(
        snapshot,
        fixtures_result.fixtures,
        BandedTeamRates(snapshot),
        fixtures_stale=fixtures_result.stale,
        fixtures_fetched_at=fixtures_result.fetched_at,
    )

    # Same best_xi + captain-doubling objective the optimiser will use
    # (optimizer-ux.md §3), so this round-trip verifies the number a
    # recommendation was made on, not just its legality.
    points_by_event: dict[int, float] = {}
    for event, result in zip(sorted(transfers_by_event), results):
        player_ids = result.state.player_ids
        projections = _project_single_event(model, player_ids, event)
        xi = best_xi(player_ids, projections, snapshot)
        points_by_event[event] = objective_points(xi, projections)

    console.print(simulation_table(transfers_by_event, results, points_by_event))
    for event, result in zip(sorted(transfers_by_event), results):
        for error in result.validation.errors:
            print(f"[red]✗ GW{event}: {error}[/red]")
        for warning in result.validation.warnings:
            print(f"[yellow]! GW{event}: {warning}[/yellow]")

    final_state = results[-1].state if results else state
    console.print(squad_state_table(final_state, snapshot))
    print(f"Bank: £{final_state.bank / 10:.1f}m  |  Free transfers: {final_state.free_transfers}")
    print(f"Total hit points: {sum(result.hit_points for result in results)}")

    if any(not result.validation.valid for result in results):
        raise typer.Exit(1)


@plan_app.command("evaluate")
def evaluate_plan(
    event: int = typer.Option(..., "--event", help="Gameweek to evaluate against actual results."),
) -> None:
    """Score ComponentProjection, NaiveProjection, OfficialEpProjection and the
    flat points_per_game baseline against a finished gameweek's actual points.
    """
    current_snapshot = load_snapshot()
    gameweek = next((gw for gw in current_snapshot.events if gw.id == event), None)
    if gameweek is None:
        error_console.print(f"No gameweek {event} in the current snapshot.")
        raise typer.Exit(1)

    service = SnapshotService()
    try:
        fixtures_result = service.load_fixtures()
        live_result = service.load_event_live(event, current_snapshot)
    except FplError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc
    finally:
        service.close()

    archive_path = (
        select_archived_snapshot(DEFAULT_ARCHIVE_DIR, gameweek.deadline_time)
        if gameweek.deadline_time is not None
        else None
    )
    if archive_path is not None:
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
        projection_snapshot = BootstrapSnapshot.from_payload(
            payload, fetched_at=datetime.fromtimestamp(archive_path.stat().st_mtime, UTC)
        )
    else:
        projection_snapshot = current_snapshot
        print(
            f"[yellow]No archived snapshot predates GW{event}'s deadline — using the current "
            "snapshot. This result is optimistic, not a backtest.[/yellow]"
        )

    fixtures = fixtures_result.fixtures
    actuals = actuals_from_live_event(live_result.live)
    player_ids = [player.id for player in projection_snapshot.elements]

    evaluations = [
        evaluate_model(
            flat_points_per_game_projections(projection_snapshot, event), actuals, model_name="baseline/flat-ppg"
        )
    ]

    naive_model = NaiveProjection(projection_snapshot, fixtures)
    evaluations.append(
        evaluate_model(_project_single_event(naive_model, player_ids, event), actuals, model_name=naive_model.name)
    )

    component_model = ComponentProjection(
        projection_snapshot,
        fixtures,
        BandedTeamRates(projection_snapshot),
        fixtures_stale=fixtures_result.stale,
        fixtures_fetched_at=fixtures_result.fetched_at,
    )
    evaluations.append(
        evaluate_model(
            _project_single_event(component_model, player_ids, event), actuals, model_name=component_model.name
        )
    )

    try:
        ep_model = OfficialEpProjection(projection_snapshot, fixtures)
        evaluations.append(
            evaluate_model(_project_single_event(ep_model, player_ids, event), actuals, model_name=ep_model.name)
        )
    except ValueError as exc:
        print(f"[yellow]OfficialEpProjection: not evaluable for GW{event} ({exc})[/yellow]")

    console.print(evaluation_table(evaluations))
    console.print(evaluation_category_table(evaluations))
    console.print(evaluation_component_table(evaluations))


if __name__ == "__main__":
    app()

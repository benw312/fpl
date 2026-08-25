from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.evaluation import CATEGORIES, COMPONENTS, ModelEvaluation
from fpl_cli.domain.squad import SquadSlots
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


def evaluation_table(evaluations: list[ModelEvaluation]) -> Table:
    table = Table(title="Projection evaluation")
    table.add_column("Model")
    table.add_column("N", justify="right")
    table.add_column("Played", justify="right")
    table.add_column("RMSE (all)", justify="right")
    table.add_column("MAE (all)", justify="right")
    table.add_column("RMSE (played)", justify="right")
    table.add_column("MAE (played)", justify="right")
    table.add_column("Spearman", justify="right")
    for evaluation in evaluations:
        table.add_row(
            evaluation.model_name,
            str(evaluation.n_players),
            str(evaluation.n_played),
            f"{evaluation.rmse_all:.3f}",
            f"{evaluation.mae_all:.3f}",
            f"{evaluation.rmse_played:.3f}",
            f"{evaluation.mae_played:.3f}",
            f"{evaluation.spearman_all:.3f}",
        )
    return table


def evaluation_category_table(evaluations: list[ModelEvaluation]) -> Table:
    """Rows = the OpenFPL return categories, columns = one per model."""
    table = Table(title="Error by return category (predicted − actual, signed mean, n)")
    table.add_column("Category")
    for evaluation in evaluations:
        table.add_column(evaluation.model_name, justify="right")
    for category in CATEGORIES:
        table.add_row(
            category,
            *(
                f"{evaluation.categories[category].mean_error:+.2f} (n={evaluation.categories[category].count})"
                for evaluation in evaluations
            ),
        )
    return table


def evaluation_component_table(evaluations: list[ModelEvaluation]) -> Table:
    """Rows = the eight components, columns = one per model. Played players only."""
    table = Table(title="Error by component (predicted − actual, signed mean, played only)")
    table.add_column("Component")
    for evaluation in evaluations:
        table.add_column(evaluation.model_name, justify="right")
    for component in COMPONENTS:
        table.add_row(
            component.removeprefix("xp_"),
            *(f"{evaluation.component_errors[component]:+.3f}" for evaluation in evaluations),
        )
    return table


def squad_grid(slots: SquadSlots, snapshot: BootstrapSnapshot) -> Group:
    """A pitch-style grid of the 15 numbered position slots, filled or empty."""
    players_by_id = snapshot.players_by_id
    clubs = snapshot.clubs
    settings = snapshot.game_settings

    picked = slots.picked_ids
    spent = sum(players_by_id[player_id].now_cost for player_id in picked if player_id in players_by_id)
    remaining = settings.squad_total_spend - spent

    club_counts: dict[int, int] = {}
    for player_id in picked:
        player = players_by_id.get(player_id)
        if player is not None:
            club_counts[player.team] = club_counts.get(player.team, 0) + 1
    club_line = "   ".join(
        f"{(clubs[club_id].short_name or clubs[club_id].name)} {count}"
        for club_id, count in sorted(club_counts.items())
    ) or "No players picked yet"

    header = Panel(
        club_line,
        title=(
            f"Squad {len(picked)}/{len(slots.slots)} \u00b7 "
            f"\u00a3{spent / 10:.1f}m spent \u00b7 \u00a3{remaining / 10:.1f}m left"
        ),
        title_align="left",
        expand=False,
    )

    grouped: dict[int, list] = {}
    for slot in slots.slots:
        grouped.setdefault(slot.position_id, []).append(slot)

    rows: list[Text] = []
    for position in snapshot.element_types:
        cells = []
        for slot in grouped.get(position.id, []):
            if slot.player_id is None:
                cells.append(f"{slot.index:>2} [ {'-' * 10} ]")
                continue
            player = players_by_id.get(slot.player_id)
            club = clubs.get(player.team) if player else None
            name = player.display_name if player else str(slot.player_id)
            club_short = club.short_name if club else "?"
            price = f"\u00a3{player.price_millions:.1f}m" if player else "?"
            cells.append(f"{slot.index:>2} [ {name:<10} {club_short:<3} {price:>6} ]")
        rows.append(Text(f"{position.singular_name_short:>4}  " + "  ".join(cells)))

    return Group(header, Text(""), *rows)

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.evaluation import CATEGORIES, COMPONENTS, ModelEvaluation
from fpl_cli.domain.squad import SquadSlots
from fpl_cli.domain.transfers import SquadState, Transfer, TransferResult

console = Console()

# Failure messages go to stderr, so redirecting stdout does not swallow them —
# which is what `typer.Exit(str)`'s accidental `sys.exit(str)` behaviour did
# before FU-3. Markup and highlighting are off deliberately: every message on
# this channel interpolates exception text, where a stray "[...]" would
# otherwise be parsed as a Rich tag and either vanish or raise. Soft wrapping
# is on for the same reason: these messages interpolate paths and URLs, and
# Rich's word wrap breaks an 80-column-crossing path across two lines, leaving
# a diagnostic that names a file nobody can copy. The terminal wraps the line
# for display either way; only the bytes differ.
error_console = Console(stderr=True, markup=False, highlight=False, style="red", soft_wrap=True)


# --- fpl players list -------------------------------------------------------


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


# --- fpl players project ----------------------------------------------------


@dataclass(frozen=True)
class ProjectionRow:
    """One row of the projection table (docs/plans/players-project.md §3).

    `player` is the whole first column, already concatenated
    ("De Cuyper · BHA · DEF"). `next_gw` and `mean_xp` are per *gameweek*, not
    per fixture — a double gameweek's two matches are already summed into the
    event they share (§1.2). `fixtures` is the total across the whole horizon,
    so it reads 5 over an unbroken horizon of 5 and is what makes `mean_xp`
    interpretable. `start_pct` is `None` where the model does not model it, and
    renders as an em dash rather than as a fabricated 0%.
    """

    player: str
    next_gw: float
    mean_xp: float
    fixtures: int
    start_pct: float | None


def projection_table(
    rows: Sequence[ProjectionRow],
    *,
    snapshot: BootstrapSnapshot,
    events: Sequence[int],
    model_name: str,
    start_note: str,
    suppressed: int,
) -> Table:
    horizon = len(events)
    span = f"GW{events[0]}" if horizon == 1 else f"GW{events[0]}–GW{events[-1]}"
    table = Table(title=f"Projected points | {span} | {model_name} | {snapshot.season}")
    table.add_column("Player")
    table.add_column(f"GW{events[0]}", justify="right")
    table.add_column(f"Next {horizon}", justify="right")
    table.add_column("Start%", justify="right")
    for row in rows:
        table.add_row(
            row.player,
            f"{row.next_gw:.1f}",
            f"{row.mean_xp:.1f} ({row.fixtures})",
            "—" if row.start_pct is None else f"{row.start_pct * 100:.0f}%",
        )
    caption = [
        f"Next {horizon} = mean xP per gameweek over {span}, with total fixtures in brackets.",
        start_note,
        "UNVALIDATED — these projections have never been scored against realised points.",
    ]
    if suppressed:
        caption.insert(
            2,
            f"{suppressed} unavailable player{'s' if suppressed != 1 else ''} hidden "
            f"(cannot be bought). --include-unavailable shows them.",
        )
    table.caption = "\n".join(caption)
    return table


# --- fpl plan simulate ------------------------------------------------------


def simulation_table(
    transfers_by_event: dict[int, list[Transfer]],
    results: list[TransferResult],
    points_by_event: Mapping[int, float],
) -> Table:
    table = Table(title="Transfer simulation")
    table.add_column("Event", justify="right")
    table.add_column("Points", justify="right")
    table.add_column("Transfers", justify="right")
    table.add_column("Hit", justify="right")
    table.add_column("Bank", justify="right")
    table.add_column("Free transfers", justify="right")
    table.add_column("Valid")
    for event, result in zip(sorted(transfers_by_event), results):
        table.add_row(
            str(event), f"{points_by_event[event]:.1f}",
            str(result.transfers_made), str(result.hit_points),
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


# --- fpl plan evaluate ------------------------------------------------------


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


# --- fpl squad create (the interactive builder) -----------------------------


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


# --- fpl plan optimise (optimizer-ux.md §4, §5) ------------------------------
#
# The largest group, and the one that decided FU-18: `optimise_header` shares
# the deadline and provenance formatting with nothing else, while the price, xP
# and colour conventions below are the same ones the tables above use. Splitting
# by command would cut through that sharing rather than along it.


def _format_timedelta(delta: timedelta) -> str:
    if delta.total_seconds() <= 0:
        return "overdue"
    days, remainder = divmod(int(delta.total_seconds()), 86400)
    hours = remainder // 3600
    if days:
        return f"{days}d {hours}h"
    minutes = (remainder % 3600) // 60
    return f"{hours}h {minutes}m"


def optimise_header(
    *,
    squad_path: str,
    events: Sequence[int],
    horizon: int,
    horizon_clamped: bool,
    model_name: str,
    last_finished_event: int | None,
    snapshot_fetched_at: datetime,
    fixtures_fetched_at: datetime | None,
    fixtures_stale: bool,
    from_event: int,
    deadline: datetime | None,
    now: datetime,
    bank: int,
    free_transfers: int,
    unvalidated: bool,
    scope_gap_lines: Sequence[str],
) -> Group:
    lines: list[Text] = []
    event_range = f"GW{events[0]}–GW{events[-1]}" if len(events) > 1 else f"GW{events[0]}"
    lines.append(Text(f"Plan · {squad_path} · {event_range} (horizon {horizon}) · {model_name}"))
    if horizon_clamped:
        lines.append(
            Text(
                f"! Horizon clamped to {horizon}: no scheduled gameweek beyond GW{events[-1]} in the current snapshot.",
                style="yellow",
            )
        )

    finished = f"GW{last_finished_event} finished" if last_finished_event is not None else "no gameweek finished yet"
    fixtures_line = f", fixtures {fixtures_fetched_at.isoformat()}" if fixtures_fetched_at else ""
    lines.append(Text(f"Snapshot {finished}, fetched {snapshot_fetched_at.isoformat()}{fixtures_line}"))
    if fixtures_stale:
        lines.append(Text("! fixtures list is stale — blanks and doubles may be wrong", style="yellow"))

    if deadline is not None:
        lines.append(Text(f"Deadline GW{from_event}: {deadline:%a %d %b %H:%M} UTC (in {_format_timedelta(deadline - now)})"))
    else:
        lines.append(Text(f"! GW{from_event} has no known deadline in this snapshot.", style="yellow"))

    lines.append(Text(f"State at GW{from_event}: bank £{bank / 10:.1f}m · {free_transfers} free transfer{'s' if free_transfers != 1 else ''}"))

    lines.append(Text(""))
    if unvalidated:
        lines.append(
            Text(
                f"! UNVALIDATED — {model_name} has never been scored against realised points.\n"
                f"  Run `fpl plan evaluate --event {last_finished_event}` before trusting the magnitudes below."
                if last_finished_event is not None
                else f"! UNVALIDATED — {model_name} has never been scored against realised points.",
                style="bold yellow",
            )
        )
    for line in scope_gap_lines:
        lines.append(Text(f"! {line}", style="yellow"))

    return Group(*lines)


@dataclass(frozen=True)
class PathRow:
    """One row of the paths table (optimizer-ux.md §4).

    `moves` is one transfer description per event, already formatted (e.g.
    "Semenyo→Saka (−4)", "—" for a held event, with a trailing "‡" on the
    horizon-edge move per §5.3) — joined with " · " to form the row's
    single descriptive cell. `points` is the undiscounted gross XI value
    per event, one entry per event in the same order.
    """

    label: str
    moves: list[str]
    points: list[float]
    net: float
    score: float
    is_hold: bool = False


def optimise_paths_table(rows: Sequence[PathRow], events: Sequence[int]) -> Table:
    table = Table(title="Paths")
    table.add_column("", justify="right")
    table.add_column("Path")
    for event in events:
        table.add_column(f"GW{event}", justify="right")
    table.add_column("Net", justify="right")
    table.add_column("Score", justify="right")

    for row in rows:
        style = "bold" if row.is_hold else None
        description = "HOLD (no transfers)" if row.is_hold else " · ".join(row.moves)
        table.add_row(
            row.label,
            description,
            *[f"{value:.1f}" for value in row.points],
            f"{row.net:+.1f}",
            f"{row.score:.2f}",
            style=style,
        )
    return table


def optimise_recommendation(
    *,
    verdict: str,
    from_event: int,
    description: str,
    break_even: float,
    gross: float,
    net: float,
    event_range: str,
    robustness_line: str | None,
) -> Group:
    style = "bold green" if verdict == "RECOMMENDED" else "bold yellow"
    lines = [
        Text(f"{verdict} — GW{from_event}: {description}", style=style),
        Text(f"  break-even {break_even:+.1f} · gross {gross:+.1f} · net {net:+.1f} over {event_range}"),
    ]
    if robustness_line is not None:
        lines.append(Text(f"  robustness: {robustness_line}"))
    return Group(*lines)


def optimise_why_table(
    *,
    events: Sequence[int],
    out_rows: Sequence[tuple[str, list[float], float]],
    in_rows: Sequence[tuple[str, list[float], float]],
    raw_delta: list[float],
    raw_delta_total: float,
    realised: list[float],
    realised_total: float,
    hit: float,
    net: float,
) -> Table:
    table = Table(title="Why")
    table.add_column("")
    for event in events:
        table.add_column(f"GW{event}", justify="right")
    table.add_column("Total", justify="right")

    for label, values, total in out_rows:
        table.add_row(f"out  {label}", *[f"{v:.1f}" for v in values], f"{total:.1f}")
    for label, values, total in in_rows:
        table.add_row(f"in   {label}", *[f"{v:.1f}" for v in values], f"{total:.1f}")
    table.add_row(
        "raw player delta", *[f"{v:+.1f}" for v in raw_delta], f"{raw_delta_total:+.1f}", style="dim"
    )
    table.add_row(
        "realised in XI", *[f"{v:+.1f}" for v in realised], f"{realised_total:+.1f}", style="bold"
    )
    table.add_row("hit", *([""] * len(events)), f"{-hit:.1f}")
    table.add_row("net", *([""] * len(events)), f"{net:+.1f}", style="bold")
    return table

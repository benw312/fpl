from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich import print

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.api.snapshots import (
    DEFAULT_ARCHIVE_DIR,
    FixturesResult,
    LiveEventResult,
    PinnedSnapshotError,
    PinnedSnapshotService,
    SnapshotProvenance,
    SnapshotResult,
    SnapshotService,
)
from fpl_cli.builder import BuilderCancelled, SquadBuilder, TerminalTooSmall
from fpl_cli.storage import capture
from fpl_cli.domain.evaluation import (
    actuals_from_live_event,
    archived_capture_time,
    evaluate_model,
    flat_points_per_game_projections,
    select_archived_snapshot,
)
from fpl_cli.domain.optimizer import (
    DEFAULT_DECAY,
    DEFAULT_FT_VALUE,
    OptimiseResult,
    Path as OptPath,
    SearchTooExpensive,
    first_move_key,
    optimise,
    rescore_first_moves,
)
from fpl_cli.domain.projections import (
    ComponentProjection,
    NaiveProjection,
    OfficialEpProjection,
    Projection,
    ProjectionModel,
)
from fpl_cli.domain.rules import validate_squad as validate_squad_players
from fpl_cli.domain.squad import best_xi, objective_points, to_ledger_payload, validate_squad_file, xi_value
from fpl_cli.domain.strength import BandedTeamRates, FittedTeamRates
from fpl_cli.domain import variants
from fpl_cli.domain.transfers import (
    Ledger,
    TransferRules,
    apply_transfers,
    parse_transfers_plan,
    replay,
    selling_price,
    simulate,
    write_transfers_plan,
)
from fpl_cli.presentation import (
    PathRow,
    ProjectionRow,
    console,
    error_console,
    evaluation_category_table,
    evaluation_component_table,
    evaluation_table,
    optimise_header,
    optimise_paths_table,
    optimise_recommendation,
    optimise_why_table,
    player_table,
    projection_table,
    simulation_table,
    squad_state_table,
)
from fpl_cli.transport import FplError

SNAPSHOT_ENV_VAR = "FPL_SNAPSHOT"

# Declared with `Annotated` rather than as a `typer.Option(...)` default so the
# Python-level default stays a real `None`. Every other option in this module
# predates that style and hands a `typer.OptionInfo` to anything that calls the
# command function directly — which the tests do throughout, passing each one
# explicitly to work around it. A pinning flag that read as "pinned to
# OptionInfo" when omitted would be a trap, so this one is left callable.
SnapshotOption = Annotated[
    Path | None,
    typer.Option(
        "--snapshot",
        help=(
            "Pin this run to a bootstrap-static capture at PATH: never fetches, never "
            f"writes the cache. Overrides ${SNAPSHOT_ENV_VAR}."
        ),
    ),
]

# Declared `Annotated` for the same reason as `SnapshotOption`: the tests call
# `cli.sync()` directly, and a `typer.Option(...)` default would hand each of
# them an `OptionInfo` to pass on to `SnapshotService` as an archive directory.
#
# Deliberately with no environment variable behind it, unlike `--snapshot`.
# `--snapshot` names what a run *reads*, so a pinned shell is a coherent thing
# to want; this names where a run *writes* the one artefact that cannot be
# fetched again. A shell variable is invisible at the point of use and sticky
# across the invocations that follow, so the failure it enables is a sync that
# believes it filed the day's canonical capture into an archive it never
# reached. The flag goes on the deviation, never on the routine: forgetting it
# writes a scratch capture nobody wanted, which is recoverable; the inverse —
# a stale variable silently diverting the timer's capture — is not.
ArchiveDirOption = Annotated[
    Path | None,
    typer.Option(
        "--archive-dir",
        help=(
            "File this run's capture under PATH instead of the default archive. For "
            "test and verification syncs. Note this covers the capture only: the "
            "bootstrap and fixtures caches are still refreshed in place."
        ),
    ),
]


# Declared `Annotated` for the same reason as `SnapshotOption` above: the tests
# call `cli.evaluate_plan(...)` directly, and a `typer.Option(...)` default
# would hand them a `typer.OptionInfo` where the code expects a list — which is
# exactly the trap that comment describes, and it fired here the first time.
EvaluateModelsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--model",
        help=(
            "Registered variant to score. Repeatable; default naive/1.0, "
            "component/1.1-price, component/1.2, component/1.2-availability, "
            "official-ep/1.0."
        ),
    ),
]


def resolve_snapshot_path(explicit: Path | None) -> Path | None:
    """`--snapshot` if given, else `$FPL_SNAPSHOT`, else `None` for an unpinned run.

    The flag beats the environment so a pinned shell can still be overridden
    for a single command. An empty or whitespace-only variable reads as unset
    rather than as the current directory.
    """
    if explicit is not None:
        return explicit
    from_env = os.environ.get(SNAPSHOT_ENV_VAR, "").strip()
    return Path(from_env) if from_env else None


def snapshot_service(pinned: Path | None) -> SnapshotService | PinnedSnapshotService:
    """The one place that chooses between the writing service and the read-only one."""
    if pinned is not None:
        return PinnedSnapshotService(pinned)
    return SnapshotService()


@dataclass(frozen=True)
class LoadedSnapshot:
    """A snapshot together with where it came from.

    The provenance is carried alongside rather than derived at the point of
    use, because by then the distinction is gone: a cached snapshot and a live
    one are the same object, and only the load knew which it was. `capture` is
    the manifest block for a directory pin and `None` for every other run — the
    absence is reported, not omitted, so a consumer can tell "this run had no
    manifest" from "this consumer forgot to look".
    """

    snapshot: BootstrapSnapshot
    provenance: SnapshotProvenance
    capture: dict | None = None


def _snapshot_provenance(
    pinned: Path | None, result: SnapshotResult, *, manifest: dict | None
) -> SnapshotProvenance:
    """`path` names the file the snapshot was read from, not the capture that
    contains it — `provenance.capture.path` already names that, and FU-40's
    rule is satisfied by a path a reader can hash, per file, as `fixtures`
    already reports."""
    if pinned is not None:
        path = pinned / capture.BOOTSTRAP_FILENAME if manifest is not None else pinned
        return SnapshotProvenance(source="pinned", captured_at=result.snapshot.fetched_at, path=path)
    return SnapshotProvenance(
        source="cache" if result.stale else "live", captured_at=result.snapshot.fetched_at
    )


def _fixtures_provenance(result: FixturesResult) -> SnapshotProvenance:
    """The result says where it came from; this only reshapes it.

    It used to infer the source from `stale`, which cannot express a pinned
    capture's fixtures — off disk, but neither stale nor cache. The path is
    reported too: FU-40's rule requires a figure to name the fixtures capture,
    and until FU-41 the payload did not supply it.
    """
    return SnapshotProvenance(source=result.source, captured_at=result.fetched_at, path=result.path)


def _capture_block(pinned: Path | None, manifest: dict | None) -> dict | None:
    """The manifest's own record: when the capture was fetched, and which
    gameweek was live at the time (FU-41)."""
    if manifest is None:
        return None
    return {
        "path": str(pinned),
        "captured_at": manifest.get("captured_at"),
        "current_event": manifest.get("current_event"),
    }


app = typer.Typer(help="A local Fantasy Premier League planning CLI.")
players_app = typer.Typer(help="Browse FPL players.")
squad_app = typer.Typer(help="Create and validate local squad plans.")
plan_app = typer.Typer(help="Simulate and optimise transfer plans.")
app.add_typer(players_app, name="players")
app.add_typer(squad_app, name="squad")
app.add_typer(plan_app, name="plan")


def load_snapshot(pinned: Path | None = None) -> LoadedSnapshot:
    service = snapshot_service(pinned)
    try:
        result = service.load()
        manifest = service.manifest() if isinstance(service, PinnedSnapshotService) else None
    except PinnedSnapshotError as exc:
        # Named separately, and first: the generic message below would say the
        # cache was unavailable, when the whole point is that a pinned run
        # never looked at it (snapshot-pinning.md §2).
        error_console.print(str(exc))
        raise typer.Exit(1) from exc
    except FplError as exc:
        error_console.print("No live snapshot or cached snapshot is available.")
        raise typer.Exit(1) from exc
    finally:
        service.close()
    if pinned is not None:
        # stderr, not stdout: `--json` output has to stay parseable.
        shape = "capture" if manifest is not None else "snapshot file"
        error_console.print(
            f"Pinned to {shape} {pinned} (captured {result.snapshot.fetched_at.isoformat()})."
        )
    if result.stale:
        # stderr, for the same reason as the pinned notice above: on stdout
        # this line lands in front of `--json` output and makes it unparseable,
        # in exactly the case a consumer most needs to read the provenance.
        error_console.print(
            f"Using cached snapshot from {result.snapshot.fetched_at.isoformat()} "
            f"— live fetch failed: {result.reason}"
        )
    return LoadedSnapshot(
        snapshot=result.snapshot,
        provenance=_snapshot_provenance(pinned, result, manifest=manifest),
        capture=_capture_block(pinned, manifest),
    )


@app.command()
def sync(archive_dir: ArchiveDirOption = None) -> None:
    """Fetch and cache the current official FPL snapshot and fixtures list."""
    # `archive_dir` goes straight through, and `SnapshotService`'s `None`
    # already means the default archive — so there is no mode to branch on
    # below, and the write path cannot tell a scratch capture from a real one.
    # That is the point: a capture filed to scratch is byte-identical to one
    # filed to the archive, so a good capture taken during verification can be
    # promoted by moving the directory.
    service = SnapshotService(archive_dir=archive_dir)
    try:
        snapshot = service.refresh()
        fixtures = service.refresh_fixtures()
        archived = service.archive(snapshot, fixtures)
    except FplError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc
    finally:
        service.close()
    console.print(f"[green]Synced {len(snapshot.elements)} players for {snapshot.season}.[/green]")
    console.print(f"[green]Synced {len(fixtures)} fixtures.[/green]")
    console.print(f"[green]Archived to {archived.path}/ as {archived.role}.[/green]")
    if archived.quarantined is not None:
        assert archived.problem is not None
        if archived.problem.kind == capture.PROBLEM_UNRECOGNISED_VERSION:
            headline = (
                "was written by a newer build of this tool, not corrupted. Nothing has been "
                "deleted; check whether you are running an old checkout before touching it."
            )
        else:
            headline = "does not verify against its own manifest. Nothing has been deleted."
        console.print(
            f"[yellow]! The capture holding that slot {headline}[/yellow]\n"
            f"[yellow]  moved aside: {archived.quarantined}[/yellow]\n"
            f"[yellow]  reason: {archived.problem.detail}[/yellow]",
            soft_wrap=True,
        )


@players_app.command("list")
def list_players(
    position: str | None = typer.Option(None, "--position", help="GKP, DEF, MID, or FWD."),
    club: str | None = typer.Option(None, "--club"),
    name: str | None = typer.Option(None, "--name"),
    available_only: bool = typer.Option(False, "--available-only"),
    limit: int = typer.Option(25, min=1, max=200),
    snapshot_path: SnapshotOption = None,
) -> None:
    """List players from the latest available snapshot."""
    snapshot = load_snapshot(resolve_snapshot_path(snapshot_path)).snapshot
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
        if club_id is None:
            # FU-17: an unknown club used to fall through to an empty list, which
            # is indistinguishable from a club that genuinely matched nothing.
            # The valid set is known here — it came from the snapshot four lines
            # up — so name it rather than leaving the user to guess. `--club`
            # matches full names only, so the list also discloses that (FU-68).
            known = ", ".join(sorted(item.name for item in snapshot.teams))
            raise typer.BadParameter(f"Unknown club {club!r}. Known clubs: {known}")
        players = [player for player in players if player.team == club_id]
    if name:
        query = name.lower()
        players = [player for player in players if query in player.display_name.lower()]
    if available_only:
        players = [player for player in players if player.can_select and not player.removed and player.status == "a"]
    players = sorted(players, key=lambda player: (-player.total_points, player.display_name))[:limit]
    console.print(player_table(players, snapshot))


# `p_start` is on every `Projection`, but it only means a start rate under
# `component`. `naive` puts the raw availability scalar there and `official-ep`
# hardcodes 0.0 — its own `assumptions` tuple says "p_start and xmins are not
# modelled" — so rendering a percentage for it would invent a measurement.
# Keyed off the `--model` string rather than sniffed from the model object
# because `Projection` has no way to mark a field as unmodelled (FU-45).
_START_NOTES = {
    "component": "Start% = modelled probability of starting. Not an interval, and not calibrated.",
    "naive": "Start% = availability only; naive models no start rate.",
    "official-ep": "Start% is not modelled by official-ep.",
}


@players_app.command("project")
def project_players(
    position: list[str] = typer.Option(
        None, "--position", help="GKP, DEF, MID or FWD. Repeatable; default all."
    ),
    top: int = typer.Option(30, "--top", min=1, help="Rows to show."),
    horizon: int = typer.Option(5, "--horizon", min=1, help="Gameweeks to average over."),
    model: str = typer.Option("component", "--model", help="component | naive | official-ep."),
    include_unavailable: bool = typer.Option(
        False, "--include-unavailable", help="Include players who cannot be bought."
    ),
    snapshot_path: SnapshotOption = None,
) -> None:
    """Rank players by projected points (docs/plans/players-project.md).

    A diagnostic, not a recommendation: the projections are unvalidated, and
    reading the top of this table is the cheapest check that the minutes model
    is producing sensible names.
    """
    if model not in _MODEL_CHOICES:
        raise typer.BadParameter(f"--model must be one of {_MODEL_CHOICES}.")

    snapshot = load_snapshot(resolve_snapshot_path(snapshot_path)).snapshot
    now = datetime.now(UTC)

    # Named `--position` rather than failing silently on an unknown value, which
    # is FU-17's still-open defect on `players list --club`. One new command is
    # not the place to add a third instance of it.
    positions_by_code = {item.singular_name_short.upper(): item.id for item in snapshot.element_types}
    requested = [value.upper() for value in (position or [])]
    unknown = [value for value in requested if value not in positions_by_code]
    if unknown:
        valid = ", ".join(sorted(positions_by_code))
        raise typer.BadParameter(f"Unknown --position {unknown[0]!r}. Use one of {valid}.")
    wanted_type_ids = {positions_by_code[value] for value in requested}

    from_event = _next_open_event(snapshot, now)
    if from_event is None:
        error_console.print("No upcoming gameweek with an open deadline in this snapshot. Run `fpl sync`.")
        raise typer.Exit(1)

    scheduled = [gameweek.id for gameweek in snapshot.events]
    last_scheduled = max(scheduled) if scheduled else None
    if last_scheduled is not None and from_event + horizon - 1 > last_scheduled:
        horizon = last_scheduled - from_event + 1
        if horizon < 1:
            error_console.print(f"No scheduled gameweek at or after GW{from_event} in this snapshot.")
            raise typer.Exit(1)
        error_console.print(f"Horizon clamped to {horizon} — GW{last_scheduled} is the last scheduled gameweek.")

    # `OfficialEpProjection.project` raises for any event but the snapshot's own
    # next one (projections.py:383-387). `_alt_models` skips it silently on that
    # condition; here the user named the model, so refusing beats projecting
    # something they did not ask for.
    next_event = next((gameweek.id for gameweek in snapshot.events if gameweek.is_next), None)
    if model == "official-ep" and (horizon != 1 or from_event != next_event):
        error_console.print(
            f"--model official-ep only projects the snapshot's next gameweek "
            f"({next_event}) at --horizon 1; this run is GW{from_event} at horizon {horizon}."
        )
        raise typer.Exit(1)

    service = snapshot_service(resolve_snapshot_path(snapshot_path))
    try:
        fixtures_result = service.load_fixtures()
    except FplError as exc:
        error_console.print(f"Could not load fixtures: {exc}")
        raise typer.Exit(1) from exc
    finally:
        service.close()

    candidates = [
        player
        for player in snapshot.elements
        if not wanted_type_ids or player.element_type in wanted_type_ids
    ]
    # `can_select and not removed` is the optimiser's own usability predicate
    # (FU-28's `_validator_usable`, unchanged by FU-35): a player the validator
    # will not accept cannot be bought, so ranking them is noise. Deliberately
    # not `players list`'s stricter `status == "a"` — a doubtful player is
    # buyable, and is exactly the row worth sense-checking.
    usable = [player for player in candidates if player.can_select and not player.removed]
    suppressed = len(candidates) - len(usable)
    if include_unavailable:
        usable, suppressed = candidates, 0
    if not usable:
        error_console.print("No players match those filters.")
        raise typer.Exit(1)

    events = [from_event + offset for offset in range(horizon)]
    projection_model = _build_model(model, snapshot, fixtures_result)
    try:
        by_event = _projections_by_event(projection_model, [player.id for player in usable], events)
    except ValueError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc

    clubs = snapshot.clubs
    position_names = snapshot.positions
    rows: list[ProjectionRow] = []
    for player in usable:
        projections = [by_event[event][player.id] for event in events]
        club = clubs.get(player.team)
        position_name = position_names.get(player.element_type)
        rows.append(
            ProjectionRow(
                player=" · ".join(
                    (
                        player.display_name,
                        # `short_name or name` for the same reason
                        # `Player.display_name` falls back: a blank cell in a
                        # diagnostic table is a silent failure, and the API
                        # types the field as optional even though it is always
                        # populated in practice.
                        (club.short_name or club.name) if club else str(player.team),
                        position_name.singular_name_short if position_name else str(player.element_type),
                    )
                ),
                next_gw=projections[0].xp_total,
                mean_xp=sum(item.xp_total for item in projections) / len(projections),
                fixtures=sum(item.fixtures for item in projections),
                start_pct=None if model == "official-ep" else projections[0].p_start,
            )
        )

    # Sorted on the next gameweek as specified. players-project.md §2 argues the
    # horizon mean is the better default and is the thing to change if so.
    rows.sort(key=lambda row: (-row.next_gw, row.player))
    console.print(
        projection_table(
            rows[:top],
            snapshot=snapshot,
            events=events,
            model_name=projection_model.name,
            start_note=_START_NOTES[model],
            suppressed=suppressed,
        )
    )


@squad_app.command("create")
def create_squad(
    output: Path = typer.Option(Path("squad.json"), "--output", help="Where to write the squad ledger."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing output file."),
    snapshot_path: SnapshotOption = None,
) -> None:
    """Interactively build a 15-player squad and write it as a transfer ledger."""
    if not sys.stdin.isatty():
        console.print("[red]fpl squad create requires an interactive terminal.[/red]")
        raise typer.Exit(1)
    if output.exists() and not force:
        console.print(f"[red]{output} already exists. Use --force to overwrite.[/red]")
        raise typer.Exit(1)

    snapshot = load_snapshot(resolve_snapshot_path(snapshot_path)).snapshot
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
def validate_squad(path: Path, snapshot_path: SnapshotOption = None) -> None:
    """Validate a JSON squad plan or transfer ledger against the current FPL rules."""
    snapshot = load_snapshot(resolve_snapshot_path(snapshot_path)).snapshot
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
def simulate_plan(squad_path: Path, transfers_path: Path, snapshot_path: SnapshotOption = None) -> None:
    """Simulate transfers from a squad ledger against a transfers plan file."""
    pinned = resolve_snapshot_path(snapshot_path)
    snapshot = load_snapshot(pinned).snapshot

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

    service = snapshot_service(pinned)
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


# --- fpl plan optimise (docs/plans/optimizer-ux.md) -------------------------

# §4: "there is no empirical basis for any threshold until the benchmark has
# been run. Until then the value is a placeholder and the output must say so
# rather than implying the margin is calibrated." No `fpl plan evaluate` run
# is persisted anywhere in this repo (it prints and exits), so there is no
# recorded RMSE to derive one from — this constant is that placeholder, in
# decayed-score points between the best and second-best distinct first move.
# [gap: uncalibrated; optimizer-ux.md §4 names this open question directly.]
_DECISION_MARGIN_PLACEHOLDER = 0.5

_MODEL_CHOICES = ("component", "naive", "official-ep")
_ROBUSTNESS_CHOICES = ("rescore", "full", "off")


def _next_open_event(snapshot: BootstrapSnapshot, now: datetime) -> int | None:
    open_events = sorted(
        (gw for gw in snapshot.events if gw.deadline_time is not None and gw.deadline_time > now),
        key=lambda gw: gw.id,
    )
    return open_events[0].id if open_events else None


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# The short names the CLI has always taken, mapped to registered variants. Both
# forms resolve: `--model component` is the default component variant, and a
# variant can also be named in full, which is how FU-47's variants are selected
# without a new alias each time.
#
# `component` moved from `component/1.0` to `component/1.1-price` on
# task/default-1.1-and-preregistration. The reason is correctness, not the
# evaluation: 1.0 consumes the API's per-90 rates as published, so one minute
# played yields a rating like 270 defensive contributions per 90, which is not
# a defensible input to anything. 1.0 stays registered — it is the comparison
# point every measurement so far is quoted against, and unregistering it would
# make those figures unreproducible.
#
# It moved again to `component/1.2` on 2026-09-19, and this one *is* the
# evaluation: FU-60 pre-registered on 2026-09-02 that 1.2 takes the default if
# and only if it beats 1.1-price on `spearman_played` in each of GW3 and GW4,
# strictly and with no margin. It did — +0.032 then +0.000517 (gw3-evaluation.md,
# gw4-evaluation.md). The second margin is 62x smaller than the first and the
# criterion has no margin clause; FU-60 §8 forbids introducing one after the
# figure exists, in either direction.
#
# Two things a reader should carry, neither of which changes the above.
# FU-60 §4 predicted the margin would shrink as appearances accumulate and §6.4
# confirms the mechanism, so a thin leg 2 was foreseen rather than discovered.
# And under FU-50 §4 — a *separate* standing rule — the best component variant
# lost to `naive/1.0` at GW4 for the first time; that clause needs two clean
# gameweeks and GW5 settles it. If it fires, the default moves again, to
# `naive/1.0`.
#
# 1.1-price stays registered for the same reason 1.0 did.
_MODEL_ALIASES: dict[str, str] = {
    "component": "component/1.2",
    "naive": "naive/1.0",
    "official-ep": "official-ep/1.0",
}


def resolve_variant(name: str) -> variants.ModelVariant:
    """A short alias or a registered variant name -> the variant.

    Raises `typer.BadParameter` naming what is available, rather than the
    KeyError the registry raises, so an unknown `--model` reads as a usage
    error at the point the user made it.
    """
    try:
        return variants.get(_MODEL_ALIASES.get(name, name))
    except KeyError as exc:
        available = ", ".join(sorted(set(_MODEL_ALIASES) | set(variants.names())))
        raise typer.BadParameter(f"Unknown --model {name!r}. Available: {available}.") from exc


def _build_model(name: str, snapshot: BootstrapSnapshot, fixtures_result) -> ProjectionModel:
    return variants.build(
        resolve_variant(name),
        snapshot,
        fixtures_result.fixtures,
        fixtures_stale=fixtures_result.stale,
        fixtures_fetched_at=fixtures_result.fetched_at,
    )


def _projections_by_event(
    model: ProjectionModel, player_ids: list[int], events: list[int]
) -> dict[int, dict[int, Projection]]:
    flat = model.project(player_ids, events)
    return {event: {pid: proj for (pid, proj_event), proj in flat.items() if proj_event == event} for event in events}


def _flat_ppg_by_event(snapshot: BootstrapSnapshot, events: list[int]) -> dict[int, dict[int, Projection]]:
    return {event: flat_points_per_game_projections(snapshot, event) for event in events}


def _alt_models(
    primary: str, snapshot: BootstrapSnapshot, fixtures_result, horizon: int, from_event: int
) -> list[tuple[str, ProjectionModel | None]]:
    """optimizer-ux.md §6: re-rank under every model but the one already
    chosen as primary, plus the flat baseline (`None` marks it — it's a
    function, not a `ProjectionModel`). `OfficialEpProjection` only
    participates at horizon 1 *and* only when `from_event` is the snapshot's
    own next event — its own `.project` raises `ValueError` for any other
    event (projections.py:383-387), so this guard is what keeps that call
    safe rather than catching the exception after the fact.
    """
    next_event = next((gw.id for gw in snapshot.events if gw.is_next), None)
    alts: list[tuple[str, ProjectionModel | None]] = []
    for name in _MODEL_CHOICES:
        if name == primary:
            continue
        if name == "official-ep" and (horizon != 1 or from_event != next_event):
            continue
        alts.append((name, _build_model(name, snapshot, fixtures_result)))
    alts.append(("baseline/flat-ppg", None))
    return alts


def _group_best_by_first_move(paths: list[OptPath]) -> dict[tuple[tuple[int, int], ...], float]:
    best: dict[tuple[tuple[int, int], ...], float] = {}
    for path in paths:
        key = first_move_key(path.first_move)
        if key not in best or path.score > best[key]:
            best[key] = path.score
    return best


def _robustness_report(
    primary_key: tuple[tuple[int, int], ...],
    alt_named_scores: list[tuple[str, dict[tuple[tuple[int, int], ...], float]]],
) -> tuple[str, str]:
    total = 1 + len(alt_named_scores)
    agree = 1
    disagreements: list[str] = []
    for name, scores in alt_named_scores:
        ranked = sorted(scores.items(), key=lambda item: -item[1])
        rank = next((index + 1 for index, (key, _) in enumerate(ranked) if key == primary_key), None)
        if rank == 1:
            agree += 1
        elif rank is None:
            disagreements.append(f"{name} did not find this move")
        else:
            disagreements.append(f"{name} ranks it {_ordinal(rank)}")
    verdict = "ROBUST" if agree == total else "MARGINAL" if agree > total / 2 else "UNSTABLE"
    label = f"{verdict} — {agree} of {total} models rank this first"
    if disagreements:
        label += " (" + "; ".join(disagreements) + ")"
    return verdict, label


def _distinct_top_paths(paths: list[OptPath], count: int) -> list[OptPath]:
    seen: set[tuple[tuple[int, int], ...]] = set()
    selected: list[OptPath] = []
    for path in paths:
        key = first_move_key(path.first_move)
        if key in seen:
            continue
        seen.add(key)
        selected.append(path)
        if len(selected) >= count:
            break
    return selected


def _move_description(transfers, snapshot: BootstrapSnapshot, hit: int, *, horizon_edge: bool) -> str:
    if not transfers:
        return "—"
    players_by_id = snapshot.players_by_id
    description = " + ".join(
        f"{players_by_id[t.out_id].display_name}→{players_by_id[t.in_id].display_name}" for t in transfers
    )
    if hit:
        description += f" (−{hit})"
    if horizon_edge:
        description += "‡"
    return description


def _path_row(label: str, path: OptPath, snapshot: BootstrapSnapshot, projections_by_event: dict[int, dict[int, Projection]]) -> PathRow:
    chain = path.chain()
    moves: list[str] = []
    points: list[float] = []
    for index, node in enumerate(chain):
        step_hit = node.hit_points - (node.parent.hit_points if node.parent is not None else 0)
        moves.append(_move_description(node.transfers, snapshot, step_hit, horizon_edge=index == len(chain) - 1))
        # FU-32: node.xi is deferred, not cached — reproduced here from
        # state.player_ids and the projection table (Node's docstring).
        node_projections = projections_by_event[node.event]
        xi = best_xi(node.state.player_ids, node_projections, snapshot)
        points.append(objective_points(xi, node_projections))
    return PathRow(label=label, moves=moves, points=points, net=path.net, score=path.score)


def _event_range(events: list[int]) -> str:
    return f"GW{events[0]}–GW{events[-1]}" if len(events) > 1 else f"GW{events[0]}"


def _scope_gap_lines(scope_gaps: list) -> list[str]:
    """FU-29: one line per run of consecutive events sharing the same k_rules,
    instead of one line per event."""
    lines: list[str] = []
    index = 0
    while index < len(scope_gaps):
        run_end = index
        while (
            run_end + 1 < len(scope_gaps)
            and scope_gaps[run_end + 1].event == scope_gaps[run_end].event + 1
            and scope_gaps[run_end + 1].k_rules == scope_gaps[index].k_rules
            and scope_gaps[run_end + 1].k_enum == scope_gaps[index].k_enum
        ):
            run_end += 1
        run = scope_gaps[index : run_end + 1]
        verb = "allows" if len(run) == 1 else "allow"
        lines.append(
            f"{_event_range([gap.event for gap in run])} {verb} up to {run[0].k_rules} transfers under the "
            f"rules; this search considers ≤{run[0].k_enum} per gameweek (FU-29, --schedule)."
        )
        index = run_end + 1
    return lines


@plan_app.command("optimise")
def optimise_plan(
    squad_path: Path,
    horizon: int = typer.Option(5, "--horizon", help="Gameweeks to search."),
    from_event: int | None = typer.Option(None, "--from-event", help="First gameweek to plan."),
    paths: int = typer.Option(3, "--paths", min=1, help="Full paths to display."),
    max_hit: int | None = typer.Option(None, "--max-hit", help="Cap on hit points per gameweek (default: uncapped)."),
    model: str = typer.Option("component", "--model", help="component | naive | official-ep."),
    decay: float = typer.Option(DEFAULT_DECAY, "--decay", help="Per-gameweek discount on the ranking objective."),
    robustness: str = typer.Option("rescore", "--robustness", help="rescore | full | off."),
    explain: bool = typer.Option(False, "--explain", help="Per-gameweek, per-player decomposition for the top path."),
    output: Path | None = typer.Option(None, "--output", help="Write the winning path as a transfers-plan JSON."),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output."),
    snapshot_path: SnapshotOption = None,
) -> None:
    """Search for the best transfer plan over the horizon (docs/plans/optimizer-ux.md)."""
    if model not in _MODEL_CHOICES:
        raise typer.BadParameter(f"--model must be one of {_MODEL_CHOICES}.")
    if robustness not in _ROBUSTNESS_CHOICES:
        raise typer.BadParameter(f"--robustness must be one of {_ROBUSTNESS_CHOICES}.")
    if model == "official-ep" and horizon != 1:
        error_console.print("--model official-ep only supports --horizon 1 (projections.py:383-387).")
        raise typer.Exit(1)

    pinned = resolve_snapshot_path(snapshot_path)
    loaded = load_snapshot(pinned)
    snapshot = loaded.snapshot
    now = datetime.now(UTC)

    try:
        ledger = Ledger.from_file(squad_path, snapshot)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        error_console.print(f"Could not read squad ledger: {exc}")
        raise typer.Exit(1) from exc
    rules = TransferRules.from_snapshot(snapshot)
    initial_state = replay(ledger, snapshot)

    if from_event is None:
        auto = _next_open_event(snapshot, now)
        if auto is None:
            error_console.print("No upcoming gameweek with an open deadline in this snapshot. Run `fpl sync`.")
            raise typer.Exit(1)
        from_event = auto
    else:
        gameweek = next((gw for gw in snapshot.events if gw.id == from_event), None)
        if gameweek is None or gameweek.deadline_time is None:
            error_console.print(f"Gameweek {from_event} has no known deadline in this snapshot.")
            raise typer.Exit(1)
        if now >= gameweek.deadline_time:
            auto = _next_open_event(snapshot, now)
            suggestion = f" The next open gameweek is GW{auto}." if auto is not None else ""
            error_console.print(f"GW{from_event}'s deadline has passed.{suggestion}")
            raise typer.Exit(1)

    scheduled_events = [gw.id for gw in snapshot.events]
    last_scheduled = max(scheduled_events) if scheduled_events else None
    horizon_clamped = False
    if last_scheduled is not None and from_event + horizon - 1 > last_scheduled:
        horizon = last_scheduled - from_event + 1
        horizon_clamped = True
        if horizon < 1:
            error_console.print(f"No scheduled gameweek at or after GW{from_event} in this snapshot.")
            raise typer.Exit(1)

    service = snapshot_service(pinned)
    try:
        fixtures_result = service.load_fixtures()
    except FplError as exc:
        error_console.print(f"Could not load fixtures: {exc}")
        raise typer.Exit(1) from exc
    finally:
        service.close()

    primary_model = _build_model(model, snapshot, fixtures_result)
    events = [from_event + offset for offset in range(horizon)]
    player_ids = [player.id for player in snapshot.elements]
    try:
        projections_flat = primary_model.project(player_ids, events)
    except ValueError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc

    effective_max_hit = max_hit if max_hit is not None else 10**9

    try:
        result: OptimiseResult = optimise(
            initial_state,
            snapshot,
            projections_flat,
            rules,
            from_event=from_event,
            horizon=horizon,
            decay=decay,
            ft_value=DEFAULT_FT_VALUE,
            max_hit=effective_max_hit,
            now=now,
        )
    except SearchTooExpensive as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc
    except ValueError as exc:
        error_console.print(str(exc))
        raise typer.Exit(1) from exc

    events = result.events  # the (possibly re-derived) horizon the search actually used
    projections_by_event = _projections_by_event(primary_model, player_ids, events)

    # Two different points on the hold path are needed: state right before the
    # horizon starts (for the header's "state at GW{from_event}") and state at
    # the horizon's last event (for the pinned HOLD row's terminal free-transfer
    # value) — free transfers accrue between the two even though bank does not.
    state_at_from_event = apply_transfers(initial_state, [], from_event, snapshot, rules, now=now).state
    hold_terminal = apply_transfers(initial_state, [], events[-1], snapshot, rules, now=now).state
    hold_points = [xi_value(initial_state.player_ids, projections_by_event[event], snapshot) for event in events]
    hold_free_after = min(hold_terminal.free_transfers, rules.free_transfer_cap)
    hold_score = (decay ** (horizon - 1)) * DEFAULT_FT_VALUE * hold_free_after
    hold_row = PathRow(label="", moves=[], points=hold_points, net=0.0, score=hold_score, is_hold=True)

    display_paths = _distinct_top_paths(result.paths, paths)
    rows = [_path_row(str(index + 1), path, snapshot, projections_by_event) for index, path in enumerate(display_paths)]
    rows.append(hold_row)

    winner = result.paths[0]
    winner_chain = winner.chain()  # one node per horizon event; never empty
    margin = (
        display_paths[0].score - display_paths[1].score if len(display_paths) >= 2 else float("inf")
    )
    headline_verdict = "RECOMMENDED" if margin >= _DECISION_MARGIN_PLACEHOLDER else "MARGINAL"

    if winner.first_move:
        root_hit = winner_chain[0].hit_points
        description = _move_description(winner.first_move, snapshot, root_hit, horizon_edge=False)
        break_even = float(root_hit)
    else:
        description = f"hold (roll to {winner_chain[0].state.free_transfers} free transfers)"
        break_even = 0.0
    gross = winner.net + winner.hit_points
    event_range = _event_range(events)

    robustness_line: str | None = None
    if robustness != "off":
        primary_key = first_move_key(winner.first_move)
        alt_named_scores: list[tuple[str, dict[tuple[tuple[int, int], ...], float]]] = []
        for name, alt_model in _alt_models(model, snapshot, fixtures_result, horizon, from_event):
            try:
                alt_table = (
                    _flat_ppg_by_event(snapshot, events)
                    if alt_model is None
                    else _projections_by_event(alt_model, player_ids, events)
                )
            except ValueError:
                continue
            if robustness == "rescore":
                scores = rescore_first_moves(result.paths, initial_state, snapshot, decay, events, alt_table)
            else:  # full
                alt_flat = {(pid, event): proj for event, table in alt_table.items() for pid, proj in table.items()}
                try:
                    alt_result = optimise(
                        initial_state, snapshot, alt_flat, rules,
                        from_event=from_event, horizon=horizon, decay=decay,
                        ft_value=DEFAULT_FT_VALUE, max_hit=effective_max_hit, now=now,
                    )
                except (SearchTooExpensive, ValueError):
                    continue
                scores = _group_best_by_first_move(alt_result.paths)
            alt_named_scores.append((name, scores))
        _, robustness_line = _robustness_report(primary_key, alt_named_scores)

    last_finished = max((gw.id for gw in snapshot.events if gw.finished), default=None)
    scope_gap_lines = _scope_gap_lines(result.scope_gaps)

    if json_output:
        payload = {
            "squad": str(squad_path),
            "model": primary_model.name,
            "events": events,
            "horizon": horizon,
            "horizon_clamped": horizon_clamped,
            "from_event": from_event,
            "unvalidated": True,
            # FU-40: a figure taken from this payload names the capture it came
            # from, so quoting it in a plan or a commit message does not depend
            # on the cache still holding what it held at the time.
            "provenance": {
                "snapshot": loaded.provenance.as_json(),
                "fixtures": _fixtures_provenance(fixtures_result).as_json(),
                "capture": loaded.capture,
            },
            "dominance_exclusions": len(result.dominance_exclusions),
            "scope_gaps": [
                {"event": gap.event, "free_transfers": gap.free_transfers, "k_rules": gap.k_rules, "k_enum": gap.k_enum}
                for gap in result.scope_gaps
            ],
            "recommendation": {
                "verdict": headline_verdict,
                "description": description,
                "break_even": break_even,
                "gross": gross,
                "net": winner.net,
            },
            "robustness": robustness_line,
            "paths": [
                {"label": row.label, "moves": row.moves, "points": row.points, "net": row.net, "score": row.score}
                for row in rows
            ],
        }
        if output is not None:
            transfers_by_event = {node.event: list(node.transfers) for node in winner_chain}
            write_transfers_plan(output, transfers_by_event)
            payload["output"] = str(output)
        # Not `rich.print`: it word-wraps at the console width and folds an
        # over-long token, so a payload carrying an absolute path — which
        # `provenance` now always may — comes out as invalid JSON.
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return

    console.print(
        optimise_header(
            squad_path=str(squad_path),
            events=events,
            horizon=horizon,
            horizon_clamped=horizon_clamped,
            model_name=primary_model.name,
            last_finished_event=last_finished,
            snapshot_fetched_at=snapshot.fetched_at,
            fixtures_fetched_at=fixtures_result.fetched_at,
            fixtures_stale=fixtures_result.stale,
            from_event=from_event,
            deadline=next((gw.deadline_time for gw in snapshot.events if gw.id == from_event), None),
            now=now,
            bank=state_at_from_event.bank,
            free_transfers=state_at_from_event.free_transfers,
            unvalidated=True,
            scope_gap_lines=scope_gap_lines,
        )
    )
    console.print(
        optimise_recommendation(
            verdict=headline_verdict,
            from_event=from_event,
            description=description,
            break_even=break_even,
            gross=gross,
            net=winner.net,
            event_range=event_range,
            robustness_line=robustness_line,
        )
    )
    console.print("")
    console.print(optimise_paths_table(rows, events))
    console.print(
        "  Net = projected points vs holding, after hits.  Score = decayed "
        f"({decay}), the sort key."
    )
    if any("‡" in move for row in rows for move in row.moves):
        console.print("  ‡ horizon-edge decision — see optimizer-ux.md §5.3.")

    later_transfer_nodes = [node for node in winner_chain[1:] if node.transfers]
    if later_transfer_nodes and winner.first_move:
        first_later = later_transfer_nodes[0]
        first_move_hit = winner_chain[0].hit_points
        first_move_state = winner_chain[0].state
        first_move_realised_total = sum(
            xi_value(first_move_state.player_ids, projections_by_event[event], snapshot)
            - xi_value(initial_state.player_ids, projections_by_event[event], snapshot)
            for event in events
        )
        first_move_net = first_move_realised_total - first_move_hit
        remaining = winner.net - first_move_net
        later_hit = first_later.hit_points - first_later.parent.hit_points
        later_desc = _move_description(first_later.transfers, snapshot, 0, horizon_edge=False)
        hit_word = "free" if later_hit == 0 else f"−{later_hit}"
        console.print(f"\n  Path 1's remaining {remaining:+.1f} comes from GW{first_later.event} {later_desc} ({hit_word}). See --explain.")

    if not explain:
        if output is not None:
            transfers_by_event = {node.event: list(node.transfers) for node in winner_chain}
            write_transfers_plan(output, transfers_by_event)
            console.print(f"\n[green]Wrote {output}.[/green]")
        return

    console.print("")
    if not winner.first_move:
        console.print(f"Why — GW{from_event}: hold — no transfer to explain.")
    else:
        first_node = winner_chain[0]
        first_move_state = first_node.state
        out_rows = [
            (
                f"{snapshot.players_by_id[t.out_id].display_name} ({snapshot.clubs[snapshot.players_by_id[t.out_id].team].short_name})",
                [projections_by_event[event][t.out_id].xp_total for event in events],
                sum(projections_by_event[event][t.out_id].xp_total for event in events),
            )
            for t in winner.first_move
        ]
        in_rows = [
            (
                f"{snapshot.players_by_id[t.in_id].display_name} ({snapshot.clubs[snapshot.players_by_id[t.in_id].team].short_name})",
                [projections_by_event[event][t.in_id].xp_total for event in events],
                sum(projections_by_event[event][t.in_id].xp_total for event in events),
            )
            for t in winner.first_move
        ]
        raw_delta = [
            sum(projections_by_event[event][t.in_id].xp_total for t in winner.first_move)
            - sum(projections_by_event[event][t.out_id].xp_total for t in winner.first_move)
            for event in events
        ]
        realised = [
            xi_value(first_move_state.player_ids, projections_by_event[event], snapshot)
            - xi_value(initial_state.player_ids, projections_by_event[event], snapshot)
            for event in events
        ]
        hit = float(first_node.hit_points)
        net = sum(realised) - hit

        console.print(f"Why — GW{from_event}: {description}  (the first move of path 1)")
        console.print("")
        console.print(
            optimise_why_table(
                events=events,
                out_rows=out_rows,
                in_rows=in_rows,
                raw_delta=raw_delta,
                raw_delta_total=sum(raw_delta),
                realised=realised,
                realised_total=sum(realised),
                hit=hit,
                net=net,
            )
        )

        footnotes: list[str] = []
        benched_events_by_out_id: dict[int, list[int]] = {}
        for event in events:
            hold_xi = best_xi(initial_state.player_ids, projections_by_event[event], snapshot)
            for t in winner.first_move:
                out_player = snapshot.players_by_id[t.out_id]
                if projections_by_event[event][t.out_id].fixtures == 0:
                    footnotes.append(f"GW{event}: {out_player.display_name}'s club blanks (0 fixtures)")
                elif t.out_id not in hold_xi.starters:
                    benched_events_by_out_id.setdefault(t.out_id, []).append(event)
        for t in winner.first_move:
            benched_events = benched_events_by_out_id.get(t.out_id, [])
            out_player = snapshot.players_by_id[t.out_id]
            if benched_events == events:
                footnotes.append(
                    f"{out_player.display_name} would have been benched in {_event_range(benched_events)} — "
                    "selling him cost nothing those weeks"
                )
            else:
                for event in benched_events:
                    footnotes.append(
                        f"GW{event}: {out_player.display_name} would have been benched anyway — "
                        "selling him cost nothing that week"
                    )
        for note in footnotes:
            console.print(f"  * {note}")

        for t in winner.first_move:
            out_player = snapshot.players_by_id[t.out_id]
            in_player = snapshot.players_by_id[t.in_id]
            holding = initial_state.holdings[t.out_id]
            sale = selling_price(holding.purchase_price, out_player.now_cost, rules)
            profit = sale - holding.purchase_price
            if profit > 0:
                console.print(
                    f"  Sale: {out_player.display_name} £{sale / 10:.1f}m (bought £{holding.purchase_price / 10:.1f}m; "
                    f"+£{profit / 10:.1f}m kept after the {rules.sell_on_fee * 100:.0f}% sell-on fee)"
                )
            else:
                console.print(f"  Sale: {out_player.display_name} £{sale / 10:.1f}m (bought £{holding.purchase_price / 10:.1f}m)")
            console.print(f"  Buy:  {in_player.display_name} £{in_player.price_millions:.1f}m")
        console.print(f"  Bank £{initial_state.bank / 10:.1f}m → £{first_move_state.bank / 10:.1f}m")

    if output is not None:
        transfers_by_event = {node.event: list(node.transfers) for node in winner_chain}
        write_transfers_plan(output, transfers_by_event)
        console.print(f"\n[green]Wrote {output}.[/green]")


plan_app.command("optimize", hidden=True)(optimise_plan)


def _report_live_provenance(result: LiveEventResult) -> None:
    """Say whether the actuals being scored against were final.

    FU-40's rule applied to the third input: a figure quoted from a run should
    carry what it was measured against. `plan evaluate` has no `--json` to
    report provenance through (FU-41 records the gap, FU-43 asks for the flag),
    so this goes on the console — where it is arguably more use, since the
    number it qualifies is printed there too.

    The settled line is deliberately printed rather than left implicit. "No
    warning appeared" is indistinguishable from "the check was skipped", and
    the whole point of recording finality is that the reader can tell.
    """
    provenance = result.provenance
    event = result.event
    if provenance.settled:
        console.print(
            f"[dim]GW{event} actuals: final (finished, data checked), from "
            f"{provenance.source}.[/dim]"
        )
        return
    detail = (
        f"finished={provenance.finished}, data_checked={provenance.data_checked}"
        if provenance.finished is not None
        else provenance.detail or "finality not recorded"
    )
    console.print(
        f"[yellow]! GW{event} actuals are NOT final ({detail}).[/yellow]\n"
        f"[yellow]  FPL awards bonus points and applies stat corrections after the final "
        f"whistle, so these scores will still change. This is an indication, not a "
        f"backtest — do not quote it as one.[/yellow]",
        soft_wrap=True,
    )


# The models evaluated when `--model` is not given. `component/1.1-price`
# replaced `component/1.0` here when it became the default, so the default run
# scores the model the rest of the CLI actually uses. `component/1.0` is still
# registered and still scored by naming it, which is how the two are compared.
#
# `component/1.2` joins the default run without becoming the default *model*:
# the `component` alias above still resolves to `component/1.1-price`, which is
# what `plan optimise` and `players project` use. It is here so that GW3 scores
# 1.2 against the same capture and the same actuals as everything else, in one
# run — comparing two runs compares two runs (this command's own docstring).
# Whether it is promoted is FU-50 §2's two-gameweek question, not this branch's.
#
# `component/1.2-availability` joins it for the same reason and a sharper one:
# it is 1.2 with S6(a) removed, and it decomposes 1.2's result only if all three
# are scored against one capture and one set of actuals. Registered after GW3
# kicked off — see FU-60 §6 for why that is defensible and how it is recorded.
_DEFAULT_EVALUATE_MODELS: tuple[str, ...] = (
    "naive/1.0",
    "component/1.1-price",
    "component/1.2",
    "component/1.2-availability",
    # FU-73 §4: both halves of 1.3 scored in the same run as their controls.
    "component/1.3-fixtures",
    "component/1.3",
    "official-ep/1.0",
)


def _report_strength_fit(built: object) -> None:
    """One line per fitted-strength model: what it fitted on, or why it fell
    back to the banded model. model-1.3.md §3.2 requires the fallback be
    recorded, and a figure quoted for `component/1.3` is not interpretable
    without knowing which strength model actually produced it."""
    rates_model = getattr(built, "rates_model", None)
    if not isinstance(rates_model, FittedTeamRates):
        return
    fit = rates_model.fit
    name = getattr(built, "name", "?")
    if fit.fallback:
        print(
            f"[yellow]{name}: fitted strength fell back to banded — {fit.fallback} "
            f"({fit.matches} results before GW{fit.target_event}).[/yellow]"
        )
        return
    print(
        f"{name}: fitted strength on {fit.matches} results before GW{fit.target_event} — "
        f"mu {fit.mu:.3f}, home {fit.home_factor:.3f}, away {fit.away_factor:.3f}, "
        f"prior {fit.prior_goals_attack / fit.mu:.1f} games (attack), "
        f"{fit.prior_goals_defence / fit.mu:.1f} games (defence)."
    )


@plan_app.command("evaluate")
def evaluate_plan(
    event: int = typer.Option(..., "--event", help="Gameweek to evaluate against actual results."),
    model: EvaluateModelsOption = None,
    snapshot_path: SnapshotOption = None,
) -> None:
    """Score projection models against a finished gameweek's actual points.

    `--model` is repeatable, and every model named is scored against **one** set
    of actuals from **one** capture in a single run. That is the point of the
    flag: comparing two variants by running the command twice and diffing the
    tables by hand compares two runs, which may have selected different archives
    or different event-live payloads between them.
    """
    pinned = resolve_snapshot_path(snapshot_path)
    current_snapshot = load_snapshot(pinned).snapshot
    gameweek = next((gw for gw in current_snapshot.events if gw.id == event), None)
    if gameweek is None:
        error_console.print(f"No gameweek {event} in the current snapshot.")
        raise typer.Exit(1)

    service = snapshot_service(pinned)
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
        # The capture's manifest, not the file's mtime (FU-41): an ad-hoc
        # capture is written hours after the data was fetched, and copying an
        # archive rewrites every mtime in it without moving the fetch.
        projection_snapshot = BootstrapSnapshot.from_payload(
            payload, fetched_at=archived_capture_time(archive_path)
        )
    else:
        projection_snapshot = current_snapshot
        print(
            f"[yellow]No archived snapshot predates GW{event}'s deadline — using the current "
            "snapshot. This result is optimistic, not a backtest.[/yellow]"
        )

    _report_live_provenance(live_result)

    fixtures = fixtures_result.fixtures
    actuals = actuals_from_live_event(live_result.live)
    player_ids = [player.id for player in projection_snapshot.elements]

    requested = list(model) if model else list(_DEFAULT_EVALUATE_MODELS)
    duplicates = [name for index, name in enumerate(requested) if name in requested[:index]]
    if duplicates:
        raise typer.BadParameter(f"--model {duplicates[0]!r} given more than once.")
    # Resolved before any projecting, so an unknown name fails immediately
    # rather than after the run has already scored the models before it.
    chosen = [resolve_variant(name) for name in requested]

    # The flat baseline is always scored. It is not one of projections.py's
    # models but the evaluation-only floor of projections.md's decision rule —
    # if the component model cannot beat it, fix minutes before adding
    # complexity — so it belongs in every comparison rather than being selected.
    evaluations = [
        evaluate_model(
            flat_points_per_game_projections(projection_snapshot, event), actuals, model_name="baseline/flat-ppg"
        )
    ]

    for variant in chosen:
        built = variants.build(
            variant,
            projection_snapshot,
            fixtures,
            fixtures_stale=fixtures_result.stale,
            fixtures_fetched_at=fixtures_result.fetched_at,
        )
        _report_strength_fit(built)
        try:
            projections = _project_single_event(built, player_ids, event)
        except ValueError as exc:
            # official-ep refuses any event but the snapshot's own next one. A
            # model that cannot score this gameweek is skipped with a reason
            # rather than failing the run, so the remaining columns still print.
            print(f"[yellow]{built.name}: not evaluable for GW{event} ({exc})[/yellow]")
            continue
        evaluations.append(evaluate_model(projections, actuals, model_name=built.name))

    console.print(evaluation_table(evaluations))
    console.print(evaluation_category_table(evaluations))
    console.print(evaluation_component_table(evaluations))


if __name__ == "__main__":
    app()

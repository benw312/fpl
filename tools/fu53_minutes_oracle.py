"""FU-53 — bound the prize from fixing the minutes model. **AN ORACLE.**

    ############################################################
    #  THIS SCRIPT READS THE ANSWER BEFORE IT PREDICTS IT.      #
    #  It cannot run outside a settled gameweek, and it must    #
    #  never be reachable from `fpl` or from `src/fpl_cli/`.    #
    ############################################################

What it does
------------
Substitutes each player's *realised* appearance for the modelled one and
re-scores through the ordinary evaluation harness. The gap between the shipped
row and the oracle row is the entire prize available from minutes-model.md's
S1-S6, FU-51, and any successor — the ceiling, not a forecast.

Why it is here and not in `src/fpl_cli/`
----------------------------------------
`pyproject.toml` packages `src/fpl_cli` only, so this file is not installed and
nothing in the package can import it. That is the point: the containment of an
outcome-leaking projection is enforced by the build, not by a comment. It also
means this module may reach into `projections.py`'s private names — which it
does, deliberately. Reusing `ComponentProjection._project_one` and
`shrunk_rates` is what makes the claim "only the minutes term was replaced"
true by construction rather than by inspection; a reimplementation of the eight
components here would be a second expression of the model and would measure
something else the moment either drifted.

The oracle variants
-------------------
`_MinutesProbabilities` carries four numbers and the substitution is not one
operation, so three are computed (FU-53's own gap asks for more than one):

    p_only    p_start/p60/p1 <- realised, xmins left as modelled
    xmins_only    xmins <- realised minutes, probabilities left as modelled
    full      all four <- realised            [the headline; see the report]

Scope
-----
Definable only for models with a separable minutes term: the three `component`
variants (via `_MinutesProbabilities`) and `naive/1.0` (via `_availability`).
`official-ep/1.0` is the API's own scalar and `baseline/flat-ppg` models no
appearance at all; for those two there is nothing to substitute and the run
says so rather than inventing a substitution.

Usage
-----
    python tools/fu53_minutes_oracle.py            # pinned defaults, GW2
    python tools/fu53_minutes_oracle.py --json out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fpl_cli.api.models import BootstrapSnapshot, Fixture, LiveEvent
from fpl_cli.domain import variants
from fpl_cli.domain.evaluation import (
    CATEGORIES,
    COMPONENTS,
    ModelEvaluation,
    PlayerActual,
    actuals_from_live_event,
    evaluate_model,
    flat_points_per_game_projections,
)
from fpl_cli.domain.projections import (
    ComponentProjection,
    NaiveProjection,
    Projection,
    _availability,
    _minutes_probabilities,
    _MinutesProbabilities,
    shrunk_rates,
)

# The pinned inputs of minutes-model.md and FU-40. Overridable, but the
# defaults are the three files every figure in that document was measured on.
PINNED = Path.home() / "fpl-pinned"
DEFAULT_BOOTSTRAP = PINNED / "gw2-pre-deadline.json"
DEFAULT_FIXTURES = PINNED / "gw2-fixtures.json"
DEFAULT_LIVE = PINNED / "gw2-live.json"
DEFAULT_EVENT = 2

# `fetched_at` reaches no projected number — it drives staleness display only —
# but the pinned copies' mtimes were rewritten by copying (minutes-model.md
# §2.6's third caveat), so the documented capture time is passed explicitly
# rather than read from the filesystem.
BOOTSTRAP_CAPTURED_AT = datetime(2026, 8, 28, 0, 32, 59, tzinfo=UTC)

# The six scored in the GW2 evaluation: the five registered variants that are
# candidate models, plus the evaluation-only floor. `component/1.0-fixture-
# minsub205` is registered but is a test fixture and variants.py forbids
# quoting it as a model, so it is not here.
MODELS: tuple[str, ...] = (
    "baseline/flat-ppg",
    "naive/1.0",
    "official-ep/1.0",
    "component/1.0",
    "component/1.1-price",
    "component/1.1-position",
)

ORACLE_MODES: tuple[str, ...] = ("p_only", "xmins_only", "full")


# --- The substitution --------------------------------------------------------


class Realised:
    """One player's settled GW outcome, in the shape the minutes model speaks.

    `played` is taken from the live payload's own flag rather than derived from
    `minutes > 0`, so the oracle's appearance term and the harness's
    `spearman_played` population are decided by the same field. (On the pinned
    capture the two agree for all 626 elements; taking the flag means they
    agree by construction on any future one.)
    """

    __slots__ = ("started", "played", "minutes")

    def __init__(self, stats: dict[str, Any]) -> None:
        self.started = bool(stats.get("starts", 0))
        self.played = bool(stats.get("played", False))
        self.minutes = float(stats.get("minutes", 0))

    @property
    def probabilities(self) -> tuple[float, float, float]:
        """(p_start, p60, p1) as certainties."""
        return (
            1.0 if self.started else 0.0,
            1.0 if self.minutes >= 60 else 0.0,
            1.0 if self.played else 0.0,
        )


def realised_from_live(live: LiveEvent) -> dict[int, Realised]:
    return {element.id: Realised(element.stats) for element in live.elements}


def substitute(modelled: _MinutesProbabilities, realised: Realised, mode: str) -> _MinutesProbabilities:
    """Replace the minutes term and nothing else.

    Every scoring rate is untouched: this function returns a
    `_MinutesProbabilities` and the caller feeds it to the model's own
    `_project_one`, so xG, xA, dc, saves, cards and bonus arrive exactly as the
    model produced them. `frac = xmins / 90` still scales the rate-driven
    components, which is the minutes term doing its job, not a rate changing.
    """
    p_start, p60, p1 = realised.probabilities
    if mode == "p_only":
        return _MinutesProbabilities(p_start=p_start, p60=p60, p1=p1, xmins=modelled.xmins)
    if mode == "xmins_only":
        return replace(modelled, xmins=realised.minutes)
    if mode == "full":
        return _MinutesProbabilities(p_start=p_start, p60=p60, p1=p1, xmins=realised.minutes)
    raise ValueError(f"Unknown oracle mode {mode!r}; expected one of {ORACLE_MODES}.")


# --- Projecting, shipped and oracled -----------------------------------------


def _single_event(
    projections: dict[tuple[int, int], Projection], event: int
) -> dict[int, Projection]:
    return {player: projection for (player, ev), projection in projections.items() if ev == event}


def component_oracle_projections(
    model: ComponentProjection,
    player_ids: list[int],
    event: int,
    realised: dict[int, Realised],
    mode: str,
) -> dict[int, Projection]:
    """`model`'s own scoring path, with a substituted minutes term.

    Reaches into `_players`, `_positions`, `_appearances`, `_minutes_config`,
    `_rate_priors`, `_rate_config` and `_project_one`. That coupling is
    intentional and is argued in the module docstring.

    A player absent from the live payload has no realised outcome, so there is
    nothing to substitute and the modelled term stands. Those players are
    outside `evaluate_model`'s intersection anyway; the count is reported.
    """
    result: dict[int, Projection] = {}
    for player_id in player_ids:
        player = model._players[player_id]
        position = model._positions[player.element_type].singular_name_short
        modelled = _minutes_probabilities(player, position, model._appearances, model._minutes_config)
        rates = shrunk_rates(player, position, model._rate_priors, model._rate_config)
        outcome = realised.get(player_id)
        minutes = modelled if outcome is None else substitute(modelled, outcome, mode)
        result[player_id] = model._project_one(player, position, minutes, rates, event)
    return result


def naive_oracle_projections(
    model: NaiveProjection,
    snapshot: BootstrapSnapshot,
    player_ids: list[int],
    event: int,
    realised: dict[int, Realised],
    mode: str,
) -> dict[int, Projection]:
    """`naive/1.0` with realised appearance in place of `_availability`.

    `NaiveProjection` has no `_project_one` seam, so its two-line expression —
    `points_per_game * availability * fixture_count` — is reproduced here
    rather than reused. `verify_naive_reproduction` asserts the reproduction is
    exact when no substitution is made, which is what stops this drifting.

    **`xmins_only` is a no-op for this model and is reported as one.** Naive
    stamps `xmins = 90 * fixtures` on the projection and never reads it: it has
    a `p_start`-shaped term and no minutes-shaped one at all.
    """
    result: dict[int, Projection] = {}
    for player_id in player_ids:
        player = model._players[player_id]
        fixture_count = len(model._schedule.get(event, {}).get(player.team, []))
        availability = _availability(player, model._minutes_config)
        outcome = realised.get(player_id)
        if outcome is not None and mode in ("p_only", "full"):
            availability = 1.0 if outcome.played else 0.0
        points_per_game = float(player.points_per_game or "0.0")
        xp_total = points_per_game * availability * fixture_count
        result[player_id] = Projection(
            player=player.id,
            event=event,
            xp_total=xp_total,
            xp_appearance=xp_total,
            xp_attack=0.0,
            xp_clean_sheet=0.0,
            xp_conceded=0.0,
            xp_saves=0.0,
            xp_defcon=0.0,
            xp_bonus=0.0,
            xp_cards=0.0,
            p_start=availability,
            xmins=90.0 * fixture_count,
            fixtures=fixture_count,
            model_version=model.name,
            assumptions=("undecomposed: entire xp_total placed in xp_appearance",),
        )
    return result


def verify_naive_reproduction(
    shipped: dict[int, Projection], reproduced: dict[int, Projection]
) -> None:
    """The reproduction above must be the shipped model when nothing is substituted."""
    assert set(shipped) == set(reproduced), "naive reproduction covers a different population"
    for player_id, projection in shipped.items():
        other = reproduced[player_id]
        assert projection.xp_total == other.xp_total, (
            f"naive reproduction drifted for player {player_id}: "
            f"{projection.xp_total!r} vs {other.xp_total!r}"
        )
        assert projection.p_start == other.p_start, f"naive p_start drifted for player {player_id}"


# --- Guards ------------------------------------------------------------------


def require_settled(payload: dict[str, Any], event: int) -> str:
    """Refuse to run against an unsettled gameweek.

    FU-43's finality argument, with more force than usual: an oracle built from
    provisional stats is not an upper bound on anything, because the outcomes it
    substitutes are still moving. Bonus points and stat corrections land after
    the final whistle.
    """
    if payload.get("event") != event:
        raise SystemExit(f"Live payload is for event {payload.get('event')!r}, not GW{event}.")
    finished = payload.get("finished")
    data_checked = payload.get("data_checked")
    if not (finished and data_checked):
        raise SystemExit(
            f"GW{event} is not settled (finished={finished}, data_checked={data_checked}). "
            "This oracle substitutes realised outcomes and cannot run before they are final."
        )
    return f"final (finished, data checked), fetched {payload.get('fetched_at')}"


def require_clean_gameweek(fixtures: list[Fixture], event: int, teams: list[int]) -> int:
    """No blanks, no doubles — FU-50 §2's meaning of 'clean'.

    Also the condition under which a per-event realised outcome equals a
    per-fixture one: `_MinutesProbabilities` is per fixture, and the live
    payload reports minutes per event. With one fixture per team the two are the
    same number. With a double they are not, and this run would be substituting
    a whole gameweek's minutes into each of two legs.
    """
    counts = {team: 0 for team in teams}
    for fixture in fixtures:
        if fixture.event != event:
            continue
        counts[fixture.team_h] = counts.get(fixture.team_h, 0) + 1
        counts[fixture.team_a] = counts.get(fixture.team_a, 0) + 1
    distinct = sorted(set(counts.values()))
    if distinct != [1]:
        raise SystemExit(
            f"GW{event} is not clean: fixture counts per team are {distinct}. "
            "The oracle substitutes an event's realised minutes into a per-fixture "
            "term, which is only the same number when every team plays once."
        )
    return sum(1 for fixture in fixtures if fixture.event == event)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Reporting ---------------------------------------------------------------


def _row(evaluation: ModelEvaluation) -> dict[str, Any]:
    return {
        "model": evaluation.model_name,
        "n": evaluation.n_players,
        "n_played": evaluation.n_played,
        "spearman_all": evaluation.spearman_all,
        "spearman_played": evaluation.spearman_played,
        "rmse_all": evaluation.rmse_all,
        "mae_all": evaluation.mae_all,
        "rmse_played": evaluation.rmse_played,
        "mae_played": evaluation.mae_played,
        "categories": {
            name: {"n": stats.count, "mean_error": stats.mean_error, "mae": stats.mae}
            for name, stats in evaluation.categories.items()
        },
        "component_errors": dict(evaluation.component_errors),
    }


def _fmt(value: float, width: int = 7, places: int = 3) -> str:
    return f"{value:>{width}.{places}f}"


def print_metric_table(rows: list[dict[str, Any]], title: str) -> None:
    print(f"\n{title}")
    header = f"{'model':<34} {'sp_all':>7} {'sp_play':>7} {'rmse_all':>8} {'mae_all':>7} {'rmse_pl':>7} {'mae_pl':>7}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['model']:<34} {_fmt(row['spearman_all'])} {_fmt(row['spearman_played'])} "
            f"{_fmt(row['rmse_all'], 8)} {_fmt(row['mae_all'])} "
            f"{_fmt(row['rmse_played'])} {_fmt(row['mae_played'])}"
        )


def print_category_table(rows: list[dict[str, Any]], title: str) -> None:
    print(f"\n{title}  (signed mean error, predicted - actual)")
    header = f"{'model':<34} " + " ".join(f"{name:>9}" for name in CATEGORIES)
    print(header)
    print("-" * len(header))
    counts = rows[0]["categories"]
    print(f"{'(n)':<34} " + " ".join(f"{counts[name]['n']:>9}" for name in CATEGORIES))
    for row in rows:
        print(
            f"{row['model']:<34} "
            + " ".join(_fmt(row["categories"][name]["mean_error"], 9) for name in CATEGORIES)
        )


def print_component_table(rows: list[dict[str, Any]], title: str) -> None:
    print(f"\n{title}  (signed mean error over played, predicted - actual)")
    header = f"{'model':<34} " + " ".join(f"{name.removeprefix('xp_'):>11}" for name in COMPONENTS)
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['model']:<34} "
            + " ".join(_fmt(row["component_errors"][name], 11) for name in COMPONENTS)
        )


# --- The run -----------------------------------------------------------------


def run(args: argparse.Namespace) -> dict[str, Any]:
    bootstrap_path = Path(args.bootstrap)
    fixtures_path = Path(args.fixtures)
    live_path = Path(args.live)
    event = args.event

    live_payload = json.loads(live_path.read_text(encoding="utf-8"))
    finality = require_settled(live_payload, event)

    bootstrap_payload = json.loads(bootstrap_path.read_text(encoding="utf-8"))
    snapshot = BootstrapSnapshot.from_payload(bootstrap_payload, fetched_at=BOOTSTRAP_CAPTURED_AT)
    fixtures = [Fixture(**row) for row in json.loads(fixtures_path.read_text(encoding="utf-8"))]
    live = LiveEvent(**live_payload["live"])

    n_fixtures = require_clean_gameweek(fixtures, event, [club.id for club in snapshot.teams])

    actuals: dict[int, PlayerActual] = actuals_from_live_event(live)
    realised = realised_from_live(live)
    player_ids = [player.id for player in snapshot.elements]
    missing = [pid for pid in player_ids if pid not in realised]

    provenance = {
        "event": event,
        "bootstrap": {"path": str(bootstrap_path), "sha256": sha256(bootstrap_path)},
        "fixtures": {"path": str(fixtures_path), "sha256": sha256(fixtures_path)},
        "live": {"path": str(live_path), "sha256": sha256(live_path), "finality": finality},
        "n_fixtures": n_fixtures,
        "n_bootstrap_elements": len(player_ids),
        "n_live_elements": len(realised),
        "n_projected_without_outcome": len(missing),
        "digests": {},
    }

    shipped: list[dict[str, Any]] = []
    oracled: dict[str, list[dict[str, Any]]] = {mode: [] for mode in ORACLE_MODES}
    notes: list[str] = []

    for name in MODELS:
        if name == "baseline/flat-ppg":
            projections = flat_points_per_game_projections(snapshot, event)
            shipped.append(_row(evaluate_model(projections, actuals, model_name=name)))
            notes.append(
                "baseline/flat-ppg: no oracle. It models no appearance term at all "
                "(p_start pinned to 1.0, xmins to 90.0, neither consumed), so there "
                "is nothing to substitute."
            )
            continue

        variant = variants.get(name)
        provenance["digests"][variant.version] = variant.digest
        model = variants.build(variant, snapshot, fixtures)
        try:
            projections = _single_event(model.project(player_ids, [event]), event)
        except ValueError as exc:
            notes.append(f"{variant.version}: not evaluable for GW{event} ({exc})")
            continue
        shipped.append(_row(evaluate_model(projections, actuals, model_name=variant.version)))

        if isinstance(model, ComponentProjection):
            for mode in ORACLE_MODES:
                oracle = component_oracle_projections(model, player_ids, event, realised, mode)
                oracled[mode].append(
                    _row(evaluate_model(oracle, actuals, model_name=variant.version))
                )
        elif isinstance(model, NaiveProjection):
            verify_naive_reproduction(
                projections,
                naive_oracle_projections(model, snapshot, player_ids, event, {}, "full"),
            )
            for mode in ORACLE_MODES:
                oracle = naive_oracle_projections(model, snapshot, player_ids, event, realised, mode)
                oracled[mode].append(
                    _row(evaluate_model(oracle, actuals, model_name=variant.version))
                )
            notes.append(
                "naive/1.0: 'xmins_only' is a no-op — the model stamps xmins and "
                "never reads it. Its p_only and full rows are identical, and both "
                "substitute realised appearance for `_availability`."
            )
        else:
            notes.append(
                f"{variant.version}: no oracle. `ep_next` is the API's own scalar "
                "with no separable minutes term; substituting anything into it "
                "would be replacing the model, not its minutes."
            )

    return {
        "provenance": provenance,
        "shipped": shipped,
        "oracle": oracled,
        "notes": notes,
    }


def report(result: dict[str, Any]) -> None:
    provenance = result["provenance"]
    print("FU-53 — the minutes oracle. AN UPPER BOUND, NOT A FORECAST.")
    print(f"GW{provenance['event']}, {provenance['n_fixtures']} fixtures, every team once.")
    for key in ("bootstrap", "fixtures", "live"):
        entry = provenance[key]
        print(f"  {key:<10} {entry['path']}  sha256 {entry['sha256'][:12]}…")
    print(f"  actuals    {provenance['live']['finality']}")
    print(
        f"  population {provenance['n_bootstrap_elements']} projected, "
        f"{provenance['n_live_elements']} live, "
        f"{provenance['n_projected_without_outcome']} projected without an outcome"
    )
    print("  digests    " + ", ".join(f"{k} {v}" for k, v in provenance["digests"].items()))

    print_metric_table(result["shipped"], "AS SHIPPED")
    for mode in ORACLE_MODES:
        rows = result["oracle"][mode]
        if rows:
            print_metric_table(rows, f"ORACLE [{mode}]")

    print_category_table(result["shipped"], "\nCATEGORY ERROR — as shipped")
    for mode in ORACLE_MODES:
        rows = result["oracle"][mode]
        if rows:
            print_category_table(rows, f"CATEGORY ERROR — oracle [{mode}]")

    print_component_table(result["shipped"], "\nCOMPONENT ERROR — as shipped")
    print_component_table(result["oracle"]["full"], "COMPONENT ERROR — oracle [full]")

    print("\nNOTES")
    for note in result["notes"]:
        print(f"  * {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bootstrap", default=str(DEFAULT_BOOTSTRAP))
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    parser.add_argument("--live", default=str(DEFAULT_LIVE))
    parser.add_argument("--event", type=int, default=DEFAULT_EVENT)
    parser.add_argument("--json", dest="json_out", default=None)
    args = parser.parse_args(argv)

    result = run(args)
    report(result)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

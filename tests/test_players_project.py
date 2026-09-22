"""`fpl players project` (docs/plans/players-project.md).

Every assertion here was demonstrated failing against a mutation of the line it
covers before being kept — the mutation is named in each test's docstring.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import typer

from fpl_cli import cli
from fpl_cli.api.models import BootstrapSnapshot, Club, Fixture
from fpl_cli.api.snapshots import FixturesResult, SnapshotResult


class StubService:
    def __init__(self, snapshot: BootstrapSnapshot, fixtures: list[Fixture] | None = None) -> None:
        self._snapshot = snapshot
        self._fixtures = fixtures or []
        self.closed = False

    def load(self) -> SnapshotResult:
        return SnapshotResult(snapshot=self._snapshot, stale=False)

    def load_fixtures(self) -> FixturesResult:
        return FixturesResult(fixtures=self._fixtures, fetched_at=datetime.now(UTC), stale=False)

    def close(self) -> None:
        self.closed = True


def _open_at(snapshot: BootstrapSnapshot, event: int) -> None:
    """Make `event` the only gameweek with an unexpired deadline.

    The conftest snapshot's deadlines are all in 2025, so pushing one into the
    future makes `_next_open_event` deterministic without freezing the clock.
    """
    for gameweek in snapshot.events:
        if gameweek.id == event:
            gameweek.deadline_time = datetime(2099, 1, 1, tzinfo=UTC)


def _name_clubs(snapshot: BootstrapSnapshot) -> None:
    """Give clubs a short_name distinct from their name, and add a sixth club.

    conftest leaves `short_name` at its "" default; real payloads always set
    it, and the distinctness is what lets a test tell which field is rendered.

    The sixth club exists so `_one_fixture_each` can pair every club off
    exactly once. conftest ships five, and an odd count forces any full round
    to either blank or double somebody — which silently contaminated the
    ranking test before this was added. No player is on club 6 (conftest
    assigns `team = id % 5 + 1`), so it contributes no rows; it is there to be
    a legal opponent for `BandedTeamRates`, which looks the opponent up by id.
    """
    snapshot.teams.append(Club(id=6, name="Club 6"))
    for club in snapshot.teams:
        club.short_name = f"C{club.id}"
    snapshot.__dict__.pop("clubs", None)


def _rig_rates(snapshot: BootstrapSnapshot, rates: dict[int, str]) -> None:
    for player_id, rate in rates.items():
        snapshot.players_by_id[player_id].points_per_game = rate


def _one_fixture_each(event: int) -> list[Fixture]:
    """Every club plays exactly once in `event` — no blank, no double.

    Requires `_name_clubs` to have added club 6. Three disjoint pairings, so
    any fixture count other than 1 in a test using this is the code's doing
    and not the fixture's.
    """
    return [
        Fixture(id=event * 10 + 1, event=event, team_h=1, team_a=2),
        Fixture(id=event * 10 + 2, event=event, team_h=3, team_a=4),
        Fixture(id=event * 10 + 3, event=event, team_h=5, team_a=6),
    ]


def _project(snapshot: BootstrapSnapshot, fixtures: list[Fixture], monkeypatch, **kwargs) -> None:
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(snapshot, fixtures))
    defaults = dict(
        position=None,
        top=30,
        horizon=1,
        model="naive",
        include_unavailable=False,
    )
    defaults.update(kwargs)
    cli.project_players(**defaults)


def test_rows_are_ranked_by_next_gameweek_xp_descending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """Ordering, and the sort key specifically.

    Under `naive`, xp_total = points_per_game * availability * fixtures, so
    rigging points_per_game fixes the whole ranking by hand. Players 3, 4 and 5
    are all DEF in different clubs, all playing once in GW2, so only the rate
    separates them: 9.0 > 5.0 > 1.0.

    Mutation: reversing the sort to `key=lambda row: row.next_gw` puts P3 last
    and fails; dropping the `-` likewise. Sorting on `mean_xp` instead passes
    here by construction (horizon 1), which is why the blank/double test below
    carries the per-column arithmetic.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "9.0", 4: "5.0", 5: "1.0"})
    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF"])
    out = capsys.readouterr().out

    rows = [line for line in out.splitlines() if "· DEF" in line]
    assert [row.split("·")[0].strip().lstrip("│ ") for row in rows[:3]] == ["P3", "P4", "P5"]
    assert "9.0" in rows[0] and "5.0" in rows[1] and "1.0" in rows[2]


def test_the_player_cell_concatenates_name_club_short_name_and_position(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """Column 1's content and separator.

    Player 3 is a DEF in team 4 (conftest: team = id % 5 + 1), so the cell must
    read "P3 · C4 · DEF" — the club's `short_name`, never its `name`.

    Mutation: rendering `club.name` gives "Club 4" and fails; joining on " "
    or "/" fails on the separator.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "9.0"})
    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF"])
    out = capsys.readouterr().out

    assert "P3 · C4 · DEF" in out
    assert "Club 4" not in out


def test_position_filter_accepts_two_positions_combined(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`--position` is repeatable and unions rather than overwrites.

    conftest ids: 1-2 GKP, 3-7 DEF, 8-12 MID, 13-15 FWD. Asking for DEF and FWD
    must return both and exclude GKP and MID.

    Mutation: `wanted_type_ids` built from `requested[-1]` alone (the
    last-flag-wins bug this test exists for) drops every DEF and fails.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF", "FWD"])
    out = capsys.readouterr().out

    assert "· DEF" in out
    assert "· FWD" in out
    assert "· MID" not in out
    assert "· GKP" not in out


def test_an_unknown_position_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """FU-17's defect must not be reproduced: an unknown value errors, naming
    itself and the valid set, rather than silently yielding an empty table.

    Mutation: filtering with `positions_by_code.get(value)` and skipping
    `None` renders an empty table and raises nothing, failing this.
    """
    _open_at(bootstrap_snapshot, 2)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot, _one_fixture_each(2)))

    with pytest.raises(typer.BadParameter) as excinfo:
        cli.project_players(position=["STRIKER"], top=30, horizon=1, model="naive", include_unavailable=False)

    assert "STRIKER" in str(excinfo.value)
    assert "DEF" in str(excinfo.value)


def test_fixture_count_and_mean_span_a_blank_and_a_double(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """The count is the horizon total, and the mean is per gameweek.

    No blank or double exists in the real fixture list this early in the season
    (players-project.md §4), so both are constructed. Player 3 is in team 4:
    GW2 it plays twice, GW3 not at all, GW4 once — three fixtures over a
    horizon of three. At points_per_game 2.0 the per-gameweek totals are
    4.0 / 0.0 / 2.0, so the mean is exactly 2.0 and the cell reads "2.0 (3)",
    while the next-gameweek column reads the double's 4.0.

    Mutations, each demonstrated failing: reporting `len(events)` instead of
    summing `fixtures` gives "(3)" here too and is caught by the second
    assertion below, where team 1's blank leaves it on two; averaging over
    `fixtures` rather than over events gives 2.0 -> 3.0; summing instead of
    averaging gives 6.0; taking the last event instead of the first for the
    next-gameweek column gives 2.0.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "2.0", 6: "2.0"})
    fixtures = [
        # GW2: team 4 twice (a double), team 1 once.
        Fixture(id=1, event=2, team_h=4, team_a=2),
        Fixture(id=2, event=2, team_h=4, team_a=5),
        Fixture(id=3, event=2, team_h=1, team_a=3),
        # GW3: team 4 blanks; team 1 plays.
        Fixture(id=4, event=3, team_h=1, team_a=2),
        # GW4: both play.
        Fixture(id=5, event=4, team_h=4, team_a=1),
    ]
    _project(bootstrap_snapshot, fixtures, monkeypatch, position=["DEF"], horizon=3)
    out = capsys.readouterr().out

    row_3 = next(line for line in out.splitlines() if "P3 ·" in line)
    assert "4.0" in row_3  # next gameweek: the double, 2.0 * 2 fixtures
    assert "2.0 (3)" in row_3  # mean over three gameweeks; three fixtures total

    # Player 6 is a DEF in team 2, which plays in GW2 and GW3 but blanks in
    # GW4 — a different shape from player 3's, so a count that echoed the
    # horizon would have to be wrong for one of them. It is also the row where
    # fixture total (2) and event count (3) differ, which is the only place a
    # mean taken over the wrong denominator shows up: 4.0 over three gameweeks
    # is 1.3, over two fixtures it would be 2.0. Player 3's row cannot catch
    # that — three fixtures in three gameweeks divides the same either way.
    row_6 = next(line for line in out.splitlines() if "P6 ·" in line)
    assert "1.3 (2)" in row_6


def test_start_percent_renders_under_component_and_is_withheld_under_official_ep(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """Start% is a percentage where it is modelled and an em dash where it is not.

    `ComponentProjection` at GW1-finished gives every DEF the positional prior
    0.65 shrunk against one appearance — a real, non-zero rate. `official-ep`
    hardcodes `p_start = 0.0` and says so in its own assumptions, so rendering
    "0%" would publish a number no model produced.

    Mutations: dropping the `model == "official-ep"` guard prints "0%" and
    fails the second half; formatting `p_start` without the *100 prints "1%"
    and fails the first.
    """
    _open_at(bootstrap_snapshot, 3)  # GW3 is the conftest snapshot's is_next
    _name_clubs(bootstrap_snapshot)
    # P3 has started its one appearance; the other four DEF have not. Without a
    # start history this assertion cannot do its job: `component` has pointed at
    # `component/1.2` since 2026-09-19 (FU-60), whose prior is *pooled from the
    # snapshot* rather than a hardcoded per-position constant, so on a fixture
    # where nobody has ever started the pooled rate is 0 and every player renders
    # "0%" — which a missing *100 also renders, leaving the mutation below
    # undetectable.
    next(player for player in bootstrap_snapshot.elements if player.id == 3).starts = 1
    _project(
        bootstrap_snapshot,
        _one_fixture_each(3),
        monkeypatch,
        position=["DEF"],
        model="component",
    )
    component_out = capsys.readouterr().out
    component_row = next(line for line in component_out.splitlines() if "P3 ·" in line)
    # The exact value, not merely "a percent sign". One finished gameweek, so
    # a = 1 and s = 1; the pooled DEF start rate is 1 of 5 DEF = 0.2, and the
    # ownership band level equals the position level because every synthetic
    # player sits in the same `<1%` band, making the band shrinkage a no-op.
    # So (1 + 4*0.2) / (1 + 4) = 0.36, against availability 1.0. Verified against
    # the model, not only derived.
    #
    # Asserting "%" alone lets a missing *100 through — 0.36 formatted to no
    # decimals is "0%", which still contains a "%".
    #
    # This read 52% until 2026-09-19, from `component/1.1-price`'s hardcoded DEF
    # prior of 0.65: (1 + 4*0.65) / (1 + 4) = 0.72 on this same fixture, and
    # (0 + 4*0.65) / (1 + 4) = 0.52 before P3 was given its start. The change is
    # the default moving, not the renderer.
    assert "36%" in component_row
    assert "Start% = modelled probability of starting" in component_out
    # Checked on the row, not the whole output: the UNVALIDATED caption
    # contains an em dash of its own.
    assert "—" not in component_row

    _project(
        bootstrap_snapshot,
        _one_fixture_each(3),
        monkeypatch,
        position=["DEF"],
        model="official-ep",
    )
    official_out = capsys.readouterr().out
    official_row = next(line for line in official_out.splitlines() if "P3 ·" in line)
    assert "—" in official_row
    assert "%" not in official_row
    assert "Start% is not modelled by official-ep" in official_out


def test_unavailable_players_are_hidden_by_default_and_counted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """The default excludes what cannot be bought, says how many, and the flag
    brings them back.

    Player 4 is made unselectable and given a rate that would otherwise put it
    top, so its absence is visible in the ranking rather than only in a count.

    Mutations: dropping `not player.removed` from the predicate lets P5 through
    and fails; hardcoding `suppressed = 0` fails the count assertion; ignoring
    `include_unavailable` fails the second half.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "1.0", 4: "9.0", 5: "9.0"})
    bootstrap_snapshot.players_by_id[4].can_select = False
    bootstrap_snapshot.players_by_id[5].removed = True

    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF"])
    hidden = capsys.readouterr().out
    assert "P4 ·" not in hidden
    assert "P5 ·" not in hidden
    assert "2 unavailable players hidden" in hidden

    _project(
        bootstrap_snapshot,
        _one_fixture_each(2),
        monkeypatch,
        position=["DEF"],
        include_unavailable=True,
    )
    shown = capsys.readouterr().out
    assert "P4 ·" in shown
    assert "P5 ·" in shown
    assert "unavailable players hidden" not in shown


def test_a_doubtful_player_is_not_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`status == "d"` stays in, deliberately.

    `players list --available-only` uses a stricter `status == "a"` predicate
    (cli.py, FU-35 §10); adopting it here would hide precisely the rows this
    command is for. This test is what stops the two predicates being
    "reconciled" later without the argument being had.

    Mutation: adding `and player.status == "a"` to the filter drops P3 and
    fails.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "9.0"})
    bootstrap_snapshot.players_by_id[3].status = "d"

    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF"])
    out = capsys.readouterr().out

    assert "P3 ·" in out
    assert "unavailable players hidden" not in out


def test_official_ep_is_refused_beyond_a_single_gameweek(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`OfficialEpProjection.project` raises for any event but the snapshot's
    next one, so the CLI refuses up front and names both numbers rather than
    surfacing a ValueError from three frames down.

    Mutation: removing the guard raises ValueError out of `project` instead of
    exiting 1, and the test fails on the exception type.
    """
    _open_at(bootstrap_snapshot, 3)
    monkeypatch.setattr(cli, "SnapshotService", lambda: StubService(bootstrap_snapshot, _one_fixture_each(3)))

    with pytest.raises(typer.Exit) as excinfo:
        cli.project_players(
            position=None, top=30, horizon=5, model="official-ep", include_unavailable=False
        )

    assert excinfo.value.exit_code == 1
    assert "official-ep" in capsys.readouterr().err


def test_top_limits_the_rows_rendered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`--top` truncates after sorting, not before.

    Mutation: slicing before the sort (`rows[:top]` then `.sort()`) leaves P7
    — the lowest-rated DEF, and last in id order — in the table and fails.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _rig_rates(bootstrap_snapshot, {3: "1.0", 4: "2.0", 5: "3.0", 6: "4.0", 7: "0.5"})
    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, position=["DEF"], top=2)
    out = capsys.readouterr().out

    assert "P6 ·" in out and "P5 ·" in out
    assert "P7 ·" not in out
    assert "P3 ·" not in out


# --- FU-71: any registered variant ---------------------------------------------


def test_a_superseded_variant_can_be_projected_by_its_full_name(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bootstrap_snapshot: BootstrapSnapshot,
) -> None:
    """`component/1.1-price` — the model every pre-GW4 figure is quoted in —
    must be reachable, and must carry the component start note.

    Mutation: restoring the `_MODEL_CHOICES` gate, which rejects it.
    """
    _open_at(bootstrap_snapshot, 2)
    _name_clubs(bootstrap_snapshot)
    _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, model="component/1.1-price")
    out = capsys.readouterr().out
    assert "component/1.1-price" in out
    assert "modelled probability of starting" in out


def test_an_unregistered_model_name_is_a_usage_error_naming_what_exists(
    monkeypatch: pytest.MonkeyPatch, bootstrap_snapshot: BootstrapSnapshot
) -> None:
    """Mutation: resolving with `variants.get` directly (a KeyError, not a
    usage error)."""
    with pytest.raises(typer.BadParameter, match="component/1.2"):
        _project(bootstrap_snapshot, _one_fixture_each(2), monkeypatch, model="component/9.9")


def test_every_registered_family_has_a_start_note() -> None:
    """FU-71's gap, closed as a registry-time check: a new family fails here,
    in the suite, instead of rendering the fallback note unnoticed.

    Mutation: deleting the `naive` entry from `_START_NOTES`.
    """
    from fpl_cli.domain import variants  # noqa: PLC0415

    assert {v.family for v in variants.all_variants()} <= set(cli._START_NOTES)


def test_an_unknown_family_gets_a_note_that_claims_nothing() -> None:
    """Mutation: `_START_NOTES[family]`, which KeyErrors at render time."""
    assert "not documented" in cli._start_note("dixon-coles")

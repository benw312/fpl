from __future__ import annotations

import json

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.builder import BuilderCancelled, SquadBuilder
from fpl_cli.domain.rules import validate_squad
from fpl_cli.domain.squad import SquadSlots, eligible_players, to_ledger_payload
from fpl_cli.domain.transfers import Ledger, current_event_id, replay


def _fill_cheapest(snapshot: BootstrapSnapshot, count: int) -> SquadSlots:
    """Greedily fills the first `count` slots with the cheapest eligible pick each time."""
    slots = SquadSlots.empty(snapshot)
    for slot in slots.slots[:count]:
        candidates = eligible_players(slots, slot.index, snapshot)
        chosen = min(candidates, key=lambda player: player.now_cost)
        slots = slots.with_pick(slot.index, chosen.id)
    return slots


# --- eligible_players -------------------------------------------------------


def test_eligible_players_excludes_wrong_position(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    gkp_slot = next(slot for slot in slots.slots if slot.position_id == 1)
    eligible = eligible_players(slots, gkp_slot.index, builder_snapshot)
    assert eligible
    assert all(player.element_type == 1 for player in eligible)


def test_eligible_players_excludes_already_picked(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    def_slot = next(slot for slot in slots.slots if slot.position_id == 2)
    first_pick = eligible_players(slots, def_slot.index, builder_snapshot)[0]
    slots = slots.with_pick(def_slot.index, first_pick.id)

    other_def_slot = next(slot for slot in slots.slots if slot.position_id == 2 and slot.player_id is None)
    eligible_ids = {player.id for player in eligible_players(slots, other_def_slot.index, builder_snapshot)}
    assert first_pick.id not in eligible_ids


def test_eligible_players_excludes_club_at_team_limit(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    def_slots = [slot for slot in slots.slots if slot.position_id == 2]

    club_one_defenders = sorted(
        (player for player in builder_snapshot.elements if player.element_type == 2 and player.team == 1),
        key=lambda player: player.id,
    )
    assert len(club_one_defenders) == 4  # fixture guarantee: one more than squad_team_limit (3)

    for slot, player in zip(def_slots, club_one_defenders[:3]):
        slots = slots.with_pick(slot.index, player.id)

    remaining_slot = next(slot for slot in def_slots if slot.player_id is None)
    eligible = eligible_players(slots, remaining_slot.index, builder_snapshot)
    eligible_ids = {player.id for player in eligible}

    fourth = club_one_defenders[3]
    assert fourth.id not in eligible_ids
    assert all(player.team != 1 for player in eligible)


def test_eligible_players_excludes_unselectable_and_removed(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    mid_slot = next(slot for slot in slots.slots if slot.position_id == 3)
    eligible_ids = {player.id for player in eligible_players(slots, mid_slot.index, builder_snapshot)}

    unselectable = next(player for player in builder_snapshot.elements if not player.can_select)
    removed = next(player for player in builder_snapshot.elements if player.removed)
    assert unselectable.id not in eligible_ids
    assert removed.id not in eligible_ids


def test_eligible_players_budget_reserve_excludes_when_other_slots_need_saving(
    builder_snapshot: BootstrapSnapshot,
) -> None:
    # 2 GKP + 5 DEF + 5 MID filled cheaply; all 3 FWD slots still empty.
    slots = _fill_cheapest(builder_snapshot, 12)
    spent = sum(builder_snapshot.players_by_id[player_id].now_cost for player_id in slots.picked_ids)
    builder_snapshot.game_settings.squad_total_spend = spent + 140
    bank = builder_snapshot.game_settings.squad_total_spend - spent

    target = next(slot for slot in slots.slots if slot.position_id == 4)
    eligible_ids = {player.id for player in eligible_players(slots, target.index, builder_snapshot)}

    picked = slots.picked_ids
    raw_afford_ids = {
        player.id
        for player in builder_snapshot.elements
        if player.element_type == 4
        and player.id not in picked
        and player.can_select
        and not player.removed
        and player.now_cost <= bank
    }

    assert eligible_ids
    assert eligible_ids < raw_afford_ids  # the reserve is strictly tighter than plain affordability


def test_eligible_players_budget_reserve_uses_full_bank_on_the_last_slot(
    builder_snapshot: BootstrapSnapshot,
) -> None:
    slots = _fill_cheapest(builder_snapshot, 14)  # every slot but one FWD is filled
    target = next(slot for slot in slots.slots if slot.player_id is None)
    spent = sum(builder_snapshot.players_by_id[player_id].now_cost for player_id in slots.picked_ids)

    picked = slots.picked_ids
    club_counts: dict[int, int] = {}
    for player_id in picked:
        player = builder_snapshot.players_by_id[player_id]
        club_counts[player.team] = club_counts.get(player.team, 0) + 1
    candidates = [
        player
        for player in builder_snapshot.elements
        if player.element_type == target.position_id
        and player.id not in picked
        and player.can_select
        and not player.removed
        and club_counts.get(player.team, 0) < builder_snapshot.game_settings.squad_team_limit
    ]
    most_expensive = max(candidates, key=lambda player: player.now_cost)

    # Bank set to exactly this candidate's price: with no other empty slot to
    # reserve for, spending the entire remaining bank here must be allowed.
    builder_snapshot.game_settings.squad_total_spend = spent + most_expensive.now_cost

    eligible_ids = {player.id for player in eligible_players(slots, target.index, builder_snapshot)}
    assert most_expensive.id in eligible_ids


def test_to_ledger_payload_round_trips_through_ledger_and_replay(
    tmp_path, builder_snapshot: BootstrapSnapshot
) -> None:
    slots = _fill_cheapest(builder_snapshot, 15)
    assert slots.is_complete

    payload = to_ledger_payload(slots, builder_snapshot)
    assert len(payload["log"]) == 15
    assert payload["genesis_event"] == current_event_id(builder_snapshot)

    path = tmp_path / "squad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    ledger = Ledger.from_file(path, builder_snapshot)
    assert ledger.legacy is False
    assert ledger.genesis_event == payload["genesis_event"]
    assert len(ledger.log) == 15

    state = replay(ledger, builder_snapshot)
    assert len(state.holdings) == 15
    assert all(holding.bought_event == ledger.genesis_event for holding in state.holdings.values())
    spent = sum(builder_snapshot.players_by_id[player_id].now_cost for player_id in slots.player_ids)
    assert state.bank == builder_snapshot.game_settings.squad_total_spend - spent

    result = validate_squad(state.player_ids, builder_snapshot)
    assert result.valid, result.errors


# --- SlotCompleter -----------------------------------------------------------


def test_slot_completer_orders_by_points_and_carries_display_meta(builder_snapshot: BootstrapSnapshot) -> None:
    with create_pipe_input() as pipe_input:
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        def_slot = next(slot for slot in builder.slots.slots if slot.position_id == 2)
        builder.active_slot = def_slot.index

        completions = list(builder.player_completer.get_completions(Document("", 0), CompleteEvent()))

    expected_order = sorted(
        eligible_players(builder.slots, def_slot.index, builder_snapshot),
        key=lambda player: -player.total_points,
    )
    assert [completion.text for completion in completions] == [player.display_name for player in expected_order]
    assert all(completion.display_meta for completion in completions)


def test_slot_completer_filters_by_typed_text_and_eligibility(builder_snapshot: BootstrapSnapshot) -> None:
    with create_pipe_input() as pipe_input:
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        def_slots = [slot for slot in builder.slots.slots if slot.position_id == 2]

        club_one_defenders = sorted(
            (player for player in builder_snapshot.elements if player.element_type == 2 and player.team == 1),
            key=lambda player: player.id,
        )
        for slot, player in zip(def_slots, club_one_defenders[:3]):
            builder.slots = builder.slots.with_pick(slot.index, player.id)

        remaining_slot = next(slot for slot in def_slots if slot.player_id is None)
        builder.active_slot = remaining_slot.index

        completions = list(builder.player_completer.get_completions(Document("", 0), CompleteEvent()))

    completed_ids = {int(completion.text.removeprefix("P")) for completion in completions}
    assert club_one_defenders[3].id not in completed_ids  # excluded: club 1 is at the team limit


# --- SquadBuilder (driven terminal) ------------------------------------------


def test_squad_builder_completes_a_full_squad_and_produces_a_valid_ledger(
    builder_snapshot: BootstrapSnapshot,
) -> None:
    plan = _fill_cheapest(builder_snapshot, 15)

    lines: list[str] = []
    for player_id in plan.player_ids:
        lines.append("")  # <Enter> -> next empty slot
        lines.append(builder_snapshot.players_by_id[player_id].display_name)
    lines.append("")  # <Enter> on a complete squad -> "done"
    input_text = "\n".join(lines) + "\n"

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(input_text)
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        result = builder.run()

    assert result.is_complete
    assert result.player_ids == plan.player_ids
    validation = validate_squad(result.player_ids, builder_snapshot)
    assert validation.valid, validation.errors


def test_squad_builder_reprompts_after_an_unresolvable_name(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    gkp_slot = slots.slots[0]
    real_pick = min(eligible_players(slots, gkp_slot.index, builder_snapshot), key=lambda player: player.now_cost)

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(f"1\nzzz-not-a-real-player\n1\n{real_pick.display_name}\nquit\n")
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        try:
            builder.run()
        except BuilderCancelled:
            pass

    assert builder.slots.slot(1).player_id == real_pick.id


def test_squad_builder_overwrites_a_filled_slot_on_repick(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    gkp_slot = slots.slots[0]
    candidates = eligible_players(slots, gkp_slot.index, builder_snapshot)
    first, second = sorted(candidates, key=lambda player: player.now_cost)[:2]

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(f"1\n{first.display_name}\n1\n{second.display_name}\nquit\n")
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        try:
            builder.run()
        except BuilderCancelled:
            pass

    assert builder.slots.slot(1).player_id == second.id


def test_squad_builder_clears_a_slot_with_d_command(builder_snapshot: BootstrapSnapshot) -> None:
    slots = SquadSlots.empty(builder_snapshot)
    gkp_slot = slots.slots[0]
    pick = min(eligible_players(slots, gkp_slot.index, builder_snapshot), key=lambda player: player.now_cost)

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(f"1\n{pick.display_name}\nd 1\nquit\n")
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        try:
            builder.run()
        except BuilderCancelled:
            pass

    assert builder.slots.slot(1).player_id is None


def test_squad_builder_quit_raises_builder_cancelled(builder_snapshot: BootstrapSnapshot) -> None:
    with create_pipe_input() as pipe_input:
        pipe_input.send_text("quit\n")
        builder = SquadBuilder(builder_snapshot, input=pipe_input, output=DummyOutput())
        try:
            builder.run()
            raise AssertionError("expected BuilderCancelled")
        except BuilderCancelled:
            pass

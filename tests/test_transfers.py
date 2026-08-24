from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl_cli.api.models import BootstrapSnapshot, Gameweek, Player
from fpl_cli.domain.rules import validate_squad, validate_squad_structure
from fpl_cli.domain.transfers import (
    Holding,
    Ledger,
    SquadState,
    Transaction,
    Transfer,
    TransferRules,
    apply_transfers,
    replay,
    selling_price,
    simulate,
)


def _rules(snapshot: BootstrapSnapshot) -> TransferRules:
    return TransferRules.from_snapshot(snapshot)


def _genesis_ledger(player_ids: list[int], prices: dict[int, int], *, event: int = 1) -> Ledger:
    log = [Transaction(event=event, type="buy", player=player_id, price=prices[player_id]) for player_id in player_ids]
    return Ledger(version=1, genesis_event=event, log=log)


def _add_pool_player(
    snapshot: BootstrapSnapshot,
    player_id: int,
    template_id: int,
    *,
    now_cost: int = 50,
    can_transact: bool = True,
) -> None:
    """Append a same-position, same-club replacement candidate not currently held."""
    template = snapshot.players_by_id[template_id]
    snapshot.elements.append(
        Player(
            id=player_id,
            web_name=f"P{player_id}",
            team=template.team,
            element_type=template.element_type,
            now_cost=now_cost,
            can_transact=can_transact,
        )
    )


# --- Selling price ---------------------------------------------------------


def test_selling_price_odd_profit_rounds_kept_half_down() -> None:
    rules = TransferRules(sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=83, rules=rules) == 81


def test_selling_price_even_profit() -> None:
    rules = TransferRules(sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=84, rules=rules) == 82


def test_selling_price_loss_borne_in_full() -> None:
    rules = TransferRules(sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=75, rules=rules) == 75


def test_selling_price_unchanged_sells_at_purchase() -> None:
    rules = TransferRules(sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=80, rules=rules) == 80


def test_selling_price_sell_at_purchase_price_setting() -> None:
    rules = TransferRules(sell_on_fee=0.5, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=True, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=95, rules=rules) == 80


def test_selling_price_derives_from_non_default_fee() -> None:
    rules = TransferRules(sell_on_fee=0.3, max_extra_free_transfers=4, transfers_cap=20, sell_at_purchase_price=False, squad_total_spend=1000)
    assert selling_price(purchase_price=80, now_cost=90, rules=rules) == 87


# --- Replay ------------------------------------------------------------


def test_replay_genesis_bank_equals_budget_minus_prices(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices)

    state = replay(ledger, bootstrap_snapshot)

    assert state.bank == 1000 - 15 * 50
    assert sorted(state.holdings) == player_ids
    assert state.free_transfers == 0


def test_replay_buy_sell_pair_updates_bank_and_holdings(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices)
    ledger.log.append(Transaction(event=2, type="sell", player=1, price=52))
    ledger.log.append(Transaction(event=2, type="buy", player=16, price=55))

    state = replay(ledger, bootstrap_snapshot)

    assert 1 not in state.holdings
    assert 16 in state.holdings
    assert state.bank == (1000 - 15 * 50) + 52 - 55


def test_replay_purchase_price_tracks_most_recent_buy(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices)
    ledger.log.append(Transaction(event=2, type="sell", player=1, price=52))
    ledger.log.append(Transaction(event=2, type="buy", player=16, price=55))
    ledger.log.append(Transaction(event=3, type="sell", player=16, price=58))
    ledger.log.append(Transaction(event=3, type="buy", player=16, price=60))

    state = replay(ledger, bootstrap_snapshot)

    holding = state.holdings[16]
    assert holding.purchase_price == 60
    assert holding.bought_event == 3


def test_replay_as_of_event_truncates(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices)
    ledger.log.append(Transaction(event=2, type="sell", player=1, price=52))
    ledger.log.append(Transaction(event=2, type="buy", player=16, price=55))
    ledger.log.append(Transaction(event=3, type="sell", player=2, price=51))
    ledger.log.append(Transaction(event=3, type="buy", player=17, price=53))

    truncated = replay(ledger, bootstrap_snapshot, as_of_event=2)

    assert 1 not in truncated.holdings
    assert 16 in truncated.holdings
    assert 2 in truncated.holdings
    assert 17 not in truncated.holdings


def test_replay_legacy_players_list_loads_and_flags(tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot) -> None:
    path = tmp_path / "squad.json"
    path.write_text('{"players": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]}', encoding="utf-8")

    ledger = Ledger.from_file(path, bootstrap_snapshot)

    assert ledger.legacy is True
    assert ledger.genesis_event == 2  # bootstrap_snapshot's is_current gameweek
    assert len(ledger.log) == 15
    assert all(transaction.type == "buy" and transaction.price == 50 and transaction.event == 2 for transaction in ledger.log)


def test_replay_current_format_loads(tmp_path: Path, bootstrap_snapshot: BootstrapSnapshot) -> None:
    path = tmp_path / "squad.json"
    path.write_text(
        '{"version": 1, "genesis_event": 1, "log": ['
        '{"event": 1, "type": "buy", "player": 1, "price": 50}'
        '], "chips_played": []}',
        encoding="utf-8",
    )

    ledger = Ledger.from_file(path, bootstrap_snapshot)

    assert ledger.legacy is False
    assert ledger.genesis_event == 1
    assert ledger.log == [Transaction(event=1, type="buy", player=1, price=50)]


# --- Free transfers ------------------------------------------------------


def test_free_transfers_accrue_one_per_gameweek(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices, event=1)

    assert replay(ledger, bootstrap_snapshot, as_of_event=2).free_transfers == 1
    assert replay(ledger, bootstrap_snapshot, as_of_event=3).free_transfers == 2
    assert replay(ledger, bootstrap_snapshot, as_of_event=5).free_transfers == 4


def test_free_transfers_cap_at_five_across_idle_gameweeks(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices, event=1)

    state = replay(ledger, bootstrap_snapshot, as_of_event=11)

    assert state.free_transfers == 5


def test_free_transfers_spend_resets_accrual(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices, event=1)
    ledger.log.append(Transaction(event=2, type="sell", player=1, price=50))
    ledger.log.append(Transaction(event=2, type="buy", player=16, price=50))

    after_transfer = replay(ledger, bootstrap_snapshot, as_of_event=2)
    assert after_transfer.free_transfers == 0

    after_next_week = replay(ledger, bootstrap_snapshot, as_of_event=3)
    assert after_next_week.free_transfers == 1


def test_genesis_grants_no_free_transfers(bootstrap_snapshot: BootstrapSnapshot) -> None:
    player_ids = list(range(1, 16))
    prices = {player_id: 50 for player_id in player_ids}
    ledger = _genesis_ledger(player_ids, prices, event=1)

    state = replay(ledger, bootstrap_snapshot, as_of_event=1)

    assert state.free_transfers == 0


# --- Hits ------------------------------------------------------------------


def _state_at(event: int, free_transfers: int, holdings: dict[int, Holding], bank: int) -> SquadState:
    return SquadState(holdings=holdings, bank=bank, event=event, free_transfers=free_transfers)


def _held(player_ids: list[int], price: int = 50, bought_event: int = 1) -> dict[int, Holding]:
    return {player_id: Holding(player=player_id, purchase_price=price, bought_event=bought_event) for player_id in player_ids}


def test_one_transfer_on_one_free_transfer_costs_nothing(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    # free_transfers=0 banked going in; the gameweek boundary accrues 1 before spending.
    state = _state_at(1, free_transfers=0, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert result.validation.valid
    assert result.hit_points == 0
    assert result.transfers_made == 1


def test_two_transfers_on_one_free_transfer_costs_four(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    _add_pool_player(bootstrap_snapshot, 102, template_id=3)
    state = _state_at(1, free_transfers=0, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state,
        [Transfer(out_id=1, in_id=101), Transfer(out_id=3, in_id=102)],
        2,
        bootstrap_snapshot,
        _rules(bootstrap_snapshot),
        now=datetime(2025, 8, 20, tzinfo=UTC),
    )

    assert result.validation.valid
    assert result.hit_points == 4


def test_three_transfers_on_one_free_transfer_costs_eight(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    _add_pool_player(bootstrap_snapshot, 102, template_id=3)
    _add_pool_player(bootstrap_snapshot, 103, template_id=8)
    state = _state_at(1, free_transfers=0, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state,
        [Transfer(out_id=1, in_id=101), Transfer(out_id=3, in_id=102), Transfer(out_id=8, in_id=103)],
        2,
        bootstrap_snapshot,
        _rules(bootstrap_snapshot),
        now=datetime(2025, 8, 20, tzinfo=UTC),
    )

    assert result.validation.valid
    assert result.hit_points == 8


def test_two_transfers_on_two_free_transfers_costs_nothing(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    _add_pool_player(bootstrap_snapshot, 102, template_id=3)
    # free_transfers=1 banked going in; accrual brings 2 available for this gameweek.
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state,
        [Transfer(out_id=1, in_id=101), Transfer(out_id=3, in_id=102)],
        2,
        bootstrap_snapshot,
        _rules(bootstrap_snapshot),
        now=datetime(2025, 8, 20, tzinfo=UTC),
    )

    assert result.validation.valid
    assert result.hit_points == 0


def test_exceeding_transfers_cap_is_an_error_not_a_hit(bootstrap_snapshot: BootstrapSnapshot) -> None:
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)
    transfers = [Transfer(out_id=1, in_id=999) for _ in range(21)]

    result = apply_transfers(state, transfers, 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert not result.validation.valid
    assert any("cap" in error.lower() for error in result.validation.errors)
    assert result.hit_points == 0
    assert result.state is state


# --- Validation --------------------------------------------------------


def test_transfer_creating_fourth_club_player_fails_structural_validation(bootstrap_snapshot: BootstrapSnapshot) -> None:
    # Player 1's club already has 3 players (ids 1, 6, 11 -> team (id%5)+1 == 2).
    # A same-position replacement on a *different* club (e.g. player 4's club)
    # pushes that club to 4.
    bootstrap_snapshot.elements.append(
        Player(id=101, web_name="P101", team=bootstrap_snapshot.players_by_id[4].team, element_type=1, now_cost=50)
    )
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(state, [Transfer(out_id=2, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert not result.validation.valid
    assert result.state is state


def test_transfer_overspending_bank_fails(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1, now_cost=5000)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert not result.validation.valid
    assert any("bank" in error.lower() for error in result.validation.errors)
    assert result.state is state


def test_mid_season_squad_over_budget_passes_structural_validation(bootstrap_snapshot: BootstrapSnapshot) -> None:
    bootstrap_snapshot.elements[0].now_cost = 5000

    structural = validate_squad_structure(list(range(1, 16)), bootstrap_snapshot)
    manual_plan = validate_squad(list(range(1, 16)), bootstrap_snapshot)

    assert structural.valid
    assert not manual_plan.valid  # confirms the two validators genuinely differ


def test_two_transfer_gameweek_not_falsely_failed_on_intermediate_state(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    _add_pool_player(bootstrap_snapshot, 102, template_id=2)
    state = _state_at(1, free_transfers=2, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state,
        [Transfer(out_id=1, in_id=101), Transfer(out_id=2, in_id=102)],
        2,
        bootstrap_snapshot,
        _rules(bootstrap_snapshot),
        now=datetime(2025, 8, 20, tzinfo=UTC),
    )

    assert result.validation.valid
    assert sorted(result.state.player_ids) == sorted([*range(3, 16), 101, 102])


def test_cannot_transact_player_blocks_transfer_out(bootstrap_snapshot: BootstrapSnapshot) -> None:
    bootstrap_snapshot.players_by_id[1].can_transact = False
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert not result.validation.valid
    assert result.state is state


def test_cannot_transact_player_blocks_transfer_in(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1, can_transact=False)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert not result.validation.valid
    assert result.state is state


# --- Deadlines -----------------------------------------------------------


def test_transfer_after_deadline_is_rejected(bootstrap_snapshot: BootstrapSnapshot) -> None:
    # Gameweek 2's deadline (from conftest) is 2025-08-22T17:30 UTC.
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state, [Transfer(out_id=1, in_id=2)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 23, tzinfo=UTC)
    )

    assert not result.validation.valid
    assert any("deadline" in error.lower() for error in result.validation.errors)
    assert result.state is state


def test_transfer_before_deadline_is_accepted(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC)
    )

    assert result.validation.valid


def test_gameweek_with_no_deadline_is_rejected(bootstrap_snapshot: BootstrapSnapshot) -> None:
    bootstrap_snapshot.events.append(Gameweek(id=99, name="Gameweek 99", deadline_time=None))
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state, [Transfer(out_id=1, in_id=2)], 99, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC)
    )

    assert not result.validation.valid
    assert result.state is state


def test_unknown_gameweek_is_rejected(bootstrap_snapshot: BootstrapSnapshot) -> None:
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    result = apply_transfers(
        state, [Transfer(out_id=1, in_id=2)], 999, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC)
    )

    assert not result.validation.valid
    assert result.state is state


# --- Immutability ----------------------------------------------------------


def test_apply_transfers_does_not_mutate_input_state_on_success(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)
    holdings_before = dict(state.holdings)
    bank_before = state.bank

    result = apply_transfers(state, [Transfer(out_id=1, in_id=101)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC))

    assert state.holdings == holdings_before
    assert state.bank == bank_before
    assert result.state is not state


def test_rejected_batch_returns_input_state_unchanged(bootstrap_snapshot: BootstrapSnapshot) -> None:
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)
    holdings_before = dict(state.holdings)

    result = apply_transfers(
        state, [Transfer(out_id=1, in_id=999)], 2, bootstrap_snapshot, _rules(bootstrap_snapshot), now=datetime(2025, 8, 20, tzinfo=UTC)
    )

    assert not result.validation.valid
    assert result.state is state
    assert state.holdings == holdings_before


# --- simulate() ------------------------------------------------------------


def test_simulate_chains_state_across_gameweeks(bootstrap_snapshot: BootstrapSnapshot) -> None:
    _add_pool_player(bootstrap_snapshot, 101, template_id=1)
    _add_pool_player(bootstrap_snapshot, 102, template_id=2)
    state = _state_at(1, free_transfers=1, holdings=_held(list(range(1, 16))), bank=250)

    results = simulate(
        state,
        {2: [Transfer(out_id=1, in_id=101)], 3: [Transfer(out_id=2, in_id=102)]},
        bootstrap_snapshot,
        _rules(bootstrap_snapshot),
        now=datetime(2025, 8, 20, tzinfo=UTC),
    )

    assert len(results) == 2
    assert 101 in results[0].state.holdings
    assert 102 in results[1].state.holdings
    assert 101 in results[1].state.holdings

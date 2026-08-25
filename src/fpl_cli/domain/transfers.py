from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fpl_cli.api.models import BootstrapSnapshot
from fpl_cli.domain.rules import ValidationResult, validate_squad_structure


@dataclass(frozen=True)
class TransferRules:
    sell_on_fee: float
    max_extra_free_transfers: int
    transfers_cap: int
    sell_at_purchase_price: bool
    squad_total_spend: int
    # [assumption: absent from bootstrap-static — not in game_settings or
    # game_config.scoring. See docs/plans/transfers.md.]
    points_per_extra_transfer: int = 4
    # [inference: implied by the field name max_extra_free_transfers ("extra"
    # relative to an unstated base) — the base itself is never stated.]
    free_transfers_per_event: int = 1

    @property
    def free_transfer_cap(self) -> int:
        return self.free_transfers_per_event + self.max_extra_free_transfers

    @classmethod
    def from_snapshot(cls, snapshot: BootstrapSnapshot) -> TransferRules:
        settings = snapshot.game_settings
        return cls(
            sell_on_fee=settings.transfers_sell_on_fee,
            max_extra_free_transfers=settings.max_extra_free_transfers,
            transfers_cap=settings.transfers_cap,
            sell_at_purchase_price=settings.element_sell_at_purchase_price,
            squad_total_spend=settings.squad_total_spend,
        )


@dataclass(frozen=True)
class Transaction:
    event: int
    type: Literal["buy", "sell"]
    player: int
    price: int


@dataclass(frozen=True)
class Ledger:
    version: int
    genesis_event: int
    log: list[Transaction]
    chips_played: list[dict[str, Any]] = field(default_factory=list)
    legacy: bool = False

    @classmethod
    def from_file(cls, path: Path, snapshot: BootstrapSnapshot) -> Ledger:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if "log" in payload:
            log = [
                Transaction(
                    event=int(item["event"]),
                    type=item["type"],
                    player=int(item["player"]),
                    price=int(item["price"]),
                )
                for item in payload["log"]
            ]
            return cls(
                version=int(payload.get("version", 1)),
                genesis_event=int(payload.get("genesis_event", 1)),
                log=log,
                chips_played=list(payload.get("chips_played", [])),
            )

        # Legacy format: a bare `players: [int]` array with no ledger. Synthesise
        # a genesis buy log at current now_cost — selling prices computed from
        # this are optimistic, since the real purchase price is unknown.
        players_by_id = snapshot.players_by_id
        genesis_event = current_event_id(snapshot)
        legacy_log = [
            Transaction(event=genesis_event, type="buy", player=player_id, price=players_by_id[player_id].now_cost)
            for player_id in (int(player_id) for player_id in payload.get("players", []))
            if player_id in players_by_id
        ]
        return cls(version=1, genesis_event=genesis_event, log=legacy_log, chips_played=[], legacy=True)


def parse_transfers_plan(path: Path) -> dict[int, list[Transfer]]:
    """Load a transfers-plan file: one entry per gameweek, transfers proposed for it.

    Schema: `[{"event": 4, "transfers": [{"out": 351, "in": 233}]}, ...]`.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    transfers_by_event: dict[int, list[Transfer]] = {}
    for entry in payload:
        event = int(entry["event"])
        if event in transfers_by_event:
            raise ValueError(f"Gameweek {event} appears more than once in the transfers plan.")
        transfers_by_event[event] = [
            Transfer(out_id=int(transfer["out"]), in_id=int(transfer["in"])) for transfer in entry["transfers"]
        ]
    return transfers_by_event


def current_event_id(snapshot: BootstrapSnapshot) -> int:
    for event in snapshot.events:
        if event.is_current:
            return event.id
    for event in snapshot.events:
        if event.is_next:
            return event.id
    return 1


@dataclass(frozen=True)
class Holding:
    player: int
    purchase_price: int
    bought_event: int


@dataclass(frozen=True)
class SquadState:
    holdings: dict[int, Holding]
    bank: int
    event: int
    free_transfers: int

    @property
    def player_ids(self) -> list[int]:
        return sorted(self.holdings)


@dataclass(frozen=True)
class Transfer:
    out_id: int
    in_id: int


@dataclass(frozen=True)
class TransferResult:
    state: SquadState
    validation: ValidationResult
    transfers_made: int
    hit_points: int
    free_transfers_remaining: int


def selling_price(purchase_price: int, now_cost: int, rules: TransferRules) -> int:
    if rules.sell_at_purchase_price:
        return purchase_price
    profit = now_cost - purchase_price
    if profit <= 0:
        return now_cost
    kept = math.floor(profit * (1 - rules.sell_on_fee))
    return purchase_price + kept


def _fold_event(
    state: SquadState,
    transactions: list[Transaction],
    event: int,
    rules: TransferRules,
    *,
    is_genesis: bool,
) -> tuple[SquadState, int, int]:
    """Apply one gameweek's transactions. Returns (new_state, transfers_made, hit_points)."""
    holdings = dict(state.holdings)
    bank = state.bank
    free_transfers = state.free_transfers

    if not is_genesis:
        free_transfers = min(free_transfers + rules.free_transfers_per_event, rules.free_transfer_cap)

    sells = [transaction for transaction in transactions if transaction.type == "sell"]
    buys = [transaction for transaction in transactions if transaction.type == "buy"]

    for transaction in sells:
        holdings.pop(transaction.player, None)
        bank += transaction.price
    for transaction in buys:
        holdings[transaction.player] = Holding(player=transaction.player, purchase_price=transaction.price, bought_event=event)
        bank -= transaction.price

    if is_genesis:
        transfers_made = 0
        hit_points = 0
    else:
        transfers_made = len(buys)
        paid = max(0, transfers_made - free_transfers)
        hit_points = paid * rules.points_per_extra_transfer
        free_transfers = max(0, free_transfers - transfers_made)

    new_state = SquadState(holdings=holdings, bank=bank, event=event, free_transfers=free_transfers)
    return new_state, transfers_made, hit_points


def replay(ledger: Ledger, snapshot: BootstrapSnapshot, *, as_of_event: int | None = None) -> SquadState:
    if as_of_event is not None and as_of_event < ledger.genesis_event:
        raise ValueError(f"as_of_event {as_of_event} precedes genesis_event {ledger.genesis_event}.")

    rules = TransferRules.from_snapshot(snapshot)
    by_event: dict[int, list[Transaction]] = {}
    for transaction in ledger.log:
        by_event.setdefault(transaction.event, []).append(transaction)

    target = as_of_event if as_of_event is not None else max([ledger.genesis_event, *by_event.keys()])

    state = SquadState(holdings={}, bank=rules.squad_total_spend, event=ledger.genesis_event, free_transfers=0)
    state, _, _ = _fold_event(state, by_event.get(ledger.genesis_event, []), ledger.genesis_event, rules, is_genesis=True)

    for event in range(ledger.genesis_event + 1, target + 1):
        state, _, _ = _fold_event(state, by_event.get(event, []), event, rules, is_genesis=False)

    return state


def apply_transfers(
    state: SquadState,
    transfers: list[Transfer],
    event: int,
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    *,
    now: datetime | None = None,
) -> TransferResult:
    if event <= state.event:
        raise ValueError(f"Cannot apply transfers for gameweek {event}; state is already at gameweek {state.event}.")

    now = now or datetime.now(UTC)
    players_by_id = snapshot.players_by_id
    errors: list[str] = []

    gameweek = next((gw for gw in snapshot.events if gw.id == event), None)
    if gameweek is None or gameweek.deadline_time is None:
        errors.append(f"Gameweek {event} has no known deadline; transfers cannot be applied.")
    elif now >= gameweek.deadline_time:
        errors.append(f"The gameweek {event} deadline has passed; transfers cannot be applied.")

    if len(transfers) > rules.transfers_cap:
        errors.append(f"{len(transfers)} transfers requested; the cap is {rules.transfers_cap} per gameweek.")

    out_ids = [transfer.out_id for transfer in transfers]
    in_ids = [transfer.in_id for transfer in transfers]

    if len(out_ids) != len(set(out_ids)):
        errors.append("The transfer batch sells the same player more than once.")
    if len(in_ids) != len(set(in_ids)):
        errors.append("The transfer batch buys the same player more than once.")

    for transfer in transfers:
        if transfer.out_id == transfer.in_id:
            errors.append(f"Player {transfer.out_id} cannot be transferred for themselves.")

    unknown_ids = sorted({player_id for player_id in (*out_ids, *in_ids) if player_id not in players_by_id})
    if unknown_ids:
        errors.append(f"Unknown player IDs: {', '.join(map(str, unknown_ids))}.")

    if not unknown_ids and not errors:
        not_held = sorted(set(out_ids) - set(state.holdings))
        if not_held:
            names = ", ".join(players_by_id[player_id].display_name for player_id in not_held)
            errors.append(f"Not in the squad, cannot be sold: {names}.")

        remaining_after_sells = set(state.holdings) - set(out_ids)
        already_held = sorted(set(in_ids) & remaining_after_sells)
        if already_held:
            names = ", ".join(players_by_id[player_id].display_name for player_id in already_held)
            errors.append(f"Already in the squad: {names}.")

        cannot_transact = sorted(
            {player_id for player_id in (*out_ids, *in_ids) if not players_by_id[player_id].can_transact}
        )
        if cannot_transact:
            names = ", ".join(players_by_id[player_id].display_name for player_id in cannot_transact)
            errors.append(f"Cannot currently be transferred: {names}.")

    if errors:
        validation = ValidationResult(errors, [], snapshot.season, snapshot.fetched_at.isoformat())
        return TransferResult(
            state=state,
            validation=validation,
            transfers_made=len(transfers),
            hit_points=0,
            free_transfers_remaining=state.free_transfers,
        )

    transactions: list[Transaction] = []
    for transfer in transfers:
        holding = state.holdings[transfer.out_id]
        out_player = players_by_id[transfer.out_id]
        in_player = players_by_id[transfer.in_id]
        sale_price = selling_price(holding.purchase_price, out_player.now_cost, rules)
        transactions.append(Transaction(event=event, type="sell", player=transfer.out_id, price=sale_price))
        transactions.append(Transaction(event=event, type="buy", player=transfer.in_id, price=in_player.now_cost))

    working_state = state
    for idle_event in range(state.event + 1, event):
        working_state, _, _ = _fold_event(working_state, [], idle_event, rules, is_genesis=False)

    tentative_state, transfers_made, hit_points = _fold_event(working_state, transactions, event, rules, is_genesis=False)

    structural = validate_squad_structure(tentative_state.player_ids, snapshot)
    final_errors = list(structural.errors)
    if tentative_state.bank < 0:
        final_errors.append(f"The transfer overspends the bank by £{-tentative_state.bank / 10:.1f}m.")

    if final_errors:
        validation = ValidationResult(final_errors, structural.warnings, snapshot.season, snapshot.fetched_at.isoformat())
        return TransferResult(
            state=state,
            validation=validation,
            transfers_made=transfers_made,
            hit_points=0,
            free_transfers_remaining=state.free_transfers,
        )

    validation = ValidationResult([], structural.warnings, snapshot.season, snapshot.fetched_at.isoformat())
    return TransferResult(
        state=tentative_state,
        validation=validation,
        transfers_made=transfers_made,
        hit_points=hit_points,
        free_transfers_remaining=tentative_state.free_transfers,
    )


def simulate(
    state: SquadState,
    transfers_by_event: dict[int, list[Transfer]],
    snapshot: BootstrapSnapshot,
    rules: TransferRules,
    *,
    now: datetime | None = None,
) -> list[TransferResult]:
    results: list[TransferResult] = []
    current = state
    for event in sorted(transfers_by_event):
        result = apply_transfers(current, transfers_by_event[event], event, snapshot, rules, now=now)
        results.append(result)
        current = result.state
    return results

from __future__ import annotations

import re
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.shortcuts import CompleteStyle
from rich.table import Table

from fpl_cli.api.models import BootstrapSnapshot, Player
from fpl_cli.domain.squad import SquadSlots, eligible_players
from fpl_cli.presentation import console, squad_grid

MIN_TERMINAL_HEIGHT = 20
MAX_COMPLETIONS = 40


class BuilderCancelled(Exception):
    """The user quit, or interrupted the builder, before completing the squad."""


class TerminalTooSmall(Exception):
    def __init__(self, height: int, minimum: int) -> None:
        self.height = height
        self.minimum = minimum
        super().__init__(f"Terminal is {height} rows; the squad builder needs at least {minimum}.")


@dataclass(frozen=True)
class Candidate:
    id: int
    name: str
    key: str
    club: int
    price: int
    meta: str


def _build_candidates(snapshot: BootstrapSnapshot) -> dict[int, list[Candidate]]:
    """One Candidate list per position id, ranked by total points, built once."""
    clubs = snapshot.clubs
    by_position: dict[int, list[Candidate]] = {}
    for player in sorted(snapshot.elements, key=lambda item: -item.total_points):
        club = clubs.get(player.team)
        club_short = club.short_name if club else str(player.team)
        availability = "" if player.status == "a" else f" · {player.status}"
        meta = f"{club_short} · £{player.price_millions:.1f}m{availability}"
        candidate = Candidate(
            id=player.id,
            name=player.display_name,
            key=player.display_name.casefold(),
            club=player.team,
            price=player.now_cost,
            meta=meta,
        )
        by_position.setdefault(player.element_type, []).append(candidate)
    return by_position


class SlotCompleter(Completer):
    """Offers only the players `eligible_players` allows into the active slot."""

    def __init__(self, builder: SquadBuilder) -> None:
        self._builder = builder

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        builder = self._builder
        if builder.active_slot is None:
            return
        slot = builder.slots.slot(builder.active_slot)
        eligible_ids = {player.id for player in eligible_players(builder.slots, builder.active_slot, builder.snapshot)}
        candidates = builder.candidates_by_position.get(slot.position_id, [])

        typed = document.text_before_cursor.casefold()
        pattern = re.compile(".*?".join(re.escape(char) for char in typed)) if typed else None

        yielded = 0
        for candidate in candidates:
            if candidate.id not in eligible_ids:
                continue
            if pattern is not None and not pattern.search(candidate.key):
                continue
            yield Completion(
                candidate.name,
                start_position=-len(document.text_before_cursor),
                display=candidate.name,
                display_meta=candidate.meta,
            )
            yielded += 1
            if yielded >= MAX_COMPLETIONS:
                break


class SquadBuilder:
    def __init__(self, snapshot: BootstrapSnapshot, *, input=None, output=None) -> None:
        self.snapshot = snapshot
        self.slots = SquadSlots.empty(snapshot)
        self.candidates_by_position = _build_candidates(snapshot)
        self.active_slot: int | None = None
        self._session = PromptSession(input=input, output=output, erase_when_done=True)
        self.player_completer = SlotCompleter(self)

    def run(self) -> SquadSlots:
        if console.size.height < MIN_TERMINAL_HEIGHT:
            raise TerminalTooSmall(console.size.height, MIN_TERMINAL_HEIGHT)

        while True:
            self._render()
            try:
                command = self._prompt_slot()
            except (EOFError, KeyboardInterrupt) as exc:
                raise BuilderCancelled from exc

            if command is None:
                continue
            if command == "quit":
                raise BuilderCancelled
            if command == "done":
                if self.slots.is_complete:
                    break
                console.print("[yellow]Squad is not complete yet.[/yellow]")
                continue
            if isinstance(command, tuple):
                _, clear_index = command
                self.slots = self.slots.with_clear(clear_index)
                continue

            self._pick_player(command)

        self._render()
        return self.slots

    def _render(self) -> None:
        console.clear()
        console.print(squad_grid(self.slots, self.snapshot))
        console.print()
        console.print("[dim]slot number · <Enter> next empty · d N clear · done · quit[/dim]")

    def _prompt_slot(self) -> int | str | tuple[str, int] | None:
        raw = self._session.prompt("slot> ").strip()
        if not raw:
            empty = self.slots.empty_slots
            return empty[0].index if empty else "done"

        lowered = raw.lower()
        if lowered == "done":
            return "done"
        if lowered == "quit":
            return "quit"
        if lowered.startswith("d "):
            arg = raw[2:].strip()
            if arg.isdigit() and 1 <= int(arg) <= len(self.slots.slots):
                return ("clear", int(arg))
            console.print(f"[red]Not a slot number to clear: {arg!r}[/red]")
            return None
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(self.slots.slots):
                return index
            console.print(f"[red]No such slot: {index}[/red]")
            return None

        console.print(f"[red]Unrecognised input: {raw!r}[/red]")
        return None

    def _pick_player(self, slot_index: int) -> None:
        slot = self.slots.slot(slot_index)
        position = self.snapshot.positions.get(slot.position_id)
        label = position.singular_name_short if position else str(slot.position_id)

        self.active_slot = slot_index
        try:
            raw = self._session.prompt(
                f"player ({label} #{slot_index})> ",
                completer=self.player_completer,
                complete_while_typing=True,
                complete_style=CompleteStyle.MULTI_COLUMN,
            ).strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise BuilderCancelled from exc
        finally:
            self.active_slot = None

        if not raw:
            return

        matches = self._resolve(slot_index, raw)
        if not matches:
            console.print(f"[red]No eligible player matches {raw!r}.[/red]")
            return

        chosen = matches[0] if len(matches) == 1 else self._disambiguate(matches)
        if chosen is None:
            return

        self.slots = self.slots.with_pick(slot_index, chosen.id)
        if chosen.status != "a" or chosen.chance_of_playing_next_round == 0:
            console.print(
                f"[yellow]! {chosen.display_name} is flagged as unavailable: "
                f"{chosen.news or chosen.status}.[/yellow]"
            )

    def _resolve(self, slot_index: int, raw: str) -> list[Player]:
        eligible = eligible_players(self.slots, slot_index, self.snapshot)
        typed = raw.casefold()

        exact = [player for player in eligible if player.display_name.casefold() == typed]
        if exact:
            return exact

        pattern = re.compile(".*?".join(re.escape(char) for char in typed))
        return [player for player in eligible if pattern.search(player.display_name.casefold())]

    def _disambiguate(self, matches: list[Player]) -> Player | None:
        clubs = self.snapshot.clubs
        table = Table(title="Multiple matches")
        table.add_column("#", justify="right")
        table.add_column("Player")
        table.add_column("Club")
        table.add_column("Price", justify="right")
        for index, player in enumerate(matches, start=1):
            club = clubs.get(player.team)
            table.add_row(
                str(index), player.display_name, club.short_name if club else "?", f"£{player.price_millions:.1f}m"
            )
        console.print(table)

        try:
            raw = self._session.prompt("which #> ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise BuilderCancelled from exc

        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1]
        console.print("[red]Cancelled selection.[/red]")
        return None

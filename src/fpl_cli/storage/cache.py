from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

from fpl_cli.api.models import BootstrapSnapshot

T = TypeVar("T")


class JsonDocumentCache:
    """Path-keyed JSON document cache: raw save, typed load with mtime-derived fetched_at."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save_raw(self, payload: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def load_typed(self, parse: Callable[[object, datetime], T]) -> T | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromtimestamp(self.path.stat().st_mtime, UTC)
            return parse(payload, fetched_at)
        except (OSError, ValueError, TypeError):
            return None


class SnapshotCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".fpl-cli" / "bootstrap-static.json"
        self._store = JsonDocumentCache(self.path)

    def save(self, snapshot: BootstrapSnapshot) -> None:
        self._store.save_raw(snapshot.raw)

    def load(self) -> BootstrapSnapshot | None:
        return self._store.load_typed(
            lambda payload, fetched_at: BootstrapSnapshot.from_payload(payload, fetched_at=fetched_at)
        )

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fpl_cli.api.models import BootstrapSnapshot


class SnapshotCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path.home() / ".fpl-cli" / "bootstrap-static.json"

    def save(self, snapshot: BootstrapSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(snapshot.raw, ensure_ascii=False), encoding="utf-8")

    def load(self) -> BootstrapSnapshot | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return BootstrapSnapshot(
                **payload,
                fetched_at=datetime.fromtimestamp(self.path.stat().st_mtime, UTC),
                season=_season_from_payload(payload),
                raw=payload,
            )
        except (OSError, ValueError, TypeError):
            return None


def _season_from_payload(payload: dict) -> str:
    url = payload.get("game_config", {}).get("settings", {}).get("static_content_url", "")
    return next((part for part in reversed(str(url).rstrip("/").split("/")) if "_" in part), "unknown")

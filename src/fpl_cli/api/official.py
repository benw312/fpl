from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from fpl_cli.api.models import BootstrapSnapshot

BASE_URL = "https://fantasy.premierleague.com/api"


class FplApiError(RuntimeError):
    pass


class OfficialFplApi:
    def __init__(self, client: httpx.Client | None = None, base_url: str = BASE_URL) -> None:
        self._client = client or httpx.Client(timeout=15, headers={"User-Agent": "fpl-cli/0.1"})
        self._base_url = base_url.rstrip("/")

    def close(self) -> None:
        self._client.close()

    def bootstrap_static(self) -> BootstrapSnapshot:
        try:
            response = self._client.get(f"{self._base_url}/bootstrap-static/")
            response.raise_for_status()
            payload: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise FplApiError(f"Could not fetch the FPL snapshot: {exc}") from exc

        try:
            return BootstrapSnapshot(
                **payload,
                fetched_at=datetime.now(UTC),
                season=_season_from_payload(payload),
                raw=payload,
            )
        except Exception as exc:
            raise FplApiError(f"FPL snapshot did not match the expected shape: {exc}") from exc


def _season_from_payload(payload: dict[str, Any]) -> str:
    static_content_url = payload.get("game_config", {}).get("settings", {}).get("static_content_url", "")
    parts = str(static_content_url).rstrip("/").split("/")
    return next((part for part in reversed(parts) if "_" in part), "unknown")

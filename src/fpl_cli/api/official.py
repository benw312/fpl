from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from fpl_cli.api.models import BootstrapSnapshot, Fixture
from fpl_cli.transport import (
    AccessDenied,
    FplError,
    FplTransport,
    MalformedResponse,
    NotFound,
    RateLimited,
    RequestTimeout,
    ServerError,
    TransportError,
)

__all__ = [
    "AccessDenied",
    "FplApiError",
    "FplError",
    "MalformedResponse",
    "NotFound",
    "OfficialFplApi",
    "RateLimited",
    "RequestTimeout",
    "ServerError",
    "TransportError",
]


class FplApiError(FplError):
    """The payload did not match the expected FPL schema."""


class OfficialFplApi:
    def __init__(self, transport: FplTransport | None = None) -> None:
        self._transport = transport or FplTransport()
        self._owns_transport = transport is None

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()

    def bootstrap_static(self) -> BootstrapSnapshot:
        payload = self._transport.get_json("/bootstrap-static/")
        try:
            return BootstrapSnapshot.from_payload(payload, fetched_at=datetime.now(UTC))
        except ValidationError as exc:
            raise FplApiError(f"FPL snapshot did not match the expected shape: {exc}") from exc

    def fixtures(self) -> list[Fixture]:
        payload = self._transport.get_json("/fixtures/")
        try:
            return [Fixture.model_validate(item) for item in payload]
        except ValidationError as exc:
            raise FplApiError(f"FPL fixtures did not match the expected shape: {exc}") from exc

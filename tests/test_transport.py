from __future__ import annotations

import httpx
import pytest
import respx

from fpl_cli.transport import (
    AccessDenied,
    FplTransport,
    MalformedResponse,
    NotFound,
    RateLimited,
    RequestTimeout,
    RetryPolicy,
    ServerError,
)


def make_transport(recording_sleep, **policy_kwargs) -> FplTransport:
    policy = RetryPolicy(**{"base_delay": 0.5, "max_delay": 4.0, "jitter": 0.25, **policy_kwargs})
    return FplTransport(base_url="https://fpl.test/api", policy=policy, sleep=recording_sleep)


@respx.mock
def test_timeout_then_success(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.side_effect = [httpx.ReadTimeout("boom"), httpx.Response(200, json={"ok": True})]
    transport = make_transport(recording_sleep)

    result = transport.get_json("/bootstrap-static/")

    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_timeout_exhausted(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(side_effect=httpx.ReadTimeout("boom"))
    transport = make_transport(recording_sleep)

    with pytest.raises(RequestTimeout) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert excinfo.value.attempts == 3
    assert len(recording_sleep.delays) == 2


@respx.mock
def test_connect_error_retried(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.side_effect = [httpx.ConnectError("no route"), httpx.Response(200, json={"ok": True})]
    transport = make_transport(recording_sleep)

    result = transport.get_json("/bootstrap-static/")

    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_503_then_success(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.side_effect = [httpx.Response(503), httpx.Response(200, json={"ok": True})]
    transport = make_transport(recording_sleep)

    result = transport.get_json("/bootstrap-static/")

    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_5xx_exhausted(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(return_value=httpx.Response(503))
    transport = make_transport(recording_sleep)

    with pytest.raises(ServerError) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert excinfo.value.status_code == 503


@respx.mock
def test_429_with_short_retry_after_is_retried(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"ok": True}),
    ]
    transport = make_transport(recording_sleep)

    result = transport.get_json("/bootstrap-static/")

    assert result == {"ok": True}
    assert route.call_count == 2
    assert recording_sleep.delays == [1.0]


@respx.mock
def test_429_with_long_retry_after_is_not_retried(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "3600"})
    )
    transport = make_transport(recording_sleep)

    with pytest.raises(RateLimited) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert excinfo.value.retry_after == 3600
    assert recording_sleep.delays == []


@respx.mock
def test_429_with_no_retry_after_is_not_retried(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(return_value=httpx.Response(429))
    transport = make_transport(recording_sleep)

    with pytest.raises(RateLimited) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert excinfo.value.retry_after is None
    assert recording_sleep.delays == []


@respx.mock
def test_429_with_unparseable_retry_after_is_treated_as_absent(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "not-a-date"})
    )
    transport = make_transport(recording_sleep)

    with pytest.raises(RateLimited) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert excinfo.value.retry_after is None
    assert recording_sleep.delays == []


@respx.mock
def test_403_is_not_retried(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.mock(return_value=httpx.Response(403))
    transport = make_transport(recording_sleep)

    with pytest.raises(AccessDenied) as excinfo:
        transport.get_json("/bootstrap-static/")

    assert route.call_count == 1
    assert "block" in str(excinfo.value).lower()


@respx.mock
def test_404_is_not_retried(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.mock(return_value=httpx.Response(404))
    transport = make_transport(recording_sleep)

    with pytest.raises(NotFound):
        transport.get_json("/bootstrap-static/")

    assert route.call_count == 1


@respx.mock
def test_malformed_html_body_is_not_retried(recording_sleep) -> None:
    route = respx.get("https://fpl.test/api/bootstrap-static/")
    route.mock(return_value=httpx.Response(200, text="<html>blocked</html>"))
    transport = make_transport(recording_sleep)

    with pytest.raises(MalformedResponse):
        transport.get_json("/bootstrap-static/")

    assert route.call_count == 1


@respx.mock
def test_json_scalar_body_is_malformed(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(return_value=httpx.Response(200, json=42))
    transport = make_transport(recording_sleep)

    with pytest.raises(MalformedResponse):
        transport.get_json("/bootstrap-static/")


@respx.mock
def test_backoff_sequence_increases_and_stays_in_jitter_band(recording_sleep) -> None:
    respx.get("https://fpl.test/api/bootstrap-static/").mock(return_value=httpx.Response(503))
    transport = make_transport(recording_sleep, attempts=3, base_delay=0.5, max_delay=4.0, jitter=0.25)

    with pytest.raises(ServerError):
        transport.get_json("/bootstrap-static/")

    delays = recording_sleep.delays
    assert len(delays) == 2
    assert 0.375 <= delays[0] <= 0.625
    assert 0.75 <= delays[1] <= 1.25
    assert delays[0] < delays[1]


@respx.mock
def test_injected_client_is_not_closed(recording_sleep) -> None:
    client = httpx.Client()
    transport = FplTransport(client=client, base_url="https://fpl.test/api", sleep=recording_sleep)

    transport.close()

    assert not client.is_closed
    client.close()

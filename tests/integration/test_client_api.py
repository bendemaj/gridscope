import logging

import httpx
import pytest
from conftest import END, FIXTURES, START, mock_response
from fastapi.testclient import TestClient

from gridscope import GridScope
from gridscope.api.app import create_app
from gridscope.config import Settings
from gridscope.errors import (
    InvalidQuery,
    MissingToken,
    NoData,
    ProviderAuthenticationError,
    ProviderRateLimit,
    ProviderUnavailable,
)
from gridscope.models import GenerationType
from gridscope.providers.entsoe.client import ENTSOEProvider


async def test_client_vertical_slice(gs):
    prices = await gs.prices("AT", START, END)
    assert prices.meta.count == 4
    assert str(prices.to_dataframe().index.tz) == "UTC"
    assert (await gs.load("AT", START, END)).data[0].value == 1000
    assert len((await gs.generation("AT", START, END, GenerationType.SOLAR)).data) == 4
    assert (await gs.renewable_share("AT", START, END)).data[0].value == 20
    assert (await gs.residual_load("AT", START, END)).data[0].value == 800
    imports = await gs.net_imports("AT", START, END, neighbors=["DE_LU"])
    assert imports.data[0].value == 400
    assert "not a national total" in imports.meta.warnings[0]
    assert (await gs.price_volatility("AT", START, END, window=2)).data[-1].value > 0
    assert (await gs.price_spread("AT", START, END)).data[0].value == 110
    assert (await gs.detect_anomalies("AT", START, END, window=2)).data[-1].is_anomaly


async def test_validation_before_credentials():
    async with GridScope(settings=Settings(entsoe_api_token=None, _env_file=None)) as client:
        with pytest.raises(InvalidQuery):
            await client.prices("INVALID", START, END)
        with pytest.raises(InvalidQuery):
            await client.flows("AT", "AT", START, END)
        with pytest.raises(MissingToken):
            await client.prices("AT", START, END)


async def test_parameters_header_auth_and_cache(caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return mock_response(request)

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="PRIVATE_TEST_TOKEN", _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        with caplog.at_level(logging.INFO):
            first = await client.prices("AT", START, END)
            again = await client.prices("AT", START, END)
        assert len(calls) == 1
        assert first.data[0].retrieved_at == again.data[0].retrieved_at
        assert calls[0].headers["SECURITY_TOKEN"] == "PRIVATE_TEST_TOKEN"
        assert "securityToken" not in calls[0].url.params
        assert calls[0].url.params["contract_MarketAgreement.type"] == "A01"
        assert (
            calls[0].url.params["classificationSequence_AttributeInstanceComponent.position"] == "1"
        )
        assert "PRIVATE_TEST_TOKEN" not in caplog.text


@pytest.mark.parametrize(
    "status,error",
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (429, ProviderRateLimit),
        (503, ProviderUnavailable),
    ],
)
async def test_provider_error_mapping(status, error):
    provider = ENTSOEProvider(
        Settings(entsoe_api_token="private", max_retries=0, _env_file=None),
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, text="do not leak raw provider body private")
        ),
    )
    async with GridScope(provider) as client:
        with pytest.raises(error) as exc:
            await client.prices("AT", START, END)
        assert "private" not in str(exc.value)


async def test_long_retry_after_fails_without_early_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "600"})

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        with pytest.raises(ProviderRateLimit):
            await client.prices("AT", START, END)
        assert len(calls) == 1


async def test_transient_retry(monkeypatch):
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("gridscope.providers.entsoe.client.asyncio.sleep", sleep)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503) if len(calls) == 1 else mock_response(request)

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        assert len((await client.prices("AT", START, END)).data) == 4
    assert 1.0 in sleeps
    assert len(calls) == 2


async def test_no_data_400_not_generic_error():
    xml = (
        b"<Acknowledgement_MarketDocument><Reason><code>999</code>"
        b"<text>No matching data found</text></Reason></Acknowledgement_MarketDocument>"
    )
    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(lambda r: httpx.Response(400, content=xml)),
        )
    ) as client:
        with pytest.raises(NoData):
            await client.load("AT", START, END)


@pytest.mark.parametrize(
    "route",
    [
        "prices",
        "load",
        "generation",
        "flows",
        "intelligence/renewable-share",
        "intelligence/residual-load",
        "intelligence/net-imports",
        "intelligence/price-volatility",
        "intelligence/price-spread",
        "intelligence/anomalies",
    ],
)
def test_rest_endpoints(route):
    gs = GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(mock_response),
        )
    )
    # Lifespan owns and closes the client when supplied through dependency override below.
    app = create_app()
    from gridscope.api.app import get_client

    app.dependency_overrides[get_client] = lambda: gs
    with TestClient(app) as client:
        r = client.get(
            "/v1/" + route,
            params={
                "zone": "AT",
                "start": START.isoformat(),
                "end": END.isoformat(),
                "from_zone": "DE_LU",
                "to_zone": "AT",
                "neighbors": "DE_LU",
                "window": 2,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["meta"]["count"] == len(r.json()["data"])
        assert r.json()["data"]
        client.portal.call(gs.aclose)


def test_health_docs_validation_and_missing_token():
    from gridscope.api.app import get_client

    app = create_app()
    gs = GridScope(settings=Settings(entsoe_api_token=None, _env_file=None))
    app.dependency_overrides[get_client] = lambda: gs
    with TestClient(app) as client:
        for route in ["/health", "/docs", "/openapi.json", "/v1/zones", "/v1/sources"]:
            assert client.get(route).status_code == 200
        params = {"start": "2026-09-01", "end": "2026-09-02"}
        assert client.get("/v1/prices", params={**params, "zone": "BAD"}).status_code == 422
        r = client.get("/v1/prices", params=params)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "missing_api_token"
        assert (
            client.get(
                "/v1/intelligence/price-volatility", params={**params, "window": 1}
            ).status_code
            == 422
        )
        client.portal.call(gs.aclose)


async def test_example_report_uses_provider_values(gs):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "system_example", Path(__file__).parents[2] / "examples/austria_system.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = await module.report(gs, START.isoformat(), END.isoformat())
    assert "AUSTRIA" in text
    assert "1.15 GW" in text
    assert "37.50 EUR/MWh" in text
    assert "DE_LU only" in text


async def test_price_pagination_after_outside_interval_page(monkeypatch):
    from copy import deepcopy
    from xml.etree import ElementTree as ET

    from gridscope.providers.entsoe.parser import read_xml

    root = read_xml((FIXTURES / "prices.xml").read_bytes())
    ts = root.find("TimeSeries")
    root.remove(ts)
    # 100 full-day series outside the requested UTC interval must not stop pagination.
    ts.find("Period/timeInterval/start").text = "2026-08-31T00:00Z"
    ts.find("Period/timeInterval/end").text = "2026-08-31T01:00Z"
    for _ in range(100):
        root.append(deepcopy(ts))
    first_page = ET.tostring(root)
    offsets = []

    def handler(request):
        offsets.append(request.url.params["offset"])
        return (
            httpx.Response(200, content=first_page) if len(offsets) == 1 else mock_response(request)
        )

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        assert len((await client.prices("AT", START, END)).data) == 4
    assert offsets == ["0", "100"]


async def test_long_range_chunking_and_partial_warning():
    from datetime import timedelta

    calls = []

    def handler(request):
        calls.append(request.url.params)
        if len(calls) == 1:
            return mock_response(request)
        return httpx.Response(
            400,
            content=(
                b"<Acknowledgement_MarketDocument><Reason>"
                b"<text>No matching data found</text></Reason></Acknowledgement_MarketDocument>"
            ),
        )

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        series = await client.prices("AT", START, START + timedelta(days=32))
        assert len(calls) == 2
        assert calls[0]["periodEnd"] == calls[1]["periodStart"]
        assert any("No data" in w for w in series.meta.warnings)


@pytest.mark.parametrize("ttl", [0, 0.000001])
async def test_cache_disable_and_expiry(ttl):
    calls = []

    def handler(request):
        calls.append(request)
        return mock_response(request)

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="test", cache_ttl_seconds=ttl, _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        await client.prices("AT", START, END)
        await client.prices("AT", START, END)
    assert len(calls) == 2


async def test_transport_timeout_does_not_leak_credentials():
    def handler(request):
        raise httpx.ReadTimeout("private-token", request=request)

    async with GridScope(
        ENTSOEProvider(
            Settings(entsoe_api_token="private-token", max_retries=0, _env_file=None),
            transport=httpx.MockTransport(handler),
        )
    ) as client:
        with pytest.raises(ProviderUnavailable) as exc:
            await client.prices("AT", START, END)
        assert "private-token" not in str(exc.value)

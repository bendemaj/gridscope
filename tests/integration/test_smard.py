import asyncio
from datetime import timedelta

import httpx
import pytest
from conftest import END, START
from fastapi.testclient import TestClient

from gridscope import GridScope
from gridscope.api.app import create_app
from gridscope.config import Settings
from gridscope.errors import MalformedResponse, NoData, ProviderRateLimit, UnsupportedDataset
from gridscope.models import GenerationType
from gridscope.providers.smard.client import SMARDProvider
from gridscope.storage import SQLiteStore

STAMP = int(START.timestamp() * 1000)


def handler(request):
    assert "SECURITY_TOKEN" not in request.headers
    assert "securityToken" not in request.url.params
    fid = int(request.url.path.split("/")[3])
    if "index_" in request.url.path:
        return httpx.Response(200, json={"timestamps": [STAMP]})
    values = [-10, 0, None, 20] if fid == 4169 else [10, 20, None, 40]
    if fid == 4848:
        values = [-10, -20, None, -40]
    return httpx.Response(
        200,
        json={
            "meta_data": {"created": STAMP},
            "series": [[STAMP + 900000 * i, v] for i, v in enumerate(values)],
        },
    )


def provider(callback=handler, **settings):
    return SMARDProvider(
        Settings(entsoe_api_token="secret-test-token", max_retries=0, _env_file=None, **settings),
        transport=httpx.MockTransport(callback),
    )


async def test_all_datasets_units_direction_and_provenance():
    async with GridScope(provider()) as gs:
        load = await gs.load("DE", START, END)
        assert [p.value for p in load.data] == [40, 80, None, 160]
        assert load.data[2].quality == "missing"
        assert load.data[0].source_revision == str(STAMP)
        assert "SMARD.de" in load.meta.attribution
        prices = await gs.prices("DE_LU", START, END)
        assert [p.value for p in prices.data] == [-10, 0, None, 20]
        generation = await gs.generation("DE", START, END)
        assert {p.generation_type for p in generation.data} >= {
            GenerationType.HYDRO,
            GenerationType.GAS,
        }
        flow = await gs.flows("AT", "DE_LU", START, END)
        assert [p.value for p in flow.data] == [40, 80, None, 160]
        assert flow.data[0].from_zone == "AT"
        assert any("sign reversed" in n for n in flow.data[0].notes)
        imports = await gs.net_imports("DE_LU", START, END, neighbors=["AT"])
        assert imports.data[0].value == 0
        assert "SMARD" in imports.meta.attribution and "ENTSO-E" not in imports.meta.attribution


async def test_cache_retains_retrieval_time_and_clear_cache_refreshes():
    calls = []

    def recorded(request):
        calls.append(request)
        return handler(request)

    p = provider(recorded)
    async with GridScope(p) as gs:
        first = await gs.prices("DE_LU", START, END)
        second = await gs.prices("DE_LU", START, END)
        assert first.data == second.data
        assert len(calls) == 2
        p.clear_cache()
        await gs.prices("DE_LU", START, END)
        assert len(calls) == 4


async def test_capabilities_fail_without_network_or_fallback():
    def unexpected(request):
        pytest.fail("Unsupported dataset must fail before a request")

    async with GridScope(provider(unexpected)) as gs:
        for method, args in [
            ("prices", ("DE",)),
            ("load", ("FR",)),
            ("generation", ("NL",)),
            ("flows", ("FR", "NL")),
        ]:
            with pytest.raises(UnsupportedDataset):
                await getattr(gs, method)(*args, START, END)


@pytest.mark.parametrize(
    "payload",
    [
        {"series": [[STAMP, True]], "meta_data": {}},
        {"series": [[STAMP, float("inf")]], "meta_data": {}},
        {"series": [[STAMP, -1]], "meta_data": {}},
        {"series": [[STAMP, 1], [STAMP, 2]], "meta_data": {}},
        {"series": [[STAMP // 1000, 1]], "meta_data": {}},
    ],
)
async def test_malformed_values_are_rejected(payload):
    import json

    def invalid(request):
        if "index_" in request.url.path:
            return handler(request)
        return httpx.Response(200, content=json.dumps(payload))

    async with GridScope(provider(invalid)) as gs:
        with pytest.raises(MalformedResponse):
            await gs.load("DE", START, END)


@pytest.mark.parametrize("status,error", [(404, NoData), (429, ProviderRateLimit)])
async def test_missing_and_long_retry_errors_are_safe(status, error):
    async with GridScope(
        provider(
            lambda r: httpx.Response(status, headers={"Retry-After": "999"}, text="private body")
        )
    ) as gs:
        with pytest.raises(error) as caught:
            await gs.load("DE", START, END)
        assert "private" not in str(caught.value)


async def test_index_anchors_control_week_selection_across_dst():
    anchors = [STAMP - 167 * 3600000, STAMP, STAMP + 169 * 3600000]
    calls = []

    def indexed(request):
        calls.append(request.url.path)
        if "index_" in request.url.path:
            return httpx.Response(200, json={"timestamps": anchors})
        return handler(request)

    async with GridScope(provider(indexed)) as gs:
        await gs.load("DE", START, END)
    assert len(calls) == 2
    assert calls[-1].endswith(f"_{STAMP}.json")


def test_rest_storage_resampling_and_offline_as_of(tmp_path):
    p = provider()
    store = SQLiteStore(tmp_path / "history.sqlite3")
    gs = GridScope(p, store=store)
    try:
        with TestClient(create_app(gs)) as client:
            query = {
                "provider": "smard",
                "zone": "DE",
                "start": START.isoformat(),
                "end": END.isoformat(),
            }
            raw = client.get("/v1/load", params=query)
            assert raw.status_code == 200
            history = client.get("/v1/history/load", params=query).json()["data"]
            assert len(history) == 1
            cutoff = history[0]["recorded_at"]

            original_request = p._request

            async def fail_request(path):
                pytest.fail("Stored queries must never call the provider")

            p._request = fail_request
            stored = client.get(
                "/v1/load",
                params=query | {"mode": "stored", "as_of": cutoff, "resolution": "PT60M"},
            )
            assert stored.status_code == 200
            assert len(stored.json()["data"]) == 1
            assert stored.json()["data"][0]["value"] is None
            assert stored.json()["data"][0]["quality"] == "incomplete"
            assert len(client.get("/v1/history/load", params=query).json()["data"]) == 1
            missing = client.get(
                "/v1/load",
                params=query | {"mode": "stored", "end": (END + timedelta(hours=1)).isoformat()},
            )
            assert missing.status_code == 404
            invalid = client.get("/v1/load", params=query | {"as_of": cutoff})
            assert invalid.status_code == 422
            p._request = original_request
    finally:
        asyncio.run(gs.aclose())
        store.close()


async def test_filtered_generation_stores_all_types_and_failed_fetch_does_not_overwrite(tmp_path):
    from gridscope.errors import ProviderUnavailable

    p = provider(cache_ttl_seconds=0)
    store = SQLiteStore(tmp_path / "history.db")
    try:
        async with GridScope(p, store=store) as gs:
            solar = await gs.generation("AT", START, END, GenerationType.SOLAR)
            assert all(p.generation_type == GenerationType.SOLAR for p in solar.data)
            full = await gs.with_options(mode="stored").generation("AT", START, END)
            assert len(full.data) > len(solar.data)
            assert GenerationType.NUCLEAR not in {p.generation_type for p in full.data}
            old_http = p.http
            p.http = httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(503))
            )
            await old_http.aclose()
            with pytest.raises(ProviderUnavailable):
                await gs.generation("AT", START, END)
            assert len(gs.history("generation", START, END, zone="AT")) == 1
    finally:
        store.close()

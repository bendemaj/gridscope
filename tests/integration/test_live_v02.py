"""Opt in: RUN_LIVE_V02_TESTS=1 pytest tests/integration/test_live_v02.py -m live."""

import os

import pytest

from gridscope import GridScope, resample
from gridscope.normalization.time import utc

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_V02_TESTS") != "1", reason="Live v0.2 coverage checks are opt-in."
    ),
]


@pytest.mark.parametrize("provider", ["entsoe", "smard"])
@pytest.mark.parametrize("zone", ["DE_LU", "FR", "BE", "NL", "PL", "DK1", "NO2", "SE4", "CZ", "CH"])
async def test_neighbor_prices(provider, zone):
    async with GridScope(provider) as gs:
        series = await gs.prices(zone, "2026-09-01", "2026-09-02")
        assert series.data and all(p.value is not None for p in series.data)
        assert all(p.zone == zone and p.unit == "EUR/MWh" for p in series.data)


async def test_smard_dk2_prices():
    async with GridScope("smard") as gs:
        assert len((await gs.prices("DK2", "2026-09-01", "2026-09-02")).data) == 96


@pytest.mark.parametrize("provider", ["entsoe", "smard"])
@pytest.mark.parametrize(
    "start,end,hours",
    [
        ("2026-03-29T00:00:00+01:00", "2026-03-30T00:00:00+02:00", 23),
        ("2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+01:00", 25),
    ],
)
async def test_german_dst_coverage_and_energy(provider, start, end, hours):
    async with GridScope(provider) as gs:
        load = await gs.load("DE", start, end)
        assert len(load.data) == hours * 4
        hourly = resample(load, "PT60M")
        assert all(p.value is not None for p in hourly.data)
        assert sum(p.value * 0.25 for p in load.data) == pytest.approx(
            sum(p.value for p in hourly.data)
        )
        generation = await gs.generation("DE", start, end)
        assert generation.data
        assert all(utc(start) <= p.timestamp < utc(end) for p in generation.data)


@pytest.mark.parametrize("provider", ["entsoe", "smard"])
@pytest.mark.parametrize(
    "origin,target", [("DE_LU", "AT"), ("AT", "DE_LU"), ("DE_LU", "FR"), ("FR", "DE_LU")]
)
async def test_directional_flows(provider, origin, target):
    async with GridScope(provider) as gs:
        result = await gs.flows(origin, target, "2026-09-01", "2026-09-02")
        assert len(result.data) == 96
        assert all(p.value is not None and p.value >= 0 for p in result.data)

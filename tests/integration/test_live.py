"""Manual credentialed checks: RUN_LIVE_ENTSOE_TESTS=1 uv run pytest -m live."""

import os

import pytest

from gridscope import GridScope

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_ENTSOE_TESTS") != "1", reason="Live ENTSO-E verification is opt-in."
    ),
]


async def test_live_austria():
    start = os.getenv("GRIDSCOPE_LIVE_START", "2026-09-01")
    end = os.getenv("GRIDSCOPE_LIVE_END", "2026-09-02")
    async with GridScope() as gs:
        assert (await gs.prices("AT", start, end)).data
        assert (await gs.load("AT", start, end)).data
        assert (await gs.generation("AT", start, end)).data
        assert (await gs.flows("DE_LU", "AT", start, end)).data

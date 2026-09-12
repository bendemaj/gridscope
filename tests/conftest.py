from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from gridscope import GridScope
from gridscope.config import Settings
from gridscope.models import DataQuality, GenerationPoint, GenerationType, PricePoint
from gridscope.providers.entsoe.client import ENTSOEProvider

FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2026, 9, 1, tzinfo=UTC)
END = START + timedelta(hours=1)


def point(cls=PricePoint, value=1.0, i=0, **kwargs):
    return cls(
        timestamp=START + timedelta(minutes=15 * i),
        zone="AT",
        value=value,
        resolution="PT15M",
        source="fixture",
        source_dataset="test",
        retrieved_at=START,
        quality=DataQuality.MISSING if value is None else DataQuality.OBSERVED,
        **kwargs,
    )


def generation(values=(100, 100, 800), i=0):
    return [
        point(GenerationPoint, v, i, generation_type=t)
        for t, v in zip(
            [GenerationType.SOLAR, GenerationType.WIND_ONSHORE, GenerationType.GAS],
            values,
            strict=True,
        )
    ]


def mock_response(request: httpx.Request) -> httpx.Response:
    kind = {"A44": "prices", "A65": "load", "A75": "generation", "A11": "flows"}[
        request.url.params["documentType"]
    ]
    xml = (FIXTURES / f"{kind}.xml").read_bytes()
    if kind == "flows" and request.url.params["out_Domain"] == "10YAT-APG------L":
        xml = (
            xml.replace(b"10YAT-APG------L", b"TEMP")
            .replace(b"10Y1001A1001A82H", b"10YAT-APG------L")
            .replace(b"TEMP", b"10Y1001A1001A82H")
        )
        for value in (500, 600, 700, 800):
            xml = xml.replace(f">{value}<".encode(), b">100<")
    return httpx.Response(200, content=xml)


@pytest.fixture
async def gs():
    settings = Settings(entsoe_api_token="test-token", _env_file=None)
    async with GridScope(
        ENTSOEProvider(settings, transport=httpx.MockTransport(mock_response))
    ) as client:
        yield client

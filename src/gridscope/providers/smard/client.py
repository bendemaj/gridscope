"""SMARD's public chart interface; no credential or provider fallback required."""

import asyncio
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, ValidationError

from gridscope.config import Settings
from gridscope.errors import (
    MalformedResponse,
    NoData,
    ProviderRateLimit,
    ProviderUnavailable,
    UnsupportedDataset,
)
from gridscope.models import (
    DataQuality,
    FlowPoint,
    GenerationPoint,
    LoadPoint,
    PricePoint,
    Series,
    SeriesMeta,
    TimeResolution,
)
from gridscope.models.common import Point
from gridscope.providers.smard.mappings import (
    ATTRIBUTION,
    FLOW_FILTERS,
    GENERATION_FILTERS,
    PRICE_FILTERS,
)

BASE_URL = "https://www.smard.de/app/chart_data"
P = TypeVar("P", bound=Point)


class Index(BaseModel):
    timestamps: list[StrictInt]


class Payload(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    series: list[tuple[StrictInt, StrictFloat | None]]
    meta_data: dict[str, object]


class SMARDProvider:
    name = "SMARD"

    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings or Settings()
        self.http = httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            transport=transport,
            headers={"User-Agent": "GridScope/0.2 (+https://github.com/bendemaj/gridscope)"},
        )
        self._cache: OrderedDict[str, tuple[float, bytes, datetime]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self.http.aclose()

    def clear_cache(self) -> None:
        self._cache.clear()

    async def _request(self, path: str) -> tuple[bytes, datetime]:
        cached = self._cache.get(path)
        if cached and time.monotonic() - cached[0] < self.settings.cache_ttl_seconds:
            self._cache.move_to_end(path)
            return cached[1], cached[2]
        for attempt in range(self.settings.max_retries + 1):
            async with self._lock:
                await asyncio.sleep(max(0, 0.2 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
            delay = float(2**attempt)
            try:
                response = await self.http.get(f"{BASE_URL}/{path}")
            except httpx.HTTPError:
                if attempt == self.settings.max_retries:
                    raise ProviderUnavailable("SMARD request failed.") from None
            else:
                if response.status_code == 404:
                    raise NoData("SMARD has no publication for this series or period.")
                if response.status_code in {429, 500, 502, 503, 504}:
                    if response.status_code == 429:
                        try:
                            delay = max(delay, float(response.headers.get("Retry-After", delay)))
                        except ValueError:
                            raise ProviderRateLimit("SMARD requested a retry later.") from None
                        if not 0 <= delay <= 30 or attempt == self.settings.max_retries:
                            raise ProviderRateLimit("SMARD rate limit reached; retry later.")
                    elif attempt == self.settings.max_retries:
                        raise ProviderUnavailable("SMARD is temporarily unavailable.")
                elif response.is_success:
                    if len(response.content) > 30_000_000:
                        raise MalformedResponse("SMARD response exceeds the size limit.")
                    retrieved = datetime.now(UTC)
                    if self.settings.cache_ttl_seconds:
                        self._cache[path] = (time.monotonic(), response.content, retrieved)
                        self._cache.move_to_end(path)
                        while len(self._cache) > 128:
                            self._cache.popitem(last=False)
                    return response.content, retrieved
                else:
                    raise ProviderUnavailable("SMARD rejected the request.")
            await asyncio.sleep(delay)
        raise ProviderUnavailable("SMARD request failed.")

    async def _fetch(
        self,
        model: type[P],
        dataset: str,
        filter_id: int,
        region: str,
        start: datetime,
        end: datetime,
        **scope: object,
    ) -> Series[P]:
        prefix = f"{filter_id}/{region}"
        raw, _ = await self._request(f"{prefix}/index_quarterhour.json")
        try:
            anchors = Index.model_validate_json(raw).timestamps
            if anchors != sorted(set(anchors)) or any(t <= 0 or t % 1000 for t in anchors):
                raise ValueError
        except (ValidationError, ValueError):
            raise MalformedResponse("Invalid SMARD publication index.") from None
        # Weekly anchors are supplied by SMARD and vary with DST. Do not add 168 hours.
        start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
        selected = [
            anchor
            for i, anchor in enumerate(anchors)
            if anchor < end_ms and (i + 1 == len(anchors) or anchors[i + 1] > start_ms)
        ]
        points: dict[datetime, P] = {}
        warnings: list[str] = []
        for anchor in selected:
            path = f"{prefix}/{filter_id}_{region}_quarterhour_{anchor}.json"
            try:
                raw, retrieved = await self._request(path)
            except NoData:
                warnings.append("A SMARD publication chunk is unavailable; coverage is incomplete.")
                continue
            try:
                payload = Payload.model_validate_json(raw)
                for stamp, value in payload.series:
                    if stamp <= 0 or stamp % 900_000:
                        raise ValueError
                    timestamp = datetime.fromtimestamp(stamp / 1000, UTC)
                    if not start <= timestamp < end:
                        continue
                    notes: tuple[str, ...] = (
                        ("SMARD MWh per 15 minutes converted to average MW (x4).",)
                        if dataset != "prices"
                        else (
                            "SMARD chart cadence is 15 minutes; historical hourly products "
                            "may be repeated by the provider.",
                        )
                    )
                    if dataset == "flows" and scope.get("to_zone") == region.replace("-", "_"):
                        # SMARD chart imports are negative; our named direction is positive.
                        value = -value if value is not None else None
                        notes += ("SMARD import sign reversed to positive named-direction flow.",)
                    point = model.model_validate(
                        dict(
                            timestamp=timestamp,
                            value=value if dataset == "prices" or value is None else value * 4,
                            resolution=TimeResolution.QUARTER_HOUR,
                            source="SMARD",
                            source_dataset=dataset,
                            retrieved_at=retrieved,
                            quality=DataQuality.MISSING if value is None else DataQuality.OBSERVED,
                            source_document=f"{BASE_URL}/{path}",
                            source_revision=str(payload.meta_data.get("created", "unknown")),
                            source_series=f"{filter_id}/{region}",
                            notes=notes,
                            **scope,
                        )
                    )
                    if timestamp in points and points[timestamp] != point:
                        raise ValueError
                    points[timestamp] = point
            except (ValidationError, ValueError, OverflowError, OSError):
                raise MalformedResponse("Invalid or overlapping SMARD observations.") from None
        if not points:
            raise NoData("SMARD returned no observations in the requested interval.")
        ordered = sorted(points.values(), key=lambda p: p.timestamp)
        if (
            ordered[0].timestamp > start
            or ordered[-1].timestamp + timedelta(minutes=15) < end
            or any(
                b.timestamp - a.timestamp != timedelta(minutes=15)
                for a, b in zip(ordered, ordered[1:], strict=False)
            )
        ):
            warnings.append("SMARD coverage has gaps; absent observations are not filled.")
        if any(p.value is None for p in ordered):
            warnings.append("SMARD publishes null observations in this interval.")
        if dataset == "prices":
            warnings.append("Chart cadence may differ from the original auction interval.")
        return Series(
            data=ordered,
            meta=SeriesMeta(
                source="SMARD",
                dataset=dataset,
                start=start,
                end=end,
                zone=str(scope["zone"]) if "zone" in scope else None,
                from_zone=str(scope["from_zone"]) if "from_zone" in scope else None,
                to_zone=str(scope["to_zone"]) if "to_zone" in scope else None,
                warnings=warnings,
                attribution=ATTRIBUTION,
            ),
        )

    async def get_prices(self, zone: str, start: datetime, end: datetime) -> Series[PricePoint]:
        if zone not in PRICE_FILTERS:
            raise UnsupportedDataset(
                "SMARD prices require a supported bidding zone; use DE_LU for Germany."
            )
        return await self._fetch(
            PricePoint, "prices", PRICE_FILTERS[zone], "DE", start, end, zone=zone
        )

    async def get_load(self, zone: str, start: datetime, end: datetime) -> Series[LoadPoint]:
        if zone not in {"DE", "DE_LU", "AT", "LU"}:
            raise UnsupportedDataset("SMARD load supports DE, DE_LU, AT and LU.")
        return await self._fetch(
            LoadPoint, "load", 410, zone.replace("_", "-"), start, end, zone=zone
        )

    async def get_generation(
        self, zone: str, start: datetime, end: datetime
    ) -> Series[GenerationPoint]:
        if zone not in {"DE", "DE_LU", "AT", "LU"}:
            raise UnsupportedDataset("SMARD generation supports DE, DE_LU, AT and LU.")
        points: list[GenerationPoint] = []
        warnings = ["Reported generation types only; missing technologies are not assumed zero."]
        for filter_id, (kind, zones) in GENERATION_FILTERS.items():
            if zone not in zones:
                continue
            try:
                series = await self._fetch(
                    GenerationPoint,
                    "generation",
                    filter_id,
                    zone.replace("_", "-"),
                    start,
                    end,
                    zone=zone,
                    generation_type=kind,
                    production_code=str(filter_id),
                )
            except NoData:
                warnings.append(f"SMARD {kind} is unavailable for this interval.")
                continue
            points.extend(series.data)
            warnings.extend(series.meta.warnings)
        if not points:
            raise NoData("SMARD returned no generation for this interval.")
        return Series(
            data=sorted(points, key=lambda p: (p.timestamp, p.generation_type)),
            meta=SeriesMeta(
                source="SMARD",
                dataset="generation",
                zone=zone,
                start=start,
                end=end,
                warnings=list(dict.fromkeys(warnings)),
                attribution=ATTRIBUTION,
            ),
        )

    async def get_flows(
        self, from_zone: str, to_zone: str, start: datetime, end: datetime
    ) -> Series[FlowPoint]:
        if (from_zone, to_zone) not in FLOW_FILTERS:
            raise UnsupportedDataset("This directional physical border is not mapped for SMARD.")
        filter_id, region = FLOW_FILTERS[from_zone, to_zone]
        return await self._fetch(
            FlowPoint, "flows", filter_id, region, start, end, from_zone=from_zone, to_zone=to_zone
        )

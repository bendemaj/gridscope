import asyncio
import logging
import time
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import TypeVar

import httpx

from gridscope.config import Settings
from gridscope.errors import (
    MalformedResponse,
    MissingToken,
    NoData,
    ProviderAuthenticationError,
    ProviderRateLimit,
    ProviderRejected,
    ProviderUnavailable,
)
from gridscope.models import FlowPoint, GenerationPoint, LoadPoint, PricePoint, Series, SeriesMeta
from gridscope.models.common import Point
from gridscope.normalization.time import resolution_delta
from gridscope.providers.entsoe.mappings import AREA_CODES
from gridscope.providers.entsoe.parser import check_acknowledgement, parse, read_xml, series_count

P = TypeVar("P", bound=Point)
logger = logging.getLogger("gridscope.provider")
ENDPOINT = "https://web-api.tp.entsoe.eu/api"


class ENTSOEProvider:
    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None
    ):
        self.settings = settings or Settings()
        self._http = httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            transport=transport,
            headers={"User-Agent": "GridScope/0.1 (github.com/bendemaj/gridscope)"},
        )
        self._cache: OrderedDict[tuple[tuple[str, str], ...], tuple[float, bytes, datetime]] = (
            OrderedDict()
        )
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def aclose(self) -> None:
        await self._http.aclose()
        self._cache.clear()

    def clear_cache(self) -> None:
        self._cache.clear()

    async def _request(self, params: dict[str, str]) -> tuple[bytes, datetime]:
        token = self.settings.entsoe_api_token
        if token is None or not token.get_secret_value().strip():
            raise MissingToken(
                "Set ENTSOE_API_TOKEN in your environment or .env after obtaining API access."
            )
        key = tuple(sorted(params.items()))
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < self.settings.cache_ttl_seconds:
            self._cache.move_to_end(key)
            return cached[1], cached[2]
        for attempt in range(self.settings.max_retries + 1):
            response: httpx.Response | None = None
            async with self._lock:
                await asyncio.sleep(max(0.0, 0.2 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
            try:
                # Header authentication avoids placing the credential in HTTPX URL logs.
                response = await self._http.get(
                    ENDPOINT, params=params, headers={"SECURITY_TOKEN": token.get_secret_value()}
                )
            except httpx.TransportError:
                if attempt == self.settings.max_retries:
                    raise ProviderUnavailable("ENTSO-E connection failed or timed out.") from None
            if response is not None:
                status = response.status_code
                if status in {401, 403}:
                    raise ProviderAuthenticationError("ENTSO-E rejected the API token.")
                if status not in {429, 500, 502, 503, 504}:
                    if len(response.content) > 20_000_000:
                        raise MalformedResponse("Provider response exceeds the v0.1 size limit.")
                    root = read_xml(response.content)
                    check_acknowledgement(root)
                    if status != 200:
                        raise ProviderRejected("ENTSO-E rejected the request.")
                    retrieved = datetime.now(UTC)
                    if self.settings.cache_ttl_seconds > 0:
                        self._cache[key] = (time.monotonic(), response.content, retrieved)
                        self._cache.move_to_end(key)
                        while len(self._cache) > 128:
                            self._cache.popitem(last=False)
                    return response.content, retrieved
                if attempt == self.settings.max_retries:
                    if status == 429:
                        raise ProviderRateLimit("ENTSO-E rate limit reached; try again later.")
                    raise ProviderUnavailable("ENTSO-E is temporarily unavailable.")
            delay = float(2**attempt)
            if response is not None and (retry := response.headers.get("Retry-After")):
                try:
                    delay = max(delay, float(retry))
                except ValueError:
                    try:
                        delay = max(
                            delay,
                            (parsedate_to_datetime(retry) - datetime.now(UTC)).total_seconds(),
                        )
                    except (ValueError, TypeError, OverflowError):
                        pass
            if delay > 30:
                raise ProviderRateLimit("Provider requested an extended cooldown; retry later.")
            logger.warning(
                "provider_retry",
                extra={
                    "attempt": attempt + 1,
                    "status": response.status_code if response is not None else None,
                },
            )
            await asyncio.sleep(delay)
        raise ProviderUnavailable("ENTSO-E request failed.")

    async def _fetch(
        self,
        model: type[P],
        dataset: str,
        start: datetime,
        end: datetime,
        params: dict[str, str],
        *,
        zone: str | None = None,
        from_zone: str | None = None,
        to_zone: str | None = None,
    ) -> Series[P]:
        data: list[P] = []
        warnings: list[str] = []
        cursor = start
        while cursor < end:
            stop = min(cursor + timedelta(days=31), end)
            query = dict(
                params,
                periodStart=cursor.strftime("%Y%m%d%H%M"),
                periodEnd=stop.strftime("%Y%m%d%H%M"),
            )
            offset = 0
            while True:
                if dataset == "prices":
                    query["offset"] = str(offset)
                try:
                    xml, retrieved = await self._request(query)
                except NoData:
                    if offset == 0:
                        warnings.append(f"No data for {cursor.isoformat()} to {stop.isoformat()}.")
                    break
                try:
                    page = parse(
                        xml,
                        model,
                        start=cursor,
                        end=stop,
                        retrieved_at=retrieved,
                        dataset=dataset,
                        zone=zone,
                        from_zone=from_zone,
                        to_zone=to_zone,
                    )
                    data.extend(page)
                except NoData:
                    pass  # Whole-day price pages can fall outside the requested interval.
                if dataset != "prices" or series_count(xml) < 100:
                    break
                offset += 100
                if offset > 4900:
                    raise MalformedResponse("Price pagination exceeded the supported limit.")
            cursor = stop
        if not data:
            raise NoData("ENTSO-E has no matching data for this interval.")
        data.sort(key=lambda p: p.timestamp)
        streams: dict[str, list[P]] = {}
        for point in data:
            identity = (
                point.production_code or point.generation_type.value
                if isinstance(point, GenerationPoint)
                else "all"
            )
            streams.setdefault(identity, []).append(point)
        for name, points in streams.items():
            covered = start
            for point in points:
                if point.timestamp < covered:
                    raise MalformedResponse("Overlapping or unaligned intervals in provider data.")
                if point.timestamp > covered or point.value is None:
                    warnings.append(f"Missing intervals in {name}; values were not filled.")
                covered = point.timestamp + resolution_delta(point.resolution)
            if covered < end:
                warnings.append(f"Incomplete interval coverage in {name}.")
        if dataset == "generation":
            warnings.append(
                "Generation covers reported production types only; "
                "absent types are not assumed zero."
            )
        return Series(
            data=data,
            meta=SeriesMeta(
                source="ENTSOE",
                dataset=dataset,
                start=start,
                end=end,
                zone=zone,
                from_zone=from_zone,
                to_zone=to_zone,
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    async def get_prices(self, zone: str, start: datetime, end: datetime) -> Series[PricePoint]:
        return await self._fetch(
            PricePoint,
            "prices",
            start,
            end,
            {
                "documentType": "A44",
                "in_Domain": AREA_CODES[zone],
                "out_Domain": AREA_CODES[zone],
                "contract_MarketAgreement.type": "A01",
                **(
                    {"classificationSequence_AttributeInstanceComponent.position": "1"}
                    if zone in {"AT", "DE_LU"}
                    else {}
                ),
            },
            zone=zone,
        )

    async def get_load(self, zone: str, start: datetime, end: datetime) -> Series[LoadPoint]:
        return await self._fetch(
            LoadPoint,
            "load",
            start,
            end,
            {
                "documentType": "A65",
                "processType": "A16",
                "outBiddingZone_Domain": AREA_CODES[zone],
            },
            zone=zone,
        )

    async def get_generation(
        self, zone: str, start: datetime, end: datetime
    ) -> Series[GenerationPoint]:
        return await self._fetch(
            GenerationPoint,
            "generation",
            start,
            end,
            {"documentType": "A75", "processType": "A16", "in_Domain": AREA_CODES[zone]},
            zone=zone,
        )

    async def get_flows(
        self, from_zone: str, to_zone: str, start: datetime, end: datetime
    ) -> Series[FlowPoint]:
        return await self._fetch(
            FlowPoint,
            "flows",
            start,
            end,
            {
                "documentType": "A11",
                "out_Domain": AREA_CODES[from_zone],
                "in_Domain": AREA_CODES[to_zone],
            },
            from_zone=from_zone,
            to_zone=to_zone,
        )

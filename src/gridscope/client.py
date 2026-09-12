from collections.abc import Sequence
from types import TracebackType
from typing import TypeVar

from pydantic import BaseModel

from gridscope.config import Settings
from gridscope.errors import InvalidQuery, NoData
from gridscope.intelligence import metrics
from gridscope.models import (
    AnomalyPoint,
    FlowPoint,
    GenerationPoint,
    GenerationType,
    LoadPoint,
    MetricPoint,
    PricePoint,
    Series,
    SeriesMeta,
)
from gridscope.normalization.time import DateInput, date_range
from gridscope.normalization.zones import zone_code
from gridscope.providers.base import GridDataProvider
from gridscope.providers.entsoe.client import ENTSOEProvider

T = TypeVar("T", bound=BaseModel)


class GridScope:
    """Async service shared by Python, REST, and future MCP adapters."""

    def __init__(
        self, provider: GridDataProvider | None = None, *, settings: Settings | None = None
    ):
        self.provider = provider or ENTSOEProvider(settings)

    async def __aenter__(self) -> "GridScope":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.provider.aclose()

    async def prices(self, zone: str, start: DateInput, end: DateInput) -> Series[PricePoint]:
        return await self.provider.get_prices(zone_code(zone), *date_range(start, end))

    async def load(self, zone: str, start: DateInput, end: DateInput) -> Series[LoadPoint]:
        return await self.provider.get_load(zone_code(zone), *date_range(start, end))

    async def generation(
        self,
        zone: str,
        start: DateInput,
        end: DateInput,
        generation_type: GenerationType | None = None,
    ) -> Series[GenerationPoint]:
        series = await self.provider.get_generation(zone_code(zone), *date_range(start, end))
        if generation_type is not None:
            return Series(
                data=[p for p in series.data if p.generation_type == generation_type],
                meta=series.meta.model_copy(deep=True),
            )
        return series

    async def flows(
        self, from_zone: str, to_zone: str, start: DateInput, end: DateInput
    ) -> Series[FlowPoint]:
        a, b = zone_code(from_zone), zone_code(to_zone)
        if a == b:
            raise InvalidQuery("Flow endpoints must differ.")
        return await self.provider.get_flows(a, b, *date_range(start, end))

    @staticmethod
    def _derived(data: list[T], name: str, *inputs: SeriesMeta) -> Series[T]:
        meta = inputs[0].model_copy(deep=True)
        meta.dataset = name
        meta.source = ",".join(sorted({m.source for m in inputs}))
        meta.warnings = list(dict.fromkeys(w for m in inputs for w in m.warnings))
        meta.attribution = "Derived by GridScope. " + inputs[0].attribution
        return Series(data=data, meta=meta)

    async def renewable_share(
        self, zone: str, start: DateInput, end: DateInput
    ) -> Series[MetricPoint]:
        generation = await self.generation(zone, start, end)
        return self._derived(
            metrics.renewable_share(generation.data), "renewable_share", generation.meta
        )

    async def residual_load(
        self, zone: str, start: DateInput, end: DateInput
    ) -> Series[MetricPoint]:
        load = await self.load(zone, start, end)
        generation = await self.generation(zone, start, end)
        return self._derived(
            metrics.residual_load(load.data, generation.data),
            "residual_load",
            load.meta,
            generation.meta,
        )

    async def net_imports(
        self, zone: str, start: DateInput, end: DateInput, *, neighbors: Sequence[str]
    ) -> Series[MetricPoint]:
        zone = zone_code(zone)
        neighbors = [zone_code(n) for n in neighbors]
        if not neighbors or len(set(neighbors)) != len(neighbors) or zone in neighbors:
            raise InvalidQuery("Specify distinct neighbors excluding the target zone.")
        a, b = date_range(start, end)
        points: list[FlowPoint] = []
        warnings = [f"Selected borders only: {', '.join(neighbors)}; not a national total."]
        for neighbor in neighbors:
            for origin, target in [(neighbor, zone), (zone, neighbor)]:
                try:
                    series = await self.flows(origin, target, a, b)
                    points.extend(series.data)
                    warnings.extend(series.meta.warnings)
                except NoData:
                    warnings.append(f"Missing {origin} to {target}; affected metrics are null.")
        if not points:
            raise NoData("No flow data for the selected borders.")
        return Series(
            data=metrics.net_imports(points, zone, neighbors),
            meta=SeriesMeta(
                source=",".join(sorted({p.source for p in points})),
                dataset="net_imports",
                zone=zone,
                start=a,
                end=b,
                warnings=list(dict.fromkeys(warnings)),
            ),
        )

    async def price_spread(
        self, zone: str, start: DateInput, end: DateInput, *, timezone: str = "Europe/Vienna"
    ) -> Series[MetricPoint]:
        prices = await self.prices(zone, start, end)
        return self._derived(
            metrics.price_spread(prices.data, timezone), "price_spread", prices.meta
        )

    async def price_volatility(
        self, zone: str, start: DateInput, end: DateInput, *, window: int = 24
    ) -> Series[MetricPoint]:
        if window < 2:
            raise InvalidQuery("Window must be at least 2 observations.")
        prices = await self.prices(zone, start, end)
        return self._derived(
            metrics.price_volatility(prices.data, window), "price_volatility", prices.meta
        )

    async def detect_anomalies(
        self, zone: str, start: DateInput, end: DateInput, *, window: int = 24, threshold: float = 3
    ) -> Series[AnomalyPoint]:
        if window < 2 or not 0 < threshold < float("inf"):
            raise InvalidQuery("Require window >= 2 and a finite positive threshold.")
        prices = await self.prices(zone, start, end)
        return self._derived(
            metrics.detect_anomalies(prices.data, window, threshold), "anomalies", prices.meta
        )

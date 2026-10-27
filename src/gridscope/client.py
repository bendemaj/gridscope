import asyncio
from collections.abc import Sequence
from copy import copy
from types import TracebackType
from typing import Literal, TypeVar

from pydantic import BaseModel

from gridscope.config import Settings
from gridscope.errors import InvalidQuery, NoData, StorageUnavailable
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
    TimeResolution,
)
from gridscope.models.common import Point
from gridscope.normalization.resampling import resample
from gridscope.normalization.time import DateInput, date_range, utc
from gridscope.normalization.zones import zone_code
from gridscope.providers.base import GridDataProvider
from gridscope.providers.entsoe.client import ENTSOEProvider
from gridscope.providers.smard.client import SMARDProvider
from gridscope.storage import MODELS, Snapshot, SQLiteStore

T = TypeVar("T", bound=BaseModel)
P = TypeVar("P", bound=Point)


class GridScope:
    """Async service shared by Python, REST, and future MCP adapters."""

    def __init__(
        self,
        provider: GridDataProvider | Literal["entsoe", "smard"] | None = None,
        *,
        settings: Settings | None = None,
        store: SQLiteStore | None = None,
        mode: Literal["live", "stored"] = "live",
        as_of: DateInput | None = None,
        resolution: TimeResolution | None = None,
    ) -> None:
        self.mode, self.as_of, self.resolution = mode, as_of, resolution
        self._validate_options()
        settings = settings or Settings()
        selected = settings.provider if provider is None else provider
        if isinstance(selected, str):
            if selected not in {"entsoe", "smard"}:
                raise InvalidQuery("Provider must be entsoe or smard.")
            self.provider: GridDataProvider = (
                SMARDProvider(settings) if selected == "smard" else ENTSOEProvider(settings)
            )
        else:
            self.provider = selected
        self.store = store or (
            SQLiteStore(settings.storage_path) if settings.storage_path else None
        )
        self._owns_store = store is None
        self._owns_provider = True

    def _validate_options(self) -> None:
        if self.mode not in {"live", "stored"}:
            raise InvalidQuery("Mode must be live or stored.")
        if self.as_of is not None and self.mode != "stored":
            raise InvalidQuery("as_of requires stored mode.")
        if self.as_of is not None:
            self.as_of = utc(self.as_of)

    def with_options(
        self,
        *,
        mode: Literal["live", "stored"] = "live",
        as_of: DateInput | None = None,
        resolution: TimeResolution | None = None,
    ) -> "GridScope":
        """A non-owning query view sharing this client's transport and history store."""
        view = copy(self)
        view.mode, view.as_of, view.resolution = mode, as_of, resolution
        view._owns_store = view._owns_provider = False
        view._validate_options()
        return view

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
        try:
            if self._owns_provider:
                await self.provider.aclose()
        finally:
            if self.store is not None and self._owns_store:
                self.store.close()

    async def _query(
        self,
        model: type[P],
        dataset: str,
        start: DateInput,
        end: DateInput,
        *,
        zone: str | None = None,
        from_zone: str | None = None,
        to_zone: str | None = None,
        resolution: TimeResolution | None = None,
    ) -> Series[P]:
        a, b = date_range(start, end)
        if self.mode == "stored":
            if self.store is None:
                raise StorageUnavailable(
                    "Configure GRIDSCOPE_STORAGE_PATH or supply a SQLiteStore."
                )
            series = await asyncio.to_thread(
                self.store.read,
                model,
                getattr(self.provider, "name", "ENTSOE"),
                dataset,
                a,
                b,
                zone=zone,
                from_zone=from_zone,
                to_zone=to_zone,
                as_of=self.as_of,
            )
        else:
            raw: (
                Series[PricePoint] | Series[LoadPoint] | Series[GenerationPoint] | Series[FlowPoint]
            )
            if dataset == "flows":
                assert from_zone is not None and to_zone is not None
                raw = await self.provider.get_flows(from_zone, to_zone, a, b)
            else:
                assert zone is not None
                if dataset == "prices":
                    raw = await self.provider.get_prices(zone, a, b)
                elif dataset == "load":
                    raw = await self.provider.get_load(zone, a, b)
                else:
                    raw = await self.provider.get_generation(zone, a, b)
            series = Series(
                data=[model.model_validate(p.model_dump()) for p in raw.data],
                meta=raw.meta.model_copy(deep=True),
            )
            if self.store is not None:
                await asyncio.to_thread(self.store.save, series)
        target = resolution or self.resolution
        return resample(series, target) if target else series

    def history(
        self,
        dataset: str,
        start: DateInput,
        end: DateInput,
        *,
        zone: str | None = None,
        from_zone: str | None = None,
        to_zone: str | None = None,
        as_of: DateInput | None = None,
        limit: int = 100,
    ) -> list[Snapshot]:
        if dataset not in MODELS:
            raise InvalidQuery("History supports prices, load, generation and flows.")
        if dataset == "flows":
            if zone is not None or not from_zone or not to_zone:
                raise InvalidQuery("Flow history requires from_zone and to_zone only.")
            from_zone, to_zone = zone_code(from_zone), zone_code(to_zone)
            if from_zone == to_zone:
                raise InvalidQuery("Flow endpoints must differ.")
        else:
            if not zone or from_zone is not None or to_zone is not None:
                raise InvalidQuery("Dataset history requires zone only.")
            zone = zone_code(zone)
        if self.store is None:
            raise StorageUnavailable("Configure GRIDSCOPE_STORAGE_PATH or supply a SQLiteStore.")
        return self.store.history(
            getattr(self.provider, "name", "ENTSOE"),
            dataset,
            start,
            end,
            zone=zone,
            from_zone=from_zone,
            to_zone=to_zone,
            as_of=as_of or self.as_of,
            limit=limit,
        )

    async def prices(
        self,
        zone: str,
        start: DateInput,
        end: DateInput,
        *,
        resolution: TimeResolution | None = None,
    ) -> Series[PricePoint]:
        return await self._query(
            PricePoint, "prices", start, end, zone=zone_code(zone), resolution=resolution
        )

    async def load(
        self,
        zone: str,
        start: DateInput,
        end: DateInput,
        *,
        resolution: TimeResolution | None = None,
    ) -> Series[LoadPoint]:
        return await self._query(
            LoadPoint, "load", start, end, zone=zone_code(zone), resolution=resolution
        )

    async def generation(
        self,
        zone: str,
        start: DateInput,
        end: DateInput,
        generation_type: GenerationType | None = None,
        *,
        resolution: TimeResolution | None = None,
    ) -> Series[GenerationPoint]:
        series = await self._query(
            GenerationPoint, "generation", start, end, zone=zone_code(zone), resolution=resolution
        )
        if generation_type is not None:
            return Series(
                data=[p for p in series.data if p.generation_type == generation_type],
                meta=series.meta.model_copy(deep=True),
            )
        return series

    async def flows(
        self,
        from_zone: str,
        to_zone: str,
        start: DateInput,
        end: DateInput,
        *,
        resolution: TimeResolution | None = None,
    ) -> Series[FlowPoint]:
        a, b = zone_code(from_zone), zone_code(to_zone)
        if a == b:
            raise InvalidQuery("Flow endpoints must differ.")
        return await self._query(
            FlowPoint, "flows", start, end, from_zone=a, to_zone=b, resolution=resolution
        )

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
        attributions: list[str] = []
        warnings = [f"Selected borders only: {', '.join(neighbors)}; not a national total."]
        for neighbor in neighbors:
            for origin, target in [(neighbor, zone), (zone, neighbor)]:
                try:
                    series = await self.flows(origin, target, a, b)
                    points.extend(series.data)
                    warnings.extend(series.meta.warnings)
                    attributions.append(series.meta.attribution)
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
                attribution="Derived by GridScope. " + " ".join(dict.fromkeys(attributions)),
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

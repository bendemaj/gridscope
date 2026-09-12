from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from gridscope import GridScope, __version__
from gridscope.errors import GridScopeError
from gridscope.logging import configure_logging
from gridscope.models import (
    AnomalyPoint,
    FlowPoint,
    GenerationPoint,
    GenerationType,
    LoadPoint,
    MetricPoint,
    PricePoint,
    Series,
    Zone,
)
from gridscope.normalization.zones import ZONES
from gridscope.registry.sources import SOURCES, SourceDataset


async def get_client(request: Request) -> GridScope:
    return request.app.state.gridscope  # type: ignore[no-any-return]


Client = Annotated[GridScope, Depends(get_client)]
Window = Annotated[int, Query(ge=2, le=10000)]


def create_app(client: GridScope | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.gridscope = client or GridScope()
        yield
        if client is None:
            await app.state.gridscope.aclose()

    app = FastAPI(
        title="GridScope",
        version=__version__,
        lifespan=lifespan,
        description="Austria-first normalized electricity data. Intervals are [start, end) in UTC.",
    )

    @app.exception_handler(GridScopeError)
    async def handle_error(request: Request, exc: GridScopeError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content={"error": {"code": exc.code, "message": str(exc)}}
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/v1/zones")
    async def zones() -> dict[str, list[Zone]]:
        return {"data": list(ZONES.values())}

    @app.get("/v1/sources")
    async def sources() -> dict[str, list[SourceDataset]]:
        return {"data": SOURCES}

    @app.get("/v1/prices")
    async def prices(client: Client, start: str, end: str, zone: str = "AT") -> Series[PricePoint]:
        return await client.prices(zone, start, end)

    @app.get("/v1/load")
    async def load(client: Client, start: str, end: str, zone: str = "AT") -> Series[LoadPoint]:
        return await client.load(zone, start, end)

    @app.get("/v1/generation")
    async def generation(
        client: Client,
        start: str,
        end: str,
        zone: str = "AT",
        generation_type: GenerationType | None = None,
    ) -> Series[GenerationPoint]:
        return await client.generation(zone, start, end, generation_type)

    @app.get("/v1/flows")
    async def flows(
        client: Client, start: str, end: str, from_zone: str, to_zone: str
    ) -> Series[FlowPoint]:
        return await client.flows(from_zone, to_zone, start, end)

    @app.get("/v1/intelligence/renewable-share")
    async def renewable_share(
        client: Client, start: str, end: str, zone: str = "AT"
    ) -> Series[MetricPoint]:
        return await client.renewable_share(zone, start, end)

    @app.get("/v1/intelligence/residual-load")
    async def residual_load(
        client: Client, start: str, end: str, zone: str = "AT"
    ) -> Series[MetricPoint]:
        return await client.residual_load(zone, start, end)

    @app.get("/v1/intelligence/net-imports")
    async def net_imports(
        client: Client,
        start: str,
        end: str,
        neighbors: Annotated[list[str], Query(min_length=1)],
        zone: str = "AT",
    ) -> Series[MetricPoint]:
        return await client.net_imports(zone, start, end, neighbors=neighbors)

    @app.get("/v1/intelligence/price-volatility")
    async def price_volatility(
        client: Client, start: str, end: str, zone: str = "AT", window: Window = 24
    ) -> Series[MetricPoint]:
        return await client.price_volatility(zone, start, end, window=window)

    @app.get("/v1/intelligence/price-spread")
    async def price_spread(
        client: Client, start: str, end: str, zone: str = "AT", timezone: str = "Europe/Vienna"
    ) -> Series[MetricPoint]:
        return await client.price_spread(zone, start, end, timezone=timezone)

    @app.get("/v1/intelligence/anomalies")
    async def anomalies(
        client: Client,
        start: str,
        end: str,
        zone: str = "AT",
        window: Window = 24,
        threshold: Annotated[float, Query(gt=0, allow_inf_nan=False)] = 3,
    ) -> Series[AnomalyPoint]:
        return await client.detect_anomalies(zone, start, end, window=window, threshold=threshold)

    return app


app = create_app()

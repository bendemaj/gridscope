# GridScope

**The open grid intelligence layer.** One typed interface for fragmented European
electricity-system data, starting with Austria and ENTSO-E.

GridScope v0.2 provides an async Python client, pandas interoperability, a FastAPI
REST service, SMARD and ENTSO-E connectors, deterministic grid metrics, explicit
resampling and optional SQLite history. It has no frontend or external database requirement.

```text
ENTSO-E / SMARD → provider connector → normalization → typed models
                                                 ↓
                                       grid intelligence
                                                 ↓
                                     Python / REST / future MCP
```

## Install and configure

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/bendemaj/gridscope.git
cd gridscope
uv sync --locked
cp .env.example .env
```

Set `ENTSOE_API_TOKEN` in `.env` or your environment. The project loads `.env` from
the current working directory. Do not commit it. Obtain REST API access and a token
using the [official instructions](https://transparencyplatform.zendesk.com/hc/en-us/articles/12845911031188-How-to-get-security-token).
The API health check, documentation and SMARD data work without credentials.
ENTSO-E data requests without a token give a structured `missing_api_token` error. Credentials travel in the provider's
`SECURITY_TOKEN` header, not URLs or application logs.

On a macOS setup that marks editable-install `.pth` files as hidden, Python can
report `ModuleNotFoundError: gridscope` after a successful editable install. Use
`uv sync --locked --no-editable` and add `--no-editable` to `uv run` commands on
that machine. After editing source, refresh the installed copy with
`uv sync --locked --no-editable --reinstall-package gridscope`. This workaround
is unnecessary on installations where editable imports work normally.

## Python

```python
import asyncio
from gridscope import GridScope


async def main():
    async with GridScope() as gs:
        prices = await gs.prices("AT", start="2026-09-01", end="2026-09-02")
        print(prices.to_dataframe()[["value", "unit", "quality"]])
        load = await gs.load("AT", "2026-09-01", "2026-09-02")
        generation = await gs.generation("AT", "2026-09-01", "2026-09-02")
        flows = await gs.flows("DE_LU", "AT", "2026-09-01", "2026-09-02")
        share = await gs.renewable_share("AT", "2026-09-01", "2026-09-02")
        residual = await gs.residual_load("AT", "2026-09-01", "2026-09-02")
        imports = await gs.net_imports("AT", "2026-09-01", "2026-09-02", neighbors=["DE_LU"])
        volatility = await gs.price_volatility("AT", "2026-09-01", "2026-09-02", window=24)
        anomalies = await gs.detect_anomalies(
            "AT", "2026-09-01", "2026-09-02", window=24, threshold=3
        )
        print(share.meta.warnings)


asyncio.run(main())
```

The async context manager closes the HTTP connection. The service also accepts a
`GridDataProvider` implementation for another source or test transport.
Use `GenerationType.SOLAR` as `generation_type=` to filter generation. Typed
`Series[PricePoint]`, `Series[LoadPoint]`, `Series[GenerationPoint]` and
`Series[FlowPoint]` are canonical; DataFrames are a convenience view.

Dates mean **UTC midnight**. ISO datetimes must include an offset. For an Austrian
local day, use local-offset boundaries, e.g. `2026-09-01T00:00:00+02:00` through
`2026-09-02T00:00:00+02:00`. Selection is by interval start in **[start, end)**;
values retain their native interval duration. No partial-interval prorating occurs.
Use aligned boundaries for period aggregates. Ranges are limited to 366 days and
split into requests of at most 31 days. DST days can contain 23 or 25 hours.

## Germany, neighbors and provider selection

The default remains ENTSO-E. Select `GridScope("smard")` in Python, `provider=smard`
in REST, or `GRIDSCOPE_PROVIDER=smard` in `.env`. SMARD requires no token. Sources
never switch automatically: unsupported combinations return `unsupported_dataset`.

Use **DE** for German country load/generation and **DE_LU** for the combined
Germany–Luxembourg bidding zone, including prices. `LU` represents Luxembourg;
it has no separate day-ahead price in this registry. `/v1/zones` exposes `area_type`.
New neighboring bidding zones include FR, BE, NL, PL, DK1, DK2, NO2 and SE4, alongside
AT, CZ, CH, SK, HU, SI and IT_NORTH. Registration does not guarantee every dataset.
See the [verified coverage and provider contracts](docs/providers.md#v02-coverage).

```python
from gridscope import GridScope
from gridscope.models import TimeResolution

async with GridScope("smard", resolution=TimeResolution.HOUR) as gs:
    prices = await gs.prices("DE_LU", "2026-09-01", "2026-09-02")
    load = await gs.load("DE", "2026-09-01", "2026-09-02")
    residual = await gs.residual_load("DE", "2026-09-01", "2026-09-02")
```

SMARD load/generation/flow charts publish MWh per 15 minutes; GridScope divides by
0.25 hours to return MW. Its negative import chart values become positive in the
named flow direction. Prices remain EUR/MWh. SMARD's quarter-hour price chart can
repeat older hourly products; the cadence is flagged and is not claimed as native
auction resolution. SMARD's aggregated `hydro` category excludes pumped storage.

## Historical observations and revisions

Uncomment `GRIDSCOPE_STORAGE_PATH=data/gridscope.sqlite3` in your own `.env` to
persist successful queries. Alternatively pass `Settings(storage_path=...)` or a
`SQLiteStore` to the Python client. This is opt-in and adds no database dependency.
Local database files and journals are ignored by Git and Docker build contexts.

Each successful live query appends the full raw response before filtering and
resampling. Repeated observations, changed values, nulls, removed technologies,
source revision IDs and retrieval times remain available. Provider cache hits also
produce a capture and retain their original retrieval time. Disable the response
cache or call `clear_cache()` on the provider to request a fresh publication.

```python
from gridscope import GridScope
from gridscope.config import Settings

settings = Settings(storage_path="data/gridscope.sqlite3")
async with GridScope("smard", settings=settings) as gs:
    await gs.load("DE", "2026-09-01", "2026-09-02")
    snapshots = gs.history("load", "2026-09-01", "2026-09-02", zone="DE")
    cutoff = snapshots[-1].recorded_at

async with GridScope("smard", settings=settings, mode="stored", as_of=cutoff) as gs:
    historic = await gs.load("DE", "2026-09-01", "2026-09-02")
```

`recorded_at` / `as_of` refer to when this installation captured data, not when the
provider originally knew it. Stored mode makes no network requests. The newest
eligible capture replaces its whole requested interval, including omissions.
Uncaptured dates return `no_data`; captured provider gaps stay missing. Providers,
datasets, zones and flow directions have separate histories. `history()` returns
the latest 100 overlapping captures (configurable up to 1,000), in chronological
order, with their original full query scope. Storage grows with captures; no
retention job or automatic backfill is scheduled. See [storage details](docs/storage.md).

## Explicit resampling

Use `resolution=TimeResolution.HOUR` on a raw Python query, on `GridScope(...)` for
all metric inputs, or `resolution=PT60M` in REST. For an already fetched series,
call `gridscope.resample(series, "PT60M")`. Supported targets are PT15M, PT30M,
PT60M and P1D. Native data is returned when no resolution is selected.

Duration-weighted average MW preserves energy (`sum(MW × hours)`). Prices use a
duration-weighted average, not a volume-weighted price. Each technology and flow
direction stays separate. Gaps/nulls yield null `incomplete` bins. Complete bins
are `derived` and retain input provenance. Upsampling, overlapping intervals and
misaligned boundaries are rejected. Bins align to UTC; P1D is exactly 24 UTC hours.
Local DST days can be resampled into 23 or 25 hourly bins. Local-day price spread
continues to use its explicit timezone and `period_end`.

## REST API

```bash
uv run uvicorn gridscope.api.app:app --reload
```

Open [Swagger docs](http://localhost:8000/docs) or
[OpenAPI JSON](http://localhost:8000/openapi.json).

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/zones
curl http://localhost:8000/v1/sources
curl 'http://localhost:8000/v1/prices?zone=AT&start=2026-09-01&end=2026-09-02'
curl 'http://localhost:8000/v1/load?zone=AT&start=2026-09-01&end=2026-09-02'
curl 'http://localhost:8000/v1/generation?zone=AT&start=2026-09-01&end=2026-09-02&generation_type=solar'
curl 'http://localhost:8000/v1/flows?from_zone=DE_LU&to_zone=AT&start=2026-09-01&end=2026-09-02'
curl 'http://localhost:8000/v1/intelligence/net-imports?zone=AT&neighbors=DE_LU&start=2026-09-01&end=2026-09-02'
curl 'http://localhost:8000/v1/intelligence/price-volatility?zone=AT&window=24&start=2026-09-01&end=2026-09-02'
```

All data/intelligence endpoints accept `provider=entsoe|smard`, `mode=live|stored`,
`as_of=<offset-aware timestamp>` (stored mode only) and optional `resolution`.

```bash
curl 'http://localhost:8000/v1/load?provider=smard&zone=DE&start=2026-09-01&end=2026-09-02&resolution=PT60M'
curl 'http://localhost:8000/v1/load?provider=smard&mode=stored&zone=DE&start=2026-09-01&end=2026-09-02'
curl 'http://localhost:8000/v1/history/load?provider=smard&zone=DE&start=2026-09-01&end=2026-09-02'
```

History requires configured storage and returns `{data: [{id, recorded_at, series}]}`.
Flow history uses `from_zone` and `to_zone`. Query `mode=stored&as_of=...` to limit
history to captures known at that instant; resolution never changes raw history.

Intelligence endpoints also include `renewable-share`, `residual-load`,
`price-spread` and `anomalies`. Data responses use `{data, meta}`; metadata includes
source, requested interval, count, scope, warnings and attribution. Domain errors
use `{error: {code, message}}`; invalid FastAPI parameters use HTTP 422 validation details.

## Metrics and missing data

- **Renewable share:** renewable output / reported total output × 100. Renewable
  categories: solar, both winds, biomass, geothermal, run-of-river and reservoir
  hydro, aggregated SMARD hydro, marine and other renewable. Pumped storage, energy storage and mixed
  waste are excluded from the numerator. Zero/missing totals produce null.
- **Residual load:** load minus reported solar and wind. If a variable technology
  appears anywhere in the returned interval, it must be present at the timestamp.
  Technologies absent throughout the response cannot be assessed. This is a
  reported-data metric, not a claim of complete national coverage.
- **Net imports:** imports minus exports for explicitly requested neighbors.
  Positive means importing. Both directions are required at each timestamp;
  unavailable directions produce null, never assumed zero. A DE_LU-only result
  is a border balance, not Austria's total imports.
- **Price spread:** local-day max minus min (Europe/Vienna by default). Partial
  days are flagged incomplete. The explicit `period_end` accounts for DST.
- **Volatility:** sample standard deviation (`ddof=1`) of N contiguous observations,
  including the current point. `window=24` means six hours at 15-minute resolution.
- **Anomalies:** rolling z-score against the previous N contiguous observations.
  No lookahead; insufficient history produces null. A zero-variance baseline has
  undefined z-score; a different observed value is explicitly flagged. This is a
  statistical signal, not an operational grid-security assessment.

Cross-series metrics require matching units and resolutions; callers must choose
any resampling policy explicitly. Known missing interval values remain null.
Gaps, overlaps, unknown production types and partial coverage are exposed or rejected.
Raw metrics are also available in `gridscope.intelligence.metrics` without HTTP calls.

## Examples

```bash
uv run python examples/germany_history.py --start 2026-09-01 --end 2026-09-02
uv run python examples/austria_prices.py --start 2026-09-01 --end 2026-09-02
uv run python examples/austria_system.py --start 2026-09-01 --end 2026-09-02
uv sync --group examples
uv run --group examples jupyter lab
```

Open `examples/austria_analysis.ipynb` for a matplotlib plot of load, production
and prices. Examples query actual provider data; the report is tested using an
injected mock provider. Synthetic fixture values live only in the test suite.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Unit and integration tests require no token. To verify all four datasets live:

```bash
RUN_LIVE_ENTSOE_TESTS=1 uv run pytest tests/integration/test_live.py -m live -v
RUN_LIVE_V02_TESTS=1 uv run pytest tests/integration/test_live_v02.py -m live -v
```

Optional `GRIDSCOPE_LIVE_START` and `GRIDSCOPE_LIVE_END` override the live test dates.
CI checks Python 3.12/3.13 and builds the container.

## Docker

```bash
docker build -t gridscope .
docker run --rm --env-file .env -p 8000:8000 gridscope
```

The container runs as a non-root user. Only the API and its runtime dependencies
are installed. An external database is unnecessary. To keep SQLite history across
container replacements, use a named volume:

```bash
docker run --rm --env-file .env -p 8000:8000 \
  -e GRIDSCOPE_STORAGE_PATH=/app/data/gridscope.sqlite3 \
  -v gridscope-history:/app/data gridscope
```

## Provider behavior and provenance

HTTP timeouts default to 30 seconds. Transient failures use up to three retries
with exponential backoff. Requests are spaced at least 200 ms apart per client;
multiple clients sharing a token must coordinate their aggregate rate. Long
`Retry-After` cooldowns are surfaced to callers without premature retries.

A bounded in-memory response cache keeps up to 128 query responses for 300 seconds.
It is per client/process, retains original retrieval timestamps and expires lazily.
Set `GRIDSCOPE_CACHE_TTL_SECONDS=0` to disable it; call the ENTSO-E provider's
`clear_cache()` to invalidate it. The response cache does not persist across restarts; configured SQLite snapshots do. Historical
provider revisions become visible after expiry. Tokens never enter cache keys.

Points retain provider document, revision, series, curve, dataset and retrieval time.
A03 expansion follows provider-defined constant blocks; it is not interpolation.

Attribute data to **ENTSO-E Transparency Platform** and identify GridScope's
normalization/derived calculations. The current free-reuse list includes physical
flows with exceptions; it does not establish blanket CC-BY permission for prices,
actual load or generation. Their primary-owner rights require verification.
SMARD data uses CC BY 4.0 with credit **Bundesnetzagentur | SMARD.de** and an
indication of changes. See [provider sources and reuse notes](docs/providers.md) and `/v1/sources`.
This registry records source information, not legal advice.

## Current limitations

Live Austrian prices, load, generation and DE_LU→AT flows were verified on
13 September 2026 for the UTC day 1 September 2026. Your own token is required.
The Austrian system report also completed against live data.
Docker configuration is included; local image validation depends on a running engine.
No automated currency conversion, implicit resampling, forecast, authentication
or full-market coverage guarantee. v0.2 live verification and limitations are recorded
in [provider coverage](docs/providers.md#v02-coverage). ENTSO-E DK2 prices can contain
ambiguous overlapping auctions and are rejected; SMARD DK2 prices were verified.
Austrian and DE_LU prices use
SDAC auction sequence 1. Exact duplicate price publications within a response are
collapsed with their identifiers retained; conflicting overlaps are rejected.
Very large replies are rejected.
The v0.2 API is intended for local development, not a public multi-tenant service.

## Roadmap

| Version | Focus |
| --- | --- |
| v0.1 | Austria, ENTSO-E, normalized data, deterministic metrics, Python/REST |
| v0.2 | Germany and neighbors, SMARD, historical observations/revisions, explicit resampling |
| v0.3 | Forecasting primitives, outages, balancing |
| v0.4 | MCP adapter, webhooks, event detection |
| v0.5 | GridScope dashboard |
| Later | Validated stress/flexibility intelligence, forecast APIs, private deployments |

See [architecture](docs/architecture.md), [data model](docs/data-model.md),
[provider documentation](docs/providers.md) and [roadmap](docs/roadmap.md).

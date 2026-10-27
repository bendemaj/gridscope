# Architecture

`GridScope` is the async application service shared by Python and FastAPI.
It validates user-facing zones and intervals before provider calls. Providers
implement a small `GridDataProvider` protocol and return typed `Series` objects.
The default ENTSO-E provider owns HTTP, retries, throttling, response caching,
query chunking/pagination, XML decoding and identifier translation.

The domain model is Pydantic v2. `source` is an extensible string rather than an
enum that forces future providers to modify core types. Provider EIC mappings are
isolated from the public zone registry. Readable generation categories live in the
domain; raw production codes are optional provenance. Common point subclasses
are grouped in `models/points.py` to avoid one-field modules.

`intelligence/metrics.py` contains pure deterministic functions. It imports only
normalized models/utilities, never provider code. The service retrieves inputs
and packages metric results; FastAPI delegates to that service and does not
reimplement calculations. A future MCP adapter can call the same service methods.
APG, Elia, Energinet, Elexon and weather integrations can implement their
own connectors without importing ENTSO-E constants into the domain.

Lifetimes are explicit: use `async with GridScope()`, or call `aclose()`. FastAPI
owns a lazy client per selected provider per lifespan. Callers supplying a client to `create_app(client)`
retain responsibility for closing it. A cache is scoped to that client and bounded
by entry count. An optional SQLite store captures raw responses before any filtering
or resampling. No worker queue or external cache service is required.

The provider requests at most 31 days at a time and follows 100-series price
pagination. It trims points by interval start after decoding provider periods.
Ambiguous overlapping series fail rather than double-counting power. Mixed
resolutions can be returned as raw series; metrics reject mismatched resolutions
unless the caller explicitly chooses a common target resolution.
No implicit interpolation, currency conversion or operational grid-stress score
is introduced.

Tests separate normalization/metrics/parser behavior from HTTP/REST integration.
The HTTP transport is injectable; no regular test requires a credential. Fixtures
are deliberately synthetic and never presented as real Austrian data. Live checks
are explicit opt-in.

## v0.2 modules

`providers/smard` owns the public JSON chart interface, weekly index traversal,
regional/filter mapping, throttling, bounded cache and retries. It validates
millisecond UTC timestamps and finite values, converts interval MWh to MW and
reverses signed imports into positive directional flows. It never shares a token
with SMARD or silently switches sources. German country areas and the DE_LU market
remain separate domain zones.

`normalization/resampling.py` is a pure duration-weighted reducer. It accepts raw
series, rejects upsampling/overlaps, keeps each technology/direction separate and
produces null bins for incomplete coverage. Input provenance is retained. Metrics
use the chosen resolution on all raw inputs, while default requests remain native.

`storage.py` appends complete normalized snapshots to SQLite and reconstructs
as-of views. Snapshots replace covered intervals, so removed observations and
changed interval layouts are revisions too. Async retrieval offloads SQLite work
to threads. The store adds no dependency beyond the Python standard library.
See [capture semantics and ownership](storage.md).

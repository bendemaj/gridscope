# Historical observations

SQLite is optional. Set `GRIDSCOPE_STORAGE_PATH`, pass a path through `Settings`,
or inject `SQLiteStore(path)`. The parent directory is created when necessary.
Use a persistent volume for containers. Protect and back up the local database
according to your deployment; it contains observations, not the ENTSO-E token.

## Capture and revisions

Every successful live raw query is recorded atomically as an immutable snapshot:
source, dataset, zone or directional border, query start/end, local UTC capture
time and the complete normalized `{data, meta}` payload. All point provenance,
quality, null values and warnings are retained. Generation filters and resampling
run **after** capture. Failed requests do not replace existing history. Partial
successful publications are retained with their coverage warnings.

This is a capture log, not an upstream revision archive. Two identical retrievals
can have different snapshot IDs. Provider `source_revision` is stored verbatim;
SMARD uses the chart's creation timestamp, since it has no ENTSO-E-style revision
number. A cache hit creates a new capture of the same publication, retaining the
original `retrieved_at`. To observe a changed upstream publication, expire or clear
the provider cache. Revisions that happened before this installation first fetched
the data cannot be reconstructed. There is no automatic scheduler, backfill or
retention deletion in v0.2.

## Query semantics

`mode="stored"` reads only SQLite. An optional `as_of` selects captures recorded
at or before that offset-aware instant. This is **local knowledge time**, not
publication time or the point's delivery timestamp. Prices, load, generation,
flows and all existing intelligence methods can use stored mode. Derived results
are recomputed from captured inputs and are not written over raw observations.

Captures are applied in `(recorded_at, id)` order. A newer query replaces its entire
[start, end) interval, including omitted timestamps and generation types. Removed
technologies cannot revive values from an older capture. Points retain native
resolution; the last capture is not automatically resampled. If partial refreshes
with changed resolutions would create overlapping native intervals, the read is
rejected: refresh the full aligned range to obtain a consistent snapshot.

An interval not fully covered by captured query ranges returns `no_data`. A range
that was fetched but had source gaps returns those gaps and warnings; it is not
filled from earlier versions. Selection, as in the live API, uses interval starts.
A provider gap and an interval never fetched are different conditions. Source,
dataset, zone and exact flow direction form separate history scopes; no providers
are merged.

`GridScope.history(dataset, start, end, zone=..., limit=100)` returns the latest
matching captures in chronological order. Captures intersect the query but retain
their original full scope and payload. `limit` is 1–1000; use `as_of` to inspect older
captures. The REST equivalent is `/v1/history/{dataset}`; flow history requires
`from_zone` and `to_zone` instead of `zone`. REST `resolution` does not alter history.
An empty history returns an empty list; a stored data query without captures returns
404. Missing storage configuration returns `storage_unavailable` (503).

## Ownership and implementation

`GridScope` closes stores it creates from settings. Callers who inject a store
retain responsibility for `close()`. `with_options(...)` produces a non-owning view;
keep its parent client open while using it. FastAPI owns lazy clients for the
selected providers and closes them at shutdown; injected clients remain caller-owned.

The standard-library `sqlite3` connection uses WAL, a five-second busy timeout,
a lock for shared-thread access and transactional appends. SQLite work for async
queries runs in worker threads. Separate local clients can share the same database.
Schema version 1 is recorded in `PRAGMA user_version`; unknown versions are rejected.
Use a local filesystem suitable for SQLite; no distributed writer coordination is
provided. For a live database, use SQLite's backup API or stop writers before copying
it so committed WAL data is included. Files and journals are excluded from Git.

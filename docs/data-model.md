# Unified Grid Schema v0.2

Every point carries an aware UTC `timestamp` (interval start), nullable finite
`value`, explicit `unit`, ISO `resolution`, `source`, `source_dataset`, UTC
`retrieved_at`, `quality` and notes. Optional source document/revision/series/curve
fields preserve provider provenance. Explicitly resampled points also retain
`input_provenance`: source, dataset, document, revision, series, original resolution
and retrieval time for each contributing publication. Price points also retain the auction sequence
and identifiers of exact duplicate price publications collapsed within a response. Pydantic models forbid unknown fields and
are frozen; model validation normalizes aware timestamps to UTC.

| Model | Additional fields | Unit / value |
| --- | --- | --- |
| PricePoint | zone, currency | EUR/MWh, negative prices allowed |
| LoadPoint | zone | MW, nonnegative or missing |
| GenerationPoint | zone, generation_type, production_code | MW output, nonnegative or missing |
| FlowPoint | from_zone, to_zone | MW, nonnegative in the named direction |
| MetricPoint | zone, metric, optional period_end | Explicit metric-specific unit |
| AnomalyPoint | observed, baseline, deviation, z_score, is_anomaly | Nullable statistical outputs |

`observed` means published by the source, not independently verified. `missing`
means no value for a known interval. `derived` denotes calculated values;
`incomplete` denotes insufficient data, unknown classifications or partial periods.
A `Series` uses `{data, meta}`. Metadata includes query scope and warnings, and its
count is set from the actual number of points. `to_dataframe()` returns a sorted
UTC DatetimeIndex while retaining unit and provenance columns.

Supported raw resolutions are PT15M, PT30M, PT60M (PT1H aliases PT60M). A daily
spread uses P1D plus explicit `period_end`, because a local calendar day can span
23/24/25 hours. Query timestamps must use whole minutes; date-only values mean UTC,
and naive datetime values are rejected. Offset-aware local input normalizes to UTC.
Ambiguous ZoneInfo datetimes require the correct fold; imaginary local times fail.

A01 absent positions produce missing points. A03 omitted positions repeat the
provider-defined block value until the next position or period end. Explicit null
points stop propagation. Blocks never extend across period boundaries. Gaps
between periods remain gaps with coverage warnings. Missing generation technology
series are never constructed from the enum. Unknown PSR codes map to `unknown`
with the original code retained and a warning; B25 maps to `energy_storage`.

Renewable share is a share of reported production, not consumption or the national
energy mix including imports. Pumping consumption is excluded from generation.
Net imports require both directional observations for every selected border at
each timestamp. Missing directions are not equivalent to zero. All metric
alignment is exact, with no implicit resampling. Rolling windows reset across gaps.

## v0.2 area and aggregation rules

`Zone.area_type` distinguishes `country` (DE, LU) from `bidding_zone`. Provider EICs
and SMARD filter IDs stay inside their respective adapters. DE country production
is never relabeled as DE_LU; prices require the appropriate bidding zone.

SMARD's `hydro` category is aggregated renewable hydro, distinct from ENTSO-E's
`hydro_run_of_river` and `hydro_reservoir`. It does not contain pumped storage; the
source's separate pumping generation filter maps to `hydro_pumped_storage`. SMARD
filter IDs are retained as `production_code`, and `source_series` records the filter
and reporting region. SMARD `source_revision` records chart creation milliseconds.

Resampling supports PT15M, PT30M, PT60M and P1D targets. It uses duration-weighted
means for MW and EUR/MWh. P1D aggregation is exactly 24 UTC hours; it is distinct
from a timezone-aware daily price spread. Complete aggregates are `derived`; gaps,
explicit nulls or incomplete inputs produce null `incomplete` outputs. No category,
provider, zone or flow direction is summed into another. Upsampling and source
intervals crossing target boundaries are rejected.

History uses `Snapshot {id, recorded_at, series}`. Its series remains the original
normalized query, including provenance and warnings. IDs identify local captures;
they are not provider revision identifiers. See [history semantics](storage.md).

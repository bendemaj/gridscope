# Unified Grid Schema v0.1

Every point carries an aware UTC `timestamp` (interval start), nullable finite
`value`, explicit `unit`, ISO `resolution`, `source`, `source_dataset`, UTC
`retrieved_at`, `quality` and notes. Optional source document/revision/series/curve
fields preserve provider provenance. Pydantic models forbid unknown fields and
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

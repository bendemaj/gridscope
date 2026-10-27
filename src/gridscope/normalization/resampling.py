"""Explicit UTC, duration-weighted aggregation of normalized raw observations."""

from collections import defaultdict
from datetime import timedelta
from typing import TypeVar

from gridscope.errors import InvalidQuery
from gridscope.models import DataQuality, Series, TimeResolution
from gridscope.models.common import Point, SourceReference
from gridscope.models.points import FlowPoint, GenerationPoint, LoadPoint, PricePoint
from gridscope.normalization.time import resolution_delta

P = TypeVar("P", bound=Point)


def resample(series: Series[P], resolution: TimeResolution | str) -> Series[P]:
    """Downsample MW or EUR/MWh, preserving energy and missingness, never upsample.

    Bins are anchored to UTC midnight. Bounds must align with the requested bins.
    P1D means exactly 24 UTC hours, not a local market day. Each generation type,
    provider, zone and flow direction remains a separate stream.
    """
    try:
        target = TimeResolution(resolution)
    except ValueError:
        raise InvalidQuery(f"Unsupported resampling resolution: {resolution}.") from None
    delta = timedelta(days=1) if target == TimeResolution.DAY else resolution_delta(target)
    seconds = delta.total_seconds()
    if any(t.timestamp() % seconds for t in (series.meta.start, series.meta.end)):
        raise InvalidQuery("Resampling requires UTC boundaries aligned to the target resolution.")
    groups: dict[tuple[object, ...], list[P]] = defaultdict(list)
    for point in series.data:
        if not isinstance(point, (PricePoint, LoadPoint, GenerationPoint, FlowPoint)):
            raise InvalidQuery("Resample raw prices, load, generation or flows before metrics.")
        native = (
            timedelta(days=1)
            if point.resolution == TimeResolution.DAY
            else resolution_delta(point.resolution)
        )
        if native > delta:
            raise InvalidQuery("Upsampling is not supported; choose a coarser resolution.")
        if not series.meta.start <= point.timestamp < series.meta.end:
            raise InvalidQuery("Point lies outside the series bounds.")
        offset = (point.timestamp - series.meta.start) % delta
        if offset + native > delta:
            raise InvalidQuery("Source interval crosses a target boundary; align inputs first.")
        groups[
            (
                type(point),
                point.source,
                point.source_dataset,
                point.unit,
                getattr(point, "zone", None),
                getattr(point, "from_zone", None),
                getattr(point, "to_zone", None),
                getattr(point, "generation_type", None),
                getattr(point, "production_code", None),
            )
        ].append(point)
    result: list[P] = []
    for points in groups.values():
        points.sort(key=lambda p: p.timestamp)
        bins: dict[int, list[P]] = defaultdict(list)
        previous_end = series.meta.start
        for point in points:
            if point.timestamp < previous_end:
                raise InvalidQuery("Overlapping source intervals cannot be resampled.")
            previous_end = point.timestamp + (
                timedelta(days=1)
                if point.resolution == TimeResolution.DAY
                else resolution_delta(point.resolution)
            )
            bins[int((point.timestamp - series.meta.start) / delta)].append(point)
        for index in range(int((series.meta.end - series.meta.start) / delta)):
            members = bins[index]
            covered = 0.0
            weighted = 0.0
            valid = True
            for member in members:
                duration = (
                    timedelta(days=1)
                    if member.resolution == TimeResolution.DAY
                    else resolution_delta(member.resolution)
                ).total_seconds()
                covered += duration
                if member.value is None or member.quality in (
                    DataQuality.MISSING,
                    DataQuality.INCOMPLETE,
                ):
                    valid = False
                else:
                    weighted += member.value * duration
            complete = valid and covered == seconds
            template = members[0] if members else points[0]
            refs = tuple(
                dict.fromkeys(
                    ref
                    for p in members
                    for ref in (
                        p.input_provenance
                        or (
                            SourceReference(
                                source=p.source,
                                dataset=p.source_dataset,
                                document=p.source_document,
                                revision=p.source_revision,
                                series=p.source_series,
                                resolution=p.resolution,
                                retrieved_at=p.retrieved_at,
                            ),
                        )
                    )
                )
            )
            updates: dict[str, object] = {
                "timestamp": series.meta.start + index * delta,
                "value": weighted / seconds if complete else None,
                "resolution": target,
                "quality": DataQuality.DERIVED if complete else DataQuality.INCOMPLETE,
                "retrieved_at": max(p.retrieved_at for p in (members or points)),
                "input_provenance": refs,
                "notes": tuple(dict.fromkeys(n for p in members for n in p.notes))
                + ("Duration-weighted UTC aggregation by GridScope; gaps are not filled.",),
            }
            for field in ("source_document", "source_revision", "source_series", "source_curve"):
                values = {getattr(p, field) for p in members}
                updates[field] = next(iter(values)) if len(values) == 1 else None
            if isinstance(template, PricePoint):
                sequences = {
                    p.source_auction_sequence for p in members if isinstance(p, PricePoint)
                }
                updates["source_auction_sequence"] = (
                    next(iter(sequences)) if len(sequences) == 1 else None
                )
                updates["duplicate_source_series"] = tuple(
                    dict.fromkeys(
                        s
                        for p in members
                        if isinstance(p, PricePoint)
                        for s in p.duplicate_source_series
                    )
                )
            result.append(type(template).model_validate(template.model_dump() | updates))
    meta = series.meta.model_copy(deep=True)
    meta.warnings.append(f"Explicit duration-weighted resampling to {target}; bins use UTC.")
    if any(p.value is None for p in result):
        meta.warnings.append("Incomplete resampling bins are null, including unobserved intervals.")
    meta.attribution = "Resampled by GridScope. " + meta.attribution
    return Series(data=sorted(result, key=lambda p: p.timestamp), meta=meta)

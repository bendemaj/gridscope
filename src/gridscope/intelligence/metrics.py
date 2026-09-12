"""Deterministic metrics over normalized points; no provider dependencies."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from statistics import mean, stdev
from typing import TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from gridscope.errors import InvalidQuery
from gridscope.models import (
    AnomalyPoint,
    DataQuality,
    FlowPoint,
    GenerationPoint,
    GenerationType,
    LoadPoint,
    MetricPoint,
    PricePoint,
    TimeResolution,
)
from gridscope.models.common import Point
from gridscope.normalization.time import resolution_delta
from gridscope.normalization.zones import zone_code

VARIABLE_RENEWABLES = frozenset(
    {GenerationType.SOLAR, GenerationType.WIND_ONSHORE, GenerationType.WIND_OFFSHORE}
)
RENEWABLES = VARIABLE_RENEWABLES | frozenset(
    {
        GenerationType.BIOMASS,
        GenerationType.GEOTHERMAL,
        GenerationType.HYDRO_RUN_OF_RIVER,
        GenerationType.HYDRO_RESERVOIR,
        GenerationType.MARINE,
        GenerationType.OTHER_RENEWABLE,
    }
)
P = TypeVar("P", bound=Point)


def _validate(points: Sequence[P]) -> None:
    if not points:
        return
    if len({p.resolution for p in points}) != 1:
        raise InvalidQuery(
            "Metrics require matching resolutions; explicitly resample inputs first."
        )
    if len({p.unit for p in points}) != 1:
        raise InvalidQuery("Metrics require matching units.")
    if len({getattr(p, "zone", None) for p in points}) != 1:
        raise InvalidQuery("Metrics require one zone.")


def _metric(
    points: Sequence[Point],
    zone: str,
    metric: str,
    value: float | None,
    unit: str,
    notes: tuple[str, ...] = (),
    incomplete: bool = False,
) -> MetricPoint:
    first = points[0]
    return MetricPoint(
        timestamp=first.timestamp,
        zone=zone,
        metric=metric,
        value=value,
        unit=unit,
        resolution=first.resolution,
        source=",".join(sorted({p.source for p in points})),
        source_dataset=metric,
        retrieved_at=max(p.retrieved_at for p in points),
        quality=DataQuality.INCOMPLETE if incomplete or value is None else DataQuality.DERIVED,
        notes=notes,
    )


def _generation_groups(points: Sequence[GenerationPoint]) -> dict[datetime, list[GenerationPoint]]:
    _validate(points)
    groups: dict[datetime, list[GenerationPoint]] = defaultdict(list)
    seen: set[tuple[datetime, GenerationType, str | None]] = set()
    for p in points:
        key = (p.timestamp, p.generation_type, p.production_code)
        if key in seen:
            raise InvalidQuery("Duplicate generation observations.")
        seen.add(key)
        groups[p.timestamp].append(p)
    return dict(sorted(groups.items()))


def renewable_share(points: Sequence[GenerationPoint]) -> list[MetricPoint]:
    """Percentage of reported output; storage and mixed waste excluded from numerator."""
    groups = _generation_groups(points)
    expected = {(p.generation_type, p.production_code) for p in points}
    result = []
    for group in groups.values():
        complete = {(p.generation_type, p.production_code) for p in group} == expected and all(
            p.value is not None for p in group
        )
        total = sum(p.value for p in group if p.value is not None)
        renewable = sum(
            p.value for p in group if p.generation_type in RENEWABLES and p.value is not None
        )
        value = renewable / total * 100 if complete and total > 0 else None
        result.append(
            _metric(
                group,
                group[0].zone,
                "renewable_share",
                value,
                "%",
                ("Share of reported generation; no assumption about unreported types.",),
                incomplete=any(p.generation_type == GenerationType.UNKNOWN for p in group),
            )
        )
    return result


def residual_load(
    load: Sequence[LoadPoint], generation: Sequence[GenerationPoint]
) -> list[MetricPoint]:
    _validate([*load, *generation])
    groups = _generation_groups(generation)
    expected = {p.generation_type for p in generation if p.generation_type in VARIABLE_RENEWABLES}
    result = []
    _ordered(load)
    for p in sorted(load, key=lambda p: p.timestamp):
        group = [g for g in groups.get(p.timestamp, []) if g.generation_type in VARIABLE_RENEWABLES]
        complete = (
            bool(expected)
            and {g.generation_type for g in group} == expected
            and all(g.value is not None for g in group)
        )
        value = (
            p.value - sum(g.value for g in group if g.value is not None)
            if p.value is not None and complete
            else None
        )
        result.append(
            _metric(
                [p, *group],
                p.zone,
                "residual_load",
                value,
                "MW",
                (
                    "Load minus reported solar and wind; "
                    "unreported technologies are not assumed zero.",
                ),
            )
        )
    return result


def net_imports(
    points: Sequence[FlowPoint], zone: str, neighbors: Sequence[str]
) -> list[MetricPoint]:
    """Positive means net imports over explicitly selected borders, not national totals."""
    zone = zone_code(zone)
    neighbors = [zone_code(n) for n in neighbors]
    if not neighbors or len(set(neighbors)) != len(neighbors) or zone in neighbors:
        raise InvalidQuery("Provide distinct neighboring zones excluding the target zone.")
    _validate(points)
    expected = {(zone, n) for n in neighbors} | {(n, zone) for n in neighbors}
    groups: dict[datetime, dict[tuple[str, str], FlowPoint]] = defaultdict(dict)
    for p in points:
        pair = (p.from_zone, p.to_zone)
        if pair not in expected:
            raise InvalidQuery("Flow falls outside the requested border scope.")
        if pair in groups[p.timestamp]:
            raise InvalidQuery("Duplicate directional flow observations.")
        groups[p.timestamp][pair] = p
    result = []
    for _, group in sorted(groups.items()):
        complete = set(group) == expected and all(p.value is not None for p in group.values())
        value = (
            sum(
                p.value * (1 if p.to_zone == zone else -1)
                for p in group.values()
                if p.value is not None
            )
            if complete
            else None
        )
        result.append(
            _metric(
                list(group.values()),
                zone,
                "net_imports",
                value,
                "MW",
                (f"Selected borders: {', '.join(neighbors)}. Positive = net importing.",),
            )
        )
    return result


def _ordered[Q: (PricePoint, LoadPoint)](points: Sequence[Q]) -> list[Q]:
    _validate(points)
    ordered = sorted(points, key=lambda p: p.timestamp)
    if len({p.timestamp for p in points}) != len(points):
        raise InvalidQuery("Duplicate timestamps in metric input.")
    for a, b in zip(ordered, ordered[1:], strict=False):
        if b.timestamp < a.timestamp + resolution_delta(a.resolution):
            raise InvalidQuery("Overlapping observations in metric input.")
    return ordered


def _window(points: Sequence[Point], size: int) -> list[float] | None:
    if len(points) != size or any(p.value is None for p in points):
        return None
    if any(
        b.timestamp != a.timestamp + resolution_delta(a.resolution)
        for a, b in zip(points, points[1:], strict=False)
    ):
        return None
    return [p.value for p in points if p.value is not None]


def price_volatility(points: Sequence[PricePoint], window: int = 24) -> list[MetricPoint]:
    """Sample standard deviation of the last N contiguous observations, including current."""
    if window < 2:
        raise InvalidQuery("Rolling window must be at least 2 observations.")
    ordered = _ordered(points)
    result = []
    for i, p in enumerate(ordered):
        group = ordered[max(0, i - window + 1) : i + 1]
        values = _window(group, window)
        result.append(
            _metric(
                group,
                p.zone,
                "price_volatility",
                stdev(values) if values else None,
                p.unit,
                (f"Sample standard deviation (ddof=1); window={window} observations.",),
            ).model_copy(update={"timestamp": p.timestamp})
        )
    return result


def detect_anomalies(
    points: Sequence[PricePoint], window: int = 24, threshold: float = 3
) -> list[AnomalyPoint]:
    """Compare each observation with the preceding N points (no lookahead)."""
    if window < 2 or not 0 < threshold < float("inf"):
        raise InvalidQuery("Require window >= 2 and a finite positive threshold.")
    ordered = _ordered(points)
    result = []
    for i, p in enumerate(ordered):
        previous = ordered[max(0, i - window) : i]
        values = _window(previous, window)
        if previous and p.timestamp != previous[-1].timestamp + resolution_delta(p.resolution):
            values = None
        baseline = mean(values) if values else None
        deviation = p.value - baseline if p.value is not None and baseline is not None else None
        sigma = stdev(values) if values else None
        z = deviation / sigma if deviation is not None and sigma else None
        anomaly = (
            abs(z) > threshold
            if z is not None
            else (deviation != 0 if deviation is not None and sigma == 0 else None)
        )
        notes: tuple[str, ...] = (
            f"Prior window={window}; |z| > {threshold}. Statistical signal, not grid security.",
        )
        if sigma == 0:
            notes += ("Constant baseline: z-score undefined; any nonzero deviation is flagged.",)
        metric = _metric(
            [*previous, p], p.zone, "anomaly", z, "z-score", notes, incomplete=deviation is None
        ).model_dump()
        metric.update(
            timestamp=p.timestamp,
            quality=DataQuality.DERIVED if deviation is not None else DataQuality.INCOMPLETE,
        )
        result.append(
            AnomalyPoint(
                **metric,
                observed=p.value,
                baseline=baseline,
                deviation=deviation,
                z_score=z,
                is_anomaly=anomaly,
            )
        )
    return result


def price_spread(
    points: Sequence[PricePoint], timezone: str = "Europe/Vienna"
) -> list[MetricPoint]:
    """Local-calendar-day maximum minus minimum. Partial days are flagged."""
    ordered = _ordered(points)
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise InvalidQuery("Unknown IANA timezone.") from None
    groups: dict[datetime, list[PricePoint]] = defaultdict(list)
    for p in ordered:
        day = datetime.combine(p.timestamp.astimezone(tz).date(), time(), tzinfo=tz)
        groups[day].append(p)
    result = []
    for day, group in sorted(groups.items()):
        stop = (day + timedelta(days=1)).astimezone(UTC)
        begin = day.astimezone(UTC)
        values = [p.value for p in group if p.value is not None]
        step = resolution_delta(group[0].resolution)
        complete = (
            group[0].timestamp == begin
            and group[-1].timestamp + step == stop
            and _window(group, int((stop - begin) / step)) is not None
        )
        metric = _metric(
            group,
            group[0].zone,
            "price_spread",
            max(values) - min(values) if values else None,
            group[0].unit,
            (f"Daily range in {timezone}; incomplete days use observed prices only.",),
            not complete,
        )
        result.append(
            metric.model_copy(
                update={"timestamp": begin, "resolution": TimeResolution.DAY, "period_end": stop}
            )
        )
    return result

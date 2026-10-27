from datetime import timedelta

import pytest
from conftest import END, START, generation, point

from gridscope.errors import InvalidQuery
from gridscope.models import (
    DataQuality,
    GenerationPoint,
    LoadPoint,
    Series,
    SeriesMeta,
    TimeResolution,
)
from gridscope.normalization.resampling import resample
from gridscope.normalization.time import utc


def series(points, start=START, end=END):
    return Series(
        data=points,
        meta=SeriesMeta(source="fixture", dataset="load", zone="AT", start=start, end=end),
    )


def test_mw_energy_and_provenance_are_preserved():
    raw = series(
        [
            point(LoadPoint, value=v, i=i).model_copy(
                update={"source_document": f"doc-{i}", "source_revision": str(i)}
            )
            for i, v in enumerate([100, 200, 300, 400])
        ]
    )
    result = resample(raw, "PT60M")
    assert len(result.data) == 1
    p = result.data[0]
    assert p.value == 250
    assert sum(p.value * 0.25 for p in raw.data) == p.value
    assert p.quality == DataQuality.DERIVED
    assert len(p.input_provenance) == 4
    assert p.source_document is None
    assert raw.data[0].resolution == "PT15M"
    assert raw.meta.warnings == []


@pytest.mark.parametrize("values", [[1, None, 3, 4], [1, 2, 3]])
def test_missing_or_absent_intervals_produce_null(values):
    result = resample(series([point(LoadPoint, v, i) for i, v in enumerate(values)]), "PT60M")
    assert result.data[0].value is None
    assert result.data[0].quality == DataQuality.INCOMPLETE


def test_empty_bins_and_technology_streams_are_not_combined():
    raw = series([p for i in range(4) for p in generation(i=i)], end=END + timedelta(hours=1))
    result = resample(raw, "PT60M")
    assert len(result.data) == 6
    assert sorted(p.value for p in result.data[:3]) == [100, 100, 800]
    assert all(p.value is None for p in result.data[3:])
    assert all(isinstance(p, GenerationPoint) for p in result.data)


def test_prices_are_duration_weighted_and_negative_values_survive():
    raw = series(
        [
            point(value=-20, i=0).model_copy(update={"resolution": TimeResolution.HALF_HOUR}),
            point(value=100, i=2),
            point(value=140, i=3),
        ]
    )
    assert resample(raw, "PT60M").data[0].value == 50


def test_reject_upsampling_overlap_and_misalignment():
    hourly = series([point().model_copy(update={"resolution": TimeResolution.HOUR})])
    with pytest.raises(InvalidQuery, match="Upsampling"):
        resample(hourly, "PT15M")
    with pytest.raises(InvalidQuery, match="Overlapping"):
        resample(series([point(), point()]), "PT60M")
    with pytest.raises(InvalidQuery, match="aligned"):
        resample(series([point()], start=START + timedelta(minutes=15)), "PT60M")
    shifted = point().model_copy(update={"timestamp": START + timedelta(minutes=55)})
    with pytest.raises(InvalidQuery, match="crosses"):
        resample(series([shifted]), "PT60M")


@pytest.mark.parametrize(
    "start,end,hours",
    [
        ("2026-03-29T00:00:00+01:00", "2026-03-30T00:00:00+02:00", 23),
        ("2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+01:00", 25),
    ],
)
def test_dst_energy_is_conserved(start, end, hours):
    a, b = utc(start), utc(end)
    points = [
        point(LoadPoint, 50).model_copy(update={"timestamp": a + timedelta(minutes=15 * i)})
        for i in range(hours * 4)
    ]
    hourly = resample(series(points, a, b), "PT60M")
    assert len(hourly.data) == hours
    assert sum(p.value for p in hourly.data) == 50 * hours
    with pytest.raises(InvalidQuery, match="aligned"):
        resample(series(points, a, b), "P1D")


def test_daily_bins_are_utc_24_hours():
    points = [point(LoadPoint, 50, i) for i in range(96)]
    daily = resample(series(points, end=START + timedelta(days=1)), "P1D")
    assert daily.data[0].value == 50
    assert daily.data[0].resolution == "P1D"

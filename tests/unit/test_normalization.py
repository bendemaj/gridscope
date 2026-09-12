from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import point
from pydantic import ValidationError

from gridscope.errors import InvalidQuery, MalformedResponse
from gridscope.models import GenerationType, PricePoint
from gridscope.normalization.time import date_range, resolution_delta, utc
from gridscope.normalization.units import power_mw, price_eur_mwh
from gridscope.normalization.zones import ZONES, zone_code
from gridscope.providers.entsoe.mappings import AREA_CODES, PRODUCTION_TYPES


@pytest.mark.parametrize(
    "value", ["2026-09-01", "2026-09-01T00:00:00Z", "2026-09-01T02:00:00+02:00"]
)
def test_utc(value):
    assert utc(value) == datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "value", ["not-a-date", "2026-09-01T12:00", datetime(2026, 1, 1), "2026-02-30"]
)
def test_bad_time(value):
    with pytest.raises(InvalidQuery):
        utc(value)


@pytest.mark.parametrize(
    "a,b,hours",
    [
        ("2026-03-29T00:00+01:00", "2026-03-30T00:00+02:00", 23),
        ("2026-10-25T00:00+02:00", "2026-10-26T00:00+01:00", 25),
    ],
)
def test_dst_days(a, b, hours):
    start, end = date_range(a, b)
    assert (end - start).total_seconds() / 3600 == hours


def test_dst_fold_and_nonexistent_local_time():
    tz = ZoneInfo("Europe/Vienna")
    assert utc(datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=0)) != utc(
        datetime(2026, 10, 25, 2, 30, tzinfo=tz, fold=1)
    )
    with pytest.raises(InvalidQuery):
        utc(datetime(2026, 3, 29, 2, 30, tzinfo=tz))


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-01-01", "2026-01-01"),
        ("2026-02-01", "2026-01-01"),
        ("2020-01-01", "2026-01-01"),
        ("2026-01-01T00:00:01Z", "2026-01-02"),
    ],
)
def test_invalid_ranges(start, end):
    with pytest.raises(InvalidQuery):
        date_range(start, end)


def test_zones_and_mapping():
    assert set(ZONES) == set(AREA_CODES)
    assert AREA_CODES["AT"] == "10YAT-APG------L"
    assert AREA_CODES["DE_LU"] == "10Y1001A1001A82H"
    assert zone_code(" de-lu ") == "DE_LU"
    with pytest.raises(InvalidQuery):
        zone_code("INVALID")
    assert PRODUCTION_TYPES["B16"] == GenerationType.SOLAR
    assert PRODUCTION_TYPES["B10"] == GenerationType.HYDRO_PUMPED_STORAGE
    assert PRODUCTION_TYPES["B25"] == GenerationType.ENERGY_STORAGE


@pytest.mark.parametrize(
    "unit,value,expected", [("MAW", 20, 20), ("KWT", 1000, 1), ("GW", 1, 1000), ("MW", None, None)]
)
def test_power(unit, value, expected):
    assert power_mw(value, unit) == expected


def test_units_not_assumed():
    with pytest.raises(MalformedResponse):
        power_mw(10, "MWH")
    with pytest.raises(MalformedResponse):
        price_eur_mwh(10, "GBP", "MWH")
    assert price_eur_mwh(-10, "EUR", "MWH") == -10
    assert resolution_delta("PT30M").total_seconds() == 1800


def test_model_validates_nonfinite_and_naive():
    with pytest.raises(ValidationError):
        point(PricePoint, float("nan"))
    with pytest.raises(ValidationError):
        point(PricePoint, float("inf"))
    assert point(PricePoint, -1).value == -1

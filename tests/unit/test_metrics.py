from datetime import datetime, timedelta

import pytest
from conftest import generation, point

from gridscope.errors import InvalidQuery
from gridscope.intelligence.metrics import (
    detect_anomalies,
    net_imports,
    price_spread,
    price_volatility,
    renewable_share,
    residual_load,
)
from gridscope.models import DataQuality, FlowPoint, GenerationType, LoadPoint, PricePoint


def test_renewable_share_and_zero():
    assert renewable_share(generation())[0].value == 20
    assert renewable_share(generation((0, 0, 0)))[0].value is None
    assert renewable_share(generation((100, None, 800)))[0].quality == DataQuality.INCOMPLETE


def test_storage_not_renewable():
    points = generation()
    points[0] = points[0].model_copy(
        update={"generation_type": GenerationType.HYDRO_PUMPED_STORAGE}
    )
    assert renewable_share(points)[0].value == 10


def test_missing_type_not_zero():
    points = [*generation(), *generation(i=1)[:2]]
    assert renewable_share(points)[1].value is None
    with pytest.raises(InvalidQuery):
        renewable_share([*generation(), generation()[0]])


def test_residual_load():
    assert residual_load([point(LoadPoint, 1000)], generation())[0].value == 800
    assert residual_load([point(LoadPoint, 1000)], [])[0].value is None
    assert residual_load([point(LoadPoint, None)], generation())[0].value is None


def test_alignment_is_explicit():
    loads = [point(LoadPoint, 1000)]
    gen = generation()
    gen[0] = gen[0].model_copy(update={"resolution": "PT60M"})
    with pytest.raises(InvalidQuery):
        residual_load(loads, gen)


def flow(origin, target, value):
    base = point(LoadPoint, value).model_dump(exclude={"zone"})
    return FlowPoint(**base, from_zone=origin, to_zone=target)


def test_net_imports_requires_both_directions():
    points = [flow("DE_LU", "AT", 500), flow("AT", "DE_LU", 200)]
    assert net_imports(points, "AT", ["DE_LU"])[0].value == 300
    assert net_imports(points[:1], "AT", ["DE_LU"])[0].value is None
    assert net_imports(points, "AT", ["DE_LU", "CZ"])[0].value is None
    assert net_imports([flow("AT", "DE_LU", 800), points[0]], "AT", ["DE_LU"])[0].value == -300
    with pytest.raises(InvalidQuery):
        net_imports([*points, points[0]], "AT", ["DE_LU"])


def test_rolling_std_and_gaps():
    prices = [point(PricePoint, v, i) for i, v in enumerate([1, 2, 3, 4])]
    result = price_volatility(prices, 3)
    assert [p.value for p in result] == [None, None, 1, 1]
    assert result[-1].timestamp == prices[-1].timestamp
    assert price_volatility([prices[0], *prices[2:]], 3)[-1].value is None
    with pytest.raises(InvalidQuery):
        price_volatility(prices, 1)


def test_zscore_excludes_current():
    prices = [point(PricePoint, v, i) for i, v in enumerate([1, 2, 3, 20])]
    result = detect_anomalies(prices, 3, 3)
    assert result[-1].baseline == 2
    assert result[-1].z_score == 18
    assert result[-1].is_anomaly
    assert result[0].is_anomaly is None


def test_constant_baseline_serializes_finitely():
    prices = [point(PricePoint, v, i) for i, v in enumerate([0, 0, 0, 10])]
    p = detect_anomalies(prices, 3)[-1]
    assert p.z_score is None and p.is_anomaly
    assert "Infinity" not in p.model_dump_json()


@pytest.mark.parametrize("hours,start", [(23, "2026-03-28T23:00Z"), (25, "2026-10-24T22:00Z")])
def test_spread_dst_calendar_day(hours, start):
    a = datetime.fromisoformat(start)
    prices = [
        point(PricePoint, float(i), i).model_copy(
            update={"timestamp": a + timedelta(minutes=15 * i)}
        )
        for i in range(hours * 4)
    ]
    result = price_spread(prices)
    assert len(result) == 1
    assert result[0].quality == DataQuality.DERIVED
    assert result[0].value == hours * 4 - 1
    assert result[0].period_end - result[0].timestamp == timedelta(hours=hours)
    assert price_spread(prices[:-1])[0].quality == DataQuality.INCOMPLETE

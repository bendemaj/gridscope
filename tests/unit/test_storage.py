from datetime import timedelta

import pytest
from conftest import END, START, generation, point

from gridscope.errors import InvalidQuery, NoData, StorageUnavailable
from gridscope.models import GenerationPoint, PricePoint, Series, SeriesMeta, TimeResolution
from gridscope.normalization.resampling import resample
from gridscope.storage import SQLiteStore


def prices(value=1, start=START, end=END, source="ENTSOE"):
    return Series(
        data=[
            point(value=value, i=i).model_copy(
                update={"source": source, "source_dataset": "prices", "source_revision": str(value)}
            )
            for i in range(4)
            if start <= START + timedelta(minutes=i * 15) < end
        ],
        meta=SeriesMeta(source=source, dataset="prices", zone="AT", start=start, end=end),
    )


def test_revisions_as_of_survive_restart_without_erasing_observations(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = SQLiteStore(path)
    first = prices(1)
    store.save(first)
    cutoff = store.history("ENTSOE", "prices", START, END, zone="AT")[0].recorded_at
    store.save(prices(2))
    store.close()
    reopened = SQLiteStore(path)
    try:
        old = reopened.read(PricePoint, "ENTSOE", "prices", START, END, zone="AT", as_of=cutoff)
        assert old.data == first.data
        latest = reopened.read(PricePoint, "ENTSOE", "prices", START, END, zone="AT")
        assert {p.value for p in latest.data} == {2}
        assert latest.data[0].source_revision == "2"
        assert len(reopened.history("ENTSOE", "prices", START, END, zone="AT")) == 2
        with pytest.raises(NoData):
            reopened.read(
                PricePoint,
                "ENTSOE",
                "prices",
                START,
                END,
                zone="AT",
                as_of=cutoff - timedelta(seconds=1),
            )
    finally:
        reopened.close()


def test_partial_refresh_replaces_only_its_interval_and_sources_are_isolated(tmp_path):
    store = SQLiteStore(tmp_path / "history.db")
    try:
        store.save(prices(1))
        store.save(prices(2, start=START + timedelta(minutes=30)))
        store.save(prices(99, source="SMARD"))
        latest = store.read(PricePoint, "ENTSOE", "prices", START, END, zone="AT")
        assert [p.value for p in latest.data] == [1, 1, 2, 2]
        with pytest.raises(NoData):
            store.read(PricePoint, "ENTSOE", "prices", START, END + timedelta(hours=1), zone="AT")
        with pytest.raises(NoData):
            store.read(PricePoint, "ENTSOE", "prices", START, END, zone="DE_LU")
    finally:
        store.close()


def test_new_snapshot_removes_omitted_technology_instead_of_reviving_old_values(tmp_path):
    store = SQLiteStore(tmp_path / "history.db")
    meta = SeriesMeta(source="ENTSOE", dataset="generation", zone="AT", start=START, end=END)
    try:
        data = generation()
        store.save(Series(data=data, meta=meta))
        store.save(Series(data=data[:1], meta=meta))
        latest = store.read(GenerationPoint, "ENTSOE", "generation", START, END, zone="AT")
        assert latest.data == data[:1]
        assert len(store.history("ENTSOE", "generation", START, END, zone="AT")[0].series.data) == 3
    finally:
        store.close()


def test_two_connections_and_unchanged_refetches_are_preserved(tmp_path):
    one, two = [SQLiteStore(tmp_path / "history.db") for _ in range(2)]
    try:
        one.save(prices())
        two.save(prices())
        snapshots = one.history("ENTSOE", "prices", START, END, zone="AT")
        assert len(snapshots) == 2
        assert snapshots[0].series.data == snapshots[1].series.data
        assert len(one.history("ENTSOE", "prices", START, END, zone="AT", limit=1)) == 1
        with pytest.raises(InvalidQuery):
            one.save(resample(prices(), "PT60M"))
    finally:
        one.close()
        two.close()
    with pytest.raises(StorageUnavailable):
        one.save(prices())


def test_resolution_revision_replaces_full_snapshot_but_partial_overlap_is_rejected(tmp_path):
    store = SQLiteStore(tmp_path / "history.db")
    try:
        hourly = prices()
        hourly.data = [hourly.data[0].model_copy(update={"resolution": TimeResolution.HOUR})]
        store.save(hourly)
        store.save(prices(2, start=START + timedelta(minutes=30)))
        with pytest.raises(InvalidQuery, match="incompatible interval"):
            store.read(PricePoint, "ENTSOE", "prices", START, END, zone="AT")
        store.save(prices(3))
        result = store.read(PricePoint, "ENTSOE", "prices", START, END, zone="AT")
        assert len(result.data) == 4 and all(p.value == 3 for p in result.data)
    finally:
        store.close()

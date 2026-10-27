"""Local append-only observation snapshots, with reproducible as-of reads."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TypeVar

from pydantic import BaseModel

from gridscope.errors import InvalidQuery, NoData, StorageUnavailable
from gridscope.models import FlowPoint, GenerationPoint, LoadPoint, PricePoint, Series
from gridscope.models.common import Point, UTCDateTime
from gridscope.normalization.time import DateInput, date_range, resolution_delta, utc

RawPoint = PricePoint | GenerationPoint | LoadPoint | FlowPoint
P = TypeVar("P", bound=Point)
MODELS: dict[str, type[Point]] = {
    "prices": PricePoint,
    "load": LoadPoint,
    "generation": GenerationPoint,
    "flows": FlowPoint,
}


class Snapshot(BaseModel):
    id: int
    recorded_at: UTCDateTime
    series: Series[RawPoint]


def _stamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds")


def _scope(zone: str | None, from_zone: str | None, to_zone: str | None) -> str:
    return f"{zone or ''}|{from_zone or ''}|{to_zone or ''}"


class SQLiteStore:
    """Every successful retrieval is a snapshot, including unchanged observations.

    Provider revision IDs remain untouched. recorded_at is local knowledge time.
    Snapshots preserve absent categories and revised interval layouts, not just values.
    """

    def __init__(self, path: str | Path) -> None:
        self._lock = RLock()
        self._closed = False
        try:
            if str(path) != ":memory:":
                Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(Path(path).expanduser()), check_same_thread=False)
            self._db.execute("PRAGMA busy_timeout=5000")
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                self._db.close()
                raise StorageUnavailable("Unsupported GridScope storage schema version.")
            self._db.execute("PRAGMA journal_mode=WAL")
            with self._db:
                self._db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, dataset TEXT NOT NULL,
                    scope TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
                    recorded_at TEXT NOT NULL, payload TEXT NOT NULL
                )""")
                self._db.execute("""CREATE INDEX IF NOT EXISTS snapshots_lookup
                    ON snapshots(source, dataset, scope, start, end, recorded_at)""")
                self._db.execute("PRAGMA user_version=1")
        except (sqlite3.Error, OSError):
            raise StorageUnavailable("Could not open the GridScope history database.") from None

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True

    def save(self, series: Series[P]) -> int:
        meta = series.meta
        model = MODELS.get(meta.dataset)
        if model is None or any(type(p) is not model for p in series.data):
            raise InvalidQuery(
                "Store only normalized raw datasets, before filtering or resampling."
            )
        if any(p.input_provenance or p.quality == "derived" for p in series.data):
            raise InvalidQuery("Derived observations cannot replace raw provider snapshots.")
        try:
            with self._lock, self._db:
                cursor = self._db.execute(
                    """INSERT INTO snapshots(source,dataset,scope,start,end,recorded_at,payload)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        meta.source,
                        meta.dataset,
                        _scope(meta.zone, meta.from_zone, meta.to_zone),
                        _stamp(meta.start),
                        _stamp(meta.end),
                        _stamp(datetime.now(UTC)),
                        series.model_dump_json(),
                    ),
                )
                assert cursor.lastrowid is not None
                return cursor.lastrowid
        except sqlite3.Error:
            raise StorageUnavailable("Could not persist the provider observations.") from None

    def history(
        self,
        source: str,
        dataset: str,
        start: DateInput,
        end: DateInput,
        *,
        zone: str | None = None,
        from_zone: str | None = None,
        to_zone: str | None = None,
        as_of: DateInput | None = None,
        limit: int | None = 100,
    ) -> list[Snapshot]:
        a, b = date_range(start, end)
        if dataset not in MODELS or (limit is not None and not 1 <= limit <= 1000):
            raise InvalidQuery("Use a raw dataset and history limit between 1 and 1000.")
        statement = """SELECT id, recorded_at, payload FROM snapshots
            WHERE source=? AND dataset=? AND scope=? AND start<? AND end>?
            AND recorded_at<=? ORDER BY recorded_at DESC, id DESC"""
        params: list[object] = [
            source,
            dataset,
            _scope(zone, from_zone, to_zone),
            _stamp(b),
            _stamp(a),
            _stamp(utc(as_of) if as_of is not None else datetime.max.replace(tzinfo=UTC)),
        ]
        if limit is not None:
            statement += " LIMIT ?"
            params.append(limit)
        try:
            with self._lock:
                rows = self._db.execute(statement, params).fetchall()
            return [
                Snapshot(
                    id=row[0],
                    recorded_at=row[1],
                    series=Series[RawPoint].model_validate_json(row[2]),
                )
                for row in reversed(rows)
            ]
        except (sqlite3.Error, ValueError):
            raise StorageUnavailable("Could not read the GridScope observation history.") from None

    def read(
        self,
        model: type[P],
        source: str,
        dataset: str,
        start: datetime,
        end: datetime,
        *,
        zone: str | None = None,
        from_zone: str | None = None,
        to_zone: str | None = None,
        as_of: DateInput | None = None,
    ) -> Series[P]:
        snapshots = self.history(
            source,
            dataset,
            start,
            end,
            zone=zone,
            from_zone=from_zone,
            to_zone=to_zone,
            as_of=as_of,
            limit=None,
        )
        if not snapshots:
            raise NoData("No stored observations match this scope and as-of time.")
        # Require full query coverage by snapshots; never silently fetch missing dates.
        cursor = start
        for a, b in sorted((s.series.meta.start, s.series.meta.end) for s in snapshots):
            if a > cursor:
                break
            cursor = max(cursor, b)
        if cursor < end:
            raise NoData("The requested interval has not been fully captured in storage.")
        points: list[P] = []
        warnings: list[str] = []
        for snapshot in snapshots:
            meta = snapshot.series.meta
            # A new publication replaces its entire query interval, including omissions.
            points = [p for p in points if not meta.start <= p.timestamp < meta.end]
            points.extend(
                model.model_validate(p.model_dump())
                for p in snapshot.series.data
                if start <= p.timestamp < end
            )
            warnings.extend(meta.warnings)
        ends: dict[tuple[object, ...], datetime] = {}
        for point in sorted(points, key=lambda p: p.timestamp):
            key = (getattr(point, "generation_type", None), getattr(point, "production_code", None))
            if key in ends and point.timestamp < ends[key]:
                raise InvalidQuery(
                    "Stored snapshots have incompatible interval boundaries. "
                    "Refresh the full range with aligned boundaries before combining it."
                )
            ends[key] = point.timestamp + resolution_delta(point.resolution)
        meta = snapshots[-1].series.meta.model_copy(deep=True)
        meta.start, meta.end = start, end
        meta.warnings = list(
            dict.fromkeys(
                warnings
                + [
                    "Stored observations only; newest snapshot wins within each captured interval.",
                ]
            )
        )
        return Series(data=sorted(points, key=lambda p: p.timestamp), meta=meta)

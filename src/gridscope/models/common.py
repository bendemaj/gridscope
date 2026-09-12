from datetime import datetime
from enum import StrEnum
from typing import Annotated, Generic, TypeVar

import pandas as pd
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from gridscope.normalization.time import utc

UTCDateTime = Annotated[datetime, BeforeValidator(utc)]


class DataQuality(StrEnum):
    OBSERVED = "observed"
    MISSING = "missing"
    DERIVED = "derived"
    INCOMPLETE = "incomplete"


class TimeResolution(StrEnum):
    QUARTER_HOUR = "PT15M"
    HALF_HOUR = "PT30M"
    HOUR = "PT60M"
    DAY = "P1D"


class Point(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    timestamp: UTCDateTime
    value: float | None
    unit: str
    resolution: TimeResolution
    source: str
    source_dataset: str
    retrieved_at: UTCDateTime
    quality: DataQuality = DataQuality.OBSERVED
    source_document: str | None = None
    source_revision: str | None = None
    source_series: str | None = None
    source_curve: str | None = None
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def check_missing(self) -> "Point":
        if self.value is None and self.quality == DataQuality.OBSERVED:
            raise ValueError("An observed point requires a value.")
        return self


T = TypeVar("T", bound=BaseModel)


class SeriesMeta(BaseModel):
    source: str
    dataset: str
    start: UTCDateTime
    end: UTCDateTime
    count: int = 0
    zone: str | None = None
    from_zone: str | None = None
    to_zone: str | None = None
    warnings: list[str] = Field(default_factory=list)
    attribution: str = "Source: ENTSO-E Transparency Platform. Normalized by GridScope."


class Series(BaseModel, Generic[T]):
    data: list[T]
    meta: SeriesMeta

    @model_validator(mode="after")
    def count_points(self) -> "Series[T]":
        self.meta.count = len(self.data)
        return self

    def to_dataframe(self) -> pd.DataFrame:
        frame = pd.DataFrame([point.model_dump(mode="python") for point in self.data])
        if "timestamp" in frame:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
            frame = frame.set_index("timestamp").sort_index()
        return frame

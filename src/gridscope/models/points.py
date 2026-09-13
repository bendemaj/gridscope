from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from gridscope.models.common import Point, UTCDateTime
from gridscope.normalization.zones import zone_code

ZoneCode = Annotated[str, BeforeValidator(zone_code)]


class GenerationType(StrEnum):
    BIOMASS = "biomass"
    LIGNITE = "lignite"
    COAL_GAS = "coal_gas"
    GAS = "gas"
    COAL = "coal"
    OIL = "oil"
    OIL_SHALE = "oil_shale"
    PEAT = "peat"
    GEOTHERMAL = "geothermal"
    HYDRO_PUMPED_STORAGE = "hydro_pumped_storage"
    HYDRO_RUN_OF_RIVER = "hydro_run_of_river"
    HYDRO_RESERVOIR = "hydro_reservoir"
    MARINE = "marine"
    NUCLEAR = "nuclear"
    OTHER_RENEWABLE = "other_renewable"
    SOLAR = "solar"
    WASTE = "waste"
    WIND_OFFSHORE = "wind_offshore"
    WIND_ONSHORE = "wind_onshore"
    OTHER = "other"
    ENERGY_STORAGE = "energy_storage"
    UNKNOWN = "unknown"


class PricePoint(Point):
    zone: ZoneCode
    source_auction_sequence: int | None = Field(default=None, ge=1)
    duplicate_source_series: tuple[str, ...] = ()
    currency: Literal["EUR"] = "EUR"
    unit: Literal["EUR/MWh"] = "EUR/MWh"


class LoadPoint(Point):
    zone: ZoneCode
    value: float | None = Field(ge=0)
    unit: Literal["MW"] = "MW"


class GenerationPoint(LoadPoint):
    generation_type: GenerationType
    production_code: str | None = None


class FlowPoint(Point):
    from_zone: ZoneCode
    to_zone: ZoneCode
    value: float | None = Field(ge=0)
    unit: Literal["MW"] = "MW"

    @model_validator(mode="after")
    def distinct_zones(self) -> "FlowPoint":
        if self.from_zone == self.to_zone:
            raise ValueError("Flow endpoints must differ.")
        return self


class MetricPoint(Point):
    zone: ZoneCode
    metric: str
    period_end: UTCDateTime | None = None


class AnomalyPoint(MetricPoint):
    observed: float | None
    baseline: float | None
    deviation: float | None
    z_score: float | None
    is_anomaly: bool | None

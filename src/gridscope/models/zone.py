from typing import Literal

from pydantic import BaseModel, ConfigDict


class Zone(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    name: str
    countries: tuple[str, ...]
    timezone: str
    active: bool = True
    area_type: Literal["bidding_zone", "country"] = "bidding_zone"

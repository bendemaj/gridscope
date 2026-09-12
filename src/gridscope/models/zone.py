from pydantic import BaseModel, ConfigDict


class Zone(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    name: str
    countries: tuple[str, ...]
    timezone: str
    active: bool = True

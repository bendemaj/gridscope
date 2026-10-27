from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)
    provider: Literal["entsoe", "smard"] = Field(
        default="entsoe", validation_alias="GRIDSCOPE_PROVIDER"
    )
    storage_path: Path | None = Field(default=None, validation_alias="GRIDSCOPE_STORAGE_PATH")
    entsoe_api_token: SecretStr | None = None
    timeout_seconds: float = Field(default=30, gt=0, validation_alias="GRIDSCOPE_TIMEOUT_SECONDS")
    max_retries: int = Field(default=3, ge=0, le=5, validation_alias="GRIDSCOPE_MAX_RETRIES")
    cache_ttl_seconds: float = Field(
        default=300, ge=0, validation_alias="GRIDSCOPE_CACHE_TTL_SECONDS"
    )

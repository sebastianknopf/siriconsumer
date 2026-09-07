from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIRI_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    state_dir: Path = Path("/app/state")
    log_level: str = "INFO"
    debug_siri_logging: bool = False
    spool_max_messages_per_subscription: int = Field(default=100, ge=1)
    spool_worker_count: int = Field(default=4, ge=1, le=64)
    spool_retry_base_seconds: float = Field(default=1.0, gt=0)
    spool_retry_max_seconds: float = Field(default=60.0, gt=0)
    spool_max_retries: int = Field(default=5, ge=0)
    direct_delivery_throttle_timeout_seconds: float = Field(default=5.0, gt=0)
    fetched_delivery_max_more_data_requests: int = Field(default=100, ge=0)
    provider_check_interval_seconds: float = Field(default=30.0, gt=0)
    provider_request_timeout_seconds: float = Field(default=20.0, gt=0)

    @property
    def database_path(self) -> Path:
        return self.state_dir / "siri.db"

    @property
    def spool_path(self) -> Path:
        return self.state_dir / "spool"

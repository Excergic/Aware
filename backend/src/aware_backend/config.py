from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AWARE_", extra="ignore")

    app_name: str = "aware-backend"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://user:password@localhost/aware"
    test_database_url: str | None = None

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    stun_server: str = "stun:stun.l.google.com:19302"
    frame_sample_interval_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

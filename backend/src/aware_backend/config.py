from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AWARE_", extra="ignore")

    app_name: str = "aware-backend"
    app_version: str = "0.1.0"
    environment: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()

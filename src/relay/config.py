from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: str = "data/relay.db"
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_path: str = "data/relay.db"
    agent_provider: str = "deterministic"
    agent_api_key: str | None = None
    agent_model: str = "gpt-5-mini"
    agent_base_url: str = "https://api.openai.com/v1"
    agent_timeout_seconds: float = 30
    max_investigation_steps: int = 20
    max_repeated_tool_calls: int = 2
    max_tool_retries: int = 1
    evaluation_results_path: str = "evaluation-results.json"
    seed_demo_data: bool = True
    fixture_telemetry_url: str = "http://localhost:8001"
    telemetry_timeout_seconds: float = 3
    telemetry_freshness_seconds: int = 60
    ripestat_base_url: str = "https://stat.ripe.net/data"
    ripestat_freshness_seconds: int = 43200
    model_config = SettingsConfigDict(env_prefix="RELAY_", env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()

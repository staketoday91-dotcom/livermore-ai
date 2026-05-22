from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Runtime configuration shared by all Antigravity services."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///antigravity.db"
    unusual_whales_token: str = ""
    uw_base_url: str = "https://api.unusualwhales.com/api"
    uw_client_api_id: Optional[str] = "100001"

    log_level: str = "INFO"
    agent_loop_interval_seconds: int = 300
    macro_interval_seconds: int = 3600
    sector_interval_seconds: int = 14400
    whale_interval_seconds: int = 120
    daily_limit_backoff_seconds: int = 3600

    min_option_premium: float = 100_000
    high_conviction_score: int = 65

    streamlit_port: int = 8501


@lru_cache
def get_settings() -> Settings:
    return Settings()


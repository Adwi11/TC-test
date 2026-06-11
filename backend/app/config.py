from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment / .env."""

    ollama_api_key: str = ""
    ollama_base_url: str = "https://ollama.com"
    extraction_model: str = "gpt-oss:120b-cloud"
    agent_model: str = "gpt-oss:120b-cloud"
    vision_model: str = "qwen3-vl:235b-cloud"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/resume_agent"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""

    resend_api_key: str = ""
    resend_from: str = ""

    max_upload_mb: int = 10
    cors_origins: str = "http://localhost:5173"
    cors_origin_regex: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def normalized_database_url(self) -> str:
        """Return DATABASE_URL rewritten to the asyncpg driver if needed."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        """Parse comma-separated CORS_ORIGINS into a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Memoised settings accessor."""
    return Settings()

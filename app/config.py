from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "cu013-agentic-ivr"
    app_version: str = "0.2.0"
    log_level: str = "INFO"

    # Google Cloud
    gcp_project_id: str = "planillas-acv-tivit"
    gcp_region: str = "us-east1"

    # Vertex AI / Gemini
    vertex_location: str = "global"
    vertex_model: str = "gemini-3.5-flash-lite"

    # Firestore
    firestore_database_id: str = "(default)"
    firestore_collection: str = "conversations"


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()

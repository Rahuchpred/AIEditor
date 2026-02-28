from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.constants import DEFAULT_MAX_BYTES, DEFAULT_MAX_DURATION_SECONDS


class Settings(BaseSettings):
    app_name: str = "AIEdit Feature 4 API"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/aiedit"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    storage_backend: str = "s3"
    s3_bucket_name: str = "aiedit-analysis"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    local_storage_path: str = ".local-storage"

    media_max_bytes: int = DEFAULT_MAX_BYTES
    media_max_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS

    task_execution_mode: str = "queue"

    elevenlabs_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AIEDIT_ELEVENLABS_API_KEY", "ELEVENLABS_API_KEY"),
    )
    elevenlabs_api_url: str = "https://api.elevenlabs.io/v1/speech-to-text"
    elevenlabs_model_id: str = Field(
        default="scribe_v1",
        validation_alias=AliasChoices("AIEDIT_ELEVENLABS_MODEL_ID", "ELEVENLABS_MODEL_ID"),
    )

    mistral_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AIEDIT_MISTRAL_API_KEY", "MISTRAL_API_KEY"),
    )
    mistral_api_url: str = "https://api.mistral.ai/v1/chat/completions"
    mistral_model: str = Field(
        default="mistral-small-latest",
        validation_alias=AliasChoices("AIEDIT_MISTRAL_MODEL", "MISTRAL_MODEL"),
    )
    provider_timeout_seconds: float = Field(default=60.0, ge=1.0)

    model_config = SettingsConfigDict(
        env_prefix="AIEDIT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

"""Application configuration.

Centralizes all settings so they can be overridden via environment variables
or a .env file without touching code. Uses pydantic-settings for validation.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with sensible defaults."""

    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = (
        "sqlite:////tmp/certificates.db"
        if os.getenv("VERCEL")
        else "sqlite:///./certificates.db"
    )
    certificates_dir: str = (
        "/tmp/generated_certificates"
        if os.getenv("VERCEL")
        else "generated_certificates"
    )
    uploaded_templates_dir: str = (
        "/tmp/uploaded_templates"
        if os.getenv("VERCEL")
        else "uploaded_templates"
    )
    max_recipients_per_job: int = 10000


settings = Settings()

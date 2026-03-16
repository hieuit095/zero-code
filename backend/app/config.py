"""
Application settings loaded from environment variables / `.env` file.

All secrets (API keys, sandbox URLs) are server-side only — never exposed to the frontend.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenHands (legacy REST mode — kept for backward compat)
    openhands_api_url: str = "http://localhost:3000"
    openhands_api_key: str = ""

    # LLM (used by OpenHands SDK)
    llm_api_key: str = ""
    llm_model: str = "anthropic/claude-sonnet-4-5-20250929"
    llm_base_url: str = ""

    # Workspace
    workspace_dir: str = "./workspaces"

    # CORS
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def workspace_path(self) -> Path:
        path = Path(self.workspace_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()

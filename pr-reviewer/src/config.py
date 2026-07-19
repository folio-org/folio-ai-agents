from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, populated from environment variables."""

    # AWS / Bedrock
    aws_region: str = "us-west-2"
    bedrock_model_id: str = "anthropic.claude-haiku-4-5-20251001-v1:0"
    bedrock_max_tokens: int = 4096
    bedrock_temperature: float = 0.1
    # bedrock_top_p is intentionally omitted: Bedrock Converse rejects requests
    # that specify both temperature and top_p for Claude models.
    bedrock_guardrail_id: str | None = None
    bedrock_guardrail_version: str | None = None

    # S3 bucket (shared by token budget and prompt templates)
    s3_token_bucket: str = "folio-ai-agents-prompts"
    s3_token_prefix: str = "token-usage"
    s3_prompts_bucket: str = "folio-ai-agents-prompts"
    s3_prompts_key: str = "prompts/v1/prompts.json"
    monthly_budget_dollars: float = 100.0

    # GitHub (optional — users supply tokens per-request)
    github_token: str | None = None
    github_app_id: str | None = None
    github_app_installation_id: str | None = None
    github_app_private_key: str | None = None
    github_app_bot_username: str = "folio-pr-reviewer[bot]"
    github_webhook_secret: str | None = None

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()

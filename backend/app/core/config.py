"""Application configuration.

Everything the application needs at runtime arrives through the environment so
the same image can run locally, in CI and in a customer environment. Secrets are
never written to logs (see :mod:`app.core.logging`) and never have defaults.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "production"]
LLMProviderName = Literal["openai", "fake"]
EmbeddingProviderName = Literal["openai", "local"]
ExecutorName = Literal["celery", "inline"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Product ---------------------------------------------------------------
    product_name: str = "Veriflow"
    product_tagline: str = "Evidence-verified AI investigations"
    app_env: AppEnv = "local"
    log_level: str = "INFO"

    # Persistence -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://veriflow:veriflow@localhost:5433/veriflow"
    test_database_url: str = "postgresql+psycopg://veriflow:veriflow@localhost:5433/veriflow_test"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_statement_timeout_ms: int = 30_000

    # Redis / Celery --------------------------------------------------------
    redis_url: str = "redis://localhost:6380/0"
    celery_broker_url: str = "redis://localhost:6380/1"
    celery_result_backend: str = "redis://localhost:6380/2"
    celery_queue: str = "veriflow"

    # Workflow --------------------------------------------------------------
    workflow_executor: ExecutorName = "celery"
    max_parallel_investigations: int = Field(default=4, ge=1, le=32)
    max_plan_tasks: int = Field(default=40, ge=1, le=200)
    max_investigation_candidates: int = Field(default=10, ge=1, le=50)
    max_tool_calls_per_task: int = Field(default=25, ge=1, le=200)
    max_retrieval_chunks: int = Field(default=8, ge=1, le=50)
    max_objective_chars: int = Field(default=4000, ge=50, le=20_000)
    task_max_retries: int = Field(default=3, ge=0, le=10)
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 30.0
    stale_task_timeout_seconds: int = 900

    # Risk engine thresholds ------------------------------------------------
    risk_threshold_critical: float = 75.0
    risk_threshold_high: float = 60.0
    risk_threshold_medium: float = 40.0
    risk_investigation_threshold: float = 45.0

    # LLM -------------------------------------------------------------------
    llm_provider: LLMProviderName = "fake"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 4096
    llm_structured_output_retries: int = Field(default=2, ge=0, le=5)
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    # Embeddings ------------------------------------------------------------
    embedding_provider: EmbeddingProviderName = "local"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 128
    chunk_target_chars: int = 900
    chunk_overlap_chars: int = 120

    # Cost model (USD per 1M tokens) ---------------------------------------
    llm_input_cost_per_mtok: float = 0.15
    llm_output_cost_per_mtok: float = 0.60
    embedding_cost_per_mtok: float = 0.02

    # Observability ---------------------------------------------------------
    otel_enabled: bool = False
    otel_service_name: str = "veriflow-api"
    otel_exporter_otlp_endpoint: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Web / security --------------------------------------------------------
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    api_key: str | None = None
    api_max_page_size: int = Field(default=100, ge=1, le=500)
    api_max_request_bytes: int = 256_000

    # Failure injection -----------------------------------------------------
    failure_injection_enabled: bool = False
    llm_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    vector_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    api_failure_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # Synthetic data --------------------------------------------------------
    seed_random_seed: int = 20260301
    seed_customer_count: int = Field(default=3000, ge=1, le=50_000)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "openai_api_key",
        "api_key",
        "langfuse_public_key",
        "langfuse_secret_key",
        "otel_exporter_otlp_endpoint",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return origins or [self.frontend_url]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failure_injection_active(self) -> bool:
        """Failure injection can never be active in production, whatever the env says."""
        return self.failure_injection_enabled and not self.is_production

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_llm_provider(self) -> LLMProviderName:
        """Fall back to the deterministic provider when no live credential exists.

        This keeps the whole platform runnable (and testable) without a paid API
        key instead of failing at the first agent call.
        """
        if self.llm_provider == "openai" and not self.openai_api_key:
            return "fake"
        return self.llm_provider

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_embedding_provider(self) -> EmbeddingProviderName:
        if self.embedding_provider == "openai" and not self.openai_api_key:
            return "local"
        return self.embedding_provider

    @computed_field  # type: ignore[prop-decorator]
    @property
    def langfuse_configured(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Always reach for configuration through this function rather than importing a
    module-level instance: tests override individual fields on the cached object
    (``monkeypatch.setattr(get_settings(), "max_parallel_investigations", 1)``)
    and every caller must observe the same change.
    """
    return Settings()


def reload_settings() -> Settings:
    """Re-read the environment. Used by tests that patch ``os.environ``."""
    get_settings.cache_clear()
    return get_settings()

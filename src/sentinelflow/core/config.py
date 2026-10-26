"""Application settings loaded from environment variables and an optional .env file."""

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    The database URL is optional so the process can start and serve liveness
    checks before PostgreSQL is provisioned. Authentication fails closed when
    the JWT secret is missing or too short.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "SentinelFlow"
    app_env: str = "development"
    debug: bool = False
    database_url: str | None = None

    jwt_secret: SecretStr | None = None
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    jwt_issuer: str = Field(default="sentinelflow", min_length=1, max_length=64)
    jwt_audience: str = Field(default="sentinelflow-api", min_length=1, max_length=64)

    # Login throttling. Enforced through the database, so it works across
    # processes that share one database (see docs/ARCHITECTURE.md).
    login_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    login_rate_limit_ip_attempts: int = Field(default=20, ge=1, le=1000)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1, le=86400)

    # AI agent. Every field is optional: when the model is not configured the
    # rest of the API keeps working and only the investigation endpoint fails
    # closed with an explicit configuration error.
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_base: str | None = None
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    agent_max_rounds: int = Field(default=5, ge=1, le=20)
    agent_max_tool_calls: int = Field(default=8, ge=1, le=50)
    agent_tool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    #: A 'running' investigation whose lease expired is treated as interrupted.
    #: Must exceed the worst-case run time (rounds x model timeout).
    agent_stale_after_seconds: int = Field(default=600, ge=60, le=7200)
    #: Hard wall-clock ceiling for one investigation. Enforced inside the agent
    #: loop, so a run cannot outlive its lease no matter how slow the provider is.
    agent_max_runtime_seconds: int = Field(default=180, ge=30, le=1800)
    #: Refuse new investigations when this many are queued or running.
    agent_max_pending: int = Field(default=50, ge=1, le=1000)

    # Durable queue. Tasks live in the database; a single in-process worker
    # claims them with a lease. No Redis/Celery: one node, one queue table.
    agent_worker_enabled: bool = True
    agent_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)
    #: Must be greater than agent_max_runtime_seconds, otherwise a healthy but
    #: slow run would have its lease expire and be executed twice.
    agent_lease_seconds: int = Field(default=240, ge=30, le=3600)
    agent_max_attempts: int = Field(default=2, ge=1, le=5)
    agent_retry_backoff_seconds: int = Field(default=5, ge=0, le=300)

    #: Largest accepted request body. Anything bigger is rejected before parsing.
    max_request_body_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)

    @model_validator(mode="after")
    def _lease_must_outlive_a_run(self) -> "Settings":
        """A healthy run must never lose its lease and be executed twice."""
        if self.agent_lease_seconds <= self.agent_max_runtime_seconds:
            raise ValueError(
                "AGENT_LEASE_SECONDS must be greater than "
                "AGENT_MAX_RUNTIME_SECONDS, otherwise a slow run can be "
                "claimed twice"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()

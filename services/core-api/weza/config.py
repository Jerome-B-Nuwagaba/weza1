"""Runtime configuration. Every secret comes from the environment (TSD §69) — never from the repo."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field("local", description="local | dev | test | uat | production")
    database_url: str = "postgresql+psycopg://weza:weza@localhost:5432/weza"

    # Secrets. Defaults are for LOCAL/TEST only; production refuses to start with them (see main.py).
    secret_key: str = "local-dev-secret-change-me-0123456789abcdef"
    vault_master_key: str = "bG9jYWwtZGV2LXZhdWx0LWtleS0zMmJ5dGVzLWxvbmch"  # base64, 32 bytes
    blind_index_key: str = "local-dev-blind-index-key"

    cors_origins: str = "http://localhost:3000"
    public_web_url: str = "http://localhost:3000"

    # Behaviour flags
    run_worker_inprocess: bool = True
    worker_poll_seconds: float = 2.0
    seed_demo: bool = False
    demo_mode: bool = True  # shows demo banners, allows OTP display delivery
    mfa_enforced: bool = False  # production: True (blueprint §10.6)

    # OTP (TSD §13)
    otp_delivery: str = "display"  # display | sms
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_max_resends: int = 3
    otp_resend_cooldown_seconds: int = 30

    # AI control plane (TSD §8, §76–77)
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_timeout_seconds: float = 20.0
    ai_server_fallbacks: bool = True

    # Channels
    whatsapp_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_verify_token: str | None = None
    sms_provider: str = "console"
    smtp_url: str | None = None

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    customer_session_days: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Render/Neon give postgres:// or postgresql:// — normalise to the psycopg3 driver.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()

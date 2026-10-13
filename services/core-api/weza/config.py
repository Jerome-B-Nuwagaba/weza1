"""Runtime configuration. Every secret comes from the environment (TSD §69) — never from the repo."""

import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER = "REPLACE_ME"


def is_configured(value: str | None) -> bool:
    """False for unset, blank or the REPLACE_ME template placeholder (case-insensitive)."""
    v = (value or "").strip()
    return bool(v) and v.upper() != PLACEHOLDER


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

    # Channels. A value that is empty, unset or the template placeholder (REPLACE_ME) means NOT CONFIGURED:
    # the app then stays in simulator/console mode and never calls Meta or an SMS provider.
    # >>> USER INPUT REQUIRED: real WhatsApp Cloud API values (Meta developer dashboard → WhatsApp → API Setup,
    # and App settings → Basic for the app secret). Put them ONLY in services/core-api/.env (untracked).
    whatsapp_token: str | None = None  # permanent/system-user access token
    whatsapp_phone_number_id: str | None = None  # "Phone number ID" (not the phone number itself)
    whatsapp_app_secret: str | None = None  # signs inbound webhooks (X-Hub-Signature-256)
    whatsapp_verify_token: str | None = None  # any string you choose; must match the Meta webhook form
    whatsapp_api_version: str = "v21.0"  # Graph API version, e.g. v21.0
    whatsapp_business_account_id: str | None = None  # WABA id — only needed later for templates
    whatsapp_business_number: str | None = None  # public business number (digits) for the "Continue on WhatsApp" link
    # >>> USER INPUT REQUIRED: SMS provider for real OTP delivery. console/simulator = no real SMS.
    sms_provider: str = "console"
    sms_api_key: str | None = None
    sms_username: str | None = None
    sms_sender_id: str | None = None
    smtp_url: str | None = None

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    customer_session_days: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def whatsapp_send_ready(self) -> bool:
        return is_configured(self.whatsapp_token) and is_configured(self.whatsapp_phone_number_id)

    @property
    def whatsapp_webhook_ready(self) -> bool:
        return is_configured(self.whatsapp_app_secret)

    @property
    def whatsapp_verify_ready(self) -> bool:
        return is_configured(self.whatsapp_verify_token)

    @property
    def graph_api_version(self) -> str:
        v = (self.whatsapp_api_version or "").strip()
        return v if re.fullmatch(r"v\d{1,3}\.\d{1,2}", v) else "v21.0"

    @property
    def sms_provider_name(self) -> str:
        """Active real SMS provider, or 'console' when unset/placeholder/simulator."""
        p = (self.sms_provider or "").strip().lower()
        return "console" if p in ("", "console", "simulator") or not is_configured(p) else p

    @property
    def sms_ready(self) -> bool:
        """A real SMS provider is named and has an API key (provider classes may require more)."""
        return self.sms_provider_name != "console" and is_configured(self.sms_api_key)

    def channel_config_summary(self) -> dict:
        """Names only, never values — safe to log."""
        flags = {
            "WHATSAPP_APP_SECRET": self.whatsapp_webhook_ready, "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_ready,
            "WHATSAPP_TOKEN": is_configured(self.whatsapp_token),
            "WHATSAPP_PHONE_NUMBER_ID": is_configured(self.whatsapp_phone_number_id),
            "WHATSAPP_BUSINESS_NUMBER": is_configured(self.whatsapp_business_number),
            "WHATSAPP_BUSINESS_ACCOUNT_ID": is_configured(self.whatsapp_business_account_id),
            "SMS_PROVIDER": self.sms_provider_name != "console", "SMS_API_KEY": is_configured(self.sms_api_key),
            "SMS_USERNAME": is_configured(self.sms_username), "SMS_SENDER_ID": is_configured(self.sms_sender_id),
        }
        return {"configured": [k for k, v in flags.items() if v], "missing": [k for k, v in flags.items() if not v],
                "whatsapp_outbound": "live" if self.whatsapp_send_ready else "simulator",
                "whatsapp_webhook": "enabled" if self.whatsapp_webhook_ready else "disabled",
                "sms_outbound": ("provider" if self.sms_ready else "provider_incomplete")
                if self.sms_provider_name != "console" else "console",
                "verification_sms": self.sms_ready or not self.is_production}

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

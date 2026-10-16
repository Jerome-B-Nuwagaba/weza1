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
    sms_provider: str = "console"  # console | simulator | africastalking | twilio | infobip
    africastalking_username: str | None = None  # "sandbox" uses the Africa's Talking sandbox
    africastalking_api_key: str | None = None
    africastalking_sender_id: str | None = None  # registered alphanumeric sender, optional
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from: str | None = None  # E.164 number or Messaging Service SID (MG…)
    infobip_base_url: str | None = None  # your account's API base, e.g. https://xxxxx.api.infobip.com
    infobip_api_key: str | None = None
    infobip_sender: str | None = None  # registered sender ID or number, optional
    smtp_url: str | None = None  # smtp://user:pass@host:587 (STARTTLS) or smtps://user:pass@host:465 (TLS)
    smtp_from: str | None = None  # e.g. "WEZA <noreply@weza.africa>"; defaults to the SMTP username

    # Document malware scanning (blueprint C7): basic is for test only; production uses ClamAV (clamd)
    malware_scanner: str = "basic"  # basic | clamav
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0

    access_token_minutes: int = 15
    refresh_token_days: int = 7
    customer_session_days: int = 30

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    def production_problems(self) -> list[str]:
        """Go-live blockers that can be checked from configuration (blueprint 13). Empty means ready."""
        problems = []
        if "local-dev" in self.secret_key or "bG9jYWwtZGV2" in self.vault_master_key \
                or "local-dev" in self.blind_index_key:
            problems.append("development secrets (SECRET_KEY / VAULT_MASTER_KEY / BLIND_INDEX_KEY)")
        if not self.mfa_enforced:
            problems.append("MFA_ENFORCED is not true")
        if self.otp_delivery != "sms":
            problems.append("OTP_DELIVERY must be sms")
        if self.sms_provider == "africastalking":
            if not (self.africastalking_username and self.africastalking_api_key):
                problems.append("AFRICASTALKING_USERNAME / AFRICASTALKING_API_KEY missing")
            elif self.africastalking_username == "sandbox":
                problems.append("Africa's Talking sandbox account in production")
        elif self.sms_provider == "twilio":
            if not (self.twilio_account_sid and self.twilio_auth_token and self.twilio_from):
                problems.append("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM missing")
        elif self.sms_provider == "infobip":
            if not (self.infobip_base_url and self.infobip_api_key):
                problems.append("INFOBIP_BASE_URL / INFOBIP_API_KEY missing")
        else:
            problems.append(f"SMS_PROVIDER '{self.sms_provider}' does not deliver messages")
        if self.malware_scanner != "clamav":
            problems.append("MALWARE_SCANNER must be clamav (the basic scanner is for testing)")
        if not self.smtp_url:
            problems.append("SMTP_URL missing (staff email alerts)")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list the web origins, not *")
        return problems

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

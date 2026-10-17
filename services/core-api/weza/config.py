"""Runtime configuration. Every secret comes from the environment (TSD §69) — never from the repo."""

import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER = "REPLACE_ME"
# Meta Graph API version used when WHATSAPP_API_VERSION is unset or malformed. v25.0 is supported until 2028-07-29
# (developers.facebook.com/docs/graph-api/changelog/versions); v21.0, the previous default, expires 2027-01-21.
DEFAULT_GRAPH_API_VERSION = "v25.0"


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
    whatsapp_api_version: str = DEFAULT_GRAPH_API_VERSION  # Graph API version, e.g. v25.0
    whatsapp_business_account_id: str | None = None  # WABA id — only needed later for templates
    # Verification codes through WhatsApp (SMS_PROVIDER=whatsapp). Outside the 24-hour window Meta only delivers an
    # approved AUTHENTICATION template; leave the name blank to send a plain message (WhatsApp-started journeys only).
    # >>> USER INPUT REQUIRED: create the template in Meta (WhatsApp Manager → Message templates → Authentication,
    # with the copy-code button), wait for approval, then put its exact name here.
    whatsapp_otp_template_name: str | None = None
    whatsapp_otp_template_language: str = "en"
    whatsapp_business_number: str | None = None  # public business number (digits) for the "Continue on WhatsApp" link
    # Embedded Signup (Tech Provider) onboarding of the organisation's WhatsApp Business app number (coexistence).
    # Not secrets: the app ID and the Facebook Login for Business configuration ID are visible in the browser.
    # >>> USER INPUT REQUIRED: Meta app → App settings → Basic → App ID; Facebook Login for Business → Configurations.
    whatsapp_app_id: str | None = None
    whatsapp_embedded_signup_config_id: str | None = None
    # >>> USER INPUT REQUIRED: SMS provider for real OTP delivery. console/simulator = no real SMS.
    # Built in: africastalking | twilio | infobip (credentials below) | whatsapp (codes via the WhatsApp Cloud API).
    # Any other name is looked up in the provider-agnostic slot (notification/sms.py, SMS_API_KEY/USERNAME/SENDER_ID).
    sms_provider: str = "console"
    sms_api_key: str | None = None
    sms_username: str | None = None
    sms_sender_id: str | None = None
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

    # Identity verification of loan applicants against a registry: simulator (demo/test) | gnugrid
    identity_provider: str = "simulator"
    identity_verification_required: bool = False  # true: requests are only shared once the NIN is verified
    gnugrid_base_url: str | None = None
    gnugrid_api_key: str | None = None
    gnugrid_verify_path: str = "/v1/identity/verify"  # confirm against gnuGRID's API documentation
    # gnuGRID CRB, Just-In-Time: pulled only when an applicant has selected a lender and completes gnuGRID's consent
    # OTP. The mock is free and makes no network calls (dev, staging, CI); production refuses it.
    gngrid_use_mock: bool = True
    gnugrid_timeout_seconds: float = 10.0
    gnugrid_crb_otp_path: str = "/v1/crb/consent/otp"  # confirm against gnuGRID's API documentation
    gnugrid_crb_verify_path: str = "/v1/crb/consent/verify"  # confirm against gnuGRID's API documentation

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
        elif self.sms_provider_name == "whatsapp":
            if not self.whatsapp_send_ready:
                problems.append("SMS_PROVIDER=whatsapp needs WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID")
        else:
            problems.append(f"SMS_PROVIDER '{self.sms_provider}' does not deliver messages")
        if self.identity_provider == "gnugrid":
            if not (self.gnugrid_base_url and self.gnugrid_api_key):
                problems.append("GNUGRID_BASE_URL / GNUGRID_API_KEY missing")
        else:
            problems.append(f"IDENTITY_PROVIDER '{self.identity_provider}' would mark applicants verified without a "
                            "real registry check")
        if self.gngrid_use_mock:
            problems.append("GNGRID_USE_MOCK is true — credit bureau reports would be simulated")
        elif not (self.gnugrid_base_url and self.gnugrid_api_key):
            problems.append("GNUGRID_BASE_URL / GNUGRID_API_KEY missing (CRB)")
        if self.malware_scanner != "clamav":
            problems.append("MALWARE_SCANNER must be clamav (the basic scanner is for testing)")
        if not self.smtp_url:
            problems.append("SMTP_URL missing (staff email alerts)")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list the web origins, not *")
        return problems

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
        return v if re.fullmatch(r"v\d{1,3}\.\d{1,2}", v) else DEFAULT_GRAPH_API_VERSION

    @property
    def whatsapp_embedded_signup_missing(self) -> list[str]:
        """Setting names Embedded Signup still needs (the code exchange uses the app ID + app secret)."""
        need = {"WHATSAPP_APP_ID": self.whatsapp_app_id,
                "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": self.whatsapp_embedded_signup_config_id,
                "WHATSAPP_APP_SECRET": self.whatsapp_app_secret}
        return [k for k, v in need.items() if not is_configured(v)]

    @property
    def whatsapp_app_secret_format_ok(self) -> bool:
        """Meta app secrets are 32 hex characters; anything else will fail every webhook signature check."""
        return bool(re.fullmatch(r"[0-9a-fA-F]{32}", (self.whatsapp_app_secret or "").strip()))

    @property
    def sms_provider_name(self) -> str:
        """Active real SMS provider, or 'console' when unset/placeholder/simulator."""
        p = (self.sms_provider or "").strip().lower()
        return "console" if p in ("", "console", "simulator") or not is_configured(p) else p

    @property
    def whatsapp_public_number(self) -> str | None:
        """Business number for the landing-page wa.me link: digits only (country code, no +), 8–15 digits."""
        if not is_configured(self.whatsapp_business_number):
            return None
        digits = re.sub(r"\D", "", self.whatsapp_business_number or "")
        return digits if 8 <= len(digits) <= 15 else None

    @property
    def sms_ready(self) -> bool:
        """A real SMS provider is named and has an API key (provider classes may require more)."""
        name = self.sms_provider_name
        if name == "whatsapp":  # codes ride the WhatsApp Cloud API credentials
            return self.whatsapp_send_ready
        if name == "africastalking":
            return bool(self.africastalking_username and self.africastalking_api_key)
        if name == "twilio":
            return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from)
        if name == "infobip":
            return bool(self.infobip_base_url and self.infobip_api_key)
        return name != "console" and is_configured(self.sms_api_key)

    def channel_config_summary(self) -> dict:
        """Names only, never values — safe to log."""
        flags = {
            "WHATSAPP_APP_SECRET": self.whatsapp_webhook_ready, "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_ready,
            "WHATSAPP_TOKEN": is_configured(self.whatsapp_token),
            "WHATSAPP_PHONE_NUMBER_ID": is_configured(self.whatsapp_phone_number_id),
            "WHATSAPP_BUSINESS_NUMBER": is_configured(self.whatsapp_business_number),
            "WHATSAPP_OTP_TEMPLATE_NAME": is_configured(self.whatsapp_otp_template_name),
            "WHATSAPP_BUSINESS_ACCOUNT_ID": is_configured(self.whatsapp_business_account_id),
            "WHATSAPP_APP_ID": is_configured(self.whatsapp_app_id),
            "WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID": is_configured(self.whatsapp_embedded_signup_config_id),
            "SMS_PROVIDER": self.sms_provider_name != "console", "SMS_API_KEY": is_configured(self.sms_api_key),
            "SMS_USERNAME": is_configured(self.sms_username), "SMS_SENDER_ID": is_configured(self.sms_sender_id),
        }
        return {"configured": [k for k, v in flags.items() if v], "missing": [k for k, v in flags.items() if not v],
                "whatsapp_outbound": "live" if self.whatsapp_send_ready else "simulator",
                "whatsapp_webhook": "enabled" if self.whatsapp_webhook_ready else "disabled",
                "sms_outbound": ("provider" if self.sms_ready else "provider_incomplete")
                if self.sms_provider_name != "console" else "console",
                "verification_sms": self.sms_ready or not self.is_production,
                # names only: a configured value that cannot be right (e.g. an app secret that is not 32 hex chars)
                "warnings": ["WHATSAPP_APP_SECRET_FORMAT"]
                if self.whatsapp_webhook_ready and not self.whatsapp_app_secret_format_ok else []}

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

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development").lower()
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    allowed_origins_raw: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    trusted_hosts_raw: str = os.getenv("TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
    enable_in_process_scheduler: bool = os.getenv("ENABLE_IN_PROCESS_SCHEDULER", "true").lower() == "true"
    sync_interval_hours: int = int(os.getenv("SYNC_INTERVAL_HOURS", "6"))
    cron_secret: str = os.getenv("CRON_SECRET", "")
    credit_consent_version: str = os.getenv("CREDIT_CONSENT_VERSION", "v1")
    privacy_version: str = os.getenv("PRIVACY_VERSION", "v1")
    terms_version: str = os.getenv("TERMS_VERSION", "v1")
    beta_invite_required: bool = os.getenv("BETA_INVITE_REQUIRED", "true").lower() == "true"
    beta_invite_codes_raw: str = os.getenv("BETA_INVITE_CODES", "ICE800-BETA")
    beta_cohort: str = os.getenv("BETA_COHORT", "founder-beta")
    beta_invite_single_use: bool = os.getenv("BETA_INVITE_SINGLE_USE", "true").lower() == "true"
    android_package_name: str = os.getenv("ANDROID_PACKAGE_NAME", "com.ice800.app")
    default_language: str = os.getenv("DEFAULT_LANGUAGE", "es")
    method_env: str = os.getenv("METHOD_ENV", "dev")
    engine_enabled: bool = os.getenv("ENGINE_ENABLED", "false").lower() == "true"
    payments_enabled: bool = os.getenv("PAYMENTS_ENABLED", "false").lower() == "true"
    applications_enabled: bool = os.getenv("APPLICATIONS_ENABLED", "false").lower() == "true"

    @property
    def beta_invite_codes(self) -> list[str]:
        return [x.strip() for x in self.beta_invite_codes_raw.split(",") if x.strip()]

    @property
    def allowed_origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins_raw.split(",") if x.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [x.strip() for x in self.trusted_hosts_raw.split(",") if x.strip()]

    @property
    def plaid_webhook_url(self) -> str:
        return os.getenv("PLAID_WEBHOOK_URL", f"{self.public_base_url}/api/plaid/webhook")

    @property
    def plaid_redirect_uri(self) -> str | None:
        return os.getenv("PLAID_REDIRECT_URI") or None

    def validate(self) -> None:
        if self.app_env != "production":
            return
        required = {
            "JWT_SECRET": os.getenv("JWT_SECRET", ""),
            "FERNET_KEY": os.getenv("FERNET_KEY", ""),
            "CRON_SECRET": self.cron_secret,
            "PUBLIC_BASE_URL": os.getenv("PUBLIC_BASE_URL", ""),
            "PLAID_CLIENT_ID": os.getenv("PLAID_CLIENT_ID", ""),
            "PLAID_SECRET": os.getenv("PLAID_SECRET", ""),
            "CLERK_PUBLISHABLE_KEY": os.getenv("CLERK_PUBLISHABLE_KEY", ""),
            "CLERK_SECRET_KEY": os.getenv("CLERK_SECRET_KEY", ""),
        }
        missing = [k for k, v in required.items() if not v or "replace" in v.lower() or "change-this" in v.lower()]
        if missing:
            raise RuntimeError(f"Production configuration incomplete: {', '.join(missing)}")


settings = Settings()

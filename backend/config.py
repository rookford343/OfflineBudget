from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/budget.db"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: str = "*"
    FRONTEND_URL: str | None = None  # base URL for links in emails; falls back to first ALLOWED_ORIGINS entry
    # HOST/PORT removed 2026-08-15: nothing ever read them. Both the Docker
    # CMD and scripts/start.sh pass --host/--port to uvicorn directly, so
    # setting them in .env silently did nothing -- and the Settings page was
    # listing them as real configuration. Pass the flags to uvicorn instead.

    # Email / SMTP (all optional — app runs fine without these)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_FROM: str | None = None
    DAILY_SUMMARY_HOUR: int = 7  # 24-hour local time to send daily summaries
    WEEKLY_DIGEST_DAY: str = "fri"    # APScheduler cron day_of_week value -- the day the Weekly
    # Digest section (spending by category, top merchants, balance risk) gets appended to that
    # day's Daily Summary email.
    #
    # WEEKLY_DIGEST_HOUR removed 2026-08-15: it stopped meaning anything once the
    # digest became an addendum to the Daily Summary rather than its own email.
    WEEKLY_DIGEST_ENABLED: bool = False
    # Legacy name for the flag above. It was never actually a recipient list --
    # any non-blank value just meant "enabled" -- which made it a genuine
    # footgun: setting DIGEST_RECIPIENTS=wife@example.com looked like it would
    # deliver there and silently did nothing of the sort. Honoured so existing
    # .env files keep working; recipients now live in the REPORT_RECIPIENTS
    # app setting (Settings -> Notifications & Email).
    DIGEST_RECIPIENTS: str = ""
    BANK_TOKEN_ENCRYPTION_KEY: str | None = None  # Fernet key for encrypting SimpleFIN access URLs at rest
    # Same Fernet key, honest name: it now protects every secret at rest, not
    # only bank tokens (the SMTP password stored via the Settings page uses it
    # too). Falls back to BANK_TOKEN_ENCRYPTION_KEY so existing .env files
    # keep working unchanged -- see app_encryption_key below.
    APP_ENCRYPTION_KEY: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def frontend_url(self) -> str:
        if self.FRONTEND_URL:
            return self.FRONTEND_URL.rstrip("/")
        return self.allowed_origins_list[0].rstrip("/")

    @property
    def weekly_digest_enabled(self) -> bool:
        """New flag wins; the legacy DIGEST_RECIPIENTS is treated as the
        boolean it always really was (any non-blank value = enabled)."""
        return self.WEEKLY_DIGEST_ENABLED or bool(self.DIGEST_RECIPIENTS.strip())

    @property
    def app_encryption_key(self) -> str | None:
        """One Fernet key for every secret at rest. APP_ENCRYPTION_KEY is the
        name going forward; BANK_TOKEN_ENCRYPTION_KEY is honoured so existing
        deployments (and Dan's live .env) need no change."""
        return self.APP_ENCRYPTION_KEY or self.BANK_TOKEN_ENCRYPTION_KEY


settings = Settings()

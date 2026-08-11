from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/budget.db"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: str = "*"
    FRONTEND_URL: str | None = None  # base URL for links in emails; falls back to first ALLOWED_ORIGINS entry
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Email / SMTP (all optional — app runs fine without these)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_FROM: str | None = None
    DAILY_SUMMARY_HOUR: int = 7  # 24-hour local time to send daily summaries
    WEEKLY_DIGEST_DAY: str = "fri"    # APScheduler cron day_of_week value -- the day the Weekly
    # Digest section (spending by category, top merchants, balance risk) gets appended to that
    # day's Daily Summary email. WEEKLY_DIGEST_HOUR is unused now that the digest rides along in
    # the Daily Summary rather than sending as its own email at its own time.
    WEEKLY_DIGEST_HOUR: int = 7       # unused (kept for backward-compat with existing .env files)
    DIGEST_RECIPIENTS: str = ""       # on/off switch only now -- blank disables the Weekly Digest
    # addendum entirely (Daily Summary still sends). The addresses here are no longer used for
    # delivery; the digest goes to each user's own email (same recipients as the Daily Summary).
    BANK_TOKEN_ENCRYPTION_KEY: str | None = None  # Fernet key for encrypting SimpleFIN access URLs at rest

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
    def digest_recipients_list(self) -> list[str]:
        return [e.strip() for e in self.DIGEST_RECIPIENTS.split(",") if e.strip()]


settings = Settings()

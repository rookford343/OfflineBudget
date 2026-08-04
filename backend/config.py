from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./data/budget.db"
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_DAYS: int = 7
    ALLOWED_ORIGINS: str = "*"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Email / SMTP (all optional — app runs fine without these)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_FROM: str | None = None
    DAILY_SUMMARY_HOUR: int = 7  # 24-hour local time to send daily summaries
    WEEKLY_DIGEST_DAY: str = "fri"    # APScheduler cron day_of_week value
    WEEKLY_DIGEST_HOUR: int = 7       # 24-hour local time
    DIGEST_RECIPIENTS: str = ""       # comma-separated email addresses

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",")]

    @property
    def digest_recipients_list(self) -> list[str]:
        return [e.strip() for e in self.DIGEST_RECIPIENTS.split(",") if e.strip()]


settings = Settings()

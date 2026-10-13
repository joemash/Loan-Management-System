"""Application settings (equivalent of ``application.properties``).

Every field can be overridden by an environment variable with the same name in upper case
(e.g. ``DATABASE_URL``, ``AUTH_JWT_SECRET``). A local ``.env`` file is also read when present.
"""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "lms"

    database_url: str = "postgresql+psycopg://ezra_admin:ezra_admin_pass@localhost:5433/ezra_lms"
    database_echo: bool = False

    penalty_daily_rate: Decimal = Decimal("0.001")
    loan_default_after_days_past_due: int = 90
    reminder_days_before_due: int = 3

    scheduling_enabled: bool = True
    # Spring-style 6-field cron: second minute hour day-of-month month day-of-week (use mon..sun names).
    scheduler_overdue_cron: str = "0 0 1 * * *"
    scheduler_reminder_cron: str = "0 0 8 * * *"

    notifications_kafka_enabled: bool = True
    notifications_kafka_bootstrap_servers: str = "localhost:9092"
    notifications_kafka_topic: str = "notifications.events"
    notifications_kafka_group_id: str = "lms-notifications"
    notifications_outbox_poll_delay_ms: int = 2000
    notifications_retry_max_attempts: int = 5

    auth_jwt_secret: str = "change-me-in-prod-change-me-in-prod"
    auth_jwt_issuer: str = "lms-api"
    auth_jwt_clock_skew_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()

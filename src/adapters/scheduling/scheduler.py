"""APScheduler driving adapter.

Each run resolves fresh use cases from the container, so every job gets its own unit of work.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from injector import Injector

from src.application.ports.usecases import ILoanMaintenanceUseCases, INotificationUseCases
from src.infrastructure.config.settings import Settings


def spring_cron(expression: str) -> CronTrigger:
    """Parses a Spring 6-field cron (``sec min hour dom month dow``); use day names for day-of-week."""
    fields = expression.split()
    if len(fields) != 6:
        raise ValueError(f"Expected 6-field cron expression, got: {expression!r}")
    second, minute, hour, day, month, day_of_week = fields
    return CronTrigger(
        second=second,
        minute=minute,
        hour=hour,
        day=day.replace("?", "*"),
        month=month,
        day_of_week=day_of_week.replace("?", "*"),
    )


def build_scheduler(injector: Injector, settings: Settings) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1})

    if settings.scheduling_enabled:
        scheduler.add_job(
            lambda: injector.get(ILoanMaintenanceUseCases).process_overdues_and_penalties(),
            spring_cron(settings.scheduler_overdue_cron),
            id="overdue-and-penalties",
        )
        scheduler.add_job(
            lambda: injector.get(ILoanMaintenanceUseCases).publish_due_reminders(),
            spring_cron(settings.scheduler_reminder_cron),
            id="payment-due-reminders",
        )

    if settings.notifications_kafka_enabled:
        scheduler.add_job(
            lambda: injector.get(INotificationUseCases).publish_pending(),
            "interval",
            seconds=settings.notifications_outbox_poll_delay_ms / 1000,
            id="notification-outbox-publisher",
        )
    return scheduler

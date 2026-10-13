"""APScheduler driving adapter: Spring cron parsing and job registration."""

import pytest

from src.adapters.scheduling.scheduler import build_scheduler, spring_cron


def test_spring_cron_maps_six_fields():
    trigger = spring_cron("0 30 1 * * ?")
    fields = {f.name: str(f) for f in trigger.fields}
    assert (fields["second"], fields["minute"], fields["hour"], fields["day_of_week"]) == (
        "0",
        "30",
        "1",
        "*",
    )


def test_spring_cron_rejects_five_field_expressions():
    with pytest.raises(ValueError, match="6-field"):
        spring_cron("0 1 * * *")


def test_build_scheduler_registers_jobs_from_settings(injector, settings):
    enabled = settings.model_copy(update={"scheduling_enabled": True, "notifications_kafka_enabled": False})
    assert {j.id for j in build_scheduler(injector, enabled).get_jobs()} == {
        "overdue-and-penalties",
        "payment-due-reminders",
    }

    kafka_only = settings.model_copy(
        update={"scheduling_enabled": False, "notifications_kafka_enabled": True}
    )
    assert {j.id for j in build_scheduler(injector, kafka_only).get_jobs()} == {
        "notification-outbox-publisher"
    }

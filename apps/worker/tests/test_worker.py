"""Worker plumbing tests. The heartbeat job is the only real job in Phase 1."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://mip:mip@localhost:5433/mip_test")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("REDIS_URL", "")

import pytest

from worker.jobs import JOBS, Job
from worker.main import build_scheduler, run_once


def test_every_job_has_a_unique_id_and_a_positive_interval() -> None:
    ids = [job.id for job in JOBS]
    assert len(ids) == len(set(ids))
    assert all(job.interval_seconds > 0 for job in JOBS)
    assert all(job.description for job in JOBS)


def test_scheduler_registers_every_job() -> None:
    scheduler = build_scheduler()
    registered = {job.id for job in scheduler.get_jobs()}
    assert registered == {job.id for job in JOBS}
    # A slow run must coalesce rather than stack duplicate executions.
    assert all(job.max_instances == 1 for job in scheduler.get_jobs())
    assert all(job.coalesce for job in scheduler.get_jobs())


def test_a_failing_job_does_not_propagate(caplog: pytest.LogCaptureFixture) -> None:
    """The scheduler must survive one bad job."""
    from worker.main import _run_job

    def explode() -> None:
        raise RuntimeError("boom")

    _run_job(Job(id="bad", func=explode, interval_seconds=1, description="fails on purpose"))
    # No exception escaped; that is the assertion.


def test_run_once_executes_the_heartbeat_against_a_real_database() -> None:
    """Requires the docker-compose Postgres and a migrated mip_test database."""
    assert run_once() == 0

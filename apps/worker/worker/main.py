"""Worker entrypoint.

    python -m worker.main            # run the scheduler
    python -m worker.main --once     # run every job once and exit (CI smoke test)

APScheduler for now. If job volume outgrows a single process in Phase 3, the
registry in worker/jobs.py is the only thing Celery beat needs to read.
"""

from __future__ import annotations

import argparse
import signal
import sys
from types import FrameType

from app.core.config import settings
from app.core.logging import configure_logging, configure_sentry, get_logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from worker.jobs import JOBS, STARTUP_ORDER, Job

log = get_logger("worker.main")


def _run_job(job: Job) -> None:
    """One job failing must never take the scheduler down with it."""
    try:
        job.func()
    except Exception:
        log.exception("job_failed", job_id=job.id)


def ordered_jobs(jobs: tuple[Job, ...] = JOBS) -> list[Job]:
    """Start-up order first (bars before signals), then everything else."""
    by_id = {job.id: job for job in jobs}
    first = [by_id[job_id] for job_id in STARTUP_ORDER if job_id in by_id]
    return first + [job for job in jobs if job.id not in STARTUP_ORDER]


def run_once(jobs: tuple[Job, ...] = JOBS) -> int:
    configure_logging(settings)
    failures = 0
    for job in ordered_jobs(jobs):
        try:
            job.func()
            log.info("job_ok", job_id=job.id)
        except Exception:
            failures += 1
            log.exception("job_failed", job_id=job.id)
    return 1 if failures else 0


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    for job in JOBS:
        scheduler.add_job(
            _run_job,
            trigger=IntervalTrigger(seconds=job.interval_seconds),
            args=[job],
            id=job.id,
            name=job.description,
            # Never let a slow run pile up duplicate executions of the same job.
            max_instances=1,
            coalesce=True,
            misfire_grace_time=30,
        )
    return scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description="Market Intelligence Platform worker")
    parser.add_argument(
        "--once", action="store_true", help="Run every job once and exit (CI smoke test)"
    )
    args = parser.parse_args()

    if args.once:
        return run_once()

    configure_logging(settings)
    configure_sentry(settings)
    settings.assert_production_safe()

    scheduler = build_scheduler()

    def _shutdown(signum: int, frame: FrameType | None) -> None:
        log.info("worker_stopping", signal=signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("worker_starting", environment=settings.environment, jobs=[j.id for j in JOBS])
    # Catch up immediately rather than waiting a full interval: a fresh deploy
    # gets bars, quotes and signals within seconds, in dependency order.
    for job in ordered_jobs():
        _run_job(job)
    scheduler.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())

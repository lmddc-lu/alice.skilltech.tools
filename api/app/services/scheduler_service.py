import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from faststream.rabbit import RabbitBroker
from sqlalchemy import text
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.core.metrics import (
    SCHEDULER_STALLED_JOBS_SWEPT,
    SCHEDULER_TASK_CHATBOT_REINDEX,
    SCHEDULER_TASK_JOBS_IN_STATE_REFRESH,
    SCHEDULER_TASK_RECONCILE_CHATBOTS,
    SCHEDULER_TASK_STALLED_SWEEP,
    track_scheduler_run,
)
from app.models.enums import ReindexFrequency
from app.models.tables import Chatbot, User
from app.repositories.job import JobRepository
from app.services.indexing_service import IndexingService
from app.services.messaging_service import broadcast_job_cancellations
from app.services.monitoring_service import MonitoringService

logger = logging.getLogger(__name__)

_CHATBOT_REINDEX_JOB_PREFIX = "chatbot_reindex:"

# pg_try_advisory_lock takes a bigint. Fold UUIDs and fixed names into
# the positive int63 range. Collisions just serialize unrelated work.
_INT63_MASK = (1 << 63) - 1
# arbitrary distinct constant for the singleton stalled-job checker
_STALLED_JOB_LOCK_KEY = 0x5C4E_D11E_5_7A11_5B & _INT63_MASK


def _chatbot_reindex_job_id(chatbot_id: UUID) -> str:
    return f"{_CHATBOT_REINDEX_JOB_PREFIX}{chatbot_id}"


def _chatbot_reindex_lock_key(chatbot_id: UUID) -> int:
    return chatbot_id.int & _INT63_MASK


@contextmanager
def _try_pg_advisory_lock(key: int) -> Iterator[bool]:
    """Yield True iff this process won the Postgres advisory lock for key.

    Session-level lock held by the connection, released on context exit
    or when the worker process dies. Non-PostgreSQL backends (SQLite in
    tests) yield True since they're inherently single-process.
    """
    if engine.dialect.name != "postgresql":
        yield True
        return

    with engine.connect() as conn:
        got = bool(
            conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        )
        try:
            yield got
        finally:
            if got:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                except Exception as e:
                    # connection close releases the lock anyway
                    logger.warning(f"pg_advisory_unlock({key}) failed: {e}")


def _scheduler_timezone() -> ZoneInfo:
    """Resolve the configured timezone, falling back to UTC if invalid.

    Containers run in UTC but schedules are entered as local wall-clock
    time, so the cron trigger is anchored in this zone.
    """
    name = settings.SCHEDULER_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning(f"Unknown SCHEDULER_TIMEZONE={name!r}, falling back to UTC")
        return ZoneInfo("UTC")


class SchedulerService:
    """Handles periodic background tasks."""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()
        self._is_running = False

    def start(self) -> None:
        if self._is_running:
            logger.warning("Scheduler is already running")
            return

        self.scheduler.add_job(
            self._check_stalled_jobs,
            IntervalTrigger(minutes=5),
            id="check_stalled_jobs",
            name="Check for stalled jobs",
            replace_existing=True,
        )

        # periodic reconcile so schedule edits on one uvicorn worker
        # eventually propagate to all workers (each runs its own
        # in-memory APScheduler). firing duplication is handled
        # separately via Postgres advisory locks.
        self.scheduler.add_job(
            self._reconcile_chatbot_schedules,
            IntervalTrigger(minutes=2),
            id="reconcile_chatbot_schedules",
            name="Reconcile chatbot reindex schedules",
            replace_existing=True,
        )

        # Refreshes the jobs_in_state Prometheus gauge from DB counts.
        # Every uvicorn worker fires this on the same cadence; the gauge
        # uses multiprocess_mode="max" so the aggregated value tracks
        # whichever worker queried most recently.
        self.scheduler.add_job(
            self._refresh_jobs_in_state_gauge,
            IntervalTrigger(seconds=30),
            id="refresh_jobs_in_state_gauge",
            name="Refresh jobs_in_state metric",
            replace_existing=True,
        )

        self.scheduler.start()
        self._is_running = True
        logger.info("Scheduler started with stalled job checker and reconciler")

        # first pass at startup so cron jobs are registered before the
        # first interval fire (~2 min later)
        self._reconcile_chatbot_schedules()
        # and seed the gauge so /metrics has real values before the first
        # 30s tick lands
        self._refresh_jobs_in_state_gauge()

    def shutdown(self) -> None:
        if self._is_running:
            self.scheduler.shutdown(wait=True)
            self._is_running = False
            logger.info("Scheduler shut down")

    def schedule_chatbot_reindex(
        self,
        chatbot_id: UUID,
        frequency: str,
        hour: int,
        minute: int,
        day_of_week: int | None = None,
        day_of_month: int | None = None,
    ) -> None:
        """Register or replace the reindex trigger for a chatbot.

        frequency is a ReindexFrequency value. Weekly requires
        day_of_week (0=Mon..6=Sun). Monthly requires day_of_month
        (1..28 to avoid short-month edge cases).
        """
        if not (0 <= hour <= 23):
            raise ValueError("hour must be in 0..23")
        if not (0 <= minute <= 59):
            raise ValueError("minute must be in 0..59")

        tz = _scheduler_timezone()
        if frequency == ReindexFrequency.WEEKLY.value:
            if day_of_week is None or not (0 <= day_of_week <= 6):
                raise ValueError("day_of_week must be in 0..6 (Mon=0) for weekly")
            trigger = CronTrigger(
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
                timezone=tz,
            )
            description = f"day_of_week={day_of_week}"
        elif frequency == ReindexFrequency.MONTHLY.value:
            if day_of_month is None or not (1 <= day_of_month <= 28):
                raise ValueError("day_of_month must be in 1..28 for monthly")
            trigger = CronTrigger(
                day=day_of_month,
                hour=hour,
                minute=minute,
                timezone=tz,
            )
            description = f"day_of_month={day_of_month}"
        else:
            raise ValueError(f"Unsupported frequency: {frequency!r}")

        self.scheduler.add_job(
            self._run_chatbot_reindex,
            trigger,
            args=[chatbot_id],
            id=_chatbot_reindex_job_id(chatbot_id),
            name=f"{frequency.capitalize()} reindex for chatbot {chatbot_id}",
            replace_existing=True,
            misfire_grace_time=60 * 60,  # 1h grace if worker was down
            coalesce=True,
        )
        logger.info(
            f"Scheduled chatbot {chatbot_id} reindex ({frequency}): "
            f"{description} hour={hour} minute={minute} tz={tz.key}"
        )

    def unschedule_chatbot_reindex(self, chatbot_id: UUID) -> None:
        """Remove the reindex trigger for a chatbot, if any."""
        job_id = _chatbot_reindex_job_id(chatbot_id)
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Unscheduled chatbot {chatbot_id} reindex")
        except Exception:
            # remove_job raises JobLookupError if the id is unknown
            pass

    def _reconcile_chatbot_schedules(self) -> None:
        """Make the in-memory cron registry match the DB.

        Runs at startup and on a 2-min interval so all uvicorn workers
        converge despite each having its own scheduler instance.
        """
        with track_scheduler_run(SCHEDULER_TASK_RECONCILE_CHATBOTS):
            self._reconcile_chatbot_schedules_inner()

    def _reconcile_chatbot_schedules_inner(self) -> None:
        try:
            with Session(engine) as session:
                rows = list(
                    session.exec(
                        select(Chatbot).where(
                            col(Chatbot.reindex_schedule_enabled).is_(True)
                        )
                    )
                )
        except Exception as e:
            logger.error(
                f"Failed to read chatbot schedules during reconcile: {e}",
                exc_info=True,
            )
            return

        desired: set[UUID] = set()
        for chatbot in rows:
            if (
                chatbot.reindex_schedule_frequency is None
                or chatbot.reindex_schedule_hour is None
            ):
                continue
            desired.add(chatbot.id)
            try:
                self.schedule_chatbot_reindex(
                    chatbot.id,
                    frequency=chatbot.reindex_schedule_frequency,
                    hour=chatbot.reindex_schedule_hour,
                    minute=chatbot.reindex_schedule_minute,
                    day_of_week=chatbot.reindex_schedule_day_of_week,
                    day_of_month=chatbot.reindex_schedule_day_of_month,
                )
            except Exception as e:
                logger.error(
                    f"Failed to register schedule for chatbot {chatbot.id}: {e}"
                )

        # drop registrations whose DB row no longer wants a schedule
        for job in self.scheduler.get_jobs():
            if not job.id.startswith(_CHATBOT_REINDEX_JOB_PREFIX):
                continue
            try:
                cb_id = UUID(job.id[len(_CHATBOT_REINDEX_JOB_PREFIX) :])
            except ValueError:
                continue
            if cb_id not in desired:
                self.unschedule_chatbot_reindex(cb_id)

    def _run_chatbot_reindex(self, chatbot_id: UUID) -> None:
        """APScheduler entry point: trigger a reindex for the given chatbot.

        With --workers 8 every worker fires this at the same instant.
        The advisory lock on chatbot_id ensures only the first proceeds.
        Skipped firings (lost the lock) don't count as scheduler runs —
        only one worker actually does the work, and that's what we measure.
        """
        lock_key = _chatbot_reindex_lock_key(chatbot_id)
        try:
            with _try_pg_advisory_lock(lock_key) as got:
                if not got:
                    logger.info(
                        f"Scheduled reindex for chatbot {chatbot_id} skipped: "
                        f"another worker already handled this firing"
                    )
                    return
                with track_scheduler_run(SCHEDULER_TASK_CHATBOT_REINDEX):
                    asyncio.run(self._trigger_chatbot_reindex(chatbot_id))
        except Exception as e:
            logger.error(
                f"Scheduled reindex for chatbot {chatbot_id} failed: {e}",
                exc_info=True,
            )

    async def _trigger_chatbot_reindex(self, chatbot_id: UUID) -> None:
        broker = RabbitBroker(settings.RABBITMQ_URL)
        await broker.start()
        try:
            with Session(engine) as session:
                chatbot = session.get(Chatbot, chatbot_id)
                if not chatbot:
                    logger.warning(
                        f"Scheduled reindex skipped: chatbot {chatbot_id} "
                        f"no longer exists"
                    )
                    return
                if not chatbot.reindex_schedule_enabled:
                    logger.info(
                        f"Scheduled reindex skipped: chatbot {chatbot_id} "
                        f"schedule disabled"
                    )
                    return
                if not chatbot.enabled:
                    logger.info(
                        f"Scheduled reindex skipped: chatbot {chatbot_id} is disabled"
                    )
                    return
                owner = session.get(User, chatbot.owner_id)
                if not owner:
                    logger.warning(
                        f"Scheduled reindex skipped: owner for chatbot "
                        f"{chatbot_id} not found"
                    )
                    return
                # if all Moodle datasources are gone, periodic reindex
                # is pointless: file/free-text KBs reingest on user
                # edits. skip rather than churning the worker.
                if not IndexingService._get_moodle_datasource_ids(
                    session, chatbot.knowledge_base_id
                ):
                    logger.info(
                        f"Scheduled reindex skipped: chatbot {chatbot_id} "
                        f"no longer has any Moodle datasource"
                    )
                    return
                indexing = IndexingService(broker)
                await indexing.trigger_reindex(
                    session=session,
                    knowledge_base_id=chatbot.knowledge_base_id,
                    user=owner,
                    force=True,
                    force_ocr=chatbot.force_ocr,
                )
                logger.info(f"Scheduled reindex triggered for chatbot {chatbot_id}")
        finally:
            await broker.stop()

    def _check_stalled_jobs(self) -> None:
        """Check for and mark stalled jobs.

        Runs in a background thread so it opens its own session. The
        advisory lock collapses --workers 8 firings to one effective run.
        Workers that lost the lock are not counted as scheduler runs —
        only the winning worker does the work, and that's what we measure.
        """
        logger.debug("Running stalled job check...")

        with _try_pg_advisory_lock(_STALLED_JOB_LOCK_KEY) as got:
            if not got:
                return
            # log+swallow at the outermost layer (original behavior) so a
            # bad sweep doesn't keep escalating through APScheduler's own
            # logger; the metric outcome="error" is enough signal.
            try:
                with track_scheduler_run(SCHEDULER_TASK_STALLED_SWEEP):
                    with Session(engine) as session:
                        job_repo = JobRepository(session)
                        stalled_jobs = job_repo.mark_stalled_jobs(
                            running_stale_minutes=settings.JOB_RUNNING_STALE_MINUTES,
                            running_absolute_minutes=settings.JOB_RUNNING_ABSOLUTE_MINUTES,
                            pending_timeout_minutes=settings.JOB_PENDING_TIMEOUT_MINUTES,
                        )
                        SCHEDULER_STALLED_JOBS_SWEPT.inc(len(stalled_jobs))

                        if stalled_jobs:
                            logger.warning(
                                f"Marked {len(stalled_jobs)} jobs as stalled: "
                                f"{[str(j.id) for j in stalled_jobs]}"
                            )
                            try:
                                asyncio.run(
                                    broadcast_job_cancellations(
                                        settings.RABBITMQ_URL,
                                        [j.id for j in stalled_jobs],
                                    )
                                )
                            except Exception as e:
                                logger.error(
                                    f"Failed to broadcast cancellations: {e}",
                                    exc_info=True,
                                )
            except Exception as e:
                logger.error(f"Error checking for stalled jobs: {e}", exc_info=True)

    def _refresh_jobs_in_state_gauge(self) -> None:
        """Periodic refresh of the jobs_in_state Prometheus gauge."""
        try:
            with track_scheduler_run(SCHEDULER_TASK_JOBS_IN_STATE_REFRESH):
                with Session(engine) as session:
                    MonitoringService(session).refresh_jobs_in_state_gauge()
        except Exception as e:
            logger.error(f"Failed to refresh jobs_in_state gauge: {e}", exc_info=True)


scheduler_service = SchedulerService()

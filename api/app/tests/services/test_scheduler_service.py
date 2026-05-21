import uuid
from types import SimpleNamespace

import pytest

from app.models.enums import ReindexFrequency
from app.services.scheduler_service import (
    SchedulerService,
    _chatbot_reindex_job_id,
    _chatbot_reindex_lock_key,
    _try_pg_advisory_lock,
)


@pytest.fixture
def service() -> SchedulerService:
    """Fresh SchedulerService, never started.

    APScheduler add_job works pre-start (queues the job), so we exercise
    registration without spinning up a thread or paying wall-clock time.
    """
    return SchedulerService()


@pytest.fixture
def chatbot_id() -> uuid.UUID:
    return uuid.uuid4()


class TestSchedulerServiceWeekly:
    def test_registers_weekly_job(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        service.schedule_chatbot_reindex(
            chatbot_id,
            frequency=ReindexFrequency.WEEKLY.value,
            hour=6,
            minute=0,
            day_of_week=6,  # Sunday
        )

        job = service.scheduler.get_job(_chatbot_reindex_job_id(chatbot_id))
        assert job is not None

    def test_replaces_existing_job(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        # replace_existing is jobstore-level dedup and only kicks in once
        # the scheduler is started. Start paused to enable the jobstore
        # without firing real triggers.
        service.scheduler.start(paused=True)
        try:
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=6,
                minute=0,
                day_of_week=0,
            )
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=8,
                minute=30,
                day_of_week=3,
            )

            jobs = [
                j
                for j in service.scheduler.get_jobs()
                if j.id == _chatbot_reindex_job_id(chatbot_id)
            ]
            assert len(jobs) == 1
        finally:
            service.scheduler.shutdown(wait=False)

    def test_rejects_missing_day_of_week(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        with pytest.raises(ValueError, match="day_of_week"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=6,
                minute=0,
                day_of_week=None,
            )

    @pytest.mark.parametrize("bad_dow", [-1, 7, 100])
    def test_rejects_out_of_range_day_of_week(
        self,
        service: SchedulerService,
        chatbot_id: uuid.UUID,
        bad_dow: int,
    ) -> None:
        with pytest.raises(ValueError, match="day_of_week"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=6,
                minute=0,
                day_of_week=bad_dow,
            )


class TestSchedulerServiceMonthly:
    def test_registers_monthly_job(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        service.schedule_chatbot_reindex(
            chatbot_id,
            frequency=ReindexFrequency.MONTHLY.value,
            hour=3,
            minute=15,
            day_of_month=15,
        )

        job = service.scheduler.get_job(_chatbot_reindex_job_id(chatbot_id))
        assert job is not None

    def test_rejects_missing_day_of_month(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        with pytest.raises(ValueError, match="day_of_month"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.MONTHLY.value,
                hour=3,
                minute=0,
                day_of_month=None,
            )

    @pytest.mark.parametrize("bad_dom", [0, 29, 31])
    def test_rejects_out_of_range_day_of_month(
        self,
        service: SchedulerService,
        chatbot_id: uuid.UUID,
        bad_dom: int,
    ) -> None:
        # cap at 28 to avoid month-length edge cases; 29/31 would
        # silently skip in February etc.
        with pytest.raises(ValueError, match="day_of_month"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.MONTHLY.value,
                hour=3,
                minute=0,
                day_of_month=bad_dom,
            )


class TestSchedulerServiceCommonValidation:
    @pytest.mark.parametrize("bad_hour", [-1, 24, 99])
    def test_rejects_out_of_range_hour(
        self,
        service: SchedulerService,
        chatbot_id: uuid.UUID,
        bad_hour: int,
    ) -> None:
        with pytest.raises(ValueError, match="hour"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=bad_hour,
                minute=0,
                day_of_week=0,
            )

    @pytest.mark.parametrize("bad_minute", [-1, 60, 999])
    def test_rejects_out_of_range_minute(
        self,
        service: SchedulerService,
        chatbot_id: uuid.UUID,
        bad_minute: int,
    ) -> None:
        with pytest.raises(ValueError, match="minute"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency=ReindexFrequency.WEEKLY.value,
                hour=6,
                minute=bad_minute,
                day_of_week=0,
            )

    def test_rejects_unknown_frequency(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        with pytest.raises(ValueError, match="frequency"):
            service.schedule_chatbot_reindex(
                chatbot_id,
                frequency="daily",
                hour=6,
                minute=0,
                day_of_week=0,
            )


class TestSchedulerServiceUnschedule:
    def test_removes_existing_job(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        service.schedule_chatbot_reindex(
            chatbot_id,
            frequency=ReindexFrequency.WEEKLY.value,
            hour=6,
            minute=0,
            day_of_week=0,
        )
        service.unschedule_chatbot_reindex(chatbot_id)

        assert service.scheduler.get_job(_chatbot_reindex_job_id(chatbot_id)) is None

    def test_is_idempotent_when_no_job(
        self, service: SchedulerService, chatbot_id: uuid.UUID
    ) -> None:
        # the chatbot delete path relies on this not raising
        service.unschedule_chatbot_reindex(chatbot_id)


class TestAdvisoryLockHelper:
    def test_yields_true_on_non_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # non-Postgres backends (dev SQLite, unit-test envs) short-circuit
        # and grant the lock, nothing to coordinate with anyway
        fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        monkeypatch.setattr("app.services.scheduler_service.engine", fake_engine)

        with _try_pg_advisory_lock(12345) as got:
            assert got is True


class TestChatbotReindexLockKey:
    def test_fits_signed_int63(self) -> None:
        cb_id = uuid.uuid4()
        key = _chatbot_reindex_lock_key(cb_id)

        # pg_try_advisory_lock takes a bigint. Mask to int63 so the value
        # is always positive regardless of the UUID's high bits.
        assert 0 <= key < (1 << 63)

    def test_stable_per_uuid(self) -> None:
        cb_id = uuid.uuid4()
        assert _chatbot_reindex_lock_key(cb_id) == _chatbot_reindex_lock_key(cb_id)

    def test_distinct_uuids_get_distinct_keys(self) -> None:
        # collisions are harmless, but a folded int63 from a 128-bit UUID
        # should almost never collide; smoke check against a constant.
        keys = {_chatbot_reindex_lock_key(uuid.uuid4()) for _ in range(100)}
        assert len(keys) == 100


class TestReconcileChatbotSchedules:
    def _make_chatbot_row(
        self,
        chatbot_id: uuid.UUID,
        *,
        enabled: bool = True,
        frequency: str | None = "weekly",
        day_of_week: int | None = 6,
        day_of_month: int | None = None,
        hour: int | None = 6,
        minute: int = 0,
    ) -> SimpleNamespace:
        # reconciler reads attributes by name; SimpleNamespace avoids the
        # SQLAlchemy state a real Chatbot instance needs
        return SimpleNamespace(
            id=chatbot_id,
            reindex_schedule_enabled=enabled,
            reindex_schedule_frequency=frequency,
            reindex_schedule_day_of_week=day_of_week,
            reindex_schedule_day_of_month=day_of_month,
            reindex_schedule_hour=hour,
            reindex_schedule_minute=minute,
        )

    def _patch_session_to_return(
        self,
        rows: list[SimpleNamespace],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # replace the Session(engine) read with a fake that returns
        # given rows on .exec(). No SQLAlchemy here, we just need the
        # reconciler's behavior under a known result set.
        class _FakeResult:
            def __init__(self, rows: list[SimpleNamespace]) -> None:
                self._rows = rows

            def all(self) -> list[SimpleNamespace]:
                return self._rows

            def __iter__(self):  # type: ignore[no-untyped-def]
                return iter(self._rows)

        class _FakeSession:
            def __init__(self, rows: list[SimpleNamespace]) -> None:
                self._rows = rows

            def __enter__(self) -> "_FakeSession":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def exec(self, _stmt: object) -> _FakeResult:
                return _FakeResult(self._rows)

        monkeypatch.setattr(
            "app.services.scheduler_service.Session",
            lambda _engine: _FakeSession(rows),
        )

    def test_adds_schedule_from_db(
        self, service: SchedulerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cb_id = uuid.uuid4()
        self._patch_session_to_return([self._make_chatbot_row(cb_id)], monkeypatch)

        service._reconcile_chatbot_schedules()

        assert service.scheduler.get_job(_chatbot_reindex_job_id(cb_id)) is not None

    def test_removes_stale_registration(
        self, service: SchedulerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pre-register a chatbot the next DB read won't return: simulates
        # a schedule disabled (or chatbot deleted) on another worker. The
        # reconciler must drop our stale cron entry.
        stale_id = uuid.uuid4()
        service.schedule_chatbot_reindex(
            stale_id,
            frequency=ReindexFrequency.WEEKLY.value,
            hour=6,
            minute=0,
            day_of_week=0,
        )
        assert service.scheduler.get_job(_chatbot_reindex_job_id(stale_id)) is not None

        self._patch_session_to_return([], monkeypatch)
        service._reconcile_chatbot_schedules()

        assert service.scheduler.get_job(_chatbot_reindex_job_id(stale_id)) is None

    def test_skips_rows_with_missing_required_fields(
        self, service: SchedulerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # enabled row with no frequency/hour gets skipped, no cron entry
        broken_id = uuid.uuid4()
        self._patch_session_to_return(
            [self._make_chatbot_row(broken_id, frequency=None, hour=None)],
            monkeypatch,
        )

        service._reconcile_chatbot_schedules()

        assert service.scheduler.get_job(_chatbot_reindex_job_id(broken_id)) is None

    def test_leaves_unrelated_jobs_alone(
        self, service: SchedulerService, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # reconciler should only touch jobs whose id starts with the
        # chatbot reindex prefix. The stalled-job checker, reconciler
        # itself, and any future system jobs must survive.
        from apscheduler.triggers.interval import IntervalTrigger

        service.scheduler.add_job(
            lambda: None,
            IntervalTrigger(minutes=5),
            id="check_stalled_jobs",
            name="Check for stalled jobs",
        )
        self._patch_session_to_return([], monkeypatch)

        service._reconcile_chatbot_schedules()

        assert service.scheduler.get_job("check_stalled_jobs") is not None

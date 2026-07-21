import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from faststream.rabbit import ExchangeType, RabbitExchange
from sqlmodel import Session, select

from app.core.metrics import JOB_TOTAL_DURATION_SECONDS, JOBS_COMPLETED
from app.models.enums import (
    JobStatus,
    JobType,
    KnowledgeBaseStatus,
    SourceType,
    SyncErrorCode,
)
from app.models.tables import (
    DataSource,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
    User,
)
from app.repositories.job import JobRepository, _job_age_seconds
from app.services.datasource_service import DatasourceService
from app.services.index_manifest import rebuild_decision
from app.services.knowledgebase_service import KnowledgebaseService
from app.services.messaging_service import CANCEL_EXCHANGE

_cancel_exchange = RabbitExchange(
    name=CANCEL_EXCHANGE, type=ExchangeType.FANOUT, durable=True
)

logger = logging.getLogger(__name__)


class IndexingService:
    """Triggers reindexing jobs for knowledge bases."""

    def __init__(self, broker: Any) -> None:
        self.broker = broker

    async def trigger_reindex(
        self,
        session: Session,
        knowledge_base_id: UUID,
        user: User,
        force: bool = False,
        force_ocr: bool = False,
    ) -> dict[str, Any]:
        """Prepare and publish a reindex job for a KB.

        A reindex is incremental by default: the worker skips files whose
        indexed content and OCR state are unchanged (an OCR toggle is
        detected per file via the force_ocr stamp on chunks). It escalates
        to a forced full rebuild when the caller asks for one, or when the
        KB's index manifest requires it (missing, or its fingerprint drifted
        from the desired embedding config / schema version).

        If the KB has Moodle datasources, their metadata cache is
        refreshed first so the content browser tree picks up
        new/renamed/deleted activities; ingestion then runs against the
        freshly-cached structure.

        When Moodle datasources exist, ingestion is deferred behind
        their metadata sync: the prepared payload and waiting list are
        stored on the job's input_params, and the metadata-sync
        completion handler in `workers.py` fires ingestion when the
        last datasource lands. Otherwise ingestion publishes right away.
        """
        job_repo = JobRepository(session)

        needs_commit = False
        existing = job_repo.get_active_for_knowledge_base(knowledge_base_id)
        if existing:
            existing.status = JobStatus.CANCELLED.value
            existing.error_message = "Cancelled: new ingestion triggered"
            needs_commit = True
            logger.info(
                f"Cancelled existing job {existing.id} for KB {knowledge_base_id}"
            )
            await self.broker.publish(
                json.dumps({"job_id": str(existing.id)}),
                exchange=_cancel_exchange,
            )

        # always reset KB status so prepare_haystack_sync doesn't 409.
        # covers the case where a previous job ended (stalled/failed/completed)
        # but the KB status never got reset from PROCESSING
        kb = session.get(KnowledgeBase, knowledge_base_id)
        if kb and kb.status == KnowledgeBaseStatus.PROCESSING:
            kb.status = KnowledgeBaseStatus.READY
            needs_commit = True
            logger.info(f"Reset KB {knowledge_base_id} from PROCESSING to READY")

        if needs_commit:
            session.commit()

        # escalate an incremental sync to a forced rebuild when the collection
        # cannot be trusted to match the desired config (see rebuild_decision).
        # force_ocr needs no escalation: the worker detects an OCR flip per
        # file via the force_ocr stamp and replaces only affected chunks.
        if not force:
            rebuild = rebuild_decision(kb.index_manifest if kb else None)
            if rebuild.stale:
                force = True
                logger.info(
                    f"Escalating sync of KB {knowledge_base_id} to full "
                    f"rebuild: {rebuild.reason}"
                )

        job = job_repo.create_job(
            job_type=JobType.INGESTION,
            user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            input_params={
                "force": force,
                "knowledge_base_id": str(knowledge_base_id),
            },
        )
        logger.info(f"Created ingestion job {job.id} for KB {knowledge_base_id}")

        try:
            sync_result = KnowledgebaseService(session).prepare_haystack_sync(
                kb_id=str(knowledge_base_id),
                user=user,
                force=force,
                force_ocr=force_ocr,
            )

            sync_job = sync_result.pop("sync_job")

            # workers need job_id to update progress
            sync_job["job_id"] = str(job.id)

            moodle_datasource_ids = self._get_moodle_datasource_ids(
                session, knowledge_base_id
            )

            if moodle_datasource_ids:
                # park ingestion only behind datasources that published
                # successfully. a broker reject would otherwise block
                # ingestion forever waiting on a sync that never runs
                published_ids = await self._publish_metadata_sync_for_datasources(
                    session, moodle_datasource_ids, user
                )
            else:
                published_ids = []

            if published_ids:
                # defer ingestion behind metadata refresh. payload and
                # waiting list are persisted on the job itself; the
                # metadata-sync completion handler in `workers.py` fires
                # ingestion when the last datasource lands. the job
                # stays PENDING until then, which the cancel and
                # stalled-job paths correctly treat as "active"
                job.input_params = json.dumps(
                    {
                        "force": force,
                        "knowledge_base_id": str(knowledge_base_id),
                        "deferred_ingestion": {
                            "sync_job": sync_job,
                            "waiting_for_datasources": [str(d) for d in published_ids],
                        },
                    }
                )
                session.commit()
                logger.info(
                    f"Reindex job {job.id} deferred behind metadata sync of "
                    f"{len(published_ids)}/{len(moodle_datasource_ids)} "
                    f"Moodle datasource(s)"
                )
            else:
                # no Moodle datasources, or every metadata-sync publish
                # failed. fire ingestion immediately so the user still
                # gets fresh content even if the cached tree stays stale
                await self.broker.publish(
                    json.dumps(sync_job),
                    routing_key="ingestion_jobs",
                )
                logger.info(
                    f"Published ingestion job {job.id} for knowledge base "
                    f"{knowledge_base_id} (no deferred metadata refresh)"
                )

            sync_result["job_id"] = str(job.id)
            return sync_result

        except Exception as e:
            job_repo.fail_job(
                job.id,
                error_message=f"Failed to publish job: {str(e)}",
                error_details=None,
            )
            # prepare_haystack_sync flips KB.status to "processing" before
            # we publish. without this reset, a publish failure strands
            # the KB in PROCESSING with no running job: spinner forever,
            # and the next reindex hits the 409 guard
            try:
                self.kb_repo_reset_to_error(session, knowledge_base_id)
            except Exception as reset_exc:
                logger.error(
                    f"Failed to reset KB {knowledge_base_id} to error: {reset_exc}"
                )
            logger.error(f"Failed to publish ingestion job {job.id}: {e}")
            raise

    @staticmethod
    def kb_repo_reset_to_error(session: Session, knowledge_base_id: UUID) -> None:
        """Reset a KB stuck in PROCESSING after a publish failure to ERROR.

        Technical detail is captured on the job and in the logs by the caller;
        the KB only carries the user-facing code.
        """
        kb = session.get(KnowledgeBase, knowledge_base_id)
        if kb is None:
            return
        if kb.status == KnowledgeBaseStatus.PROCESSING:
            kb.status = KnowledgeBaseStatus.ERROR
            kb.last_sync_error = SyncErrorCode.FAILED
            session.commit()

    @staticmethod
    def _get_moodle_datasource_ids(
        session: Session, knowledge_base_id: UUID
    ) -> list[UUID]:
        """UUIDs of every Moodle datasource linked to the KB."""
        links = session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id
            )
        ).all()

        out: list[UUID] = []
        for link in links:
            datasource = session.get(DataSource, link.datasource_id)
            if datasource and datasource.source_type == SourceType.MOODLE:
                out.append(datasource.id)
        return out

    async def _publish_metadata_sync_for_datasources(
        self,
        session: Session,
        datasource_ids: list[UUID],
        user: User,
    ) -> list[UUID]:
        """Publish a metadata-sync job per datasource. Returns the published ones.

        Per-datasource failures are logged, never raised. Callers use the
        returned list as the waiting set so a publish failure can't
        strand a deferred ingestion.
        """
        published: list[UUID] = []
        ds_service = DatasourceService(session)
        for datasource_id in datasource_ids:
            try:
                metadata_job = ds_service.prepare_metadata_sync_job(
                    datasource_id=datasource_id,
                    user=user,
                    force=True,
                )
                await self.broker.publish(
                    json.dumps(metadata_job),
                    routing_key="metadata_sync_jobs",
                )
                published.append(datasource_id)
            except Exception as e:
                logger.warning(
                    f"Failed to publish metadata sync for datasource "
                    f"{datasource_id}: {e}"
                )
        return published

    async def trigger_reindex_safe(
        self,
        session: Session,
        knowledge_base_id: UUID,
        user: User,
        force: bool = False,
        force_ocr: bool = False,
    ) -> tuple[bool, str | None]:
        """Wraps trigger_reindex; returns (ok, error_message) instead of raising."""
        try:
            await self.trigger_reindex(
                session, knowledge_base_id, user, force, force_ocr
            )
            return True, None
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to trigger reindexing: {error_msg}")
            return False, error_msg

    async def trigger_metadata_sync(
        self,
        session: Session,
        datasource_id: UUID,
        user: User,
        force: bool = False,
    ) -> dict[str, Any]:
        """Trigger metadata sync for a datasource. Returns sync metadata with job_id."""
        job_repo = JobRepository(session)

        job = job_repo.create_job(
            job_type=JobType.METADATA_SYNC,
            user_id=user.id,
            datasource_id=datasource_id,
            input_params={
                "force": force,
                "datasource_id": str(datasource_id),
            },
        )
        logger.info(
            f"Created metadata sync job {job.id} for datasource {datasource_id}"
        )

        try:
            sync_job = DatasourceService(session).prepare_metadata_sync_job(
                datasource_id=datasource_id,
                user=user,
                force=force,
            )

            sync_job["job_id"] = str(job.id)

            await self.broker.publish(
                json.dumps(sync_job),
                routing_key="metadata_sync_jobs",
            )

            logger.info(
                f"Published metadata sync job {job.id} for datasource {datasource_id}"
            )

            return {
                "job_id": str(job.id),
                "datasource_id": str(datasource_id),
                "message": "Metadata sync started",
            }

        except Exception as e:
            job_repo.fail_job(
                job.id,
                error_message=f"Failed to publish job: {str(e)}",
            )
            logger.error(f"Failed to publish metadata sync job {job.id}: {e}")
            raise

    async def trigger_content_sync(
        self,
        session: Session,
        datasource_id: UUID,
        user: User,
        selected_files: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Trigger content sync for a datasource. Returns sync metadata with job_id."""
        job_repo = JobRepository(session)

        job = job_repo.create_job(
            job_type=JobType.CONTENT_SYNC,
            user_id=user.id,
            datasource_id=datasource_id,
            input_params={
                "force": force,
                "datasource_id": str(datasource_id),
                "selected_files_count": len(selected_files) if selected_files else 0,
            },
        )
        logger.info(f"Created content sync job {job.id} for datasource {datasource_id}")

        try:
            sync_job = DatasourceService(session).prepare_content_sync_job(
                datasource_id=datasource_id,
                user=user,
                selected_files=selected_files,
                force=force,
            )

            sync_job["job_id"] = str(job.id)

            await self.broker.publish(
                json.dumps(sync_job),
                routing_key="content_sync_jobs",
            )

            logger.info(
                f"Published content sync job {job.id} for datasource {datasource_id}"
            )

            return {
                "job_id": str(job.id),
                "datasource_id": str(datasource_id),
                "files_to_sync": len(sync_job.get("selected_files", [])),
                "message": "Content sync started",
            }

        except Exception as e:
            job_repo.fail_job(
                job.id,
                error_message=f"Failed to publish job: {str(e)}",
            )
            logger.error(f"Failed to publish content sync job {job.id}: {e}")
            raise

    def get_job_status(self, session: Session, job_id: UUID) -> dict[str, Any] | None:
        """Current status of a job, or None if not found."""
        job_repo = JobRepository(session)
        job = job_repo.get(job_id)

        if not job:
            return None

        deferred = job_repo.get_deferred_state(job)
        phase = "waiting_metadata" if deferred else None
        progress_message = job.progress_message
        if deferred and not progress_message:
            n = len(deferred["waiting_for_datasources"])
            progress_message = (
                f"Waiting on Moodle metadata refresh ({n} datasource"
                f"{'s' if n != 1 else ''})"
            )

        return {
            "job_id": str(job.id),
            "job_type": job.job_type,
            "status": job.status,
            "phase": phase,
            "progress": {
                "current": job.progress_current,
                "total": job.progress_total,
                "message": progress_message,
                "percentage": (
                    (job.progress_current / job.progress_total * 100)
                    if job.progress_total > 0
                    else 0
                ),
            },
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
        }

    async def cancel_job(self, session: Session, job_id: UUID) -> bool:
        """Cancel a pending or running job. Returns False if already finalized."""
        job_repo = JobRepository(session)
        job = job_repo.get(job_id)

        if not job:
            return False

        if job.status not in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
            logger.warning(f"Cannot cancel job {job_id} - status is {job.status}")
            return False

        now = datetime.now(UTC)
        job.status = JobStatus.CANCELLED.value
        job.error_message = "Job cancelled by user"
        session.commit()

        JOBS_COMPLETED.labels(
            job_type=job.job_type, status=JobStatus.CANCELLED.value
        ).inc()
        JOB_TOTAL_DURATION_SECONDS.labels(
            job_type=job.job_type, status=JobStatus.CANCELLED.value
        ).observe(_job_age_seconds(job, now))

        await self.broker.publish(
            json.dumps({"job_id": str(job_id)}),
            exchange=_cancel_exchange,
        )

        logger.info(f"Job {job_id} cancelled")
        return True

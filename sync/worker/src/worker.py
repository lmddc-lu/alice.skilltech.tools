import json
import logging
import sys
import tempfile
import traceback
from pathlib import Path
from typing import TypedDict

from api.haystack import HaystackClient
from config import Config
from core.file_adapter import FileSourceAdapter
from core.moodle_adapter import MoodleSourceAdapter
from core.moodle_export_client import (
    MoodleAuthenticationError,
    MoodleConnectionError,
)
from core.nextcloud_adapter import NextCloudSourceAdapter
from core.processors import default_registry as processor_registry
from core.source_adapter import SourceAdapter
from core.source_types import SourceType
from core.url_validation import log_effective_allowlists
from messaging.progress import ProgressPublisher
from messaging.rabbitmq import QueueConfig, QueueNames, RabbitMQClient
from metrics import (
    CHUNKS_CREATED,
    FILE_STAGE_DOWNLOAD,
    FILE_STAGE_INGEST,
    JOB_STATUS_AUTH_ERROR,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_TYPE_CONTENT_SYNC,
    JOB_TYPE_INGESTION,
    JOB_TYPE_METADATA_SYNC,
    track_file_stage,
    track_job,
)
from storage.minio_client import MinioStorage

logger = logging.getLogger(__name__)

# generic user-facing message; specific converter error goes in error_detail for admin triage
USER_FACING_INGEST_ERROR = "Could not process file"


class JobFileState:
    """Per-file lifecycle states published over job_progress_updates.

    Mirrors app.models.JobFileState. Pinned by test_jobfilestate_contract.py.
    """

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    SKIPPED = "skipped"
    FAILED = "failed"


class JobFileErrorCode:
    """Stable failure codes for per-file FAILED states.

    Codes are stage-specific so a failed file tells you where in the
    pipeline it died without reading the traceback.

    Mirrors app.models.JobFileErrorCode. Pinned by test_jobfilestate_contract.py.
    """

    # ingestion succeeded but produced zero chunks (image-only PDF, scanned page)
    EMPTY_CONTENT = "empty_content"
    # could not fetch the file from object storage
    DOWNLOAD_FAILED = "download_failed"
    # H5P/SCORM preprocessing failed or produced no output
    PROCESSOR_FAILED = "processor_failed"
    # rag-pipeline reported failure or the call raised
    INGESTION_FAILED = "ingestion_failed"
    # rag-pipeline went stale or exceeded the absolute time budget
    INGESTION_TIMEOUT = "ingestion_timeout"


class FailedFile(TypedDict):
    filename: str
    error: str


class SyncStats(TypedDict):
    """Result of _sync_with_hayhooks."""

    succeeded: int
    failed: int
    failed_files: list[FailedFile]
    chunks_created: int


class JobCancelledException(Exception):
    """Raised when a job is cancelled via RabbitMQ signal."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job {job_id} was cancelled")


class SyncWorker:
    def __init__(self, config: Config):
        self.config = config
        self.mq_client = None
        self.storage = MinioStorage(
            config.minio_url, config.minio_access_key, config.minio_secret_key
        )
        self.content_sync_queue = QueueConfig(QueueNames.CONTENT_SYNC)
        self.ingestion_queue = QueueConfig(QueueNames.INGESTION)
        self.metadata_sync_queue = QueueConfig(QueueNames.METADATA_SYNC)
        # publisher resolves mq_client lazily; start() wires it via _connect_rabbitmq
        self.progress = ProgressPublisher(lambda: self.mq_client)
        self.moodle = MoodleSourceAdapter(self.config, self.storage)
        self.adapters: dict[SourceType, SourceAdapter] = {
            SourceType.MOODLE: self.moodle,
            SourceType.NEXTCLOUD: NextCloudSourceAdapter(self.config, self.storage),
            SourceType.FILE: FileSourceAdapter(self.config, self.storage),
        }
        log_effective_allowlists()

    def _progress_publisher(self) -> ProgressPublisher:
        # tests construct via __new__ and only set mq_client, so build on first access
        pub = self.__dict__.get("progress")
        if pub is None:
            pub = ProgressPublisher(lambda: self.mq_client)
            self.__dict__["progress"] = pub
        return pub

    def _get_adapter(self, source_type: SourceType) -> SourceAdapter:
        # lazy fallback for tests that construct via __new__
        registry = self.__dict__.get("adapters")
        if registry is None:
            config = getattr(self, "config", None)
            storage = getattr(self, "storage", None)
            moodle = self.__dict__.get("moodle") or MoodleSourceAdapter(config, storage)
            self.__dict__["moodle"] = moodle
            registry = {
                SourceType.MOODLE: moodle,
                SourceType.NEXTCLOUD: NextCloudSourceAdapter(config, storage),
                SourceType.FILE: FileSourceAdapter(config, storage),
            }
            self.__dict__["adapters"] = registry
        return registry[source_type]

    def _connect_rabbitmq(self):
        try:
            if self.mq_client:
                try:
                    self.mq_client.connection.close()
                except Exception:
                    pass
            self.mq_client = RabbitMQClient(self.config.rabbitmq_url)
            self.mq_client.setup_queue(self.content_sync_queue)
            self.mq_client.setup_queue(self.ingestion_queue)
            self.mq_client.setup_queue(self.metadata_sync_queue)
            logger.info("Successfully connected to RabbitMQ")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    def _publish_progress(
        self,
        job_id,
        *,
        message: str | None = None,
        total_files: int | None = None,
        file: dict | None = None,
    ) -> None:
        self._progress_publisher().publish_progress(
            job_id, message=message, total_files=total_files, file=file
        )

    def _publish_file_state(
        self,
        job_id,
        *,
        file_id,
        filename: str,
        state: str,
        error_message: str | None = None,
        error_detail: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._progress_publisher().publish_file_state(
            job_id,
            file_id=file_id,
            filename=filename,
            state=state,
            error_message=error_message,
            error_detail=error_detail,
            error_code=error_code,
        )

    def process_metadata_sync_message(self, ch, method, properties, body):
        message = None
        job_id = None

        with track_job(JOB_TYPE_METADATA_SYNC) as job_status:
            try:
                message = json.loads(body)
                job_id = message.get("job_id")

                logger.info(
                    f"Processing metadata sync message (job_id={job_id}): "
                    f"{message.get('datasource_id')}"
                )

                datasource_id = message["datasource_id"]
                source_type = SourceType.parse(message.get("source_type"))
                owner_email = message.get("owner_email")
                force = message.get("force", False)

                if not owner_email:
                    raise ValueError("owner_email is required in metadata sync message")

                courses_metadata = self._get_adapter(source_type).sync_metadata(
                    message, force
                )

                completion_message = {
                    "job_id": job_id,
                    "datasource_id": datasource_id,
                    "courses": courses_metadata,
                    "operation": "metadata_sync",
                }
                # the message was acked at claim (at-most-once, see
                # RabbitMQClient.start_consuming) and will never redeliver;
                # publishing an outcome is the only signal the API gets.
                self.mq_client.publish(
                    self.metadata_sync_queue.completed_name, completion_message
                )
                logger.info(
                    f"Completed metadata sync for datasource {datasource_id} (job_id={job_id})"
                )

            except (MoodleAuthenticationError, MoodleConnectionError) as e:
                job_status["value"] = JOB_STATUS_AUTH_ERROR
                logger.error(f"Authentication/Connection error in metadata sync: {e}")
                self._handle_auth_error(
                    method,
                    body,
                    str(e),
                    job_id,
                    error_detail=traceback.format_exc(),
                    error_kind="auth"
                    if isinstance(e, MoodleAuthenticationError)
                    else "connection",
                )
            except Exception as e:
                job_status["value"] = JOB_STATUS_FAILED
                logger.error(f"Error processing metadata sync message: {e}")
                self._handle_error(
                    method,
                    body,
                    job_id,
                    error_msg=f"{type(e).__name__}: {e}",
                    error_detail=traceback.format_exc(),
                )

    def process_content_sync_message(self, ch, method, properties, body):
        message = None
        job_id = None

        with track_job(JOB_TYPE_CONTENT_SYNC) as job_status:
            try:
                message = json.loads(body)
                job_id = message.get("job_id")

                logger.info(
                    f"Processing content sync message (job_id={job_id}): "
                    f"{message.get('datasource_id')}"
                )

                datasource_id = message["datasource_id"]
                source_type = SourceType.parse(message.get("source_type"))
                owner_email = message.get("owner_email")
                selected_files = message.get("selected_files", [])
                force = message.get("force", False)

                if not owner_email:
                    raise ValueError("owner_email is required in content sync message")

                files_downloaded = self._get_adapter(source_type).sync_content(
                    message, selected_files, force
                )

                completion_message = {
                    "job_id": job_id,
                    "datasource_id": datasource_id,
                    "files_downloaded": files_downloaded,
                    "operation": "content_sync",
                }
                self.mq_client.publish(
                    self.content_sync_queue.completed_name, completion_message
                )
                logger.info(
                    f"Completed content sync for datasource {datasource_id} (job_id={job_id}). "
                    f"Downloaded {files_downloaded} files."
                )

            except (MoodleAuthenticationError, MoodleConnectionError) as e:
                job_status["value"] = JOB_STATUS_AUTH_ERROR
                logger.error(f"Authentication/Connection error in content sync: {e}")
                self._handle_auth_error(
                    method,
                    body,
                    str(e),
                    job_id,
                    error_detail=traceback.format_exc(),
                    error_kind="auth"
                    if isinstance(e, MoodleAuthenticationError)
                    else "connection",
                )
            except Exception as e:
                job_status["value"] = JOB_STATUS_FAILED
                logger.error(f"Error processing content sync message: {e}")
                self._handle_error(
                    method,
                    body,
                    job_id,
                    error_msg=f"{type(e).__name__}: {e}",
                    error_detail=traceback.format_exc(),
                )

    def process_ingestion_message(self, ch, method, properties, body):
        """KB sync with automatic content download."""
        message = None
        job_id = None

        with track_job(JOB_TYPE_INGESTION) as job_status:
            try:
                message = json.loads(body)
                job_id = message.get("job_id")

                logger.info(
                    f"Processing KB sync message (job_id={job_id}): "
                    f"KB={message.get('knowledge_base_id')}"
                )

                kb_id = message["knowledge_base_id"]
                kb_name = message["knowledge_base_name"]
                kb_description = message["knowledge_base_description"]
                owner_email = message.get("owner_email")
                datasources = message["datasources"]
                haystack_url = message["haystack_url"]
                force = message.get("force", False)
                force_ocr = message.get("force_ocr", False)
                # forwarded to the rag-pipeline so it builds with the config the
                # API recorded; absent => pipeline falls back to its own env.
                embedding_config = message.get("embedding_config")

                if not owner_email:
                    raise ValueError("owner_email is required in ingestion message")

                self._publish_progress(job_id, message="Starting ingestion")

                haystack_client = HaystackClient(
                    haystack_url,
                    embedding_config=embedding_config,
                    STALE_TIMEOUT=self.config.haystack_stale_timeout,
                    ABSOLUTE_TIMEOUT=self.config.haystack_absolute_timeout,
                )
                try:
                    status = haystack_client.get_status()
                    logger.info(f"Connected to Hayhooks: {status}")
                except Exception as e:
                    raise Exception(f"Failed to connect to Hayhooks: {e}")
                self._publish_progress(
                    job_id, message="Connected to processing service"
                )

                total_downloaded, pruned_files = self._ensure_content_available(
                    datasources, owner_email, force
                )
                logger.info(f"Downloaded {total_downloaded} missing files")
                self._publish_progress(
                    job_id,
                    message=f"Downloaded {total_downloaded} files from storage",
                )

                # files pruned from storage because they no longer exist
                # upstream leave stale chunks in the index; delete those too so
                # they stop surfacing as citations. Prefer the stable file_id
                # (rename-proof); fall back to basename for chunks without one.
                # Best-effort: a failure here must not fail the sync.
                if pruned_files:
                    try:
                        file_ids = [
                            p["file_id"] for p in pruned_files if p.get("file_id")
                        ]
                        fallback_names = [
                            p["basename"] for p in pruned_files if not p.get("file_id")
                        ]
                        result = haystack_client.delete_documents(
                            file_ids=file_ids or None,
                            file_names=fallback_names or None,
                            index_name=kb_id,
                        )
                        payload = (result or {}).get("result", result) or {}
                        removed = payload.get("total_documents_removed", "?")
                        logger.info(
                            f"Pruned {len(pruned_files)} stale file(s) from index "
                            f"{kb_id}: {removed} document(s) removed"
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to prune stale documents from index {kb_id}: {e}"
                        )

                objects_to_sync = self._collect_datasource_files(
                    datasources, owner_email
                )
                n_files = len(objects_to_sync) if objects_to_sync else 0
                self._publish_progress(
                    job_id,
                    message=f"Collected {n_files} files for processing",
                    total_files=n_files,
                )

                sync_stats = self._sync_with_hayhooks(
                    haystack_client,
                    kb_id,
                    kb_name,
                    kb_description,
                    objects_to_sync,
                    force,
                    force_ocr=force_ocr,
                    job_id=job_id,
                )
                logger.info(f"Synced KB {kb_id} with Hayhooks: {sync_stats}")

                # zero succeeded means a broken KB; fail so the user can retry. partial success still completes.
                succeeded = sync_stats["succeeded"]
                failed = sync_stats["failed"]
                if succeeded == 0 and failed > 0:
                    raise Exception(
                        f"All {failed} files failed to ingest into KB {kb_id}; "
                        f"see job files for per-file errors"
                    )

                completion_message = {
                    "job_id": job_id,
                    "knowledge_base_id": kb_id,
                    "files_processed": len(objects_to_sync),
                    "files_succeeded": succeeded,
                    "files_failed": failed,
                    "failed_files": sync_stats["failed_files"],
                    "files_downloaded": total_downloaded,
                    "chunks_created": sync_stats["chunks_created"],
                    "haystack_index_name": kb_name,
                    # a forced sync recreates the Qdrant collection; the API uses
                    # this to know it can re-stamp the KB's index manifest.
                    "force": force,
                }
                self.mq_client.publish(
                    self.ingestion_queue.completed_name, completion_message
                )

                CHUNKS_CREATED.inc(sync_stats["chunks_created"])
                logger.info(
                    f"Published completion message for KB {kb_id} (job_id={job_id}): "
                    f"{succeeded} succeeded, {failed} failed"
                )

            except JobCancelledException:
                job_status["value"] = JOB_STATUS_CANCELLED
                logger.info(f"Job {job_id} cancelled, no completion published")
            except (MoodleAuthenticationError, MoodleConnectionError) as e:
                job_status["value"] = JOB_STATUS_AUTH_ERROR
                logger.error(f"Authentication/Connection error in ingestion: {e}")
                self._handle_auth_error(
                    method,
                    body,
                    str(e),
                    job_id,
                    error_detail=traceback.format_exc(),
                    error_kind="auth"
                    if isinstance(e, MoodleAuthenticationError)
                    else "connection",
                )
            except Exception as e:
                job_status["value"] = JOB_STATUS_FAILED
                logger.error(f"Error processing KB sync message: {e}")
                self._handle_error(
                    method,
                    body,
                    job_id,
                    error_msg=f"{type(e).__name__}: {e}",
                    error_detail=traceback.format_exc(),
                )

    def _sync_with_hayhooks(
        self,
        client: HaystackClient,
        kb_id: str,
        kb_name: str,
        kb_description: str,
        objects_to_sync: list[dict],
        force: bool = False,
        force_ocr: bool = False,
        job_id: str | None = None,
    ) -> SyncStats:
        """Orchestrate file sync with the Hayhooks ingestion pipeline.

        Per-file failures skip-and-continue; the caller decides partial
        success from the returned counts. JobCancelledException bubbles
        up to the handler.
        """
        logger.info(f"Starting sync with Hayhooks for KB: {kb_name} (ID: {kb_id})")
        logger.info(f"Files to process: {len(objects_to_sync)}")

        stats: SyncStats = {
            "succeeded": 0,
            "failed": 0,
            "failed_files": [],
            "chunks_created": 0,
        }

        if not objects_to_sync:
            logger.info("No files to sync")
            return stats

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            files_to_ingest = self._prepare_files_for_ingestion(
                objects_to_sync, temp_dir_path, job_id, stats
            )

            if not files_to_ingest:
                logger.warning("No valid files to ingest after processing")
                return stats

            self._ingest_prepared_files(
                client, files_to_ingest, kb_id, force, force_ocr, job_id, stats
            )

        logger.info(
            f"Completed sync with Hayhooks for KB {kb_name} (ID: {kb_id}): "
            f"{stats['succeeded']} succeeded, {stats['failed']} failed"
        )
        return stats

    def _record_file_failure(
        self,
        stats: SyncStats,
        job_id: str | None,
        file_id,
        filename: str,
        *,
        error_detail: str,
        short_error: str,
        error_code: str | None = None,
    ) -> None:
        # paired so state-publish and counter-bump can't drift
        self._publish_file_state(
            job_id,
            file_id=file_id,
            filename=filename,
            state=JobFileState.FAILED,
            error_message=USER_FACING_INGEST_ERROR,
            error_detail=error_detail,
            error_code=error_code,
        )
        stats["failed"] += 1
        stats["failed_files"].append({"filename": filename, "error": short_error})

    def _prepare_files_for_ingestion(
        self,
        objects_to_sync: list[dict],
        temp_dir: Path,
        job_id: str | None,
        stats: SyncStats,
    ) -> list[dict]:
        """Download + optionally process each source file. Skip-and-continue on failure."""
        files_to_ingest: list[dict] = []
        for file_info in objects_to_sync:
            prepared = self._prepare_single_file(file_info, temp_dir, job_id, stats)
            if prepared is not None:
                files_to_ingest.append(prepared)
        return files_to_ingest

    def _prepare_single_file(
        self,
        file_info: dict,
        temp_dir: Path,
        job_id: str | None,
        stats: SyncStats,
    ) -> dict | None:
        """Download + process one file. Returns None if recorded as failure in stats."""
        storage_file_path = file_info["path"]
        original_filename = file_info.get("filename", storage_file_path.name)
        file_id = file_info.get("file_id")
        mime_type = file_info.get("mime_type")
        source_url = file_info.get("source_url")

        self._publish_file_state(
            job_id,
            file_id=file_id,
            filename=original_filename,
            state=JobFileState.DOWNLOADING,
        )
        local_path = temp_dir / storage_file_path.name
        try:
            with track_file_stage(FILE_STAGE_DOWNLOAD):
                self.storage.download_file(
                    self.config.bucket_name, str(storage_file_path), local_path
                )
            logger.debug(f"Downloaded {storage_file_path.name} from storage")
        except Exception as e:
            logger.error(f"Error downloading file {storage_file_path}: {e}")
            self._record_file_failure(
                stats,
                job_id,
                file_id,
                original_filename,
                error_detail=f"Download error: {e}\n{traceback.format_exc()}",
                short_error=f"Download error: {e}",
                error_code=JobFileErrorCode.DOWNLOAD_FAILED,
            )
            return None

        try:
            processed_file = self._process_uploaded_file(local_path, temp_dir)
            if not (processed_file and processed_file.exists()):
                logger.warning(f"Failed to process file: {storage_file_path.name}")
                self._record_file_failure(
                    stats,
                    job_id,
                    file_id,
                    original_filename,
                    error_detail="File preprocessing produced no output",
                    short_error="File preprocessing produced no output",
                    error_code=JobFileErrorCode.PROCESSOR_FAILED,
                )
                return None

            ingest_entry = {
                "path": processed_file,
                "file_id": file_id,
                "filename": original_filename,
                "mime_type": mime_type,
            }
            if source_url:
                ingest_entry["source_url"] = source_url
            self._publish_file_state(
                job_id,
                file_id=file_id,
                filename=original_filename,
                state=JobFileState.DOWNLOADED,
            )
            return ingest_entry
        except Exception as e:
            logger.error(f"Error preparing file {storage_file_path}: {e}")
            self._record_file_failure(
                stats,
                job_id,
                file_id,
                original_filename,
                error_detail=f"Preparation error: {e}\n{traceback.format_exc()}",
                short_error=f"Preparation error: {e}",
                error_code=JobFileErrorCode.PROCESSOR_FAILED,
            )
            return None

    def _ingest_prepared_files(
        self,
        client: HaystackClient,
        files_to_ingest: list[dict],
        kb_id: str,
        force: bool,
        force_ocr: bool,
        job_id: str | None,
        stats: SyncStats,
    ) -> None:
        """Submit each prepared file to Haystack in turn.

        recreate_index is honored only on the first successful ingest: an
        initial failure must not silently drop the recreate and leave the
        old index in place.
        """
        pending_recreate = force
        total = len(files_to_ingest)
        for idx, file_info in enumerate(files_to_ingest):
            succeeded = self._ingest_one_file(
                client,
                file_info,
                kb_id,
                pending_recreate,
                force_ocr,
                job_id,
                stats,
                position=(idx + 1, total),
            )
            if succeeded:
                pending_recreate = False

    def _ingest_one_file(
        self,
        client: HaystackClient,
        file_info: dict,
        kb_id: str,
        recreate_index: bool,
        force_ocr: bool,
        job_id: str | None,
        stats: SyncStats,
        *,
        position: tuple[int, int],
    ) -> bool:
        """Ingest one prepared file. Returns True iff it ended up INGESTED."""
        file_id = file_info.get("file_id")
        filename = file_info["filename"]
        idx, total = position

        if self.mq_client.is_job_cancelled(job_id):
            logger.info(f"Job {job_id} cancelled, stopping ingestion")
            self._publish_progress(job_id, message="Job cancelled")
            raise JobCancelledException(job_id)

        self._publish_file_state(
            job_id,
            file_id=file_id,
            filename=filename,
            state=JobFileState.INGESTING,
        )
        logger.info(f"Ingesting file {idx}/{total}: {filename}")

        # keep progress_updated_at ticking during slow docling runs so mark_stalled_jobs doesn't reap us
        on_haystack_progress = self._progress_publisher().haystack_tick_handler(
            job_id,
            filename,
            pct_step=self.config.haystack_progress_pct_step,
            max_interval_seconds=self.config.haystack_progress_max_interval_seconds,
        )

        try:
            with track_file_stage(FILE_STAGE_INGEST):
                result = client.ingest_files(
                    file_infos=[file_info],
                    index_name=kb_id,
                    recreate_index=recreate_index,
                    export_type="doc_chunks",
                    force_ocr=force_ocr,
                    on_progress=on_haystack_progress,
                    cancel_check=lambda: self.mq_client.is_job_cancelled(job_id),
                    client_job_id=job_id,
                )
        except Exception as e:
            logger.exception(f"Ingestion raised for {filename}")
            self._record_file_failure(
                stats,
                job_id,
                file_id,
                filename,
                error_detail=f"Ingestion raised: {e}\n{traceback.format_exc()}",
                short_error=f"Ingestion raised: {e}",
                error_code=JobFileErrorCode.INGESTION_FAILED,
            )
            return False

        if result.cancelled:
            # in-flight file marked SKIPPED (no INGESTED|FAILED resolution), then bubble up
            self._publish_file_state(
                job_id,
                file_id=file_id,
                filename=filename,
                state=JobFileState.SKIPPED,
                error_message="Job cancelled",
            )
            self._publish_progress(job_id, message="Job cancelled")
            raise JobCancelledException(job_id)

        if not result.success:
            raw_err = result.error or "Ingestion failed"
            logger.warning(
                f"Ingestion failed for {filename}: {raw_err} "
                f"(detail: {result.error_detail})"
            )
            error_detail = result.error_detail or raw_err
            if result.haystack_job_id:
                # join key into the rag-pipeline's logs and Redis job store
                error_detail += f"\nhaystack_job_id={result.haystack_job_id}"
            self._record_file_failure(
                stats,
                job_id,
                file_id,
                filename,
                error_detail=error_detail,
                short_error=raw_err,
                error_code=JobFileErrorCode.INGESTION_TIMEOUT
                if result.timed_out
                else JobFileErrorCode.INGESTION_FAILED,
            )
            return False

        # docling can report success with zero chunks (image-only PDF, scanned page); surface as failure
        if not result.documents_ingested:
            empty_err = "File parsed but no text content extracted"
            logger.warning(f"Empty ingestion result for {filename}: {empty_err}")
            self._record_file_failure(
                stats,
                job_id,
                file_id,
                filename,
                error_detail=empty_err,
                short_error=empty_err,
                error_code=JobFileErrorCode.EMPTY_CONTENT,
            )
            return False

        stats["succeeded"] += 1
        stats["chunks_created"] += result.documents_ingested
        logger.info(
            f"File {idx}/{total} complete: {result.documents_ingested} documents"
        )
        self._publish_file_state(
            job_id,
            file_id=file_id,
            filename=filename,
            state=JobFileState.INGESTED,
        )
        return True

    def _ensure_content_available(
        self, datasources: list[dict], owner_email: str, force: bool = False
    ) -> tuple[int, list[dict]]:
        """Ensure selected content is in storage; dispatches per SourceAdapter.

        Returns (files_downloaded, pruned). pruned is a list of
        {"file_id", "basename"} records for storage objects removed because
        they no longer exist upstream; the caller deletes the matching
        documents from the vector index.
        """
        total_downloaded = 0
        pruned_records: list[dict] = []

        for datasource in datasources:
            try:
                source_type = SourceType.parse(datasource.get("source_type"))
            except ValueError as e:
                logger.warning(f"Skipping datasource: {e}")
                continue
            selected_files = datasource.get("selected_files", [])
            datasource_id = datasource.get("datasource_id")
            ds_owner_email = datasource.get("owner_email", owner_email)

            if not selected_files:
                logger.info(f"No selected files for datasource {datasource_id}")
                continue

            logger.info(f"Ensuring content availability for datasource {datasource_id}")
            downloaded, pruned = self._get_adapter(source_type).ensure_content(
                datasource, ds_owner_email, selected_files, force
            )
            total_downloaded += downloaded
            pruned_records.extend(pruned)

        return total_downloaded, pruned_records

    def _collect_datasource_files(
        self, datasources: list[dict], owner_email: str
    ) -> list[dict]:
        """Collect files by dispatching to source adapters.

        Adapters return dicts with at least path/filename/mime_type;
        Moodle also adds source_url/file_id.
        """
        objects_to_sync: list[dict] = []

        for datasource in datasources:
            try:
                source_type = SourceType.parse(datasource.get("source_type"))
            except ValueError as e:
                logger.warning(f"Skipping datasource: {e}")
                continue

            if not datasource.get("selected_files"):
                logger.warning(
                    f"No selected files for datasource "
                    f"{datasource.get('datasource_id')}"
                )
                continue

            logger.info(
                f"Processing datasource {datasource.get('datasource_id')} "
                f"(type: {source_type.name})"
            )
            objects_to_sync.extend(
                self._get_adapter(source_type).collect_files(datasource, owner_email)
            )

        logger.info(f"Total files collected for sync: {len(objects_to_sync)}")
        return objects_to_sync

    def _process_uploaded_file(self, file_path: Path, temp_dir: Path) -> Path | None:
        """Convert via the processor registry, or pass through. None on failure."""
        processor = processor_registry.find(file_path)
        if processor is None:
            return file_path
        try:
            return processor.process(file_path, temp_dir)
        except Exception:
            logger.error(
                "Processor %s failed for %s",
                processor.name,
                file_path.name,
                exc_info=True,
            )
            return None

    def _build_failure_payload(
        self,
        routing_key: str,
        message: dict,
        job_id: str | None,
        error_msg: str,
        error_detail: str | None,
        error_kind: str | None = None,
    ) -> tuple[str, dict] | None:
        """Build (queue, payload) for a job-level failure. Keeps both error handlers in lockstep.

        error_kind is the failure-dashboard bucket, set here where the
        exception type is known; without it the API falls back to
        string-matching on the error message.
        """
        base: dict = {"job_id": job_id, "error": error_msg}
        if error_detail:
            base["error_detail"] = error_detail
        if error_kind:
            base["error_kind"] = error_kind
        if routing_key == QueueNames.METADATA_SYNC:
            return (
                self.metadata_sync_queue.failed_name,
                {
                    **base,
                    "datasource_id": message.get("datasource_id"),
                    "operation": "metadata_sync",
                },
            )
        if routing_key == QueueNames.CONTENT_SYNC:
            return (
                self.content_sync_queue.failed_name,
                {
                    **base,
                    "datasource_id": message.get("datasource_id"),
                    "operation": "content_sync",
                    "files_downloaded": 0,
                },
            )
        if routing_key == QueueNames.INGESTION:
            return (
                self.ingestion_queue.failed_name,
                {
                    **base,
                    "knowledge_base_id": message.get("knowledge_base_id"),
                    "files_processed": 0,
                    "files_downloaded": 0,
                },
            )
        return None

    def _handle_auth_error(
        self,
        method,
        body: bytes,
        error_msg: str,
        job_id: str | None = None,
        error_detail: str | None = None,
        error_kind: str | None = None,
    ) -> None:
        """Immediately fail the job. error_detail carries the traceback; error_msg stays user-facing."""
        try:
            message = json.loads(body)

            if job_id is None:
                job_id = message.get("job_id")

            built = self._build_failure_payload(
                method.routing_key, message, job_id, error_msg, error_detail, error_kind
            )
            if built is not None:
                queue, payload = built
                self.mq_client.publish(queue, payload)

            logger.info(f"Published auth error for job_id={job_id}")

        except Exception as e:
            logger.error(f"Error in auth error handler: {e}")

    def _handle_error(
        self,
        method,
        body: bytes,
        job_id: str | None = None,
        error_msg: str = "Job failed",
        error_detail: str | None = None,
    ) -> None:
        """Publish to the failed queue. error_detail carries the traceback; error_msg stays generic."""
        try:
            message = json.loads(body)

            if job_id is None:
                job_id = message.get("job_id")

            logger.error(f"Job failed (job_id={job_id}). Moving to failed queue.")

            built = self._build_failure_payload(
                method.routing_key, message, job_id, error_msg, error_detail
            )
            if built is not None:
                queue, payload = built
                self.mq_client.publish(queue, payload)

        except Exception as e:
            logger.error(f"Error in error handler: {e}")

    def start(self) -> None:
        try:
            logger.info("Starting worker...")
            self._connect_rabbitmq()

            self.mq_client.consume(
                self.content_sync_queue.name, self.process_content_sync_message
            )
            self.mq_client.consume(
                self.ingestion_queue.name, self.process_ingestion_message
            )
            self.mq_client.consume(
                self.metadata_sync_queue.name, self.process_metadata_sync_message
            )

            logger.info(
                "Worker started. Listening on: %s, %s, %s",
                self.content_sync_queue.name,
                self.ingestion_queue.name,
                self.metadata_sync_queue.name,
            )
            self.mq_client.start_consuming()

        except KeyboardInterrupt:
            logger.info("Worker stopped by user")
        except Exception as e:
            logger.critical(f"Worker failed: {e}")
            sys.exit(1)

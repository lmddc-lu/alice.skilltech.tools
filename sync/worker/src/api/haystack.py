import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from metrics import (
    HAYSTACK_OUTCOME_ERROR,
    HAYSTACK_OUTCOME_OK,
    HAYSTACK_OUTCOME_TIMEOUT,
    HAYSTACK_REQUEST_DURATION,
    HAYSTACK_REQUESTS,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# (stage_or_status, progress_pct, raw_status_dict)
ProgressCallback = Callable[[str, int, dict], None]

# polled per iteration so long Docling conversions can be interrupted
# between status ticks, not only at file boundaries
CancelCheck = Callable[[], bool]


def _safe_cancelled(cancel_check: CancelCheck) -> bool:
    try:
        return bool(cancel_check())
    except Exception as e:
        logger.warning(f"cancel_check raised, treating as not cancelled: {e}")
        return False


@dataclass
class IngestionResult:
    success: bool
    documents_ingested: int
    error: str | None = None
    # verbose converter payload kept separate so the user-facing error stays short
    error_detail: str | None = None
    # distinct from a regular failure so the caller raises JobCancelledException
    # instead of recording a file failure
    cancelled: bool = False
    # stale/absolute timeout, so the caller can classify without string-matching
    timed_out: bool = False
    # rag-pipeline's own job id, for correlating with hayhooks logs/Redis
    haystack_job_id: str | None = None


@dataclass
class HaystackClient:
    base_url: str

    # API-dictated embedding config ({model, dim, distance, sparse_model}),
    # forwarded to the rag-pipeline on submit so it builds the collection with
    # the config the control plane recorded. None => pipeline uses its own env.
    embedding_config: dict | None = None

    # short on purpose: /status returns in ms, don't let a black-holed SYN stall the poller
    DEFAULT_TIMEOUT: int = 5
    SUBMIT_TIMEOUT: int = 60
    RESULT_TIMEOUT: int = 30
    CONNECT_TIMEOUT: int = 10
    POLL_INTERVAL: int = 5
    # worker-side stale check, independent of the API-side mark_stalled_jobs scheduler
    STALE_TIMEOUT: int = 900
    # 24h safety net
    ABSOLUTE_TIMEOUT: int = 86400
    MAX_POLL_FAILURES: int = 12

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            **kwargs.pop("headers", {}),
        }
        read_timeout = kwargs.pop("timeout", self.DEFAULT_TIMEOUT)
        # tuple so connection failures surface fast
        timeout = (self.CONNECT_TIMEOUT, read_timeout)
        logger.debug(f"{method} {url}")
        outcome = HAYSTACK_OUTCOME_ERROR
        start = time.perf_counter()
        try:
            response = requests.request(
                method, url, headers=headers, timeout=timeout, **kwargs
            )
            response.raise_for_status()
            outcome = HAYSTACK_OUTCOME_OK
            return response.json()
        except requests.exceptions.Timeout:
            outcome = HAYSTACK_OUTCOME_TIMEOUT
            raise
        finally:
            HAYSTACK_REQUEST_DURATION.observe(time.perf_counter() - start)
            HAYSTACK_REQUESTS.labels(outcome=outcome).inc()

    def submit_ingestion(
        self,
        file_infos: list[dict],
        index_name: str,
        recreate_index: bool = False,
        export_type: str = "doc_chunks",
        force_ocr: bool = False,
        client_job_id: str | None = None,
    ) -> str:
        """Submit an async ingestion job. Returns the rag-pipeline's job_id.

        client_job_id is the platform's Job id; it rides along so the
        rag-pipeline can log and store it for cross-service correlation.
        """
        files = []
        file_metadata = []
        for info in file_infos:
            file_path = info["path"]
            if not file_path.exists():
                raise FileNotFoundError(f"File {file_path} not found")
            files.append(("files", open(file_path, "rb")))
            meta = {
                "file_id": info.get("file_id"),
                "filename": info.get("filename", file_path.name),
                "stored_filename": file_path.name,
                "mime_type": info.get("mime_type"),
            }
            if info.get("source_url"):
                meta["source_url"] = info["source_url"]
            file_metadata.append(meta)

        try:
            data = {
                "export_type": export_type,
                "recreate_index": recreate_index,
                "index_name": index_name,
                "file_metadata": json.dumps(file_metadata),
                "force_ocr": force_ocr,
                "action": "submit",
            }
            if client_job_id:
                data["client_job_id"] = client_job_id
            if self.embedding_config:
                data["embedding_config"] = json.dumps(self.embedding_config)
            response = self._make_request(
                method="POST",
                endpoint="/document_ingestion/run",
                files=files,
                data=data,
                timeout=self.SUBMIT_TIMEOUT,
            )
            result = response.get("result", {})
            job_id = result.get("job_id")
            if not job_id:
                raise RuntimeError(f"Submit did not return job_id: {result}")
            return job_id
        finally:
            for _, fh in files:
                fh.close()

    def get_ingestion_status(self, job_id: str) -> dict:
        """Query job status from hayhooks."""
        data = {"action": "status", "job_id": job_id}
        response = self._make_request(
            method="POST",
            endpoint="/document_ingestion/run",
            data=data,
            timeout=self.DEFAULT_TIMEOUT,
        )
        return response.get("result", {})

    def get_ingestion_result(self, job_id: str) -> dict:
        """Fetch completed job result from hayhooks."""
        data = {"action": "result", "job_id": job_id}
        response = self._make_request(
            method="POST",
            endpoint="/document_ingestion/run",
            data=data,
            timeout=self.RESULT_TIMEOUT,
        )
        return response.get("result", {})

    def ingest_files(
        self,
        file_infos: list[dict],
        index_name: str,
        recreate_index: bool = False,
        export_type: str = "doc_chunks",
        force_ocr: bool = False,
        on_progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
        client_job_id: str | None = None,
    ) -> IngestionResult:
        """Ingest files via async submit+poll.

        on_progress fires per status snapshot change; exceptions are swallowed.
        cancel_check is polled per iteration; cancellation is best-effort and
        only stops the local wait, not the remote Haystack job.
        client_job_id (the platform Job id) is forwarded to the rag-pipeline
        for log correlation.
        """
        if not file_infos:
            raise ValueError("No files provided for ingestion")

        # skip submit if already cancelled while queued
        if cancel_check is not None and _safe_cancelled(cancel_check):
            return IngestionResult(
                success=False,
                documents_ingested=0,
                error="Cancelled before submit",
                cancelled=True,
            )

        job_id = self.submit_ingestion(
            file_infos,
            index_name,
            recreate_index,
            export_type,
            force_ocr,
            client_job_id=client_job_id,
        )
        logger.info(f"Submitted async ingestion job: {job_id}")

        result = self._await_ingestion(
            job_id, on_progress=on_progress, cancel_check=cancel_check
        )
        result.haystack_job_id = job_id
        return result

    def _await_ingestion(
        self,
        job_id: str,
        *,
        on_progress: ProgressCallback | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> IngestionResult:
        """Poll one submitted rag-pipeline job to a terminal IngestionResult."""
        start_time = time.monotonic()
        last_status_snapshot = None
        last_change_time = start_time
        consecutive_failures = 0

        while True:
            elapsed = time.monotonic() - start_time

            if elapsed > self.ABSOLUTE_TIMEOUT:
                return IngestionResult(
                    success=False,
                    documents_ingested=0,
                    error=f"Job {job_id} exceeded absolute timeout ({self.ABSOLUTE_TIMEOUT}s)",
                    timed_out=True,
                )

            if cancel_check is not None and _safe_cancelled(cancel_check):
                logger.info(f"Job {job_id} cancelled mid-poll; aborting wait")
                return IngestionResult(
                    success=False,
                    documents_ingested=0,
                    error=f"Job {job_id} cancelled",
                    cancelled=True,
                )

            time.sleep(self.POLL_INTERVAL)

            try:
                status = self.get_ingestion_status(job_id)
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                logger.warning(
                    f"Status poll failed for job {job_id} "
                    f"({consecutive_failures}/{self.MAX_POLL_FAILURES}): {e}"
                )
                if consecutive_failures >= self.MAX_POLL_FAILURES:
                    return IngestionResult(
                        success=False,
                        documents_ingested=0,
                        error=f"Lost connection to Hayhooks after {consecutive_failures} consecutive poll failures: {e}",
                    )
                continue

            current_snapshot = (
                status.get("status"),
                status.get("stage"),
                status.get("progress_pct"),
            )
            logger.info(
                f"Job {job_id}: status={status.get('status')}, "
                f"stage={status.get('stage')}, "
                f"progress={status.get('progress_pct')}%, "
                f"elapsed={status.get('elapsed', '?')}s"
            )

            if current_snapshot != last_status_snapshot:
                last_status_snapshot = current_snapshot
                last_change_time = time.monotonic()
                if on_progress is not None:
                    try:
                        stage = status.get("stage") or status.get("status") or ""
                        pct = int(status.get("progress_pct") or 0)
                        on_progress(stage, pct, status)
                    except Exception as cb_err:
                        logger.warning(
                            f"on_progress callback raised for job {job_id}: {cb_err}"
                        )

            if time.monotonic() - last_change_time > self.STALE_TIMEOUT:
                return IngestionResult(
                    success=False,
                    documents_ingested=0,
                    error=f"Job {job_id} stale: no progress for {self.STALE_TIMEOUT}s",
                    timed_out=True,
                )

            job_status = status.get("status")

            if job_status == "completed":
                result_data = None
                for attempt in range(3):
                    try:
                        result_data = self.get_ingestion_result(job_id)
                        break
                    except Exception as e:
                        if attempt < 2:
                            logger.warning(
                                f"Result fetch failed for job {job_id} (attempt {attempt + 1}/3): {e}"
                            )
                            time.sleep(self.POLL_INTERVAL)
                        else:
                            return IngestionResult(
                                success=False,
                                documents_ingested=0,
                                error=f"Failed to fetch result after 3 attempts: {e}",
                            )

                inner = result_data.get("result", result_data)
                if not inner.get("success", False):
                    return IngestionResult(
                        success=False,
                        documents_ingested=0,
                        error=inner.get("error", "Unknown error from Haystack"),
                    )
                return IngestionResult(
                    success=True,
                    documents_ingested=inner.get("documents_created", 0),
                )

            if job_status == "failed":
                # pipeline wrapper stores per-file converter errors via
                # set_result before set_failed, so fetch them here
                error_detail = None
                try:
                    result_data = self.get_ingestion_result(job_id)
                    inner = (result_data.get("result", {}) if result_data else {}) or {}
                    failed_files = inner.get("failed_files") or []
                    if failed_files:
                        error_detail = "; ".join(
                            f"{ff.get('filename', '?')}: {ff.get('error', '?')}"
                            for ff in failed_files
                        )
                except Exception as detail_err:
                    logger.debug(
                        f"Could not fetch error_detail for failed job {job_id}: {detail_err}"
                    )
                return IngestionResult(
                    success=False,
                    documents_ingested=0,
                    error=status.get("error", "Job failed without error message"),
                    error_detail=error_detail,
                )

            if status.get("error") and "not found" in status.get("error", "").lower():
                return IngestionResult(
                    success=False,
                    documents_ingested=0,
                    error=status["error"],
                )

    def ingest_file(
        self,
        file_path: Path,
        index_name: str,
        recreate_index: bool = False,
        export_type: str = "doc_chunks",
        file_id: str = None,
        filename: str = None,
        mime_type: str = None,
    ) -> dict:
        """Ingest a single file using the document_ingestion pipeline."""
        file_info = {
            "path": file_path,
            "file_id": file_id,
            "filename": filename or file_path.name,
            "mime_type": mime_type,
        }
        return self.ingest_files([file_info], index_name, recreate_index, export_type)

    def list_documents(self, index_name: str | None = None) -> dict:
        """List documents in an index."""
        data = {"action": "list"}
        if index_name:
            data["index_name"] = index_name

        return self._make_request("POST", "document_management/run", json=data)

    def delete_documents(
        self,
        file_names: list[str] = None,
        file_paths: list[str] = None,
        index_name: str | None = None,
        file_ids: list[str] | None = None,
    ) -> dict:
        """Delete documents from an index.

        file_ids match the stable meta.file_id (rename-proof); file_names
        fall back to origin-filename matching for chunks without a file_id.
        """
        data = {"action": "delete"}

        if file_ids:
            data["file_ids"] = file_ids
        if file_names:
            data["file_names"] = file_names
        if file_paths:
            data["file_paths"] = file_paths
        if index_name:
            data["index_name"] = index_name

        return self._make_request("POST", "document_management/run", json=data)

    def query_rag(
        self,
        question: str,
        index_name: str | None = None,
        top_k: int | None = None,
        conversation_history: list[dict] | None = None,
    ) -> dict:
        """Query the RAG system."""
        data = {"question": question}

        if top_k:
            data["top_k"] = top_k
        if conversation_history:
            data["conversation_history"] = conversation_history
        if index_name:
            data["index_name"] = index_name

        return self._make_request("POST", "rag_query/run", json=data)

    def get_status(self) -> dict:
        return self._make_request("GET", "status")

    def get_pipeline_status(self, pipeline_name: str) -> dict:
        return self._make_request("GET", f"status/{pipeline_name}")

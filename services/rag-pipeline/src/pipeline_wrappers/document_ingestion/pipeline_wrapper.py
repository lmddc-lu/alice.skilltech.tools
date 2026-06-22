import json
import os
import tempfile
import threading
import traceback as tb_module
from pathlib import Path
from typing import Any

from components.DoclingChunker import DoclingChunker
from components.DoclingServeConverter import DoclingServeConverter
from config import (
    CHUNKER_MAX_TOKENS,
    CHUNKER_TOKENIZER,
    DOCLING_DOCUMENT_TIMEOUT,
    DOCLING_OCR_ENGINE,
    DOCLING_OCR_LANG,
    DOCLING_PDF_BACKEND,
    DOCLING_SERVE_API_KEY,
    DOCLING_SERVE_TIMEOUT,
    DOCLING_SERVE_URL,
    DOCLING_TABLE_MODE,
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_MODEL,
    EMBEDDING_DIM,
    JOB_TTL,
    QDRANT_HNSW_CONFIG,
    QDRANT_INDEX,
    QDRANT_URL,
    REDIS_URL,
    SPARSE_EMBED_MODEL,
    USE_SPARSE_EMBEDDINGS,
)
from fastapi import UploadFile
from hayhooks import BasePipelineWrapper
from haystack import Pipeline
from haystack.components.embedders import OpenAIDocumentEmbedder
from haystack.components.writers import DocumentWriter
from haystack.document_stores.types import DuplicatePolicy
from haystack.utils import Secret
from haystack_integrations.components.embedders.fastembed import (
    FastembedSparseDocumentEmbedder,
)
from haystack_integrations.document_stores.qdrant import QdrantDocumentStore
from index_config import resolve_embedding_config, resolve_sparse_for_index
from loguru import logger
from RedisJobStore import RedisJobStore

from .components import DocumentLogger


class IngestionPipelineWrapper(BasePipelineWrapper):
    """Document ingestion with optional hybrid search."""

    def setup(self) -> None:
        self._document_stores = {}
        self._default_index = QDRANT_INDEX

        self.document_store = self._get_document_store()

        self.job_store = RedisJobStore(REDIS_URL, JOB_TTL)

        logger.info(
            f"Embedding dim: {EMBEDDING_DIM}, Sparse embeddings: {USE_SPARSE_EMBEDDINGS}"
        )
        logger.info(f"Docling-serve URL: {DOCLING_SERVE_URL}")

    def _get_document_store(
        self,
        index_name: str = None,
        recreate: bool = False,
        embedding_dim: int | None = None,
        desired_sparse: bool | None = None,
    ) -> QdrantDocumentStore:
        if index_name is None:
            index_name = self._default_index

        if recreate or index_name not in self._document_stores:
            # On recreate, build with the desired default (dictated by the API
            # or this service's env); otherwise match the existing collection so
            # adding files to a dense collection stays dense (and never
            # mismatches and raises).
            use_sparse = resolve_sparse_for_index(
                index_name, recreate=recreate, desired_sparse=desired_sparse
            )
            logger.info(
                f"Creating document store for index: {index_name} with sparse embeddings: {use_sparse}"
            )
            self._document_stores[index_name] = QdrantDocumentStore(
                url=QDRANT_URL,
                index=index_name,
                embedding_dim=embedding_dim or EMBEDDING_DIM,
                recreate_index=recreate,
                use_sparse_embeddings=use_sparse,
                hnsw_config=QDRANT_HNSW_CONFIG,
            )

        return self._document_stores[index_name]

    def _create_indexing_pipeline(
        self,
        document_store,
        force_ocr: bool = False,
        embed_model: str | None = None,
        sparse_model: str | None = None,
    ) -> Pipeline:
        pipeline = Pipeline()

        pipeline.add_component(
            "converter",
            DoclingServeConverter(
                url=DOCLING_SERVE_URL,
                timeout=DOCLING_SERVE_TIMEOUT,
                api_key=DOCLING_SERVE_API_KEY,
                to_format="json",  # json lets us reconstruct DoclingDocument
                do_ocr=True,
                force_ocr=force_ocr,
                ocr_engine=DOCLING_OCR_ENGINE,
                ocr_lang=DOCLING_OCR_LANG,
                pdf_backend=DOCLING_PDF_BACKEND,
                table_mode=DOCLING_TABLE_MODE,
                document_timeout=DOCLING_DOCUMENT_TIMEOUT,
            ),
        )

        pipeline.add_component(
            "chunker",
            DoclingChunker(
                tokenizer=CHUNKER_TOKENIZER,
                max_tokens=CHUNKER_MAX_TOKENS,
                merge_peers=True,
            ),
        )

        pipeline.add_component("log_chunked", DocumentLogger("CHUNKED"))

        use_sparse = document_store.use_sparse_embeddings
        if use_sparse:
            pipeline.add_component(
                "sparse_embedder",
                FastembedSparseDocumentEmbedder(
                    model=sparse_model or SPARSE_EMBED_MODEL
                ),
            )

        pipeline.add_component(
            "dense_embedder",
            OpenAIDocumentEmbedder(
                api_key=Secret.from_token(EMBED_API_KEY),
                model=embed_model or EMBED_MODEL,
                api_base_url=EMBED_API_BASE,
            ),
        )

        pipeline.add_component("log_embedded", DocumentLogger("EMBEDDED"))

        pipeline.add_component(
            "writer",
            DocumentWriter(document_store=document_store, policy=DuplicatePolicy.SKIP),
        )

        pipeline.connect("converter.docling_documents", "chunker.docling_documents")
        pipeline.connect("converter.doc_metadata", "chunker.doc_metadata")
        pipeline.connect("chunker.documents", "log_chunked.documents")

        if use_sparse:
            pipeline.connect("log_chunked.documents", "sparse_embedder.documents")
            pipeline.connect("sparse_embedder", "dense_embedder")
            pipeline.connect("dense_embedder", "log_embedded.documents")
            pipeline.connect("log_embedded.documents", "writer.documents")
        else:
            pipeline.connect("log_chunked.documents", "dense_embedder.documents")
            pipeline.connect("dense_embedder", "log_embedded.documents")
            pipeline.connect("log_embedded.documents", "writer.documents")

        return pipeline

    def _save_uploaded_files(self, files: list[UploadFile]) -> list[str]:
        """Save uploaded files to a temp dir and return paths."""
        temp_dir = tempfile.mkdtemp()
        temp_paths = []

        for file in files:
            if file.filename:
                safe_filename = Path(file.filename).name
                temp_path = os.path.join(temp_dir, safe_filename)

                with open(temp_path, "wb") as temp_file:
                    content = file.file.read()
                    temp_file.write(content)

                temp_paths.append(temp_path)
                file.file.seek(0)

        return temp_paths

    def _cleanup_temp_files(self, temp_paths: list[str]) -> None:
        for temp_path in temp_paths:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    temp_dir = os.path.dirname(temp_path)
                    if os.path.exists(temp_dir) and not os.listdir(temp_dir):
                        os.rmdir(temp_dir)
            except Exception as e:
                print(f"Warning: Could not clean up temporary file {temp_path}: {e}")

    @staticmethod
    def _build_path_metadata(
        valid_paths: list[str], parsed_file_metadata: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Map each input path to its per-file metadata entry.

        Matches on basename via ``stored_filename`` (what the file was saved as
        on disk), falling back to ``filename``. The converter then carries the
        result onto its docling_documents/doc_metadata outputs, so the pipeline
        doesn't have to re-match by filename downstream.
        """
        meta_by_name: dict[str, dict[str, Any]] = {}
        for meta in parsed_file_metadata:
            for key in ("stored_filename", "filename"):
                name = meta.get(key)
                if name:
                    meta_by_name.setdefault(Path(name).name, meta)

        path_metadata: dict[str, dict[str, Any]] = {}
        for path in valid_paths:
            matched = meta_by_name.get(Path(path).name)
            if matched:
                path_metadata[path] = matched
        return path_metadata

    def _run_pipeline_background(
        self,
        job_id: str,
        valid_paths: list[str],
        temp_paths: list[str],
        index_name: str | None,
        recreate_index: bool,
        parsed_file_metadata: list[dict[str, Any]] | None,
        had_files: bool,
        force_ocr: bool = False,
        embedding_config: dict | str | None = None,
    ) -> None:
        """Run the ingestion pipeline in a thread, updating Redis job state."""
        try:
            self.job_store.update_job(job_id, status="running", stage="converting")

            # API-dictated embedding config (falls back to env). The same config
            # must shape both the store (dim/sparse) and the embedders (models).
            cfg = resolve_embedding_config(embedding_config)
            document_store = self._get_document_store(
                index_name,
                recreate_index,
                embedding_dim=cfg["dim"],
                desired_sparse=bool(cfg["sparse_model"]),
            )
            pipeline = self._create_indexing_pipeline(
                document_store,
                force_ocr=force_ocr,
                embed_model=cfg["model"],
                sparse_model=cfg["sparse_model"],
            )

            self.job_store.update_job(
                job_id, status="running", stage="running_pipeline", progress_pct=30
            )

            logger.info(
                f"[Job {job_id}] Starting pipeline run with paths: {valid_paths}"
            )
            pipeline_input = {"converter": {"paths": valid_paths}}
            if parsed_file_metadata:
                pipeline_input["converter"]["path_metadata"] = (
                    self._build_path_metadata(valid_paths, parsed_file_metadata)
                )
            result = pipeline.run(pipeline_input)

            self.job_store.update_job(
                job_id, status="running", stage="finalizing", progress_pct=90
            )

            documents_written = result.get("writer", {}).get("documents_written", [])
            failed_files = result.get("converter", {}).get("failed_files", [])

            all_failed = len(failed_files) == len(valid_paths)
            response = {
                "success": not all_failed,
                "processed_files": len(valid_paths),
                "documents_created": documents_written,
                "failed_files": failed_files,
                "recreated_index": recreate_index,
                "index_name": index_name or self._default_index,
                "file_paths": valid_paths,
                "upload_mode": had_files,
                "hybrid_search_enabled": document_store.use_sparse_embeddings,
            }

            if failed_files:
                # log full error detail (not just filenames) so admin triage
                # can recover Docling's failure reason from container logs
                # even if the Redis job store has expired.
                logger.warning(
                    f"[Job {job_id}] {len(failed_files)}/{len(valid_paths)} file(s) failed conversion: "
                    f"{[(f.get('filename'), f.get('error')) for f in failed_files]}"
                )

            if all_failed:
                error_msg = f"All {len(valid_paths)} file(s) failed conversion"
                logger.error(f"[Job {job_id}] {error_msg}")
                # store result first so callers can inspect failed_files details
                self.job_store.set_result(job_id, response)
                self.job_store.set_failed(job_id, error_msg)
            else:
                self.job_store.set_result(job_id, response)

        except Exception as e:
            logger.error(f"[Job {job_id}] Pipeline failed: {e}")
            logger.error(f"[Job {job_id}] Traceback: {tb_module.format_exc()}")
            self.job_store.set_failed(job_id, str(e))

        finally:
            if temp_paths:
                self._cleanup_temp_files(temp_paths)

    def run_api(
        self,
        files: list[UploadFile] | None = None,
        file_paths: list[str] | None = None,
        recreate_index: bool = False,
        index_name: str | None = None,
        file_metadata: str | None = None,
        force_ocr: bool = False,
        action: str = "submit",
        job_id: str | None = None,
        client_job_id: str | None = None,
        embedding_config: str | None = None,
    ) -> dict[str, Any]:
        """Run the ingestion pipeline.

        :param action: "submit", "status", or "result".
        :param file_metadata: JSON string of per-file metadata.
        :param client_job_id: the calling platform's job id, logged and kept
            in job metadata so this run can be correlated with the caller's
            job from either side.
        :param embedding_config: JSON string of the API-dictated embedding
            config ({model, dim, distance, sparse_model}); falls back to this
            service's env when absent.
        """
        if action == "status":
            if not job_id:
                return {"error": "job_id is required for action=status"}
            job = self.job_store.get_job(job_id)
            if not job:
                return {"error": f"Job {job_id} not found"}
            return job

        if action == "result":
            if not job_id:
                return {"error": "job_id is required for action=result"}
            job = self.job_store.get_job(job_id)
            if not job:
                return {"error": f"Job {job_id} not found"}
            if job["status"] == "completed":
                result = self.job_store.get_result(job_id)
                return {"status": "completed", "result": result}
            if job["status"] == "failed":
                # all_failed runs store per-file errors via set_result before
                # calling set_failed (see the pipeline run branch). Return that
                # payload so the worker can surface Docling-level error detail.
                result = self.job_store.get_result(job_id)
                response = {
                    "status": "failed",
                    "error": job.get("error", "Unknown error"),
                }
                if result is not None:
                    response["result"] = result
                return response
            return {"status": job["status"], "message": "Job is still running"}

        if action == "submit":
            temp_paths = []
            processing_paths = []

            if files:
                temp_paths = self._save_uploaded_files(files)
                processing_paths = temp_paths
            elif file_paths:
                processing_paths = file_paths
            else:
                return {"error": "No files or file_paths provided"}

            valid_paths = [p for p in processing_paths if Path(p).exists()]
            if not valid_paths:
                return {"error": "No valid file paths found"}

            parsed_file_metadata = None
            if file_metadata:
                try:
                    parsed_file_metadata = json.loads(file_metadata)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid file_metadata JSON, ignoring: {e}")

            new_job_id = self.job_store.create_job(
                metadata={
                    "file_count": len(valid_paths),
                    "index_name": index_name or self._default_index,
                    "client_job_id": client_job_id,
                }
            )
            logger.info(
                f"[Job {new_job_id}] Submitted: {len(valid_paths)} file(s), "
                f"index={index_name or self._default_index}, "
                f"client_job_id={client_job_id}"
            )

            thread = threading.Thread(
                target=self._run_pipeline_background,
                args=(
                    new_job_id,
                    valid_paths,
                    temp_paths,
                    index_name,
                    recreate_index,
                    parsed_file_metadata,
                    bool(files),
                    force_ocr,
                    embedding_config,
                ),
                daemon=True,
            )
            thread.start()

            return {"job_id": new_job_id, "status": "pending"}

        return {"error": f"Unknown action: {action}"}


PipelineWrapper = IngestionPipelineWrapper

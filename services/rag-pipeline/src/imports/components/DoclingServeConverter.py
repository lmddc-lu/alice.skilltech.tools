"""Haystack component for document conversion via docling-serve API."""

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx
from docling_core.types import DoclingDocument
from haystack import component
from loguru import logger


@component
class DoclingServeConverter:
    """Convert documents through a remote docling-serve instance.

    Uses the async API to submit jobs and poll for results.
    """

    def __init__(
        self,
        url: str,
        timeout: float,
        api_key: str | None = None,
        from_formats: list[str] | None = None,
        to_format: str = "json",
        do_ocr: bool = True,
        force_ocr: bool = False,
        ocr_engine: str = "easyocr",
        ocr_lang: list[str] | None = None,
        pdf_backend: str = "docling_parse",
        table_mode: str = "accurate",
        do_table_structure: bool = True,
        include_images: bool = False,
        abort_on_error: bool = False,
        document_timeout: float = 240.0,
        poll_interval: float = 2.0,
        max_wait_time: float = 600.0,
        chunk_max_tokens: int | None = None,
    ):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.api_key = api_key

        self.from_formats = from_formats or [
            "docx",
            "pptx",
            "html",
            "image",
            "pdf",
            "asciidoc",
            "md",
            "xlsx",
        ]
        self.to_format = to_format
        self.do_ocr = do_ocr
        self.force_ocr = force_ocr
        self.ocr_engine = ocr_engine
        self.ocr_lang = ocr_lang or ["en", "fr", "de"]
        self.pdf_backend = pdf_backend
        self.table_mode = table_mode
        self.do_table_structure = do_table_structure
        self.include_images = include_images
        self.abort_on_error = abort_on_error
        self.document_timeout = document_timeout
        self.chunk_max_tokens = chunk_max_tokens

        self.poll_interval = poll_interval
        self.max_wait_time = max_wait_time

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        return headers

    def _build_options(self) -> dict[str, Any]:
        options = {
            "from_formats": self.from_formats,
            "to_formats": [self.to_format],
            "do_ocr": self.do_ocr,
            "force_ocr": self.force_ocr,
            "ocr_engine": self.ocr_engine,
            "ocr_lang": self.ocr_lang,
            "pdf_backend": self.pdf_backend,
            "table_mode": self.table_mode,
            "do_table_structure": self.do_table_structure,
            "include_images": self.include_images,
            "abort_on_error": self.abort_on_error,
            "document_timeout": self.document_timeout,
        }
        return options

    def _submit_file_async(self, client: httpx.Client, file_path: Path) -> str:
        """Submit a file for async conversion and return task_id."""
        endpoint = f"{self.url}/v1/convert/file/async"

        data = {
            "from_formats": self.from_formats,
            "to_formats": [self.to_format],
            "do_ocr": str(self.do_ocr).lower(),
            "force_ocr": str(self.force_ocr).lower(),
            "ocr_engine": self.ocr_engine,
            "pdf_backend": self.pdf_backend,
            "table_mode": self.table_mode,
            "do_table_structure": str(self.do_table_structure).lower(),
            "include_images": str(self.include_images).lower(),
            "abort_on_error": str(self.abort_on_error).lower(),
            "document_timeout": str(self.document_timeout),
        }

        data["ocr_lang"] = self.ocr_lang

        mime_type = self._get_mime_type(file_path)
        with open(file_path, "rb") as f:
            files = {"files": (file_path.name, f, mime_type)}

            # multipart sets its own Content-Type
            headers = self._get_headers()
            headers.pop("Content-Type", None)

            response = client.post(
                endpoint,
                data=data,
                files=files,
                headers=headers,
            )

        response.raise_for_status()
        result = response.json()
        return result["task_id"]

    def _poll_for_result(
        self, client: httpx.Client, task_id: str, file_name: str
    ) -> dict[str, Any]:
        """Poll for task completion and return result."""
        poll_endpoint = f"{self.url}/v1/status/poll/{task_id}"
        result_endpoint = f"{self.url}/v1/result/{task_id}"

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > self.max_wait_time:
                raise TimeoutError(f"Conversion timed out after {self.max_wait_time}s")

            response = client.get(poll_endpoint, headers=self._get_headers())
            response.raise_for_status()
            status_data = response.json()

            task_status = status_data.get("task_status", "unknown")
            task_position = status_data.get("task_position", "?")

            if task_status == "success":
                logger.info(f"{file_name}: Conversion complete, fetching result")
                result_response = client.get(
                    result_endpoint, headers=self._get_headers()
                )
                result_response.raise_for_status()
                return result_response.json()

            elif task_status == "failure":
                # result endpoint may carry richer error details than status
                error_details = status_data.get("errors", [])
                try:
                    result_response = client.get(
                        result_endpoint, headers=self._get_headers()
                    )
                    if result_response.status_code == 200:
                        result_data = result_response.json()
                        error_details = result_data.get("errors", error_details)
                except Exception:
                    pass
                raise RuntimeError(
                    f"Conversion failed for {file_name}: {error_details}"
                )

            elif task_status in ("pending", "started"):
                logger.info(
                    f"{file_name}: Status={task_status}, position={task_position}, elapsed={elapsed:.1f}s"
                )
                time.sleep(self.poll_interval)

            else:
                logger.warning(f"{file_name}: Unknown status: {task_status}")
                time.sleep(self.poll_interval)

    def _convert_file_via_source(
        self, client: httpx.Client, file_path: Path
    ) -> dict[str, Any]:
        """Convert via the source endpoint with base64 encoding."""
        endpoint = f"{self.url}/v1/convert/source"

        with open(file_path, "rb") as f:
            file_content = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "options": self._build_options(),
            "sources": [
                {
                    "kind": "file",
                    "base64_string": file_content,
                    "filename": file_path.name,
                }
            ],
        }

        response = client.post(
            endpoint,
            json=payload,
            headers=self._get_headers(),
        )

        response.raise_for_status()
        return response.json()

    def _get_mime_type(self, file_path: Path) -> str:
        mime_type, _ = mimetypes.guess_type(file_path.name)
        return mime_type or "application/octet-stream"

    def _extract_content(self, result: dict[str, Any]) -> str:
        doc = result.get("document", {})

        format_to_field = {
            "md": "md_content",
            "json": "json_content",
            "html": "html_content",
            "text": "text_content",
            "doctags": "doctags_content",
        }

        field = format_to_field.get(self.to_format, "md_content")
        content = doc.get(field, "")

        if isinstance(content, dict):
            import json

            content = json.dumps(content)

        return content or ""

    def _extract_docling_document(
        self, result: dict[str, Any]
    ) -> DoclingDocument | None:
        doc = result.get("document", {})
        json_content = doc.get("json_content")

        if not json_content:
            return None

        try:
            return DoclingDocument.model_validate(json_content)
        except Exception as e:
            logger.error(f"Failed to reconstruct DoclingDocument: {e}")
            return None

    @component.output_types(
        docling_documents=list[DoclingDocument],
        doc_metadata=list[dict[str, Any]],
        failed_files=list[dict[str, str]],
    )
    def run(
        self,
        paths: list[str | Path],
        meta: dict[str, Any] | None = None,
        path_metadata: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Convert documents using the docling-serve async API.

        :param path_metadata: per-path metadata (file_id, filename, mime_type,
            source_url, ...), keyed by path string or basename. Travels with each
            produced DoclingDocument via the parallel ``doc_metadata`` output so
            downstream components don't need filename matching.
        """
        docling_documents = []
        doc_metadata: list[dict[str, Any]] = []
        failed_files = []
        meta = meta or {}

        path_meta_lookup: dict[str, dict[str, Any]] = {}
        if path_metadata:
            for key, value in path_metadata.items():
                path_meta_lookup[key] = value
                path_meta_lookup[Path(key).name] = value

        with httpx.Client(timeout=self.timeout) as client:
            for path in paths:
                file_path = Path(path)

                if not file_path.exists():
                    logger.warning(f"File not found: {file_path}")
                    failed_files.append(
                        {"filename": str(path), "error": "File not found"}
                    )
                    continue

                file_meta = (
                    path_meta_lookup.get(str(path))
                    or path_meta_lookup.get(file_path.name)
                    or {}
                )
                display_name = file_meta.get("filename") or file_path.name

                try:
                    logger.info(f"Submitting file to docling-serve: {display_name}")

                    task_id = self._submit_file_async(client, file_path)
                    logger.info(f"{display_name}: Submitted, task_id={task_id}")

                    result = self._poll_for_result(client, task_id, display_name)

                    status = result.get("status", "unknown")
                    if status == "failure":
                        errors = result.get("errors", [])
                        logger.error(f"Conversion failed for {display_name}: {errors}")
                        failed_files.append(
                            {"filename": display_name, "error": str(errors)}
                        )
                        continue

                    docling_doc = self._extract_docling_document(result)

                    if not docling_doc:
                        logger.warning(
                            f"No DoclingDocument extracted from {display_name}"
                        )
                        failed_files.append(
                            {
                                "filename": display_name,
                                "error": "No document extracted from conversion result",
                            }
                        )
                        continue

                    # restore user-facing filename from metadata.
                    docling_doc.origin.filename = display_name

                    docling_documents.append(docling_doc)
                    doc_metadata.append(dict(file_meta))

                    logger.info(
                        f"Converted {display_name}: "
                        f"status={status}, time={result.get('processing_time', 0):.2f}s"
                    )

                except httpx.HTTPStatusError as e:
                    logger.error(f"HTTP error converting {display_name}: {e}")
                    failed_files.append(
                        {"filename": display_name, "error": f"HTTP error: {e}"}
                    )
                except TimeoutError as e:
                    logger.error(f"Timeout converting {display_name}: {e}")
                    failed_files.append(
                        {"filename": display_name, "error": f"Timeout: {e}"}
                    )
                except Exception as e:
                    logger.error(f"Error converting {display_name}: {e}")
                    failed_files.append({"filename": display_name, "error": str(e)})

        if failed_files:
            logger.warning(
                f"{len(failed_files)}/{len(paths)} file(s) failed conversion: {[f['filename'] for f in failed_files]}"
            )

        return {
            "docling_documents": docling_documents,
            "doc_metadata": doc_metadata,
            "failed_files": failed_files,
        }

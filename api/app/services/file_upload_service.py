import hashlib
import json
import logging
import mimetypes
import tempfile
import uuid
from typing import Any
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlmodel import Session

from app.core.storage import StorageManager, get_file_storage_path
from app.models.enums import FileStatus, SourceType
from app.models.schemas import FileUploadRequest, UploadedFileResponse
from app.models.tables import UploadedFile, User
from app.repositories.datasource import DataSourceRepository
from app.repositories.uploaded_file import UploadedFileRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FileUploadManager:
    """File uploads and processing with user-based paths."""

    def __init__(self) -> None:
        self.storage = StorageManager()
        self.supported_mime_types = {
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
            "text/plain",
            "text/markdown",
            "text/html",
            "text/csv",
            "application/x-latex",
            "text/x-tex",
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/bmp",
            "image/webp",
        }
        # accepted by extension because browsers don't register a mime for
        # them (H5P is just a zip, browsers send "" or "application/zip")
        self.supported_extensions = {
            ".h5p",
        }

    def calculate_file_hash(self, file_content: bytes) -> str:
        return hashlib.sha256(file_content).hexdigest()

    def generate_stored_filename(self, original_filename: str) -> str:
        unique_id = str(uuid.uuid4())[:12]
        clean_name = original_filename.replace(" ", "_")
        return f"{unique_id}_{clean_name}"

    def validate_file(self, upload_file: UploadFile) -> tuple[bool, str]:
        if not upload_file.filename:
            return False, "Filename is required"

        if upload_file.size and upload_file.size > 100 * 1024 * 1024:
            return False, "File size exceeds 100MB limit"

        ext = (
            "." + upload_file.filename.rsplit(".", 1)[-1].lower()
            if "." in upload_file.filename
            else ""
        )
        if ext in self.supported_extensions:
            return True, ""

        mime_type = (
            upload_file.content_type or mimetypes.guess_type(upload_file.filename)[0]
        )
        if mime_type not in self.supported_mime_types:
            return False, f"Unsupported file type: {mime_type}"

        return True, ""

    async def upload_file(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        upload_file: UploadFile,
        upload_request: FileUploadRequest,
    ) -> UploadedFileResponse:
        """Upload and process a file. Storage path is {user_email}/datasources/{datasource_id}/uploads/{filename}."""
        datasource_repo = DataSourceRepository(session)
        file_repo = UploadedFileRepository(session)

        datasource = datasource_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.source_type != SourceType.FILE:
            raise HTTPException(status_code=400, detail="Invalid file datasource")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to upload to this datasource",
            )

        is_valid, error_msg = self.validate_file(upload_file)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        file_content = await upload_file.read()
        file_size = len(file_content)
        file_hash = self.calculate_file_hash(file_content)

        if not upload_file.filename:
            raise HTTPException(status_code=400, detail="Missing upload filename")
        stored_filename = self.generate_stored_filename(upload_file.filename)
        mime_type = (
            upload_file.content_type
            or mimetypes.guess_type(upload_file.filename)[0]
            or "application/octet-stream"
        )

        storage_path = get_file_storage_path(
            user_email=user.email,
            datasource_id=str(datasource_id),
            stored_filename=stored_filename,
        )

        uploaded_file = None
        try:
            uploaded_file = file_repo.create(
                {
                    "datasource_id": datasource_id,
                    "original_filename": upload_file.filename,
                    "stored_filename": stored_filename,
                    "file_size": file_size,
                    "mime_type": mime_type,
                    "file_hash": file_hash,
                    "storage_path": storage_path,
                    "tags": json.dumps(upload_request.tags),
                    "status": FileStatus.UPLOADING,
                }
            )

            with tempfile.NamedTemporaryFile() as temp_file:
                temp_file.write(file_content)
                temp_file.flush()

                success = self.storage.upload_file(
                    local_path=temp_file.name,
                    storage_path=storage_path,
                    content_type=mime_type,
                )

                if not success:
                    raise Exception("Failed to upload file to storage")

            file_repo.update(uploaded_file, {"status": FileStatus.UPLOADED})

            logger.info(
                f"Successfully uploaded file: {upload_file.filename} to {storage_path}"
            )

            return self._convert_to_response(uploaded_file)

        except Exception as e:
            if uploaded_file:
                file_repo.update(
                    uploaded_file,
                    {"status": FileStatus.ERROR, "processing_error": str(e)},
                )
            logger.error(f"Error uploading file {upload_file.filename}: {e}")
            raise HTTPException(status_code=500, detail="File upload failed")

    def get_uploaded_files(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        skip: int = 0,
        limit: int = 100,
    ) -> list[UploadedFileResponse]:
        """Uploaded files for a datasource. Ownership-checked."""
        datasource_repo = DataSourceRepository(session)
        file_repo = UploadedFileRepository(session)

        datasource = datasource_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this datasource",
            )

        files = file_repo.get_by_datasource(datasource_id, skip=skip, limit=limit)
        return [self._convert_to_response(file) for file in files]

    def get_uploaded_file(
        self,
        session: Session,
        user: User,
        file_id: UUID,
    ) -> UploadedFileResponse:
        """One uploaded file. Ownership-checked."""
        file_repo = UploadedFileRepository(session)
        datasource_repo = DataSourceRepository(session)

        uploaded_file = file_repo.get(file_id)
        if not uploaded_file:
            raise HTTPException(status_code=404, detail="File not found")

        datasource = datasource_repo.get(uploaded_file.datasource_id)
        if not datasource or datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403, detail="You don't have permission to access this file"
            )

        return self._convert_to_response(uploaded_file)

    def delete_uploaded_file(
        self,
        session: Session,
        user: User,
        file_id: UUID,
    ) -> bool:
        """Delete an uploaded file. Ownership-checked."""
        file_repo = UploadedFileRepository(session)
        datasource_repo = DataSourceRepository(session)

        uploaded_file = file_repo.get(file_id)
        if not uploaded_file:
            raise HTTPException(status_code=404, detail="File not found")

        datasource = datasource_repo.get(uploaded_file.datasource_id)
        if not datasource or datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403, detail="You don't have permission to delete this file"
            )

        try:
            if uploaded_file.storage_path:
                self.storage.delete_file(uploaded_file.storage_path)
            else:
                # fallback when storage_path wasn't recorded
                storage_path = get_file_storage_path(
                    user_email=user.email,
                    datasource_id=str(uploaded_file.datasource_id),
                    stored_filename=uploaded_file.stored_filename,
                )
                self.storage.delete_file(storage_path)

            file_repo.delete(file_id)

            logger.info(f"Deleted file: {uploaded_file.original_filename}")
            return True

        except Exception as e:
            logger.error(f"Error deleting file {file_id}: {e}")
            raise HTTPException(status_code=500, detail="File deletion failed")

    def get_file_selections(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
    ) -> dict[str, Any]:
        """File selections for KB integration."""
        file_repo = UploadedFileRepository(session)
        datasource_repo = DataSourceRepository(session)

        datasource = datasource_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this datasource",
            )

        files = file_repo.get_uploaded_and_processed(datasource_id)

        file_list = []
        total_size = 0

        for file in files:
            file_info = {
                "id": str(file.id),
                "filename": file.original_filename,
                "size": file.file_size,
                "mime_type": file.mime_type,
                "upload_date": file.upload_date.isoformat(),
                "tags": json.loads(file.tags) if file.tags else [],
                "selection_key": f"file:{file.id}",
                "storage_path": file.storage_path,
                "status": file.status,
            }

            file_list.append(file_info)
            total_size += file.file_size

        return {
            "datasource_id": str(datasource_id),
            "total_files": len(file_list),
            "total_size": total_size,
            "files": file_list,
            "selection_format": "file:file_id for individual files",
        }

    def search_files(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        filename_pattern: str | None = None,
        tags: list[str] | None = None,
        mime_types: list[str] | None = None,
        status: FileStatus | None = None,
    ) -> list[UploadedFileResponse]:
        """Search uploaded files with filters. Ownership-checked."""
        datasource_repo = DataSourceRepository(session)
        file_repo = UploadedFileRepository(session)

        datasource = datasource_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this datasource",
            )

        files = file_repo.search(
            datasource_id,
            filename_pattern=filename_pattern,
            tags=tags,
            mime_types=mime_types,
            status=status,
        )
        return [self._convert_to_response(file) for file in files]

    async def upload_text(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        title: str,
        content: str,
    ) -> UploadedFileResponse:
        """Persist a free-text entry as a text/plain file.

        Reuses the same storage and DB shape as a normal upload so the
        indexing pipeline picks it up without special-casing.
        """
        datasource_repo = DataSourceRepository(session)
        file_repo = UploadedFileRepository(session)

        datasource = datasource_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")
        if datasource.source_type != SourceType.FILE:
            raise HTTPException(status_code=400, detail="Invalid file datasource")
        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to upload to this datasource",
            )

        clean_title = (title or "").strip() or "Untitled"
        if not content or not content.strip():
            raise HTTPException(status_code=400, detail="Text content cannot be empty")

        # force .txt extension so downstream converters (and the browser
        # when re-downloading for edit) treat it as plain text even when
        # the user's title had no extension
        base_name = (
            clean_title
            if clean_title.lower().endswith(".txt")
            else f"{clean_title}.txt"
        )

        file_bytes = content.encode("utf-8")
        file_size = len(file_bytes)
        if file_size > 100 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Text exceeds 100MB limit")

        file_hash = self.calculate_file_hash(file_bytes)
        stored_filename = self.generate_stored_filename(base_name)
        mime_type = "text/plain"
        storage_path = get_file_storage_path(
            user_email=user.email,
            datasource_id=str(datasource_id),
            stored_filename=stored_filename,
        )

        uploaded_file = None
        try:
            uploaded_file = file_repo.create(
                {
                    "datasource_id": datasource_id,
                    "original_filename": base_name,
                    "stored_filename": stored_filename,
                    "file_size": file_size,
                    "mime_type": mime_type,
                    "file_hash": file_hash,
                    "storage_path": storage_path,
                    "tags": json.dumps(["free_text"]),
                    "is_free_text": True,
                    "status": FileStatus.UPLOADING,
                }
            )

            with tempfile.NamedTemporaryFile() as temp_file:
                temp_file.write(file_bytes)
                temp_file.flush()
                success = self.storage.upload_file(
                    local_path=temp_file.name,
                    storage_path=storage_path,
                    content_type=mime_type,
                )
                if not success:
                    raise Exception("Failed to upload text to storage")

            file_repo.update(uploaded_file, {"status": FileStatus.UPLOADED})
            logger.info(f"Successfully uploaded free-text entry: {base_name}")
            return self._convert_to_response(uploaded_file)

        except Exception as e:
            if uploaded_file:
                file_repo.update(
                    uploaded_file,
                    {"status": FileStatus.ERROR, "processing_error": str(e)},
                )
            logger.error(f"Error uploading free-text entry: {e}")
            raise HTTPException(status_code=500, detail="Text upload failed")

    def _convert_to_response(self, uploaded_file: UploadedFile) -> UploadedFileResponse:
        return UploadedFileResponse(
            id=uploaded_file.id,
            original_filename=uploaded_file.original_filename,
            file_size=uploaded_file.file_size,
            mime_type=uploaded_file.mime_type,
            tags=json.loads(uploaded_file.tags) if uploaded_file.tags else [],
            status=uploaded_file.status,
            upload_date=uploaded_file.upload_date,
            processed_date=uploaded_file.processed_date,
            extracted_text_length=uploaded_file.extracted_text_length,
            processing_error=uploaded_file.processing_error,
            selection_key=f"file:{uploaded_file.id}",
            storage_path=uploaded_file.storage_path or "",
            is_free_text=getattr(uploaded_file, "is_free_text", False),
        )


file_upload_manager = FileUploadManager()

"""File upload and management operations."""

import logging
from typing import Any
from uuid import UUID

from fastapi import UploadFile
from sqlmodel import Session, select

from app.models.schemas import FileUploadRequest, UploadedFileResponse
from app.models.tables import (
    DataSource,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
    User,
)
from app.services.file_upload_service import FileUploadManager
from app.services.selection_service import SelectionService

logger = logging.getLogger(__name__)


class FileService:
    """Handles file upload and management for chatbots."""

    def __init__(self, upload_manager: FileUploadManager | None = None) -> None:
        from app.services.file_upload_service import file_upload_manager

        self.upload_manager = upload_manager or file_upload_manager

    async def upload_files(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        files: list[UploadFile],
        tags: list[str] | None = None,
    ) -> list[UploadedFileResponse]:
        """Upload multiple files to a datasource. Returns the successful uploads."""
        uploaded_files = []
        tags = tags or ["chatbot_files"]

        for file in files:
            try:
                upload_request = FileUploadRequest(tags=tags, overwrite=False)
                uploaded_file = await self.upload_manager.upload_file(
                    session=session,
                    user=user,
                    datasource_id=datasource_id,
                    upload_file=file,
                    upload_request=upload_request,
                )
                uploaded_files.append(uploaded_file)
                logger.info(f"Uploaded file: {file.filename} (ID: {uploaded_file.id})")
            except Exception as e:
                logger.error(f"Failed to upload file {file.filename}: {str(e)}")

        return uploaded_files

    async def upload_text_entry(
        self,
        session: Session,
        user: User,
        datasource_id: UUID,
        title: str,
        content: str,
    ) -> UploadedFileResponse:
        """Persist a free-text entry as an uploaded file."""
        return await self.upload_manager.upload_text(
            session=session,
            user=user,
            datasource_id=datasource_id,
            title=title,
            content=content,
        )

    def delete_files_from_selections(
        self,
        session: Session,
        kb_links: list[KnowledgeBaseDatasourceLink],
        file_ids: list[str],
    ) -> list[str]:
        """Remove files from KB selections and reap what they reference.

        Deselecting a file must also delete its ``UploadedFile`` row and S3
        object, otherwise the row lingers forever as an unreferenced orphan
        (the ``db.unselected_uploaded_files`` leak). When a link's last file
        is removed, the now-orphan FILE datasource is dropped too — unless
        another link still references it.

        DB deletes are committed in a single transaction; S3 deletes run
        best-effort *after* the commit so a storage error can never resurrect
        the rows we just removed.
        """
        storage = self.upload_manager.storage
        deleted_file_ids: list[str] = []
        s3_paths_to_delete: list[str] = []
        emptied_datasource_ids: set[UUID] = set()

        for file_id in file_ids:
            file_selection_key = f"file:{file_id}"

            for link in kb_links:
                selections = SelectionService.parse_selections(link.selection)

                if file_selection_key in selections:
                    selections.remove(file_selection_key)
                    link.selection = SelectionService.serialize_selections(selections)
                    deleted_file_ids.append(file_id)

                    logger.info(
                        f"Removed file {file_id} from datasource {link.datasource_id}"
                    )

                    uploaded = session.get(UploadedFile, UUID(file_id))
                    if uploaded is not None:
                        if uploaded.storage_path:
                            s3_paths_to_delete.append(uploaded.storage_path)
                        session.delete(uploaded)

                    if not selections:
                        emptied_datasource_ids.add(link.datasource_id)
                        session.delete(link)
                        logger.info(
                            f"Removed empty datasource link for datasource {link.datasource_id}"
                        )

                    break

        # A link going empty leaves its FILE datasource orphaned (no link).
        # Drop it and any residual files, but only if nothing else links it.
        for ds_id in emptied_datasource_ids:
            still_linked = session.exec(
                select(KnowledgeBaseDatasourceLink).where(
                    KnowledgeBaseDatasourceLink.datasource_id == ds_id
                )
            ).first()
            if still_linked is not None:
                continue

            residual_files = session.exec(
                select(UploadedFile).where(UploadedFile.datasource_id == ds_id)
            ).all()
            for residual in residual_files:
                if residual.storage_path:
                    s3_paths_to_delete.append(residual.storage_path)
                session.delete(residual)

            # flush so the FK children are gone before the parent delete
            session.flush()

            datasource = session.get(DataSource, ds_id)
            if datasource is not None:
                session.delete(datasource)
                logger.info(f"Removed orphan FILE datasource {ds_id}")

        session.commit()

        for path in s3_paths_to_delete:
            try:
                storage.delete_file(path)
            except Exception as e:
                logger.error(f"Failed to delete S3 object {path}: {e}")

        return deleted_file_ids

    def add_files_to_selection(
        self,
        session: Session,
        link: KnowledgeBaseDatasourceLink,
        uploaded_files: list[UploadedFile],
    ) -> None:
        """Append uploaded files to a KB datasource link's selection."""
        existing_selections = SelectionService.parse_selections(link.selection)
        new_selections = [f"file:{str(uf.id)}" for uf in uploaded_files]
        all_selections = existing_selections + new_selections

        link.selection = SelectionService.serialize_selections(all_selections)
        session.commit()

        logger.info(f"Added {len(new_selections)} files to knowledge base selection")

    def get_file_datasource_link(
        self,
        session: Session,
        kb_links: list[KnowledgeBaseDatasourceLink],
    ) -> tuple[UUID | None, KnowledgeBaseDatasourceLink | None]:
        """Find the FILE datasource link. Returns (None, None) if missing."""
        from app.models.enums import SourceType

        for link in kb_links:
            datasource = session.get(DataSource, link.datasource_id)
            if datasource and datasource.source_type == SourceType.FILE:
                return datasource.id, link

        return None, None

    def build_file_response(self, uploaded_file: UploadedFile) -> dict[str, Any]:
        return {
            "id": str(uploaded_file.id),
            "filename": uploaded_file.original_filename,
            "size": uploaded_file.file_size,
            "mime_type": uploaded_file.mime_type,
            "upload_date": uploaded_file.upload_date.isoformat(),
            "status": uploaded_file.status.value
            if hasattr(uploaded_file.status, "value")
            else str(uploaded_file.status),
        }

    def build_files_response(
        self, uploaded_files: list[UploadedFile]
    ) -> list[dict[str, Any]]:
        return [self.build_file_response(f) for f in uploaded_files]

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.core.storage import StorageManager
from app.models.enums import KnowledgeBaseStatus, SourceType
from app.models.schemas import KnowledgeBaseResponse
from app.models.tables import (
    Chatbot,
    DataSource,
    KnowledgeBaseDatasourceLink,
    UploadedFile,
    User,
)
from app.repositories.knowledge_base import KnowledgeBaseRepository
from app.services.index_manifest import (
    desired_manifest,
    wire_config_for_manifest,
    wire_embedding_config,
)
from app.services.rag_service import delete_knowledge_by_local_id

logger = logging.getLogger(__name__)


class KnowledgebaseService:
    """Knowledge base lifecycle, sync preparation, and sync-result handlers."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.kb_repo = KnowledgeBaseRepository(session)

    def create_knowledgebase(
        self, name: str, description: str, user: User
    ) -> KnowledgeBaseResponse:
        return self.kb_repo.create_knowledge_base(
            name=name,
            description=description,
            user_id=user.id,
        )

    def delete_knowledgebase_with_validation(
        self, kb_id: str, user: User
    ) -> dict[str, Any]:
        """Delete a KB plus its vector index, linked datasources, and S3 files."""
        try:
            kb_uuid = UUID(kb_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid knowledge base ID format"
            )

        knowledge_base = self.kb_repo.get(kb_uuid)
        if not knowledge_base:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if knowledge_base.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to delete this knowledge base",
            )

        linked_chatbots = self.session.exec(
            select(Chatbot).where(Chatbot.knowledge_base_id == kb_uuid)
        ).all()

        if linked_chatbots:
            chatbot_names = [chatbot.name for chatbot in linked_chatbots]
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Cannot delete knowledge base. It is being used by chatbots.",
                    "linked_chatbots": chatbot_names,
                    "chatbot_count": len(linked_chatbots),
                    "suggestion": "Please delete or reassign the linked chatbots first.",
                },
            )

        storage_manager = StorageManager()

        kb_links = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == kb_uuid
            )
        ).all()

        total_files_deleted = 0
        all_s3_errors = []
        datasources_deleted = []

        for link in kb_links:
            datasource = self.session.get(DataSource, link.datasource_id)
            if not datasource:
                continue

            datasource_id = str(datasource.id)

            owner_email = datasource.owner.email if datasource.owner else user.email

            files_deleted, s3_errors = storage_manager.delete_datasource_files(
                user_email=owner_email, datasource_id=datasource_id
            )

            total_files_deleted += files_deleted
            if s3_errors:
                all_s3_errors.extend(s3_errors)

            logger.info(
                f"Deleted {files_deleted} S3 files for datasource {datasource_id}"
            )

            uploaded_files = self.session.exec(
                select(UploadedFile).where(UploadedFile.datasource_id == datasource.id)
            ).all()
            for uploaded_file in uploaded_files:
                self.session.delete(uploaded_file)

            self.session.delete(link)

            if datasource.moodle_config:
                for course in datasource.moodle_config.moodle_courses:
                    self.session.delete(course)
                self.session.delete(datasource.moodle_config)

            if datasource.nextcloud_config:
                self.session.delete(datasource.nextcloud_config)

            self.session.delete(datasource)
            datasources_deleted.append(datasource_id)

            logger.info(
                f"Deleted datasource {datasource_id} ({datasource.source_type})"
            )

        if all_s3_errors:
            logger.warning(
                f"Some S3 files could not be deleted for knowledge base {kb_id}: {all_s3_errors}"
            )

        deleted_index = False
        vector_index_error: str | None = None
        try:
            deleted_index = delete_knowledge_by_local_id(str(kb_uuid))
            if deleted_index:
                logger.info(f"Successfully deleted the vector index {kb_id}")
            else:
                vector_index_error = (
                    f"Vector index {kb_id} delete returned no confirmation "
                    "(may already be absent or Hayhooks unreachable)"
                )
                logger.warning(vector_index_error)
        except Exception as e:
            vector_index_error = f"Failed to delete vector index {kb_id}: {e}"
            logger.error(vector_index_error)

        deleted_kb = self.kb_repo.delete(kb_uuid)
        if not deleted_kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        self.session.commit()

        return {
            "message": "Knowledge base deleted successfully",
            "knowledge_base_id": kb_id,
            "deleted_index": deleted_index,
            "vector_index_error": vector_index_error,
            "datasources_deleted": datasources_deleted,
            "datasources_count": len(datasources_deleted),
            "s3_files_deleted": total_files_deleted,
            "s3_errors": all_s3_errors if all_s3_errors else None,
        }

    def get_knowledgebase_linked_chatbots(
        self, kb_id: str, user: User
    ) -> dict[str, Any]:
        """All chatbots linked to a specific KB."""
        try:
            kb_uuid = UUID(kb_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid knowledge base ID format"
            )

        knowledge_base = self.kb_repo.get(kb_uuid)
        if not knowledge_base:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if knowledge_base.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this knowledge base",
            )

        linked_chatbots = self.session.exec(
            select(Chatbot).where(Chatbot.knowledge_base_id == kb_uuid)
        ).all()

        chatbot_info = []
        for chatbot in linked_chatbots:
            chatbot_info.append(
                {
                    "id": str(chatbot.id),
                    "name": chatbot.name,
                    "description": chatbot.description,
                    "persona": chatbot.persona,
                }
            )

        return {
            "knowledge_base_id": kb_id,
            "knowledge_base_name": knowledge_base.name,
            "linked_chatbots": chatbot_info,
            "chatbot_count": len(chatbot_info),
            "can_delete": len(chatbot_info) == 0,
        }

    def update_knowledgebase_sources(
        self, kb_id: str, sources: dict[str, list[str]], user: User
    ) -> dict[str, Any]:
        """Update datasources and their selections for a KB."""
        try:
            kb_uuid = UUID(kb_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid knowledge base ID format"
            )

        kb = self.kb_repo.get(kb_uuid)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if kb.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to modify this knowledge base",
            )

        datasources = self.kb_repo.get_datasources(kb_uuid)
        datasource_map = {str(ds.id): ds for ds in datasources}

        def validate_selection(selection: str) -> bool:
            if selection.startswith("course:"):
                parts = selection.split(":")
                return len(parts) == 2 and bool(parts[1].strip())
            elif selection.startswith("file:"):
                parts = selection.split(":")
                return len(parts) == 2 and bool(parts[1].strip())
            elif ":" in selection:
                parts = selection.split(":")
                return len(parts) == 2 and all(p.strip() for p in parts)
            return False

        existing_links = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == kb_uuid
            )
        ).all()

        for link in existing_links:
            if str(link.datasource_id) not in sources:
                self.session.delete(link)

        for source_id, selections in sources.items():
            if source_id not in datasource_map:
                logger.warning(f"Datasource {source_id} not found, skipping")
                continue

            invalid_selections = [s for s in selections if not validate_selection(s)]
            if invalid_selections:
                logger.warning(f"Invalid selections found: {invalid_selections}")
                selections = [s for s in selections if validate_selection(s)]

            self.kb_repo.add_datasource(
                knowledge_base_id=kb_uuid,
                datasource_id=datasource_map[source_id].id,
                selection=selections,
            )

        self.session.commit()

        return {
            "message": "Knowledge base sources updated successfully",
            "knowledge_base_id": kb_id,
            "updated_sources": sources,
        }

    def get_knowledgebase_sources(self, kb_id: str, user: User) -> dict[str, Any]:
        """Current datasources and selections for a KB."""
        try:
            kb_uuid = UUID(kb_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid knowledge base ID format"
            )

        kb = self.kb_repo.get(kb_uuid)
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if kb.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this knowledge base",
            )

        links = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == kb_uuid
            )
        ).all()

        sources = {}
        for link in links:
            try:
                files = json.loads(link.selection) if link.selection else []
                sources[str(link.datasource_id)] = files
            except json.JSONDecodeError:
                sources[str(link.datasource_id)] = []

        return {
            "knowledge_base_id": kb_id,
            "sources": sources,
        }

    def prepare_haystack_sync(
        self,
        kb_id: str,
        user: User,
        force: bool = False,
        force_ocr: bool = False,
    ) -> dict[str, Any]:
        """Build the Haystack sync payload for a KB. User email is included for storage path resolution."""
        try:
            kb_uuid = UUID(kb_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid knowledge base ID format"
            )

        knowledge_base = self.kb_repo.get(kb_uuid)
        if not knowledge_base:
            raise HTTPException(status_code=404, detail="Knowledge base not found")

        if knowledge_base.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to sync this knowledge base",
            )

        if knowledge_base.status == KnowledgeBaseStatus.PROCESSING:
            raise HTTPException(
                status_code=409,
                detail="Knowledge base is already being synchronized",
            )

        datasources_data: list[dict[str, Any]] = []
        datasources_links = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == kb_uuid
            )
        ).all()

        if not datasources_links:
            raise HTTPException(
                status_code=400,
                detail="No data sources configured for this knowledge base",
            )

        for datasource_link in datasources_links:
            datasource = self.session.get(DataSource, datasource_link.datasource_id)
            if not datasource:
                logger.error(f"Datasource {datasource_link.datasource_id} not found")
                continue

            try:
                selected_files = (
                    json.loads(datasource_link.selection)
                    if datasource_link.selection
                    else []
                )
            except json.JSONDecodeError:
                logger.warning(f"Invalid selection data for datasource {datasource.id}")
                selected_files = []

            if not selected_files:
                logger.info(
                    f"No files selected for datasource {datasource.id}, skipping"
                )
                continue

            datasource_owner_email = (
                datasource.owner.email if datasource.owner else user.email
            )
            datasource_owner_role = (
                datasource.owner.role if datasource.owner else user.role
            )

            datasource_info = {
                "datasource_id": str(datasource.id),
                "source_type": datasource.source_type,
                "owner_email": datasource_owner_email,
                "owner_role": datasource_owner_role,
                "selected_files": selected_files,
            }

            if datasource.source_type == SourceType.FILE:
                resolved_files = []
                for selection in selected_files:
                    if selection.startswith("file:"):
                        file_id = selection.split(":", 1)[1]
                        try:
                            uploaded_file = self.session.get(
                                UploadedFile, UUID(file_id)
                            )
                            if (
                                uploaded_file
                                and uploaded_file.datasource_id == datasource.id
                            ):
                                if uploaded_file.storage_path:
                                    storage_path = uploaded_file.storage_path
                                else:
                                    from app.core.storage import get_file_storage_path

                                    storage_path = get_file_storage_path(
                                        user_email=datasource_owner_email,
                                        datasource_id=str(datasource.id),
                                        stored_filename=uploaded_file.stored_filename,
                                    )
                                resolved_files.append(
                                    {
                                        "path": storage_path,
                                        "file_id": file_id,
                                        "filename": uploaded_file.original_filename,
                                        "mime_type": uploaded_file.mime_type,
                                    }
                                )
                                logger.info(f"Resolved {selection} to {storage_path}")
                            else:
                                logger.warning(
                                    f"File not found for selection: {selection}"
                                )
                        except Exception as e:
                            logger.error(f"Error resolving file {selection}: {e}")

                datasource_info["selected_files"] = resolved_files
                logger.info(
                    f"Resolved {len(resolved_files)} files for FILE datasource {datasource.id}"
                )

            elif (
                datasource.source_type == SourceType.MOODLE and datasource.moodle_config
            ):
                datasource_info.update(
                    {
                        "moodle_domain": datasource.moodle_config.domain,
                        "moodle_token": datasource.moodle_config.token,
                    }
                )
            elif (
                datasource.source_type == SourceType.NEXTCLOUD
                and datasource.nextcloud_config
            ):
                datasource_info.update(
                    {
                        "nextcloud_url": datasource.nextcloud_config.url,
                        "nextcloud_username": datasource.nextcloud_config.username,
                        "nextcloud_password": datasource.nextcloud_config.password,
                    }
                )

            datasources_data.append(datasource_info)

        if not datasources_data:
            raise HTTPException(
                status_code=400,
                detail="No valid data sources with selected files found",
            )

        self.kb_repo.update_knowledge_base(
            knowledge_base_id=kb_uuid,
            status="processing",
            last_sync_error=None,
        )

        sync_job = {
            "knowledge_base_id": str(knowledge_base.id),
            "knowledge_base_name": knowledge_base.name,
            "knowledge_base_description": knowledge_base.description or "",
            "owner_email": user.email,
            "haystack_url": settings.HAYSTACK_INGESTION_URL,
            "datasources": datasources_data,
            "force": force,
            "force_ocr": force_ocr,
            # A forced sync recreates the collection, so build it with the
            # desired config (the manifest is restamped to match on completion).
            # An incremental add must reuse the model the collection was built
            # with (its stored manifest) so new chunks match the existing
            # vectors; otherwise a pending model swap corrupts the collection.
            "embedding_config": (
                wire_embedding_config()
                if force
                else wire_config_for_manifest(knowledge_base.index_manifest)
            ),
        }

        logger.info(f"Started knowledge base sync for {kb_id}")

        total_selections = sum(len(ds["selected_files"]) for ds in datasources_data)

        return {
            "message": "Knowledge base synchronization started",
            "knowledge_base_id": kb_id,
            "datasources_count": len(datasources_data),
            "total_selections": total_selections,
            "auto_download": True,
            "force": force,
            "sync_job": sync_job,
        }

    def handle_knowledgebase_sync_completion(self, message: dict[str, Any]) -> None:
        """Handle completed KB sync jobs.

        "Completed" covers full and partial success (at least one file
        indexed). If every file failed, the worker raises upstream and
        handle_knowledgebase_sync_failure runs instead.
        """
        kb_id = message.get("knowledge_base_id")
        files_processed = message.get("files_processed", 0)
        files_succeeded = message.get("files_succeeded", files_processed)
        files_failed = message.get("files_failed", 0)
        files_downloaded = message.get("files_downloaded", 0)
        force = bool(message.get("force", False))

        if not kb_id:
            logger.error("Missing knowledge_base_id in KB sync completion message")
            return

        knowledge_base = self.kb_repo.get(UUID(kb_id))
        if knowledge_base is None:
            logger.warning(f"Knowledge base {kb_id} not found")
            return

        # surface partial failures on the KB so the user notices without
        # drilling into job detail. empty on full success, warning text
        # on partial
        last_sync_error = (
            f"Sync completed with {files_failed} file failure(s); "
            f"see job detail for per-file errors"
            if files_failed
            else None
        )

        # Stamp the index manifest only when the collection was (re)built under
        # the current config: a forced sync recreates it, and a brand-new KB
        # (no manifest yet) builds it fresh. An incremental add to an
        # already-stamped collection leaves the manifest untouched, so a drifted
        # collection is never silently marked as fresh. See index_manifest.
        new_manifest = None
        if force or knowledge_base.index_manifest is None:
            new_manifest = desired_manifest().to_json()

        self.kb_repo.update_knowledge_base(
            knowledge_base_id=UUID(kb_id),
            status="ready",
            last_sync=datetime.now(),
            last_sync_error=last_sync_error,
            index_manifest=new_manifest,
        )

        logger.info(
            f"Updated knowledge base {kb_id} status: ready. "
            f"Downloaded {files_downloaded} files, "
            f"{files_succeeded} succeeded, {files_failed} failed."
        )

    def handle_knowledgebase_sync_failure(self, message: dict[str, Any]) -> None:
        kb_id = message.get("knowledge_base_id")
        error_message = message.get("error", "Unknown error")
        files_downloaded = message.get("files_downloaded", 0)

        if not kb_id:
            logger.error("Missing knowledge_base_id in KB sync failure message")
            return

        knowledge_base = self.kb_repo.get(UUID(kb_id))
        if knowledge_base is None:
            logger.warning(f"Knowledge base {kb_id} not found")
            return

        self.kb_repo.update_knowledge_base(
            knowledge_base_id=UUID(kb_id),
            status="error",
            last_sync_error=error_message,
        )

        logger.warning(
            f"Updated knowledge base {kb_id} status: error - {error_message}. "
            f"Downloaded {files_downloaded} files before failure."
        )

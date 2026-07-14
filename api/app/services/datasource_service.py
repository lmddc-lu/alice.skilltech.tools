import json
import logging
import os
import shutil
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, col, select

from app.core.storage import StorageManager
from app.models.enums import (
    DataSourceSyncStatus,
    SourceType,
    SyncErrorCode,
    UserRole,
)
from app.models.schemas import (
    DataSourceBaseModel,
    DataSourceCreate,
    DataSourceResp,
    MoodleConfig,
)
from app.models.tables import (
    DataSource,
    MoodleCourse,
    NextCloudDataSourceConfig,
    User,
)
from app.repositories.datasource import (
    DataSourceRepository,
    MoodleConfigRepository,
    NextCloudConfigRepository,
)
from app.services.url_validation import (
    UrlValidationError,
    validate_moodle_url,
)

logger = logging.getLogger(__name__)


class DatasourceService:
    """Datasource CRUD, sync job preparation, and metadata/content sync handlers."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.ds_repo = DataSourceRepository(session)
        self.moodle_repo = MoodleConfigRepository(session)
        self.nextcloud_repo = NextCloudConfigRepository(session)

    async def create_datasource(
        self,
        datasource: DataSourceCreate,
        user: User,
    ) -> DataSourceResp:
        base_datasource = DataSourceBaseModel(
            name=datasource.name,
            source_type=datasource.source_type,
            owner_id=user.id,
        )
        db_datasource = self.ds_repo.create(base_datasource.model_dump())

        if not db_datasource:
            raise HTTPException(status_code=500, detail="Failed to create datasource")

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            domain = datasource.moodle_config.domain
            token = datasource.moodle_config.token
            if not domain or not token:
                raise HTTPException(
                    status_code=400,
                    detail="Moodle configuration requires domain and token",
                )
            try:
                validate_moodle_url(
                    domain.rstrip("/"),
                    allow_private_networks=user.role == UserRole.ADMIN,
                )
            except UrlValidationError as e:
                # reject at creation time so the error surfaces near the user
                # instead of failing silently on the next sync
                raise HTTPException(status_code=400, detail=str(e))
            moodle_config = MoodleConfig(
                datasource_id=db_datasource.id,
                domain=domain,
                token=token,
            )
            self.moodle_repo.create_config(moodle_config)

        elif (
            datasource.source_type == SourceType.NEXTCLOUD
            and datasource.nextcloud_config
        ):
            if not all(
                [
                    datasource.nextcloud_config.url,
                    datasource.nextcloud_config.username,
                    datasource.nextcloud_config.password,
                ]
            ):
                raise HTTPException(
                    status_code=400,
                    detail="NextCloud configuration requires url, username, and password",
                )
            self.nextcloud_repo.create_config(
                db_datasource.id, datasource.nextcloud_config
            )

        elif datasource.source_type == SourceType.FILE:
            db_datasource.sync_status = DataSourceSyncStatus.READY
            self.session.commit()
            logger.info(f"Created FILE datasource: {datasource.name}")

        return await self.get_datasource(db_datasource.id)

    async def get_datasource(self, datasource_id: UUID) -> DataSourceResp:
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")
        return DataSourceResp.model_validate(datasource)

    async def get_datasources(
        self,
        user: User,
        skip: int = 0,
        limit: int = 100,
        source_type: SourceType | None = None,
    ) -> list[DataSourceResp]:
        return [
            DataSourceResp.model_validate(ds)
            for ds in self.ds_repo.get_by_owner(
                user.id, source_type=source_type, skip=skip, limit=limit
            )
        ]

    async def update_datasource(
        self,
        datasource_id: UUID,
        datasource: DataSourceCreate,
        user: User,
    ) -> DataSourceResp:
        existing_datasource = self.ds_repo.get(datasource_id)
        if not existing_datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if existing_datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to update this datasource",
            )

        if existing_datasource.source_type == SourceType.MOODLE:
            moodle_config = self.moodle_repo.get_by_datasource(datasource_id)
            if moodle_config:
                self.moodle_repo.delete_courses(moodle_config.id)

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            new_domain = datasource.moodle_config.domain
            if new_domain:
                try:
                    validate_moodle_url(
                        new_domain.rstrip("/"),
                        allow_private_networks=user.role == UserRole.ADMIN,
                    )
                except UrlValidationError as e:
                    raise HTTPException(status_code=400, detail=str(e))

        self.ds_repo.update(
            existing_datasource, datasource.model_dump(exclude_unset=True)
        )

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            self.moodle_repo.update_config(datasource_id, datasource.moodle_config)
        elif (
            datasource.source_type == SourceType.NEXTCLOUD
            and datasource.nextcloud_config
        ):
            self.nextcloud_repo.update_config(
                datasource_id, datasource.nextcloud_config
            )

        return await self.get_datasource(datasource_id)

    async def delete_datasource(self, datasource_id: UUID, user: User) -> bool:
        """Delete a datasource, its config, and all uploaded files."""
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to delete this datasource",
            )

        storage_manager = StorageManager()

        files_deleted, s3_errors = storage_manager.delete_datasource_files(
            user_email=user.email, datasource_id=str(datasource_id)
        )

        if s3_errors:
            logger.warning(
                f"Some S3 files could not be deleted for datasource {datasource_id}: {s3_errors}"
            )
        else:
            logger.info(
                f"Successfully deleted {files_deleted} files from S3 for datasource {datasource_id}"
            )

        datasource_path = f"/app/data/{datasource_id}"
        if os.path.exists(datasource_path):
            shutil.rmtree(datasource_path)

        result = self.ds_repo.delete_with_files(datasource_id)

        if not result:
            raise HTTPException(status_code=404, detail="Datasource not found")

        logger.info(
            f"Successfully deleted datasource {datasource_id} (type: {datasource.source_type})"
        )

        return True

    async def get_sync_status(self, datasource_id: UUID) -> dict[str, Any]:
        datasource = await self.get_datasource(datasource_id)
        return {
            "status": datasource.sync_status,
            "last_sync": datasource.last_sync,
            "last_sync_error": datasource.last_sync_error,
        }

    def get_nextcloud_config(
        self, datasource_id: UUID
    ) -> NextCloudDataSourceConfig | None:
        return self.nextcloud_repo.get_by_datasource(datasource_id)

    def prepare_metadata_sync_job(
        self, datasource_id: UUID, user: User, force: bool = False
    ) -> dict[str, Any]:
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to sync this datasource",
            )

        datasource.sync_status = DataSourceSyncStatus.PROCESSING
        self.session.commit()

        sync_job = {
            "operation": "sync_metadata",
            "datasource_id": str(datasource_id),
            "source_type": datasource.source_type,
            "owner_email": user.email,
            "owner_role": user.role,
            "force": force,
        }

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            sync_job.update(
                {
                    "moodle_domain": datasource.moodle_config.domain,
                    "moodle_token": datasource.moodle_config.token,
                }
            )
        elif (
            datasource.source_type == SourceType.NEXTCLOUD
            and datasource.nextcloud_config
        ):
            sync_job.update(
                {
                    "nextcloud_url": datasource.nextcloud_config.url,
                    "nextcloud_username": datasource.nextcloud_config.username,
                    "nextcloud_password": datasource.nextcloud_config.password,
                }
            )

        logger.info(f"Prepared metadata sync job for datasource {datasource_id}")
        return sync_job

    def handle_metadata_sync_completion(self, message: dict[str, Any]) -> None:
        datasource_id = message.get("datasource_id")
        courses_metadata = message.get("courses", [])

        if not datasource_id:
            logger.error("Missing datasource_id in metadata sync completion message")
            return

        current_ds = self.ds_repo.get(UUID(datasource_id))
        if not current_ds:
            logger.warning(f"Datasource {datasource_id} not found")
            return

        current_ds.sync_status = DataSourceSyncStatus.READY
        current_ds.last_sync = datetime.now()
        current_ds.last_sync_error = None

        if (
            current_ds.source_type == SourceType.MOODLE
            and current_ds.moodle_config
            and courses_metadata
        ):
            self.update_moodle_courses_metadata(current_ds, courses_metadata)

        self.session.commit()
        logger.info(f"Updated datasource {datasource_id} status: ready")

    def handle_metadata_sync_failure(self, message: dict[str, Any]) -> None:
        datasource_id = message.get("datasource_id")
        error_message = message.get("error", "Unknown error")

        if not datasource_id:
            logger.error("Missing datasource_id in metadata sync failure message")
            return

        current_ds = self.ds_repo.get(UUID(datasource_id))
        if not current_ds:
            logger.warning(f"Datasource {datasource_id} not found")
            return

        current_ds.sync_status = DataSourceSyncStatus.ERROR
        current_ds.last_sync_error = SyncErrorCode.FAILED
        self.session.commit()
        logger.info(
            f"Updated datasource {datasource_id} status: error - {error_message}"
        )

    def update_moodle_courses_metadata(
        self, datasource: DataSource, courses_metadata: list[dict[str, Any]]
    ) -> None:
        moodle_config = datasource.moodle_config
        existing_courses = {
            course.moodle_course_id: course for course in moodle_config.moodle_courses
        }

        updated_course_ids = set()

        for course_metadata in courses_metadata:
            course_id = str(course_metadata["id"])
            updated_course_ids.add(course_id)

            if course_id in existing_courses:
                course = existing_courses[course_id]
                course.moodle_course_name = course_metadata["fullname"]
                course.metadata_last_sync = datetime.now()
                course.metadata_version = course_metadata.get("version_hash", "")

                course_structure = {
                    "structure": course_metadata.get("structure", {}),
                    "metadata": {
                        "category": course_metadata.get("category", ""),
                        "description": course_metadata.get("description", ""),
                        "format": course_metadata.get("format", ""),
                        "last_metadata_sync": datetime.now().isoformat(),
                        "selection_key": course_metadata.get(
                            "selection_key", f"course:{course_id}"
                        ),
                        "total_files": course_metadata.get("total_files", 0),
                        "total_activities": course_metadata.get("total_activities", 0),
                    },
                }
                course.moodle_course_files = json.dumps(course_structure)
                course.total_sections = course_metadata.get("total_sections", 0)
                course.total_activities = course_metadata.get("total_activities", 0)

                logger.info(f"Updated course {course_id}: {course.moodle_course_name}")
            else:
                new_course = MoodleCourse(
                    datasource_config_id=moodle_config.id,
                    moodle_course_id=course_id,
                    moodle_course_name=course_metadata["fullname"],
                    metadata_last_sync=datetime.now(),
                    metadata_version=course_metadata.get("version_hash", ""),
                    moodle_course_files=json.dumps(
                        {
                            "structure": course_metadata.get("structure", {}),
                            "metadata": {
                                "category": course_metadata.get("category", ""),
                                "description": course_metadata.get("description", ""),
                                "format": course_metadata.get("format", ""),
                                "last_metadata_sync": datetime.now().isoformat(),
                                "selection_key": course_metadata.get(
                                    "selection_key", f"course:{course_id}"
                                ),
                                "total_files": course_metadata.get("total_files", 0),
                                "total_activities": course_metadata.get(
                                    "total_activities", 0
                                ),
                            },
                        }
                    ),
                    total_sections=course_metadata.get("total_sections", 0),
                    total_activities=course_metadata.get("total_activities", 0),
                )
                self.session.add(new_course)
                logger.info(
                    f"Added new course {course_id}: {new_course.moodle_course_name}"
                )

        for course_id, course in existing_courses.items():
            if course_id not in updated_course_ids:
                self.session.delete(course)
                logger.info(f"Removed course {course_id}: {course.moodle_course_name}")

    def prepare_content_sync_job(
        self,
        datasource_id: UUID,
        user: User,
        selected_files: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to sync this datasource",
            )

        if datasource.source_type == SourceType.FILE:
            raise HTTPException(
                status_code=400,
                detail="FILE datasources don't require content sync.",
            )

        if datasource.sync_status not in [
            DataSourceSyncStatus.READY,
            DataSourceSyncStatus.ERROR,
        ]:
            raise HTTPException(
                status_code=400,
                detail="Datasource must be metadata synced before content sync",
            )

        datasource.sync_status = DataSourceSyncStatus.PROCESSING
        self.session.commit()

        if selected_files is None or len(selected_files) == 0:
            selected_files = self.get_all_available_files(datasource_id)

        if not selected_files:
            raise HTTPException(
                status_code=400,
                detail="No files available for sync. Run metadata sync first.",
            )

        sync_job = {
            "operation": "sync_content",
            "datasource_id": str(datasource_id),
            "source_type": datasource.source_type,
            "owner_email": user.email,
            "owner_role": user.role,
            "selected_files": selected_files,
            "force": force,
        }

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            sync_job.update(
                {
                    "moodle_domain": datasource.moodle_config.domain,
                    "moodle_token": datasource.moodle_config.token,
                }
            )
        elif (
            datasource.source_type == SourceType.NEXTCLOUD
            and datasource.nextcloud_config
        ):
            sync_job.update(
                {
                    "nextcloud_url": datasource.nextcloud_config.url,
                    "nextcloud_username": datasource.nextcloud_config.username,
                    "nextcloud_password": datasource.nextcloud_config.password,
                }
            )

        logger.info(f"Prepared content sync job for datasource {datasource_id}")
        return sync_job

    def handle_content_sync_completion(self, message: dict[str, Any]) -> None:
        datasource_id = message.get("datasource_id")
        files_downloaded = message.get("files_downloaded", 0)

        if not datasource_id:
            logger.error("Missing datasource_id in content sync completion message")
            return

        datasource = self.ds_repo.get(UUID(datasource_id))
        if datasource is None:
            logger.warning(f"Datasource {datasource_id} not found")
            return

        datasource.sync_status = DataSourceSyncStatus.READY
        datasource.last_sync = datetime.now()
        datasource.last_sync_error = None
        self.session.commit()

        logger.info(
            f"Content sync completed for datasource {datasource_id}. "
            f"Downloaded {files_downloaded} files."
        )

    def handle_content_sync_failure(self, message: dict[str, Any]) -> None:
        datasource_id = message.get("datasource_id")
        error_message = message.get("error", "Unknown error")
        files_downloaded = message.get("files_downloaded", 0)

        if not datasource_id:
            logger.error("Missing datasource_id in content sync failure message")
            return

        datasource = self.ds_repo.get(UUID(datasource_id))
        if datasource is None:
            logger.warning(f"Datasource {datasource_id} not found")
            return

        datasource.sync_status = DataSourceSyncStatus.ERROR
        datasource.last_sync_error = SyncErrorCode.FAILED
        self.session.commit()

        logger.warning(
            f"Content sync failed for datasource {datasource_id}: {error_message}. "
            f"Downloaded {files_downloaded} files before failure."
        )

    def get_all_available_files(self, datasource_id: UUID) -> list[str]:
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            return []

        available_files = []

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            for course in datasource.moodle_config.moodle_courses:
                if course.moodle_course_files:
                    try:
                        course_data = json.loads(course.moodle_course_files)
                        metadata = course_data.get("metadata", {})
                        course_selection_key = metadata.get(
                            "selection_key", f"course:{course.moodle_course_id}"
                        )
                        available_files.append(course_selection_key)
                        logger.info(f"Added course selection: {course_selection_key}")
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Invalid course data for course {course.moodle_course_id}"
                        )

        return available_files

    def get_datasource_selections(
        self, datasource_id: UUID, user: User
    ) -> dict[str, Any]:
        datasource = self.ds_repo.get(datasource_id)
        if not datasource:
            raise HTTPException(status_code=404, detail="Datasource not found")

        if datasource.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this datasource",
            )

        if datasource.source_type == SourceType.FILE:
            return self._get_file_datasource_selections(datasource_id)

        selections: dict[str, Any] = {
            "datasource_id": str(datasource_id),
            "source_type": "MOODLE",
            "courses": [],
            "total_files": 0,
            "total_activities": 0,
        }

        if datasource.source_type == SourceType.MOODLE and datasource.moodle_config:
            for course in datasource.moodle_config.moodle_courses:
                if course.moodle_course_files:
                    try:
                        course_data = json.loads(course.moodle_course_files)
                        metadata = course_data.get("metadata", {})
                        structure = course_data.get("structure", {})

                        course_info = {
                            "course_id": course.moodle_course_id,
                            "course_name": course.moodle_course_name,
                            "selection_key": metadata.get(
                                "selection_key", f"course:{course.moodle_course_id}"
                            ),
                            "total_files": metadata.get("total_files", 0),
                            "total_activities": metadata.get("total_activities", 0),
                            "sections": [],
                        }

                        for section_name, section_data in structure.items():
                            if section_name.startswith("_"):
                                continue

                            section_info = {"name": section_name, "activities": []}

                            if (
                                isinstance(section_data, dict)
                                and "activities" in section_data
                            ):
                                for activity_name, activity_data in section_data[
                                    "activities"
                                ].items():
                                    activity_info = {
                                        "name": activity_name,
                                        "id": activity_data.get("id"),
                                        "type": activity_data.get("type"),
                                        "files": [],
                                    }

                                    for file_data in activity_data.get("files", []):
                                        activity_info["files"].append(
                                            {
                                                "filename": file_data.get("filename"),
                                                "selection_key": file_data.get(
                                                    "selection_key"
                                                ),
                                                "filesize": file_data.get(
                                                    "filesize", 0
                                                ),
                                            }
                                        )

                                    if activity_info["files"]:
                                        section_info["activities"].append(activity_info)

                            if section_info["activities"]:
                                course_info["sections"].append(section_info)

                        selections["courses"].append(course_info)
                        selections["total_files"] += metadata.get("total_files", 0)
                        selections["total_activities"] += metadata.get(
                            "total_activities", 0
                        )

                    except json.JSONDecodeError:
                        logger.warning(
                            f"Invalid course data for course {course.moodle_course_id}"
                        )

        return selections

    def _get_file_datasource_selections(self, datasource_id: UUID) -> dict[str, Any]:
        from app.models.enums import FileStatus
        from app.models.tables import UploadedFile

        statement = (
            select(UploadedFile)
            .where(UploadedFile.datasource_id == datasource_id)
            .where(
                col(UploadedFile.status).in_(
                    [FileStatus.UPLOADED, FileStatus.PROCESSED]
                )
            )
            .order_by(UploadedFile.original_filename)
        )

        files = self.session.exec(statement).all()

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
            "source_type": "FILE",
            "total_files": len(file_list),
            "total_size": total_size,
            "files": file_list,
            "selection_format": "Individual files: file:file_id",
        }

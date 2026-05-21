from uuid import UUID

from sqlmodel import Session, col, select

from app.models.enums import FileStatus
from app.models.tables import UploadedFile
from app.repositories.base import BaseRepository


class UploadedFileRepository(BaseRepository[UploadedFile]):
    def __init__(self, session: Session):
        super().__init__(session, UploadedFile)

    def get_by_datasource(
        self,
        datasource_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        status: FileStatus | None = None,
    ) -> list[UploadedFile]:
        statement = select(UploadedFile).where(
            UploadedFile.datasource_id == datasource_id
        )

        if status:
            statement = statement.where(UploadedFile.status == status)

        statement = (
            statement.order_by(col(UploadedFile.upload_date).desc())
            .offset(skip)
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def get_uploaded_and_processed(self, datasource_id: UUID) -> list[UploadedFile]:
        statement = (
            select(UploadedFile)
            .where(
                UploadedFile.datasource_id == datasource_id,
                col(UploadedFile.status).in_(
                    [FileStatus.UPLOADED, FileStatus.PROCESSED]
                ),
            )
            .order_by(UploadedFile.original_filename)
        )

        return list(self.session.exec(statement))

    def search(
        self,
        datasource_id: UUID,
        *,
        filename_pattern: str | None = None,
        tags: list[str] | None = None,
        mime_types: list[str] | None = None,
        status: FileStatus | None = None,
    ) -> list[UploadedFile]:
        statement = select(UploadedFile).where(
            UploadedFile.datasource_id == datasource_id
        )

        if filename_pattern:
            statement = statement.where(
                col(UploadedFile.original_filename).ilike(f"%{filename_pattern}%")
            )

        if tags:
            # match any of the tags
            for tag in tags:
                statement = statement.where(col(UploadedFile.tags).ilike(f'%"{tag}"%'))

        if mime_types:
            statement = statement.where(col(UploadedFile.mime_type).in_(mime_types))

        if status:
            statement = statement.where(UploadedFile.status == status)

        statement = statement.order_by(col(UploadedFile.upload_date).desc())
        return list(self.session.exec(statement))

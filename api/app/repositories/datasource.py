from uuid import UUID

from sqlmodel import Session, select

from app.models.enums import SourceType
from app.models.schemas import MoodleConfig, MoodleConfigCreate, NextCloudConfigCreate
from app.models.tables import (
    DataSource,
    MoodleCourse,
    MoodleDataSourceConfig,
    NextCloudDataSourceConfig,
    UploadedFile,
)
from app.repositories.base import BaseRepository


class DataSourceRepository(BaseRepository[DataSource]):
    def __init__(self, session: Session):
        super().__init__(session, DataSource)

    def get_by_name(self, name: str) -> DataSource | None:
        statement = select(DataSource).where(DataSource.name == name)
        return self.session.exec(statement).first()

    def get_by_type(
        self, source_type: SourceType, *, skip: int = 0, limit: int = 100
    ) -> list[DataSource]:
        statement = (
            select(DataSource)
            .where(DataSource.source_type == source_type)
            .offset(skip)
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def get_by_owner(
        self,
        owner_id: UUID,
        *,
        source_type: SourceType | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[DataSource]:
        statement = select(DataSource).where(DataSource.owner_id == owner_id)

        if source_type is not None:
            statement = statement.where(DataSource.source_type == source_type)

        statement = statement.offset(skip).limit(limit)
        return list(self.session.exec(statement))

    def get_with_owner_email(
        self, datasource_id: UUID
    ) -> tuple[DataSource | None, str | None]:
        datasource = self.get(datasource_id)
        if not datasource:
            return None, None

        owner_email = datasource.owner.email if datasource.owner else None
        return datasource, owner_email

    def delete_with_files(self, datasource_id: UUID) -> bool:
        statement = select(UploadedFile).where(
            UploadedFile.datasource_id == datasource_id
        )
        uploaded_files = self.session.exec(statement).all()
        for uploaded_file in uploaded_files:
            self.session.delete(uploaded_file)

        self.delete_configs(datasource_id)

        return self.delete(datasource_id) is not None

    def delete_configs(self, datasource_id: UUID) -> None:
        # courses first to avoid FK issues
        statement = (
            select(MoodleCourse)
            .join(MoodleDataSourceConfig)
            .where(MoodleDataSourceConfig.datasource_id == datasource_id)
        )
        courses = self.session.exec(statement).all()
        for course in courses:
            self.session.delete(course)

        moodle_stmt = select(MoodleDataSourceConfig).where(
            MoodleDataSourceConfig.datasource_id == datasource_id
        )
        moodle_configs = self.session.exec(moodle_stmt).all()
        for moodle_config in moodle_configs:
            self.session.delete(moodle_config)

        nextcloud_stmt = select(NextCloudDataSourceConfig).where(
            NextCloudDataSourceConfig.datasource_id == datasource_id
        )
        nextcloud_configs = self.session.exec(nextcloud_stmt).all()
        for nextcloud_config in nextcloud_configs:
            self.session.delete(nextcloud_config)

        self.session.commit()


class MoodleConfigRepository(BaseRepository[MoodleDataSourceConfig]):
    def __init__(self, session: Session):
        super().__init__(session, MoodleDataSourceConfig)

    def get_by_datasource(self, datasource_id: UUID) -> MoodleDataSourceConfig | None:
        statement = select(MoodleDataSourceConfig).where(
            MoodleDataSourceConfig.datasource_id == datasource_id
        )
        return self.session.exec(statement).first()

    def create_config(self, config: MoodleConfig) -> MoodleDataSourceConfig:
        return self.create(config.model_dump())

    def update_config(
        self, datasource_id: UUID, config: MoodleConfigCreate
    ) -> MoodleDataSourceConfig:
        """Update or create Moodle configuration."""
        db_obj = self.get_by_datasource(datasource_id)
        if not db_obj:
            return self.create_config(
                MoodleConfig(datasource_id=datasource_id, **config.model_dump())
            )

        obj_data = config.model_dump(exclude_unset=True)
        for field, value in obj_data.items():
            setattr(db_obj, field, value)

        self.session.add(db_obj)
        self.session.commit()
        self.session.refresh(db_obj)
        return db_obj

    def delete_courses(self, config_id: UUID) -> None:
        statement = select(MoodleCourse).where(
            MoodleCourse.datasource_config_id == config_id
        )
        courses = self.session.exec(statement).all()
        for course in courses:
            self.session.delete(course)
        self.session.commit()


class NextCloudConfigRepository(BaseRepository[NextCloudDataSourceConfig]):
    def __init__(self, session: Session):
        super().__init__(session, NextCloudDataSourceConfig)

    def get_by_datasource(
        self, datasource_id: UUID
    ) -> NextCloudDataSourceConfig | None:
        statement = select(NextCloudDataSourceConfig).where(
            NextCloudDataSourceConfig.datasource_id == datasource_id
        )
        return self.session.exec(statement).first()

    def create_config(
        self, datasource_id: UUID, config: NextCloudConfigCreate
    ) -> NextCloudDataSourceConfig:
        db_obj = NextCloudDataSourceConfig(
            datasource_id=datasource_id, **config.model_dump()
        )
        return self.create(db_obj)

    def update_config(
        self, datasource_id: UUID, config: NextCloudConfigCreate
    ) -> NextCloudDataSourceConfig:
        """Update or create NextCloud configuration."""
        db_obj = self.get_by_datasource(datasource_id)
        if not db_obj:
            return self.create_config(datasource_id, config)

        obj_data = config.model_dump(exclude_unset=True)
        for field, value in obj_data.items():
            setattr(db_obj, field, value)

        self.session.add(db_obj)
        self.session.commit()
        self.session.refresh(db_obj)
        return db_obj

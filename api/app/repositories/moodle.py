from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from app.models.tables import (
    MoodleCourseChatbotMapping,
    MoodleCourseChatbotMappingBase,
    MoodleIntegration,
    MoodleIntegrationBase,
)
from app.repositories.base import BaseRepository


class MoodleIntegrationRepository(BaseRepository[MoodleIntegration]):
    def __init__(self, session: Session):
        super().__init__(session, MoodleIntegration)

    def get_by_token(self, token: str) -> MoodleIntegration | None:
        """Active Moodle integration by token."""
        statement = select(MoodleIntegration).where(
            MoodleIntegration.token == token, MoodleIntegration.is_active
        )
        return self.session.exec(statement).first()

    def create_integration(
        self, integration_data: MoodleIntegrationBase
    ) -> MoodleIntegration:
        return self.create(integration_data)

    def update_integration(
        self, integration_id: UUID, integration_data: MoodleIntegrationBase
    ) -> MoodleIntegration | None:
        db_integration = self.get(integration_id)
        if not db_integration:
            return None

        update_data = integration_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_integration, field, value)

        db_integration.updated_at = datetime.now(UTC)
        self.session.add(db_integration)
        self.session.commit()
        self.session.refresh(db_integration)
        return db_integration


class CourseMappingRepository(BaseRepository[MoodleCourseChatbotMapping]):
    def __init__(self, session: Session):
        super().__init__(session, MoodleCourseChatbotMapping)

    def get_by_course(
        self, integration_id: UUID, course_id: str
    ) -> MoodleCourseChatbotMapping | None:
        statement = select(MoodleCourseChatbotMapping).where(
            MoodleCourseChatbotMapping.moodle_integration_id == integration_id,
            MoodleCourseChatbotMapping.course_id == course_id,
        )
        return self.session.exec(statement).first()

    def get_by_integration(
        self, integration_id: UUID
    ) -> list[MoodleCourseChatbotMapping]:
        statement = select(MoodleCourseChatbotMapping).where(
            MoodleCourseChatbotMapping.moodle_integration_id == integration_id
        )
        return list(self.session.exec(statement))

    def create_mapping(
        self, integration_id: UUID, mapping_data: MoodleCourseChatbotMappingBase
    ) -> MoodleCourseChatbotMapping:
        db_mapping = MoodleCourseChatbotMapping(
            moodle_integration_id=integration_id, **mapping_data.model_dump()
        )
        return self.create(db_mapping)

    def update_mapping(
        self, mapping_id: UUID, chatbot_id: UUID
    ) -> MoodleCourseChatbotMapping | None:
        db_mapping = self.get(mapping_id)
        if not db_mapping:
            return None

        db_mapping.chatbot_id = chatbot_id
        self.session.add(db_mapping)
        self.session.commit()
        self.session.refresh(db_mapping)
        return db_mapping

    def delete_by_course(
        self, integration_id: UUID, course_id: str
    ) -> MoodleCourseChatbotMapping | None:
        statement = select(MoodleCourseChatbotMapping).where(
            MoodleCourseChatbotMapping.moodle_integration_id == integration_id,
            MoodleCourseChatbotMapping.course_id == course_id,
        )
        db_mapping = self.session.exec(statement).first()

        if not db_mapping:
            return None

        self.session.delete(db_mapping)
        self.session.commit()
        return db_mapping

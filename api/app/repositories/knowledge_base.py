import json
import uuid
from datetime import datetime
from uuid import UUID

from sqlmodel import Session, select

from app.models.schemas import KnowledgeBaseResponse
from app.models.tables import (
    DataSource,
    KnowledgeBase,
    KnowledgeBaseDatasourceLink,
)
from app.repositories.base import BaseRepository


class KnowledgeBaseRepository(BaseRepository[KnowledgeBase]):
    def __init__(self, session: Session):
        super().__init__(session, KnowledgeBase)

    def create_knowledge_base(
        self,
        *,
        name: str,
        description: str | None = None,
        user_id: uuid.UUID,
        datasource_ids: list[str] | None = None,
    ) -> KnowledgeBaseResponse:
        knowledge_base = KnowledgeBase(
            name=name, description=description, user_id=user_id
        )
        self.session.add(knowledge_base)

        if datasource_ids:
            for ds_id in datasource_ids:
                datasource = self.session.get(DataSource, UUID(ds_id))
                if datasource:
                    kb_ds = KnowledgeBaseDatasourceLink(
                        knowledge_base_id=knowledge_base.id,
                        datasource_id=datasource.id,
                    )
                    self.session.add(kb_ds)

        self.session.commit()
        self.session.refresh(knowledge_base)

        return KnowledgeBaseResponse(
            id=knowledge_base.id,
            name=knowledge_base.name,
            description=knowledge_base.description,
            status=knowledge_base.status,
            user_id=user_id,
            user_email=knowledge_base.user.email,
            datasources=[str(ds.id) for ds in knowledge_base.datasources],
        )

    def get_multi_with_response(
        self, *, skip: int = 0, limit: int = 100
    ) -> list[KnowledgeBaseResponse]:
        statement = select(KnowledgeBase).offset(skip).limit(limit)
        knowledge_bases = list(self.session.exec(statement))

        responses = []
        for kb in knowledge_bases:
            datasource_ids = [str(ds.id) for ds in kb.datasources]
            responses.append(
                KnowledgeBaseResponse(
                    id=kb.id,
                    name=kb.name,
                    status=kb.status,
                    description=kb.description,
                    user_id=kb.user_id,
                    user_email=kb.user.email,
                    datasources=datasource_ids,
                )
            )
        return responses

    def update_knowledge_base(
        self,
        *,
        knowledge_base_id: UUID,
        name: str | None = None,
        description: str | None = None,
        status: str | None = None,
        last_sync: datetime | None = None,
        last_sync_error: str | None = None,
        user_id: UUID | None = None,
    ) -> KnowledgeBase | None:
        knowledge_base = self.get(knowledge_base_id)
        if not knowledge_base:
            return None

        if name is not None:
            knowledge_base.name = name
        if description is not None:
            knowledge_base.description = description
        if user_id is not None:
            knowledge_base.user_id = user_id
        if status is not None:
            knowledge_base.status = status
        if last_sync is not None:
            knowledge_base.last_sync = last_sync
        if last_sync_error is not None:
            knowledge_base.last_sync_error = last_sync_error

        self.session.commit()
        self.session.refresh(knowledge_base)
        return knowledge_base

    def get_datasources(self, knowledge_base_id: UUID) -> list[DataSource]:
        knowledge_base = self.get(knowledge_base_id)
        if not knowledge_base:
            return []
        return knowledge_base.datasources

    def add_datasource(
        self,
        *,
        knowledge_base_id: UUID,
        datasource_id: UUID,
        selection: list[str] | None = None,
    ) -> KnowledgeBaseDatasourceLink | None:
        knowledge_base = self.get(knowledge_base_id)
        datasource = self.session.get(DataSource, datasource_id)
        if not knowledge_base or not datasource:
            return None

        existing_link = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseDatasourceLink.datasource_id == datasource_id,
            )
        ).first()

        if existing_link:
            if selection is not None:
                existing_link.selection = json.dumps(selection)
                self.session.add(existing_link)
                self.session.commit()
                self.session.refresh(existing_link)
            return existing_link

        kb_datasource = KnowledgeBaseDatasourceLink(
            knowledge_base_id=knowledge_base_id,
            datasource_id=datasource_id,
            selection=json.dumps(selection or []),
        )
        self.session.add(kb_datasource)
        self.session.commit()
        self.session.refresh(kb_datasource)
        return kb_datasource

    def remove_datasource(
        self, *, knowledge_base_id: UUID, datasource_id: UUID
    ) -> KnowledgeBaseDatasourceLink | None:
        link = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseDatasourceLink.datasource_id == datasource_id,
            )
        ).first()

        if not link:
            return None

        self.session.delete(link)
        self.session.commit()
        return link

    def get_selections(
        self, *, knowledge_base_id: UUID, datasource_id: UUID
    ) -> list[str]:
        link = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseDatasourceLink.datasource_id == datasource_id,
            )
        ).first()

        if not link or not link.selection:
            return []

        try:
            result: list[str] = json.loads(link.selection)
            return result
        except json.JSONDecodeError:
            return []

    def get_files(self, *, knowledge_base_id: UUID, datasource_id: UUID) -> list[str]:
        """Legacy: files for a datasource link."""
        link = self.session.exec(
            select(KnowledgeBaseDatasourceLink).where(
                KnowledgeBaseDatasourceLink.knowledge_base_id == knowledge_base_id,
                KnowledgeBaseDatasourceLink.datasource_id == datasource_id,
            )
        ).first()

        if not link or not link.selection:
            return []

        try:
            result: list[str] = json.loads(link.selection)
            return result
        except json.JSONDecodeError:
            return []

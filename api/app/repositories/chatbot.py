import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, update
from sqlmodel import Session, col, select

from app.models.tables import Chatbot, ChatbotBase, ChatMessage, ChatSession
from app.repositories.base import BaseRepository


class ChatbotRepository(BaseRepository[Chatbot]):
    def __init__(self, session: Session):
        super().__init__(session, Chatbot)

    def get_by_owner(
        self, owner_id: UUID, *, skip: int = 0, limit: int = 100
    ) -> list[Chatbot]:
        statement = (
            select(Chatbot)
            .where(col(Chatbot.owner_id) == owner_id)
            .offset(skip)
            .limit(limit)
        )
        return list(self.session.exec(statement))

    def create_chatbot(self, chatbot: ChatbotBase, owner_id: uuid.UUID) -> Chatbot:
        db_chatbot = Chatbot(**chatbot.model_dump(), owner_id=owner_id)
        self.session.add(db_chatbot)
        self.session.commit()
        self.session.refresh(db_chatbot)
        return db_chatbot

    def update_chatbot(
        self, chatbot_id: uuid.UUID, chatbot_in: ChatbotBase | dict[str, Any]
    ) -> Chatbot:
        db_chatbot = self.session.exec(
            select(Chatbot).where(col(Chatbot.id) == chatbot_id)
        ).first()
        if not db_chatbot:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        if isinstance(chatbot_in, dict):
            update_data = chatbot_in
        else:
            update_data = chatbot_in.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(db_chatbot, key, value)

        db_chatbot.updated_at = datetime.now(UTC)
        self.session.commit()
        self.session.refresh(db_chatbot)
        return db_chatbot

    def delete_with_sessions(self, chatbot_id: uuid.UUID) -> Chatbot:
        db_chatbot = self.session.exec(
            select(Chatbot).where(col(Chatbot.id) == chatbot_id)
        ).first()
        if not db_chatbot:
            raise HTTPException(status_code=404, detail="Chatbot not found")

        chatsessions = self.session.exec(
            select(ChatSession).where(col(ChatSession.chatbot_id) == chatbot_id)
        ).all()

        for chatsession in chatsessions:
            self.session.exec(
                delete(ChatMessage).where(
                    col(ChatMessage.chat_session_id) == chatsession.id
                )
            )
            self.session.exec(
                delete(ChatSession).where(col(ChatSession.id) == chatsession.id)
            )

        self.session.delete(db_chatbot)
        self.session.commit()
        return db_chatbot

    def increment_chat_request_count(self, chatbot_id: uuid.UUID) -> None:
        self.session.exec(
            update(Chatbot)
            .where(col(Chatbot.id) == chatbot_id)
            .values(chat_request_count=Chatbot.chat_request_count + 1)
        )
        self.session.commit()

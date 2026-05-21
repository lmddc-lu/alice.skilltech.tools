from typing import Any
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, SQLModel, select


class BaseRepository[ModelType: SQLModel]:
    """Common CRUD operations."""

    def __init__(self, session: Session, model: type[ModelType]):
        self.session = session
        self.model = model

    def get(self, id: UUID) -> ModelType | None:
        return self.session.get(self.model, id)

    def get_multi(self, *, skip: int = 0, limit: int = 100) -> list[ModelType]:
        statement = select(self.model).offset(skip).limit(limit)
        return list(self.session.exec(statement))

    def create(self, obj_in: SQLModel | dict[str, Any]) -> ModelType:
        if isinstance(obj_in, dict):
            db_obj = self.model(**obj_in)
        else:
            db_obj = self.model(**obj_in.model_dump())

        self.session.add(db_obj)
        self.session.commit()
        self.session.refresh(db_obj)
        return db_obj

    def update(self, db_obj: ModelType, obj_in: SQLModel | dict[str, Any]) -> ModelType:
        obj_data = jsonable_encoder(db_obj)

        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        for field in obj_data:
            if field in update_data:
                setattr(db_obj, field, update_data[field])

        self.session.add(db_obj)
        self.session.commit()
        self.session.refresh(db_obj)
        return db_obj

    def delete(self, id: UUID) -> ModelType | None:
        db_obj = self.get(id)
        if db_obj:
            self.session.delete(db_obj)
            self.session.commit()
        return db_obj

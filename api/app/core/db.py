from sqlmodel import Session, create_engine

from app.core.config import settings
from app.models.tables import UserBase
from app.repositories.user import UserRepository

engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
)


# all SQLModel models (app.models) must be imported before init so
# relationships resolve. see https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # tables are created via Alembic migrations. to skip migrations,
    # uncomment:
    # from sqlmodel import SQLModel
    # SQLModel.metadata.create_all(engine)
    user_repo = UserRepository(session)
    user = user_repo.get_by_email("test@admin.fr")

    if not user:
        user_in = UserBase(email="test@admin.fr", is_active=True, role="admin")
        user = user_repo.create_user(user_create=user_in, provider_id="")
    pass

from uuid import UUID

from sqlmodel import Session, select

from app.models.enums import UserRole
from app.models.tables import User, UserBase
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: Session):
        super().__init__(session, User)

    def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return self.session.exec(statement).first()

    def get_by_provider_id(self, provider_id: str) -> User | None:
        statement = select(User).where(User.provider_id == provider_id)
        return self.session.exec(statement).first()

    def get_active_users(self, *, skip: int = 0, limit: int = 100) -> list[User]:
        statement = select(User).where(User.is_active).offset(skip).limit(limit)
        return list(self.session.exec(statement))

    def create_user(self, user_create: UserBase, provider_id: str) -> User:
        user_data = user_create.model_dump()
        user_data["provider_id"] = provider_id
        return self.create(user_data)

    def deactivate(self, user_id: UUID) -> User | None:
        user = self.get(user_id)
        if user:
            user.is_active = False
            self.session.add(user)
            self.session.commit()
            self.session.refresh(user)
        return user

    def is_active(self, user: User) -> bool:
        return user.is_active

    def has_role(self, user: User, required_role: UserRole) -> bool:
        """True if user has required_role or higher."""
        role_hierarchy = {
            UserRole.VIEWER: 0,
            UserRole.USER: 1,
            UserRole.ADMIN: 2,
        }
        user_role_level = role_hierarchy.get(UserRole(user.role), 0)
        required_role_level = role_hierarchy.get(required_role, 0)
        return user_role_level >= required_role_level

    def is_admin(self, user: User) -> bool:
        return user.role == UserRole.ADMIN

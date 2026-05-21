from collections.abc import Awaitable, Callable, Generator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from app.core.db import engine
from app.models.enums import UserRole
from app.models.tables import User
from app.repositories.user import UserRepository
from app.services.access_service import AccessService
from app.services.chatbot_service import ChatbotService
from app.services.datasource_service import DatasourceService
from app.services.file_service import FileService
from app.services.knowledgebase_service import KnowledgebaseService
from app.services.moodle_service import MoodleService
from app.services.selection_service import SelectionService
from app.utils.auth import decode_token

security = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_db)]
# HTTPBearer(auto_error=False) returns None when no credentials are provided,
# so the dependency type itself must include None. Wrapping the alias with
# `| None` outside the Annotated would hide the Depends marker from FastAPI's
# dependency resolver and make the parameter look like a body field.
TokenDep = Annotated[HTTPAuthorizationCredentials | None, Depends(security)]


async def get_current_user(
    request: Request,
    response: Response,
    session: SessionDep,
    credentials: TokenDep = None,
) -> User:
    """Get current user from JWT token or OAuth session."""
    user_repo = UserRepository(session)

    token = None

    if credentials:
        token = credentials.credentials

    if not token and "token" in request.cookies:
        token = request.cookies.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        data = decode_token(token)

        if not data or "id" not in data:
            raise HTTPException(status_code=401, detail="Invalid token")

        user = user_repo.get(UUID(data["id"]))

        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        if not user_repo.is_active(user):
            raise HTTPException(status_code=401, detail="User is inactive")
        return user

    except HTTPException:
        raise
    except Exception:
        if request.cookies.get("token"):
            response.delete_cookie("token")
        if request.cookies.get("refresh_token"):
            response.delete_cookie("refresh_token", path="/api/v2/oauth/refresh")
        if request.cookies.get("oauth_id_token"):
            response.delete_cookie("oauth_id_token")
        if request.cookies.get("oauth_session_id"):
            response.delete_cookie("oauth_session_id")

        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user_optional(
    request: Request,
    response: Response,
    session: SessionDep,
    credentials: TokenDep = None,
) -> User | None:
    """Get current user from JWT token or return None if not authenticated."""
    try:
        return await get_current_user(request, response, session, credentials)
    except HTTPException:
        return None


def require_role(
    required_role: UserRole,
) -> Callable[[SessionDep, User], Awaitable[User]]:
    """Dependency to check if user has required role."""

    async def role_checker(
        session: SessionDep,
        user: User = Depends(get_current_user),
    ) -> User:
        user_repo = UserRepository(session)
        if not user_repo.has_role(user, required_role):
            raise HTTPException(
                status_code=403, detail=f"Requires {required_role.value} role or higher"
            )
        return user

    return role_checker


def require_admin(session: SessionDep, user: User = Depends(get_current_user)) -> User:
    """Dependency to require admin role."""
    user_repo = UserRepository(session)
    if not user_repo.is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def require_user_role(
    session: SessionDep, user: User = Depends(get_current_user)
) -> User:
    user_repo = UserRepository(session)
    if not user_repo.has_role(user, UserRole.USER):
        raise HTTPException(status_code=403, detail="User privileges required")
    return user


def require_viewer_role(
    session: SessionDep, user: User = Depends(get_current_user)
) -> User:
    user_repo = UserRepository(session)
    if not user_repo.has_role(user, UserRole.VIEWER):
        raise HTTPException(status_code=403, detail="Viewer privileges required")
    return user


ViewerDep = Annotated[User, Depends(require_viewer_role)]
UserDep = Annotated[User, Depends(require_user_role)]
AdminUser = Annotated[User, Depends(require_admin)]
OptionalUserDep = Annotated[User | None, Depends(get_current_user_optional)]


def get_chatbot_service(session: SessionDep) -> ChatbotService:
    return ChatbotService(session)


def get_datasource_service(session: SessionDep) -> DatasourceService:
    return DatasourceService(session)


def get_knowledgebase_service(session: SessionDep) -> KnowledgebaseService:
    return KnowledgebaseService(session)


def get_file_service() -> FileService:
    return FileService()


def get_moodle_service() -> MoodleService:
    return MoodleService()


def get_access_service() -> AccessService:
    return AccessService()


def get_selection_service() -> SelectionService:
    return SelectionService()


ChatbotServiceDep = Annotated[ChatbotService, Depends(get_chatbot_service)]
DatasourceServiceDep = Annotated[DatasourceService, Depends(get_datasource_service)]
KnowledgebaseServiceDep = Annotated[
    KnowledgebaseService, Depends(get_knowledgebase_service)
]
FileServiceDep = Annotated[FileService, Depends(get_file_service)]
MoodleServiceDep = Annotated[MoodleService, Depends(get_moodle_service)]

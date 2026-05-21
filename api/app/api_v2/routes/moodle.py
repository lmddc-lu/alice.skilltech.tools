import logging
from typing import Any

from faststream.rabbit.fastapi import RabbitRouter
from pydantic import BaseModel

from app.api_v2.deps import MoodleServiceDep, UserDep
from app.core.config import settings
from app.models.enums import UserRole
from app.models.schemas import MoodleCourseInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = RabbitRouter(settings.RABBITMQ_URL, tags=["moodle"])


class MoodleConnectionTest(BaseModel):
    moodle_url: str
    token: str


class MoodleConnectionRequest(BaseModel):
    moodle_url: str
    token: str


class MoodleCoursesResponse(BaseModel):
    courses: list[MoodleCourseInfo]
    total_courses: int
    returned_courses: int
    has_more: bool


@router.post("/moodle/test-connection")
def test_moodle_connection(
    connection: MoodleConnectionTest,
    user: UserDep,
    moodle_service: MoodleServiceDep,
) -> dict[str, Any]:
    """Test a Moodle connection with the Content Export plugin.

    Verifies the URL is reachable, the token is valid, the plugin is
    installed, and the token has permission to export courses.
    """
    result = moodle_service.test_connection(
        connection.moodle_url,
        connection.token,
        allow_private_networks=user.role == UserRole.ADMIN,
    )

    if result.success:
        return {
            "success": True,
            "total_courses": result.total_courses,
            "plugin_installed": result.plugin_installed,
            "message": result.message,
        }
    else:
        return {
            "success": False,
            "error": result.error,
            "error_code": result.error_code,
        }


@router.post("/moodle/list-courses")
def list_moodle_courses(
    request: MoodleConnectionRequest,
    user: UserDep,
    moodle_service: MoodleServiceDep,
    limit: int = 100,
    offset: int = 0,
    include_hidden: bool = True,
    category_id: int = 0,
) -> MoodleCoursesResponse:
    """List all accessible courses from a Moodle instance."""
    result = moodle_service.fetch_courses(
        moodle_url=request.moodle_url,
        token=request.token,
        limit=limit,
        offset=offset,
        include_hidden=include_hidden,
        category_id=category_id,
        allow_private_networks=user.role == UserRole.ADMIN,
    )

    return MoodleCoursesResponse(
        courses=result.courses,
        total_courses=result.total_courses,
        returned_courses=result.returned_courses,
        has_more=result.has_more,
    )

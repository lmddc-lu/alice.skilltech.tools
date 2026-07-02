import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import requests
from fastapi import HTTPException
from sqlmodel import Session

from app.models.schemas import MoodleCourseInfo
from app.models.tables import DataSource
from app.services.datasource_service import DatasourceService
from app.services.url_validation import (
    UrlValidationError,
    ValidatedUrl,
    make_pinned_session,
    validate_moodle_url,
)

logger = logging.getLogger(__name__)


def _validate_moodle_url(
    url: str, *, allow_private_networks: bool = False
) -> ValidatedUrl:
    """Wrapper kept for backward compat; returns the ValidatedUrl for pinning."""
    try:
        return validate_moodle_url(url, allow_private_networks=allow_private_networks)
    except UrlValidationError as e:
        raise ValueError(str(e))


@dataclass
class MoodleConnectionResult:
    success: bool
    error: str | None = None
    error_code: str | None = None
    total_courses: int | None = None
    plugin_installed: bool = False
    message: str | None = None


@dataclass
class MoodleCoursesResult:
    courses: list[MoodleCourseInfo]
    total_courses: int
    returned_courses: int
    has_more: bool


class MoodleService:
    DEFAULT_TIMEOUT = 30

    @staticmethod
    def _build_api_url(moodle_url: str) -> str:
        return f"{moodle_url.rstrip('/')}/webservice/rest/server.php"

    @staticmethod
    def _handle_moodle_error(result: dict[str, Any]) -> tuple[str, str]:
        """Returns (error_message, error_code)."""
        error_message = result.get("message", "Unknown error")
        error_code = result.get("errorcode", "unknown")

        if "invalidtoken" in error_code.lower():
            error_message = "Invalid token. Please verify your web service token."
        elif (
            "accessexception" in error_code.lower()
            or "nopermission" in error_code.lower()
        ):
            error_message = (
                "The token does not have permission to access the Content Export plugin. "
                "Please ensure the token has the required capabilities."
            )
        elif "invalidparameter" in error_code.lower():
            error_message = "The Content Export plugin may not be installed or is not configured correctly."

        return error_message, error_code

    def test_connection(
        self,
        moodle_url: str,
        token: str,
        *,
        allow_private_networks: bool = False,
    ) -> MoodleConnectionResult:
        """Test a Moodle connection with the Content Export plugin.

        allow_private_networks is the caller's role capability. only admins
        may reach destinations inside MOODLE_ALLOWED_NETWORKS.
        """
        moodle_url = moodle_url.rstrip("/")

        try:
            validated = _validate_moodle_url(
                moodle_url, allow_private_networks=allow_private_networks
            )
        except ValueError as e:
            logger.warning(f"Moodle URL validation failed: {e}")
            return MoodleConnectionResult(success=False, error=str(e))

        api_url = self._build_api_url(moodle_url)

        data = {
            "wstoken": token,
            "wsfunction": "local_contentexport_export_all_courses",
            "moodlewsrestformat": "json",
            "include_hidden": 0,
            "category_id": 0,
            "offset": 0,
            "limit": 1,  # only fetch 1 course to test
            "include_non_enrolled": 0,
        }

        try:
            logger.info(f"Testing Moodle Content Export plugin at: {moodle_url}")

            session = make_pinned_session(validated)
            response = session.post(api_url, data=data, timeout=10)
            response.raise_for_status()
            result = response.json()

            if "exception" in result or "errorcode" in result:
                error_message, error_code = self._handle_moodle_error(result)
                logger.warning(
                    f"Moodle Content Export test failed: {error_code} - {error_message}"
                )
                return MoodleConnectionResult(
                    success=False,
                    error=error_message,
                    error_code=error_code,
                )

            pagination = result.get("pagination", {})
            if pagination is None:
                return MoodleConnectionResult(
                    success=False,
                    error="Invalid response format - Content Export plugin may not be installed",
                )

            total_courses = pagination.get("total_courses", 0)
            logger.info(
                f"Moodle connection successful: {total_courses} courses accessible"
            )

            return MoodleConnectionResult(
                success=True,
                total_courses=total_courses,
                plugin_installed=True,
                message=f"Successfully connected! Found {total_courses} accessible courses.",
            )

        except requests.exceptions.Timeout:
            logger.error(f"Timeout connecting to Moodle at {moodle_url}")
            return MoodleConnectionResult(
                success=False,
                error="Connection timeout - Moodle server did not respond in time",
            )
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to Moodle at {moodle_url}: {e}")
            return MoodleConnectionResult(
                success=False,
                error="Connection error - Could not connect to Moodle server. Please verify the URL.",
            )
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from Moodle at {moodle_url}: {e}")
            return MoodleConnectionResult(
                success=False,
                error=f"HTTP error - Server returned status code {e.response.status_code}",
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Request exception for Moodle at {moodle_url}: {e}")
            return MoodleConnectionResult(
                success=False, error=f"Request failed: {str(e)}"
            )
        except ValueError as e:
            logger.error(f"Invalid JSON response from Moodle at {moodle_url}: {e}")
            return MoodleConnectionResult(
                success=False,
                error="Invalid response from server - Expected JSON format",
            )
        except Exception as e:
            logger.error(
                f"Unexpected error testing Moodle connection: {e}", exc_info=True
            )
            return MoodleConnectionResult(
                success=False, error=f"Unexpected error: {str(e)}"
            )

    def fetch_courses(
        self,
        moodle_url: str,
        token: str,
        limit: int = 100,
        offset: int = 0,
        include_hidden: bool = True,
        category_id: int = 0,
        *,
        allow_private_networks: bool = False,
    ) -> MoodleCoursesResult:
        """Fetch courses from a Moodle instance. category_id=0 for all."""
        moodle_url = moodle_url.rstrip("/")

        try:
            validated = _validate_moodle_url(
                moodle_url, allow_private_networks=allow_private_networks
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        api_url = self._build_api_url(moodle_url)

        data = {
            "wstoken": token,
            "wsfunction": "local_contentexport_export_all_courses",
            "moodlewsrestformat": "json",
            "include_hidden": 1 if include_hidden else 0,
            "category_id": category_id,
            "offset": offset,
            "limit": min(limit, 100),
            "include_non_enrolled": 1,
            "include_site": 1,
        }

        try:
            logger.info(f"Fetching courses from Moodle at: {moodle_url}")
            session = make_pinned_session(validated)
            response = session.post(api_url, data=data, timeout=self.DEFAULT_TIMEOUT)
            response.raise_for_status()
            result = response.json()

            if "exception" in result or "errorcode" in result:
                error_message, error_code = self._handle_moodle_error(result)
                logger.error(f"Moodle API error: {error_code} - {error_message}")

                if "invalidtoken" in error_code.lower():
                    raise HTTPException(status_code=401, detail=error_message)
                elif (
                    "accessexception" in error_code.lower()
                    or "nopermission" in error_code.lower()
                ):
                    raise HTTPException(status_code=403, detail=error_message)
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Moodle error: {error_message}"
                    )

            courses_data = result.get("courses", [])
            pagination = result.get("pagination", {})

            courses = []
            for course in courses_data:
                course_metadata = course.get("metadata", {})
                courses.append(
                    MoodleCourseInfo(
                        course_id=str(course.get("id")),
                        course_name=course.get("fullname", ""),
                        shortname=course.get("shortname", ""),
                        description=course.get("description", ""),
                        category=course.get("category", ""),
                        course_url=course.get("course_url", ""),
                        moodle_domain=moodle_url,
                        selection_key=f"course:{course.get('id')}",
                        total_sections=course_metadata.get("total_sections", 0),
                        total_activities=course_metadata.get("total_activities", 0),
                    )
                )

            logger.info(f"Fetched {len(courses)} courses from Moodle")

            return MoodleCoursesResult(
                courses=courses,
                total_courses=pagination.get("total_courses", 0),
                returned_courses=pagination.get("returned_courses", len(courses)),
                has_more=pagination.get("has_more", False),
            )

        except HTTPException:
            raise
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching courses from Moodle at {moodle_url}")
            raise HTTPException(status_code=504, detail="Connection timeout")
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error to Moodle at {moodle_url}")
            raise HTTPException(
                status_code=503, detail="Could not connect to Moodle server"
            )
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from Moodle at {moodle_url}: {e}")
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"HTTP error from Moodle: {e.response.status_code}",
            )
        except Exception as e:
            logger.error(
                f"Unexpected error fetching Moodle courses: {e}", exc_info=True
            )
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch courses: {str(e)}"
            )

    def refresh_datasource_courses(self, session: Session, datasource_id: UUID) -> None:
        """Refresh Moodle courses for a datasource by fetching from the API."""
        datasource = session.get(DataSource, datasource_id)
        if not datasource or not datasource.moodle_config:
            raise HTTPException(status_code=404, detail="Moodle datasource not found")

        moodle_config = datasource.moodle_config
        moodle_url = moodle_config.domain.rstrip("/")

        allow_private = (
            datasource.owner is not None and datasource.owner.role == "admin"
        )
        try:
            validated = _validate_moodle_url(
                moodle_url, allow_private_networks=allow_private
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        api_url = self._build_api_url(moodle_url)

        data = {
            "wstoken": moodle_config.token,
            "wsfunction": "local_contentexport_export_all_courses",
            "moodlewsrestformat": "json",
            "include_hidden": 1,
            "category_id": 0,
            "offset": 0,
            "limit": 1000,
            "include_non_enrolled": 1,
            "include_site": 1,
        }

        try:
            http_session = make_pinned_session(validated)
            response = http_session.post(
                api_url, data=data, timeout=self.DEFAULT_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()

            if "exception" in result or "errorcode" in result:
                error_message = result.get("message", "Unknown error")
                logger.error(f"Moodle API error: {error_message}")
                raise HTTPException(
                    status_code=400, detail=f"Moodle error: {error_message}"
                )

            courses_metadata = result.get("courses", [])
            DatasourceService(session).update_moodle_courses_metadata(
                datasource, courses_metadata
            )

            logger.info(
                f"Refreshed {len(courses_metadata)} courses for datasource {datasource_id}"
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch courses from Moodle: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Failed to fetch courses from Moodle: {str(e)}",
            )

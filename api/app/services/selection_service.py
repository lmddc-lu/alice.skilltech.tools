import json
import logging
from uuid import UUID

logger = logging.getLogger(__name__)


class SelectionService:
    """Parse and build selection strings for files and courses."""

    @staticmethod
    def parse_selections(selection_json: str | None) -> list[str]:
        """Parse selection JSON, returning [] on failure."""
        if not selection_json:
            return []
        try:
            result = json.loads(selection_json)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse selection JSON: {selection_json[:100]}")
            return []

    @staticmethod
    def extract_file_ids(selections: list[str]) -> list[UUID]:
        """Extract file UUIDs from selections like 'file:uuid'."""
        file_ids = []
        for selection in selections:
            if selection.startswith("file:"):
                try:
                    file_id = UUID(selection.split(":", 1)[1])
                    file_ids.append(file_id)
                except (ValueError, IndexError):
                    logger.warning(f"Invalid file selection format: {selection}")
        return file_ids

    @staticmethod
    def extract_course_ids(selections: list[str]) -> list[str]:
        """Extract course IDs from selections like 'course:id'."""
        course_ids = []
        for selection in selections:
            if selection.startswith("course:"):
                try:
                    course_id = selection.split(":", 1)[1]
                    course_ids.append(course_id)
                except IndexError:
                    logger.warning(f"Invalid course selection format: {selection}")
        return course_ids

    @staticmethod
    def build_file_selection(file_id: UUID) -> str:
        """Build a file selection string from a file UUID."""
        return f"file:{file_id}"

    @staticmethod
    def build_course_selection(course_id: str) -> str:
        """Build a course selection string from a course ID."""
        return f"course:{course_id}"

    @staticmethod
    def build_file_selections(file_ids: list[UUID]) -> list[str]:
        """Build file selection strings from a list of file UUIDs."""
        return [f"file:{file_id}" for file_id in file_ids]

    @staticmethod
    def build_course_selections(course_ids: list[str]) -> list[str]:
        """Build course selection strings from a list of course IDs."""
        return [f"course:{course_id}" for course_id in course_ids]

    @staticmethod
    def serialize_selections(selections: list[str]) -> str:
        """Serialize selections list to JSON string."""
        return json.dumps(selections)

    @staticmethod
    def filter_file_selections(selections: list[str]) -> list[str]:
        """Filter to only file selections."""
        return [s for s in selections if s.startswith("file:")]

    @staticmethod
    def filter_course_selections(selections: list[str]) -> list[str]:
        """Filter to only course selections."""
        return [s for s in selections if s.startswith("course:")]

    @staticmethod
    def filter_non_course_selections(selections: list[str]) -> list[str]:
        """Filter out course selections, keeping everything else."""
        return [s for s in selections if not s.startswith("course:")]

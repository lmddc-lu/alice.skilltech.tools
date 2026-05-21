"""S3 path helpers shared by the worker and source adapters.

Single source of truth for user data layout in the object store.
Anything building an s3://.../alice/... path goes through here.
"""

from __future__ import annotations

APP_NAMESPACE = "alice"


def sanitize_email_for_path(email: str) -> str:
    return email


def get_user_base_path(user_email: str) -> str:
    return f"{sanitize_email_for_path(user_email)}/{APP_NAMESPACE}"


def get_datasource_path(user_email: str, datasource_id: str) -> str:
    return f"{get_user_base_path(user_email)}/datasources/{datasource_id}"


def get_datasource_uploads_path(user_email: str, datasource_id: str) -> str:
    return f"{get_datasource_path(user_email, datasource_id)}/uploads"


def get_knowledgebase_path(user_email: str, knowledgebase_id: str) -> str:
    return f"{get_user_base_path(user_email)}/knowledgebases/{knowledgebase_id}"

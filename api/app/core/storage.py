import logging
from datetime import timedelta

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


def sanitize_email_for_path(email: str) -> str:
    """Convert email to a safe path component."""
    if not email:
        raise ValueError("Email cannot be empty")
    return email


def get_user_base_path(user_email: str) -> str:
    return f"{sanitize_email_for_path(user_email)}/{settings.APP_S3_NAMESPACE}"


def get_datasource_path(user_email: str, datasource_id: str) -> str:
    return f"{get_user_base_path(user_email)}/datasources/{datasource_id}"


def get_datasource_uploads_path(user_email: str, datasource_id: str) -> str:
    return f"{get_datasource_path(user_email, datasource_id)}/uploads"


def get_file_storage_path(
    user_email: str, datasource_id: str, stored_filename: str
) -> str:
    return f"{get_datasource_uploads_path(user_email, datasource_id)}/{stored_filename}"


def build_chatbot_avatar_url(
    chatbot_id: object, avatar_storage_path: str | None
) -> str | None:
    """Build the browser-facing URL for a chatbot avatar.

    Returns None when no custom avatar is set. Targets an API streaming
    endpoint instead of a presigned MinIO URL (presigned URLs sign
    against the internal Docker hostname and don't resolve from the
    browser). Filename is appended as a cache-busting query param.
    """
    if not avatar_storage_path:
        return None
    cache_key = avatar_storage_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return f"/api/v2/chatbots/{chatbot_id}/avatar?v={cache_key}"


class StorageManager:
    """S3/MinIO storage operations with user-based paths."""

    def __init__(self) -> None:
        self.client = Minio(
            endpoint=settings.MINIO_URL,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            region=settings.MINIO_REGION,
            secure=settings.MINIO_URL.startswith("https"),
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        try:
            if not self.client.bucket_exists(bucket_name=self.bucket_name):
                self.client.make_bucket(bucket_name=self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Error checking/creating bucket: {e}")

    def check_connection(self) -> None:
        """Raises on failure."""
        self.client.bucket_exists(bucket_name=self.bucket_name)

    def upload_file(
        self,
        local_path: str,
        storage_path: str,
        content_type: str = "application/octet-stream",
    ) -> bool:
        try:
            self.client.fput_object(
                bucket_name=self.bucket_name,
                file_path=local_path,
                object_name=storage_path,
                content_type=content_type,
            )
            logger.info(f"Uploaded file to: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to upload file {storage_path}: {e}")
            return False

    def download_file(self, storage_path: str, local_path: str) -> bool:
        try:
            self.client.fget_object(
                bucket_name=self.bucket_name,
                file_path=local_path,
                object_name=storage_path,
            )
            logger.info(f"Downloaded file from: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to download file {storage_path}: {e}")
            return False

    def delete_file(self, storage_path: str) -> bool:
        try:
            self.client.remove_object(
                bucket_name=self.bucket_name, object_name=storage_path
            )
            logger.info(f"Deleted file: {storage_path}")
            return True
        except S3Error as e:
            logger.error(f"Failed to delete file {storage_path}: {e}")
            return False

    def delete_prefix(self, prefix: str) -> tuple[int, list[str]]:
        """Returns (files_deleted_count, errors_list)."""
        files_deleted = 0
        errors = []

        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name, prefix=prefix, recursive=True
            )

            for obj in objects:
                try:
                    self.client.remove_object(
                        bucket_name=self.bucket_name, object_name=obj.object_name
                    )
                    files_deleted += 1
                    logger.debug(f"Deleted: {obj.object_name}")
                except S3Error as e:
                    error_msg = f"Failed to delete {obj.object_name}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)

        except S3Error as e:
            error_msg = f"Failed to list objects under {prefix}: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

        if files_deleted > 0:
            logger.info(f"Deleted {files_deleted} files under prefix: {prefix}")

        return files_deleted, errors

    def delete_datasource_files(
        self, user_email: str, datasource_id: str
    ) -> tuple[int, list[str]]:
        prefix = f"{get_datasource_path(user_email, datasource_id)}/"
        return self.delete_prefix(prefix)

    def delete_user_files(self, user_email: str) -> tuple[int, list[str]]:
        """Delete ALL files for a user (use with caution!)."""
        prefix = f"{get_user_base_path(user_email)}/"
        return self.delete_prefix(prefix)

    def list_files(self, prefix: str, recursive: bool = True) -> list[str]:
        try:
            objects = self.client.list_objects(
                bucket_name=self.bucket_name, prefix=prefix, recursive=recursive
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error(f"Failed to list objects under {prefix}: {e}")
            return []

    def file_exists(self, storage_path: str) -> bool:
        try:
            self.client.stat_object(
                bucket_name=self.bucket_name, object_name=storage_path
            )
            return True
        except S3Error:
            return False

    def get_file_url(self, storage_path: str, expires_hours: int = 1) -> str | None:
        """Returns presigned URL or None on error."""
        try:
            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=storage_path,
                expires=timedelta(hours=expires_hours),
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL for {storage_path}: {e}")
            return None

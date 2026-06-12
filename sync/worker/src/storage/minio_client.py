import logging
from collections.abc import Iterator
from pathlib import Path

from minio import Minio

logger = logging.getLogger(__name__)


class MinioStorage:
    def __init__(
        self, url: str, access_key: str, secret_key: str, region: str = "garage"
    ):
        self.client = Minio(
            endpoint=url,
            access_key=access_key,
            secret_key=secret_key,
            secure=False,
            region=region,
        )

    def upload_directory(self, local_dir: Path, bucket: str, prefix: str) -> None:
        if not local_dir.exists():
            raise ValueError(f"Directory does not exist: {local_dir}")

        existing_files = {
            obj.object_name
            for obj in self.client.list_objects(
                bucket_name=bucket, prefix=prefix, recursive=True
            )
        }

        for file_path in local_dir.rglob("*"):
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(local_dir)
            object_name = str(Path(prefix) / rel_path)

            should_upload = True
            if object_name in existing_files:
                try:
                    local_size = file_path.stat().st_size
                    minio_size = self.client.stat_object(
                        bucket_name=bucket, object_name=object_name
                    ).size
                    if local_size == minio_size:
                        should_upload = False
                        logger.info(f"File unchanged, skipping: {object_name}")
                except Exception as e:
                    logger.warning(f"Error comparing files, will upload: {e}")

            if should_upload:
                self._upload_with_retry(bucket, object_name, file_path)

    def _upload_with_retry(
        self, bucket: str, object_name: str, file_path: Path, max_retries: int = 3
    ) -> None:
        for attempt in range(max_retries):
            try:
                self.client.fput_object(
                    bucket_name=bucket,
                    object_name=object_name,
                    file_path=str(file_path),
                )
                logger.info(f"Uploaded {file_path} to {object_name}")
                break
            except Exception:
                if attempt == max_retries - 1:
                    raise
                logger.warning(
                    f"Upload attempt {attempt + 1} failed for {file_path}, retrying..."
                )

    def download_file(self, bucket: str, object_name: str, destination: Path) -> None:
        self.client.fget_object(
            bucket_name=bucket, object_name=object_name, file_path=str(destination)
        )

    def list_objects(self, bucket: str, prefix: str) -> Iterator[str]:
        return self.client.list_objects(
            bucket_name=bucket, prefix=prefix, recursive=True
        )

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.client.remove_object(bucket_name=bucket, object_name=object_name)

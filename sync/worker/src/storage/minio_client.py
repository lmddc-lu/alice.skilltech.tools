import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

from minio import Minio

logger = logging.getLogger(__name__)


def object_etag(obj) -> str | None:
    """Normalized etag of a listed/statted object, or None when absent.

    Some S3 implementations quote etags in listings; strip the quotes so the
    value compares equal to the one stamped into chunk metadata at ingestion.
    """
    etag = getattr(obj, "etag", None)
    if not etag:
        return None
    return str(etag).strip('"')


def _file_md5(path: Path) -> str:
    """MD5 hex digest of a file's content, for comparison with S3 etags."""
    digest = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


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
                # skip only when the content is verifiably identical: same
                # size AND the local md5 matches the stored etag (a simple
                # PUT's etag is the content md5). A multipart etag ("-" in
                # it) or any mismatch uploads, so an in-place change of the
                # same byte size still refreshes the object and its etag.
                try:
                    stat = self.client.stat_object(
                        bucket_name=bucket, object_name=object_name
                    )
                    if file_path.stat().st_size == stat.size and object_etag(
                        stat
                    ) == _file_md5(file_path):
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

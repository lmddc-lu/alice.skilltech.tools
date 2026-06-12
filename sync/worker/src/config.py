import os
from dataclasses import dataclass


@dataclass
class Config:
    rabbitmq_url: str
    minio_url: str
    minio_access_key: str
    minio_secret_key: str
    bucket_name: str
    max_retries: int = 3
    app_s3_namespace: str = "alice"
    haystack_stale_timeout: int = 900
    haystack_absolute_timeout: int = 86400
    # the worker claims one message at a time, a slow Moodle stalls it entirely
    moodle_request_timeout: int = 30
    # debounce so docling ticks don't flood rabbit and hammer the API db
    haystack_progress_pct_step: int = 5
    haystack_progress_max_interval_seconds: float = 30.0
    worker_metrics_port: int = 9100

    @classmethod
    def from_env(cls) -> "Config":
        required_vars = [
            "RABBITMQ_URL",
            "MINIO_URL",
            "MINIO_ACCESS_KEY",
            "MINIO_SECRET_KEY",
        ]
        missing = [var for var in required_vars if var not in os.environ]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        return cls(
            rabbitmq_url=os.environ["RABBITMQ_URL"],
            minio_url=os.environ["MINIO_URL"],
            minio_access_key=os.environ["MINIO_ACCESS_KEY"],
            minio_secret_key=os.environ["MINIO_SECRET_KEY"],
            bucket_name=os.environ.get("BUCKET_NAME", "echt"),
            max_retries=int(os.environ.get("MAX_RETRIES", "3")),
            haystack_stale_timeout=int(os.environ.get("HAYSTACK_STALE_TIMEOUT", "900")),
            haystack_absolute_timeout=int(
                os.environ.get("HAYSTACK_ABSOLUTE_TIMEOUT", "86400")
            ),
            moodle_request_timeout=int(os.environ.get("MOODLE_REQUEST_TIMEOUT", "30")),
            haystack_progress_pct_step=int(
                os.environ.get("HAYSTACK_PROGRESS_PCT_STEP", "5")
            ),
            haystack_progress_max_interval_seconds=float(
                os.environ.get("HAYSTACK_PROGRESS_MAX_INTERVAL_SECONDS", "30")
            ),
            worker_metrics_port=int(os.environ.get("WORKER_METRICS_PORT", "9100")),
        )

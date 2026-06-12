from enum import IntEnum, StrEnum


class SourceType(IntEnum):
    MOODLE = 1
    NEXTCLOUD = 2
    FILE = 3


class CourseSyncState(StrEnum):
    NOT_SYNCED = "not_synced"
    METADATA_SYNCED = "metadata_synced"
    CONTENT_SYNCING = "content_syncing"
    CONTENT_SYNCED = "content_synced"
    ERROR = "error"
    OUTDATED = "outdated"


class FileStatus(StrEnum):
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class ChatbotAccessLevel(StrEnum):
    PUBLIC = "public"
    PASSWORD = "password"  # requires password
    PRIVATE = "private"  # requires SSO login


class ChatbotPersonaType(StrEnum):
    TEACHER = "teacher"
    STUDYCOMPANION = "studycompanion"
    CUSTOM = "custom"


class KnowledgeBaseStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"


class DataSourceSyncStatus(StrEnum):
    READY = "ready"
    PROCESSING = "processing"
    ERROR = "error"


class ReindexFrequency(StrEnum):
    """Cadence options for a chatbot's scheduled reindex.

    Monthly is capped at day 28 to avoid month-length edge cases.
    """

    WEEKLY = "weekly"
    MONTHLY = "monthly"


class JobType(StrEnum):
    METADATA_SYNC = "metadata_sync"
    CONTENT_SYNC = "content_sync"
    INGESTION = "ingestion"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALLED = "stalled"


class JobFileState(StrEnum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    SKIPPED = "skipped"
    FAILED = "failed"


class JobFileErrorCode(StrEnum):
    """Stable machine-readable failure reason.

    Lets the UI pick a translated message without string-matching on
    ``error_message``. NULL when the worker can't classify the failure,
    UI falls back to ``error_message``. Codes are stage-specific so a
    failed file tells you where in the pipeline it died.

    Mirrored by JobFileErrorCode in sync/worker/src/worker.py; values are
    the wire protocol.
    """

    # ingestion succeeded but produced zero chunks (image-only PDF without
    # OCR, scanned page, empty doc)
    EMPTY_CONTENT = "empty_content"
    # worker could not fetch the file from object storage
    DOWNLOAD_FAILED = "download_failed"
    # H5P/SCORM preprocessing failed or produced no output
    PROCESSOR_FAILED = "processor_failed"
    # rag-pipeline reported failure or the call raised
    INGESTION_FAILED = "ingestion_failed"
    # rag-pipeline went stale or exceeded the absolute time budget
    INGESTION_TIMEOUT = "ingestion_timeout"


# terminal states for progress tallies
JOB_FILE_DONE_STATES = frozenset(
    {JobFileState.INGESTED.value, JobFileState.SKIPPED.value, JobFileState.FAILED.value}
)

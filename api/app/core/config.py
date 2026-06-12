import warnings
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AnyUrl,
    BeforeValidator,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_core import MultiHostUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",")]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    API_V2_STR: str = "/api/v2"

    APP_S3_NAMESPACE: str = "alice"

    SECRET_KEY: str
    FRONTEND_HOST: str = "http://localhost:4200"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    # container runs in UTC but schedules are stored as local wall-clock;
    # APScheduler's CronTrigger uses this zone (ZoneInfo handles DST).
    SCHEDULER_TIMEZONE: str = "Europe/Luxembourg"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    ENABLE_OAUTH_SIGNUP: bool = True
    OAUTH_MERGE_ACCOUNTS_BY_EMAIL: bool = False

    OPENID_PROVIDER_URL: str | None = None
    OAUTH_CLIENT_ID: str | None = None
    OAUTH_CLIENT_SECRET: str | None = None
    OAUTH_SCOPES: str = "openid email profile"

    OAUTH_PROVIDER_NAME: str = "OIDC"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def OAUTH_REDIRECT_URI(self) -> str:
        return f"{self.FRONTEND_HOST}/api/v2/oauth/callback"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return MultiHostUrl.build(  # type: ignore[return-value]
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)

        return self

    # job timeouts in minutes. running jobs are reaped after STALE_MINUTES
    # without progress, or ABSOLUTE_MINUTES total runtime (hard ceiling).
    JOB_RUNNING_STALE_MINUTES: int = 30
    JOB_RUNNING_ABSOLUTE_MINUTES: int = 360
    JOB_PENDING_TIMEOUT_MINUTES: int = 120
    # terminal jobs (and their job files/events) older than this are pruned
    # by the daily retention sweep. <= 0 disables the sweep.
    JOB_RETENTION_DAYS: int = 60

    HAYSTACK_INFERENCE_URL: str
    HAYSTACK_INGESTION_URL: str

    PII_FILTER_URL: str

    RABBITMQ_URL: str

    MINIO_URL: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET_NAME: str
    MINIO_REGION: str


settings = Settings()  # type: ignore

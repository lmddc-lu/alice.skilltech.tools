import json
import time
import uuid
from typing import Any

import redis
from loguru import logger


class RedisJobStore:
    """Redis-backed job store for async ingestion jobs."""

    KEY_PREFIX = "ingestion_job"

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", job_ttl: int = 3600
    ):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.job_ttl = job_ttl
        self._test_connection()

    def _test_connection(self):
        try:
            self.redis_client.ping()
            logger.info("RedisJobStore: connection established")
        except redis.ConnectionError as e:
            logger.error(f"RedisJobStore: connection failed: {e}")
            raise

    def _key(self, job_id: str) -> str:
        return f"{self.KEY_PREFIX}:{job_id}"

    def create_job(self, metadata: dict[str, Any] | None = None) -> str:
        job_id = str(uuid.uuid4())
        key = self._key(job_id)
        now = time.time()
        fields = {
            "job_id": job_id,
            "status": "pending",
            "stage": "",
            "progress_pct": "0",
            "created_at": str(now),
            "updated_at": str(now),
            "error": "",
            "result": "",
        }
        if metadata:
            fields["metadata"] = json.dumps(metadata)
        self.redis_client.hset(key, mapping=fields)
        self.redis_client.expire(key, self.job_ttl)
        logger.info(f"Job {job_id} created")
        return job_id

    def update_job(self, job_id: str, **fields) -> None:
        key = self._key(job_id)
        if not self.redis_client.exists(key):
            logger.warning(f"Job {job_id} not found for update")
            return
        updates = {"updated_at": str(time.time())}
        for k, v in fields.items():
            updates[k] = str(v) if v is not None else ""
        self.redis_client.hset(key, mapping=updates)
        self.redis_client.expire(key, self.job_ttl)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        key = self._key(job_id)
        data = self.redis_client.hgetall(key)
        if not data:
            return None
        created_at = float(data.get("created_at", 0))
        elapsed = round(time.time() - created_at, 1) if created_at else 0
        return {
            "job_id": data.get("job_id", job_id),
            "status": data.get("status", "unknown"),
            "stage": data.get("stage", ""),
            "progress_pct": int(data.get("progress_pct", 0)),
            "elapsed": elapsed,
            "error": data.get("error", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
        }

    def set_result(self, job_id: str, result: dict[str, Any]) -> None:
        key = self._key(job_id)
        self.redis_client.hset(
            key,
            mapping={
                "status": "completed",
                "stage": "completed",
                "progress_pct": "100",
                "result": json.dumps(result),
                "updated_at": str(time.time()),
            },
        )
        self.redis_client.expire(key, self.job_ttl)
        logger.info(f"Job {job_id} completed")

    def set_failed(self, job_id: str, error: str) -> None:
        key = self._key(job_id)
        self.redis_client.hset(
            key,
            mapping={
                "status": "failed",
                "stage": "failed",
                "error": error,
                "updated_at": str(time.time()),
            },
        )
        self.redis_client.expire(key, self.job_ttl)
        logger.error(f"Job {job_id} failed: {error}")

    def get_result(self, job_id: str) -> dict[str, Any] | None:
        key = self._key(job_id)
        data = self.redis_client.hgetall(key)
        if not data:
            return None
        result_str = data.get("result", "")
        if result_str:
            try:
                return json.loads(result_str)
            except json.JSONDecodeError:
                return None
        return None

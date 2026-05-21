import json
import uuid
from datetime import timedelta
from typing import Any

import redis
from loguru import logger


class RedisSessionManager:
    """Redis-backed session store for RAG sources."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        session_ttl: int = 3600,
    ):
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.session_ttl = session_ttl
        self._test_connection()

    def _test_connection(self):
        try:
            self.redis_client.ping()
            logger.info("Valkey connection established")
        except redis.ConnectionError as e:
            logger.error(f"Valkey connection failed: {e}")
            raise

    def create_session(
        self, sources: list[dict[str, Any]], session_id: str | None = None
    ) -> str:
        """Create a session and store sources. Generates a UUID if no id given."""
        if session_id is None:
            session_id = str(uuid.uuid4())

        key = f"rag_sources:{session_id}"

        try:
            self.redis_client.setex(
                key, timedelta(seconds=self.session_ttl), json.dumps(sources)
            )
            logger.debug(f"Created session {session_id} with {len(sources)} sources")
            return session_id

        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    def get_sources(self, session_id: str) -> list[dict[str, Any]] | None:
        """Retrieve sources by session id, or None if not found."""
        key = f"rag_sources:{session_id}"

        try:
            sources_json = self.redis_client.get(key)
            if sources_json:
                return json.loads(sources_json)
            return None

        except Exception as e:
            logger.error(f"Failed to retrieve sources for session {session_id}: {e}")
            return None

    def extend_session(self, session_id: str) -> bool:
        """Extend session TTL. Returns False if session not found."""
        key = f"rag_sources:{session_id}"

        try:
            return self.redis_client.expire(key, self.session_ttl)
        except Exception as e:
            logger.error(f"Failed to extend session {session_id}: {e}")
            return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns False if not found."""
        key = f"rag_sources:{session_id}"

        try:
            result = self.redis_client.delete(key)
            return result > 0
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def cleanup_expired_sessions(self) -> int:
        """Return active session count. Redis handles real expiry; this is for monitoring."""
        try:
            keys = self.redis_client.keys("rag_sources:*")
            return len(keys)
        except Exception as e:
            logger.error(f"Failed to count sessions: {e}")
            return 0

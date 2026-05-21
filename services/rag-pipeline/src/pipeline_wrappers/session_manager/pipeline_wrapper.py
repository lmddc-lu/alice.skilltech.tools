from typing import Any

from config import REDIS_URL, SESSION_STORAGE_ENABLED, SESSION_TTL
from hayhooks import BasePipelineWrapper
from loguru import logger
from RedisSessionManager import RedisSessionManager


class SessionManagementPipelineWrapper(BasePipelineWrapper):
    """Session management ops: get sources, extend, delete."""

    def setup(self) -> None:
        self.session_manager = None

        if SESSION_STORAGE_ENABLED:
            try:
                self.session_manager = RedisSessionManager(
                    redis_url=REDIS_URL, session_ttl=SESSION_TTL
                )
                logger.info("Session management pipeline initialized with Valkey")
            except Exception as e:
                logger.error(f"Failed to initialize Valkey session manager: {e}")
                logger.info("Session management disabled")
        else:
            logger.info("Session storage is disabled in configuration")

    def run_api(
        self,
        action: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Session management API.

        :param action: 'get_sources', 'extend', 'delete', 'list_sessions', or 'health'.
        """
        if not self.session_manager:
            return {
                "success": False,
                "error": "Session management is not available (Valkey not configured)",
                "session_storage_enabled": SESSION_STORAGE_ENABLED,
            }

        try:
            if action == "get_sources":
                return self._get_sources(session_id)
            elif action == "extend":
                return self._extend_session(session_id)
            elif action == "delete":
                return self._delete_session(session_id)
            elif action == "list_sessions":
                return self._list_sessions()
            elif action == "health":
                return self._health_check()
            else:
                return {
                    "success": False,
                    "error": f"Unknown action: {action}. Valid actions: get_sources, extend, delete, list_sessions, health",
                    "session_storage_enabled": SESSION_STORAGE_ENABLED,
                }
        except Exception as e:
            logger.error(f"Error in session management action '{action}': {e}")
            return {
                "success": False,
                "error": str(e),
                "action": action,
                "session_id": session_id,
                "session_storage_enabled": SESSION_STORAGE_ENABLED,
            }

    def _get_sources(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {
                "success": False,
                "error": "session_id is required for get_sources action",
                "sources": [],
            }

        try:
            sources = self.session_manager.get_sources(session_id)
            if sources is not None:
                logger.info(
                    f"Retrieved {len(sources)} sources for session {session_id}"
                )
                return {
                    "success": True,
                    "action": "get_sources",
                    "session_id": session_id,
                    "sources": sources,
                    "sources_count": len(sources),
                }
            else:
                return {
                    "success": False,
                    "action": "get_sources",
                    "error": "Session not found or expired",
                    "session_id": session_id,
                    "sources": [],
                }
        except Exception as e:
            logger.error(f"Error retrieving sources for session {session_id}: {e}")
            return {
                "success": False,
                "action": "get_sources",
                "error": str(e),
                "session_id": session_id,
                "sources": [],
            }

    def _extend_session(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {
                "success": False,
                "error": "session_id is required for extend action",
            }

        try:
            result = self.session_manager.extend_session(session_id)
            logger.info(f"Session {session_id} extend result: {result}")
            return {
                "success": result,
                "action": "extend",
                "session_id": session_id,
                "extended": result,
                "message": "Session TTL extended"
                if result
                else "Session not found or already expired",
            }
        except Exception as e:
            logger.error(f"Error extending session {session_id}: {e}")
            return {
                "success": False,
                "action": "extend",
                "error": str(e),
                "session_id": session_id,
            }

    def _delete_session(self, session_id: str) -> dict[str, Any]:
        if not session_id:
            return {
                "success": False,
                "error": "session_id is required for delete action",
            }

        try:
            result = self.session_manager.delete_session(session_id)
            logger.info(f"Session {session_id} delete result: {result}")
            return {
                "success": result,
                "action": "delete",
                "session_id": session_id,
                "deleted": result,
                "message": "Session deleted successfully"
                if result
                else "Session not found",
            }
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return {
                "success": False,
                "action": "delete",
                "error": str(e),
                "session_id": session_id,
            }

    def _list_sessions(self) -> dict[str, Any]:
        try:
            active_count = self.session_manager.cleanup_expired_sessions()
            return {
                "success": True,
                "action": "list_sessions",
                "active_sessions": active_count,
                "session_ttl": SESSION_TTL,
                "redis_url": REDIS_URL.split("@")[-1]
                if "@" in REDIS_URL
                else REDIS_URL,
            }
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return {"success": False, "action": "list_sessions", "error": str(e)}

    def _health_check(self) -> dict[str, Any]:
        try:
            self.session_manager._test_connection()
            return {
                "success": True,
                "action": "health",
                "status": "healthy",
                "redis_connected": True,
                "session_storage_enabled": SESSION_STORAGE_ENABLED,
                "session_ttl": SESSION_TTL,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "success": False,
                "action": "health",
                "status": "unhealthy",
                "redis_connected": False,
                "error": str(e),
                "session_storage_enabled": SESSION_STORAGE_ENABLED,
            }

    async def run_api_async(
        self,
        action: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.run_api(action, session_id)


PipelineWrapper = SessionManagementPipelineWrapper

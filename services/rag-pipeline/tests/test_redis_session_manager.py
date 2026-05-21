"""Unit tests for RedisSessionManager (with a mocked Redis client)."""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def manager_cls():
    # patch redis.from_url so __init__ doesn't connect
    redis_mod = sys.modules["redis"]
    mock_client = MagicMock()
    mock_client.ping.return_value = True
    redis_mod.from_url = MagicMock(return_value=mock_client)

    from RedisSessionManager import RedisSessionManager

    return RedisSessionManager, mock_client


class TestCreateSession:
    def test_generates_uuid_when_session_id_omitted(self, manager_cls):
        cls, _client = manager_cls
        manager = cls()
        sid = manager.create_session([{"content": "x"}])
        assert isinstance(sid, str) and len(sid) > 0

    def test_uses_provided_session_id(self, manager_cls):
        cls, _client = manager_cls
        manager = cls()
        sid = manager.create_session([{"content": "x"}], session_id="given-id")
        assert sid == "given-id"

    def test_calls_setex_with_json_payload(self, manager_cls):
        cls, client = manager_cls
        manager = cls(session_ttl=600)
        sources = [{"content": "hello", "score": 1.0}]

        manager.create_session(sources, session_id="abc")

        client.setex.assert_called_once()
        call = client.setex.call_args
        key = call.args[0]
        ttl = call.args[1]
        payload = call.args[2]
        assert key == "rag_sources:abc"
        assert ttl.total_seconds() == 600
        assert json.loads(payload) == sources

    def test_propagates_setex_failures(self, manager_cls):
        cls, client = manager_cls
        client.setex.side_effect = RuntimeError("disk full")
        manager = cls()
        with pytest.raises(RuntimeError, match="disk full"):
            manager.create_session([{"content": "x"}])


class TestGetSources:
    def test_returns_parsed_sources(self, manager_cls):
        cls, client = manager_cls
        client.get.return_value = '[{"content": "x"}]'
        manager = cls()

        sources = manager.get_sources("abc")

        client.get.assert_called_once_with("rag_sources:abc")
        assert sources == [{"content": "x"}]

    def test_returns_none_when_session_missing(self, manager_cls):
        cls, client = manager_cls
        client.get.return_value = None
        manager = cls()
        assert manager.get_sources("missing") is None

    def test_returns_none_on_redis_error(self, manager_cls):
        cls, client = manager_cls
        client.get.side_effect = RuntimeError("boom")
        manager = cls()
        assert manager.get_sources("abc") is None


class TestExtendAndDeleteSession:
    def test_extend_session_calls_expire(self, manager_cls):
        cls, client = manager_cls
        client.expire.return_value = True
        manager = cls(session_ttl=120)

        assert manager.extend_session("abc") is True
        client.expire.assert_called_once_with("rag_sources:abc", 120)

    def test_extend_session_returns_false_on_error(self, manager_cls):
        cls, client = manager_cls
        client.expire.side_effect = RuntimeError("nope")
        manager = cls()
        assert manager.extend_session("abc") is False

    def test_delete_session_returns_true_when_key_existed(self, manager_cls):
        cls, client = manager_cls
        client.delete.return_value = 1
        manager = cls()
        assert manager.delete_session("abc") is True

    def test_delete_session_returns_false_when_no_key(self, manager_cls):
        cls, client = manager_cls
        client.delete.return_value = 0
        manager = cls()
        assert manager.delete_session("abc") is False

    def test_delete_session_returns_false_on_error(self, manager_cls):
        cls, client = manager_cls
        client.delete.side_effect = RuntimeError("nope")
        manager = cls()
        assert manager.delete_session("abc") is False


class TestCleanupExpiredSessions:
    def test_returns_session_count(self, manager_cls):
        cls, client = manager_cls
        client.keys.return_value = ["rag_sources:a", "rag_sources:b"]
        manager = cls()
        assert manager.cleanup_expired_sessions() == 2

    def test_returns_zero_on_error(self, manager_cls):
        cls, client = manager_cls
        client.keys.side_effect = RuntimeError("nope")
        manager = cls()
        assert manager.cleanup_expired_sessions() == 0

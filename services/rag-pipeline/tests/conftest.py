"""Shared fixtures and import-time stubs for rag-pipeline tests.

rag-pipeline depends on heavy ML libraries (haystack, docling,
sentence-transformers, fastembed, qdrant). These unit tests exercise the
pure-python logic without those libraries installed, by registering stub
modules in sys.modules before the components under test are imported.

Tests that need real haystack/redis behaviour belong in tests/integration/.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock


def _ensure_module(name: str, attrs: dict[str, Any] | None = None) -> types.ModuleType:
    if name in sys.modules:
        module = sys.modules[name]
    else:
        module = types.ModuleType(name)
        sys.modules[name] = module

    if "." in name:
        parent_name, _, attr = name.rpartition(".")
        parent = _ensure_module(parent_name)
        setattr(parent, attr, module)

    for key, value in (attrs or {}).items():
        setattr(module, key, value)
    return module


def _identity_decorator(target=None, /, *args, **kwargs):
    # usable bare (@x) and with args (@x(...))
    if callable(target) and not args and not kwargs:
        return target

    def wrapper(func):
        return func

    return wrapper


# haystack stubs

# @component is used bare AND as @component.output_types(...)
component_stub = MagicMock()
component_stub.side_effect = lambda cls: cls
component_stub.output_types = lambda **kwargs: _identity_decorator


class _StubChatMessage:
    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content
        # haystack exposes .text alongside .content
        self.text = content

    @classmethod
    def from_system(cls, content: str) -> _StubChatMessage:
        return cls("system", content)

    @classmethod
    def from_user(cls, content: str) -> _StubChatMessage:
        return cls("user", content)

    @classmethod
    def from_assistant(cls, content: str) -> _StubChatMessage:
        return cls("assistant", content)

    def __repr__(self) -> str:  # pragma: no cover
        return f"StubChatMessage({self.role!r}, {self.content!r})"


class _StubDocument:
    def __init__(
        self,
        content: str = "",
        meta: dict[str, Any] | None = None,
        score: float | None = None,
        id: str | None = None,  # noqa: A002 - mirror haystack's API
    ):
        self.content = content
        self.meta = meta or {}
        self.score = score
        self.id = id


_ensure_module(
    "haystack",
    {
        "component": component_stub,
        "Document": _StubDocument,
    },
)
_ensure_module(
    "haystack.dataclasses", {"ChatMessage": _StubChatMessage, "Document": _StubDocument}
)


# docling stubs. The real packages pull in torch/transformers; tests only
# need the glue logic so permissive stubs are enough.


class _StubHybridChunker:
    """Default chunker stub. Tests that need real output patch
    DoclingChunker._chunker on the instance.
    """

    def __init__(self, tokenizer=None, max_tokens=None, merge_peers=True):
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.merge_peers = merge_peers

    def chunk(self, docling_doc):  # pragma: no cover
        return []

    def contextualize(self, chunk):  # pragma: no cover
        return getattr(chunk, "text", "")


class _StubDoclingDocument:
    pass


_ensure_module("docling")
_ensure_module("docling.chunking", {"HybridChunker": _StubHybridChunker})
_ensure_module("docling_core")
_ensure_module("docling_core.types", {"DoclingDocument": _StubDoclingDocument})


# loguru stub

_ensure_module("loguru", {"logger": MagicMock()})


# redis stub: just what RedisSessionManager uses


class _StubConnectionError(Exception):
    pass


_redis_stub = _ensure_module("redis")
_redis_stub.ConnectionError = _StubConnectionError  # type: ignore[attr-defined]
_redis_stub.from_url = MagicMock()  # type: ignore[attr-defined]


# dotenv stub

_ensure_module("dotenv", {"load_dotenv": lambda *args, **kwargs: None})


# re-exports so tests can build fixtures

StubDocument = _StubDocument
StubChatMessage = _StubChatMessage

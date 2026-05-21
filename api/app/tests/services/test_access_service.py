import pytest
from fastapi import HTTPException

from app.services.access_service import BCRYPT_MAX_PASSWORD_BYTES, AccessService


class TestAccessServicePassword:
    def test_hash_then_verify_roundtrip(self) -> None:
        hashed = AccessService.hash_password("hunter2")

        assert hashed != "hunter2"
        assert hashed.startswith("$2")
        assert AccessService.verify_password("hunter2", hashed) is True
        assert AccessService.verify_password("wrong", hashed) is False

    def test_verify_legacy_passlib_hash(self) -> None:
        # Pinned $2b$ hash from passlib 1.7.4 (pre bcrypt-direct rewrite).
        # Guards against algorithm/format drift that would invalidate
        # every existing chatbot password in the DB.
        legacy_hash = "$2b$12$dKoNlyn/olYUzYC8T5gB4eBrLlhK8S5yizzynQl6tCYnKLaLRNUSC"

        assert (
            AccessService.verify_password("correct-horse-battery-staple", legacy_hash)
            is True
        )
        assert AccessService.verify_password("nope", legacy_hash) is False

    def test_hash_password_rejects_oversize(self) -> None:
        oversize = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

        with pytest.raises(HTTPException) as exc_info:
            AccessService.hash_password(oversize)

        assert exc_info.value.status_code == 400

    def test_verify_password_oversize_returns_false(self) -> None:
        # oversize candidate must not crash bcrypt, just fails to match
        hashed = AccessService.hash_password("hunter2")
        oversize = "a" * (BCRYPT_MAX_PASSWORD_BYTES + 1)

        assert AccessService.verify_password(oversize, hashed) is False

    def test_verify_password_handles_malformed_hash(self) -> None:
        assert AccessService.verify_password("hunter2", "not-a-bcrypt-hash") is False

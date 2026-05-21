import logging
import secrets
from datetime import datetime, timedelta
from typing import Any

import jwt
from pytz import UTC

from app.core.config import settings

logger = logging.getLogger(__name__)

SESSION_SECRET = settings.SECRET_KEY
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE = timedelta(hours=1)
REFRESH_TOKEN_EXPIRE = timedelta(days=30)


def create_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a JWT token with the given data."""
    payload = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
        payload.update({"exp": expire})

    encoded_jwt = jwt.encode(payload, SESSION_SECRET, algorithm=ALGORITHM)
    return encoded_jwt


def create_access_token(user_id: str) -> str:
    return create_token(
        data={"id": user_id, "type": "access"},
        expires_delta=ACCESS_TOKEN_EXPIRE,
    )


def create_refresh_token(user_id: str) -> str:
    return create_token(
        data={"id": user_id, "type": "refresh"},
        expires_delta=REFRESH_TOKEN_EXPIRE,
    )


def decode_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT token. Returns None if invalid."""
    try:
        decoded = jwt.decode(token, SESSION_SECRET, algorithms=[ALGORITHM])
        return decoded
    except jwt.ExpiredSignatureError:
        logger.warning("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        return None
    except Exception as e:
        logger.error(f"Error decoding token: {e}")
        return None


def create_api_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"

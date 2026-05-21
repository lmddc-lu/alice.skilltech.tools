"""Access control service for ownership and permission checks."""

import bcrypt
from fastapi import HTTPException

from app.models.enums import ChatbotAccessLevel
from app.models.tables import Chatbot, User

# bcrypt block size limit
BCRYPT_MAX_PASSWORD_BYTES = 72


class AccessService:
    """Ownership verification and access control for chatbots."""

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"), hashed_password.encode("utf-8")
            )
        except ValueError:
            # malformed hash, or secret over the 72-byte limit
            return False

    @staticmethod
    def hash_password(password: str) -> str:
        secret = password.encode("utf-8")
        if len(secret) > BCRYPT_MAX_PASSWORD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes",
            )
        return bcrypt.hashpw(secret, bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_ownership(chatbot: Chatbot, user: User) -> None:
        """Raise 403 if the user doesn't own the chatbot."""
        if chatbot.owner_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to access this chatbot",
            )

    @staticmethod
    def verify_access(
        chatbot: Chatbot,
        user: User | None,
        password: str | None = None,
    ) -> None:
        """Raise 401/403 if access is denied for the chatbot's access level."""
        if user and chatbot.owner_id == user.id:
            return

        if chatbot.access_level == ChatbotAccessLevel.PRIVATE:
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required for private chatbots",
                )
            raise HTTPException(
                status_code=403,
                detail="You don't have access to this private chatbot",
            )

        elif chatbot.access_level == ChatbotAccessLevel.PASSWORD:
            if not chatbot.password_hash:
                raise HTTPException(
                    status_code=500,
                    detail="Chatbot is password-protected but no password is set",
                )
            if not password:
                raise HTTPException(
                    status_code=403,
                    detail="This chatbot requires a password",
                )
            if not AccessService.verify_password(password, chatbot.password_hash):
                raise HTTPException(
                    status_code=403,
                    detail="Incorrect chatbot password",
                )

    @staticmethod
    def check_can_chat(
        chatbot: Chatbot,
        user: User | None,
        password: str | None = None,
    ) -> None:
        """Like verify_access but tailored to chat. Raises 401/403 if denied."""
        if user and chatbot.owner_id == user.id:
            return

        if chatbot.access_level == ChatbotAccessLevel.PRIVATE:
            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication required for private chatbots",
                )
            raise HTTPException(
                status_code=403,
                detail="You don't have access to this private chatbot",
            )

        elif chatbot.access_level == ChatbotAccessLevel.PASSWORD:
            if chatbot.password_hash and password:
                if not AccessService.verify_password(password, chatbot.password_hash):
                    raise HTTPException(
                        status_code=403,
                        detail="Incorrect chatbot password",
                    )
            elif chatbot.password_hash and not password:
                raise HTTPException(
                    status_code=403,
                    detail="This chatbot requires a password",
                )

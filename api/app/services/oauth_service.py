import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import jwt
from fastapi import HTTPException

from app.core.config import settings

log = logging.getLogger(__name__)


class OAuthManager:
    """Manages OpenID Connect authentication flows."""

    def __init__(self) -> None:
        self.provider_url = settings.OPENID_PROVIDER_URL
        self.client_id = settings.OAUTH_CLIENT_ID
        self.client_secret = settings.OAUTH_CLIENT_SECRET
        self.redirect_uri = settings.OAUTH_REDIRECT_URI
        self.scopes = settings.OAUTH_SCOPES.split()

        self._metadata_cache: dict[str, Any] | None = None
        self._jwks_cache: dict[str, Any] | None = None
        self._cache_expires: datetime | None = None

    async def get_provider_metadata(self) -> dict[str, Any]:
        """Fetch and cache OIDC provider metadata."""
        if (
            self._metadata_cache
            and self._cache_expires is not None
            and self._cache_expires > datetime.now(UTC)
        ):
            return self._metadata_cache

        if not self.provider_url:
            raise HTTPException(
                status_code=500, detail="OpenID provider URL is not configured"
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.provider_url, timeout=10.0)
                response.raise_for_status()

                self._metadata_cache = cast(dict[str, Any], response.json())
                self._cache_expires = datetime.now(UTC) + timedelta(hours=1)

                log.info(f"Fetched OIDC metadata from {self.provider_url}")
                return self._metadata_cache

        except Exception as e:
            log.error(f"Failed to fetch OIDC metadata: {e}")
            raise HTTPException(
                status_code=500, detail="Failed to fetch OpenID Connect configuration"
            )

    async def get_jwks(self) -> dict[str, Any]:
        """Fetch and cache JWKS for token verification."""
        metadata = await self.get_provider_metadata()
        jwks_uri = metadata.get("jwks_uri")

        if not jwks_uri:
            raise HTTPException(
                status_code=500, detail="JWKS URI not found in provider metadata"
            )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(jwks_uri, timeout=10.0)
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

        except Exception as e:
            log.error(f"Failed to fetch JWKS: {e}")
            raise HTTPException(status_code=500, detail="Failed to fetch signing keys")

    def generate_state(self) -> str:
        """Random state parameter for CSRF protection."""
        return secrets.token_urlsafe(32)

    def generate_nonce(self) -> str:
        """Nonce for ID token validation."""
        return secrets.token_urlsafe(32)

    async def get_authorization_url(self, state: str, nonce: str) -> str:
        metadata = await self.get_provider_metadata()
        auth_endpoint = metadata.get("authorization_endpoint")

        if not auth_endpoint:
            raise HTTPException(
                status_code=500, detail="Authorization endpoint not found"
            )

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "redirect_uri": self.redirect_uri,
            "state": state,
            "nonce": nonce,
        }

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{auth_endpoint}?{query_string}"

    async def exchange_code_for_tokens(self, code: str) -> dict[str, Any]:
        metadata = await self.get_provider_metadata()
        token_endpoint = metadata.get("token_endpoint")

        if not token_endpoint:
            raise HTTPException(status_code=500, detail="Token endpoint not found")

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    token_endpoint,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=10.0,
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

        except Exception as e:
            log.error(f"Token exchange failed: {e}")
            raise HTTPException(
                status_code=400, detail="Failed to exchange authorization code"
            )

    async def verify_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        """Verify and decode the ID token."""
        try:
            unverified_header = jwt.get_unverified_header(id_token)
            kid = unverified_header.get("kid")

            if not kid:
                raise HTTPException(
                    status_code=400, detail="No key ID (kid) found in token header"
                )

            jwks = await self.get_jwks()
            signing_key = None

            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    signing_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

            if not signing_key:
                log.error(
                    f"Available key IDs in JWKS: {[k.get('kid') for k in jwks.get('keys', [])]}"
                )
                log.error(f"Looking for key ID: {kid}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Unable to find signing key with kid: {kid}",
                )

            decoded = jwt.decode(
                id_token,
                key=cast(Any, signing_key),
                algorithms=["RS256"],
                audience=self.client_id,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                },
            )

            if decoded.get("nonce") != nonce:
                raise HTTPException(status_code=400, detail="Invalid nonce in ID token")

            return decoded

        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=400, detail="ID token has expired")
        except jwt.InvalidTokenError as e:
            log.error(f"ID token verification failed: {e}")
            raise HTTPException(status_code=400, detail="Invalid ID token")

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch user info from the userinfo endpoint."""
        metadata = await self.get_provider_metadata()
        userinfo_endpoint = metadata.get("userinfo_endpoint")

        if not userinfo_endpoint:
            # caller falls back to ID token claims
            return {}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    userinfo_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10.0,
                )
                response.raise_for_status()
                return cast(dict[str, Any], response.json())

        except Exception as e:
            log.error(f"Failed to fetch userinfo: {e}")
            return {}

    async def get_logout_url(
        self, id_token: str, post_logout_redirect_uri: str | None = None
    ) -> str | None:
        """Get the logout URL for the OIDC provider."""
        metadata = await self.get_provider_metadata()
        end_session_endpoint = metadata.get("end_session_endpoint")

        if not end_session_endpoint:
            return None

        params = {"id_token_hint": id_token}
        if post_logout_redirect_uri:
            params["post_logout_redirect_uri"] = post_logout_redirect_uri

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{end_session_endpoint}?{query_string}"


oauth_manager = OAuthManager() if settings.OPENID_PROVIDER_URL else None

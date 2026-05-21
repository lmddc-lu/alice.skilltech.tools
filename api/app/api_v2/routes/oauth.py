import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.api_v2.deps import SessionDep, UserDep
from app.core.config import settings
from app.core.rate_limit import limiter
from app.models.tables import OAuthSession, User, UserBase
from app.repositories.user import UserRepository
from app.services.oauth_service import oauth_manager
from app.utils.auth import (
    ACCESS_TOKEN_EXPIRE,
    REFRESH_TOKEN_EXPIRE,
    create_access_token,
    create_refresh_token,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["oauth"])


@router.get("/oauth/user_info")
async def protected_route(user_info: UserDep) -> User:
    return user_info


@router.get("/oauth/login")
@limiter.limit("10/minute")
async def oauth_login(request: Request, session: SessionDep) -> RedirectResponse:
    """Initiate OAuth login flow."""

    if not oauth_manager:
        raise HTTPException(status_code=400, detail="OpenID Connect is not configured")

    state = oauth_manager.generate_state()
    nonce = oauth_manager.generate_nonce()

    oauth_session = OAuthSession(
        id=state,
        state=state,
        nonce=nonce,
        provider="oidc",
    )
    session.add(oauth_session)
    session.commit()

    auth_url = await oauth_manager.get_authorization_url(state, nonce)

    logger.info(f"Starting OAuth flow with state: {state}")
    return RedirectResponse(url=auth_url)


@router.get("/oauth/callback")
@limiter.limit("10/minute")
async def oauth_callback(
    request: Request,
    session: SessionDep,
    response: Response,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle OAuth callback from provider."""

    if not oauth_manager:
        raise HTTPException(status_code=400, detail="OpenID Connect is not configured")

    if error:
        logger.error(f"OAuth error: {error}")
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    oauth_session = session.get(OAuthSession, state)
    if not oauth_session or oauth_session.state != state or not oauth_session.nonce:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    user_repo = UserRepository(session)

    try:
        tokens = await oauth_manager.exchange_code_for_tokens(code)

        id_token = tokens.get("id_token")
        access_token = tokens.get("access_token")

        if not id_token or not access_token:
            raise HTTPException(
                status_code=400, detail="ID token or access token not received"
            )

        id_token_claims = await oauth_manager.verify_id_token(
            id_token, oauth_session.nonce
        )

        userinfo = await oauth_manager.get_userinfo(access_token)

        user_data = {**id_token_claims, **userinfo}

        email = user_data.get("email")
        name = user_data.get("name") or user_data.get("preferred_username") or email
        provider_user_id = user_data.get("sub")

        if not email or not provider_user_id:
            raise HTTPException(
                status_code=400,
                detail="Required user information not provided by OAuth provider",
            )

        user = user_repo.get_by_email(email.lower())

        if not user:
            if not settings.ENABLE_OAUTH_SIGNUP:
                raise HTTPException(status_code=403, detail="OAuth signup is disabled")

            user_create = UserBase(
                email=email.lower(),
                is_active=True,
            )

            # first user becomes admin
            existing_users = user_repo.get_multi(skip=0, limit=2)
            if len(existing_users) == 0:
                user_create.role = "admin"

            user = user_repo.create_user(
                user_create=user_create,
                provider_id=provider_user_id,
            )

            logger.info(f"Created new user via OAuth: {email}")

        oauth_session.user_id = user.id
        oauth_session.provider_user_id = provider_user_id
        oauth_session.email = email
        oauth_session.name = name
        oauth_session.expires_at = datetime.now(UTC) + timedelta(
            seconds=tokens.get("expires_in", 3600)
        )

        user_repo.update(user, {"name": name})

        session.commit()

        access_token_jwt = create_access_token(str(user.id))
        refresh_token_jwt = create_refresh_token(str(user.id))

        is_secure = settings.ENVIRONMENT != "local"

        response = RedirectResponse(url=f"{settings.FRONTEND_HOST}/dashboard")

        response.set_cookie(
            key="token",
            value=access_token_jwt,
            expires=datetime.now(UTC) + ACCESS_TOKEN_EXPIRE,
            httponly=True,
            secure=is_secure,
            samesite="lax",
        )

        response.set_cookie(
            key="refresh_token",
            value=refresh_token_jwt,
            expires=datetime.now(UTC) + REFRESH_TOKEN_EXPIRE,
            httponly=True,
            secure=is_secure,
            samesite="lax",
            path="/api/v2/oauth/refresh",
        )

        response.set_cookie(
            key="oauth_id_token",
            value=id_token,
            httponly=True,
            secure=is_secure,
            samesite="lax",
        )

        logger.info(f"OAuth login successful for user: {email}")
        return response

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=400, detail="OAuth authentication failed")


@router.post("/oauth/refresh")
@limiter.limit("30/minute")
async def oauth_refresh(request: Request, session: SessionDep) -> Response:
    """Exchange a valid refresh token for a new access token."""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")

    from app.utils.auth import decode_token as _decode

    data = _decode(refresh_token)
    if not data or data.get("type") != "refresh" or "id" not in data:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_repo = UserRepository(session)
    from uuid import UUID

    user = user_repo.get(UUID(data["id"]))
    if not user or not user_repo.is_active(user):
        raise HTTPException(status_code=401, detail="User not found or inactive")

    new_access = create_access_token(str(user.id))
    is_secure = settings.ENVIRONMENT != "local"

    response = Response(status_code=204)
    response.set_cookie(
        key="token",
        value=new_access,
        expires=datetime.now(UTC) + ACCESS_TOKEN_EXPIRE,
        httponly=True,
        secure=is_secure,
        samesite="lax",
    )
    return response


@router.get("/oauth/logout")
async def oauth_logout(request: Request, response: Response) -> Response:
    """Logout from OAuth provider."""

    if not oauth_manager:
        response = RedirectResponse(url=settings.FRONTEND_HOST)
        response.delete_cookie("token")
        response.delete_cookie("refresh_token", path="/api/v2/oauth/refresh")
        response.delete_cookie("oauth_id_token")
        return response

    id_token = request.cookies.get("oauth_id_token")

    response = RedirectResponse(url=settings.FRONTEND_HOST)
    response.delete_cookie("token")
    response.delete_cookie("refresh_token", path="/api/v2/oauth/refresh")
    response.delete_cookie("oauth_id_token")
    response.delete_cookie("oauth_session_id")

    if id_token:
        try:
            logout_url = await oauth_manager.get_logout_url(
                id_token, post_logout_redirect_uri=settings.FRONTEND_HOST
            )
            if logout_url:
                return RedirectResponse(url=logout_url)
        except Exception as e:
            logger.error(f"Error getting logout URL: {e}")

    return response

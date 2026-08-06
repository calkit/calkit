"""Routes related to authentication."""

import logging
import secrets
from datetime import timedelta
from typing import Annotated, Any

import jwt
import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy import delete
from sqlmodel import select

from app import mixpanel, security, users
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.config import settings
from app.core import utcnow
from app.github import token_resp_text_to_dict
from app.messaging import generate_reset_password_email, send_email
from app.models import (
    DeviceAuth,
    Message,
    NewPassword,
    RefreshToken,
    RefreshTokenRequest,
    Token,
    User,
    UserCreate,
    UserPublic,
)
from app.security import (
    generate_password_reset_token,
    generate_refresh_token,
    get_password_hash,
    hash_refresh_token,
    verify_password_reset_token,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()

# Access token TTL from settings; refresh token lasts 90 days
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
REFRESH_TOKEN_EXPIRE_DAYS = 90
# On rotation, the old refresh token isn't killed instantly; it keeps working
# for this grace window so an interrupted rotation (the browser reloaded before
# storing the new token, or a second tab raced the refresh) can retry with it
# and get a fresh pair instead of the session dying.
REFRESH_ROTATION_GRACE_SECONDS = 60


def _make_tokens(
    user_id, description: str | None = None
) -> tuple[str, str, RefreshToken]:
    """Create a paired short-lived access token and long-lived refresh token."""
    access_token = security.create_access_token(
        subject=user_id,
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    raw_refresh = generate_refresh_token()
    token_hash = hash_refresh_token(raw_refresh)
    refresh_db = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires=utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        description=description,
    )
    return access_token, raw_refresh, refresh_db


@router.post("/login/access-token")
def login_access_token(
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    """Get an access token for future requests."""
    user = users.authenticate(
        session=session, email=form_data.username, password=form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=400, detail="Incorrect email or password"
        )
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    access_token, raw_refresh, refresh_db = _make_tokens(
        user.id, description="password login"
    )
    session.add(refresh_db)
    session.commit()
    return Token(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh,
    )


@router.post("/login/test-token")
def test_token(current_user: CurrentUser) -> UserPublic:
    """Test access token."""
    return current_user  # type: ignore


@router.post("/login/refresh")
def refresh_access_token(
    session: SessionDep,
    body: RefreshTokenRequest,
) -> Token:
    """Exchange a refresh token for a new access token and a rotated refresh
    token.

    The old token is rotated out but still honored for a short grace window
    (REFRESH_ROTATION_GRACE_SECONDS) so an interrupted rotation, e.g. the client
    reloaded before storing the new token, doesn't strand the session.
    """
    token_hash = hash_refresh_token(body.refresh_token)
    refresh_db = session.exec(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .with_for_update()
    ).first()
    if refresh_db is None or not refresh_db.is_active:
        raise HTTPException(401, "Invalid refresh token")
    if refresh_db.expired:
        raise HTTPException(401, "Refresh token has expired")

    user = session.get(User, refresh_db.user_id)
    if user is None or not user.is_active:
        # Disable the refresh token if the user is missing/inactive.
        refresh_db.is_active = False
        session.add(refresh_db)
        session.commit()
        raise HTTPException(401, "User is not active")

    # Rotate, but with a short grace window instead of deactivating instantly:
    # shorten the old token's expiry to now + grace (only the first time, so it
    # can't be kept alive forever by repeated use). A retry with it during the
    # window still succeeds and mints a fresh pair, so an interrupted rotation
    # doesn't strand the client with a dead token.
    grace_deadline = utcnow() + timedelta(
        seconds=REFRESH_ROTATION_GRACE_SECONDS
    )
    if refresh_db.expires > grace_deadline:
        refresh_db.expires = grace_deadline
    session.add(refresh_db)
    # Issue new pair
    access_token, raw_refresh, new_refresh_db = _make_tokens(
        user.id, description=refresh_db.description
    )
    session.add(new_refresh_db)
    session.commit()
    return Token(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh,
    )


@router.post("/password-recovery/{email}")
def recover_password(email: str, session: SessionDep) -> Message:
    user = users.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this email does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )
    send_email(
        email_to=user.email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Password recovery email sent")


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """Reset password."""
    email = verify_password_reset_token(token=body.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
    user = users.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="A user with this email does not exist in the system.",
        )
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    hashed_password = get_password_hash(password=body.new_password)
    user.hashed_password = hashed_password
    session.add(user)
    session.commit()
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """Get HTML content for password recovery."""
    user = users.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="A user with this username does not exist in the system.",
        )
    password_reset_token = generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )
    return HTMLResponse(
        content=email_data.html_content,
        headers={"subject:": email_data.subject},
    )


class OAuthCodeExchange(BaseModel):
    code: str
    redirect_uri: str


@router.post("/login/github")
def login_with_github(req: OAuthCodeExchange, session: SessionDep) -> Token:
    """Log in a user from GitHub authentication, creating a new account if
    necessary.

    The response from GitHub, after parsing into a dictionary, will look
    something like:

    ```
        {'access_token': '...',
        'expires_in': '28800',
        'refresh_token': '...',
        'refresh_token_expires_in': '15897600',
        'scope': '',
        'token_type': 'bearer'}
    ```
    """
    code = req.code
    logger.info("Requesting GitHub access token")
    resp = requests.get(
        "https://github.com/login/oauth/access_token",
        params=dict(
            code=code,
            client_id=settings.GH_CLIENT_ID,
            client_secret=settings.GH_CLIENT_SECRET,
        ),
    )
    # Make sure we got a 200 response, and if so, use the token to fetch
    # user details
    if not resp.status_code == 200:
        raise HTTPException(400, "GitHub authentication failed")
    out = token_resp_text_to_dict(resp.text)
    if "access_token" not in out:
        raise HTTPException(
            400, f"GitHub authentication failed: {out['error']}"
        )
    logger.info(f"Data from GitHub has keys: {list(out.keys())}")
    # Get user information from GitHub
    logger.info("Requesting GitHub user")
    gh_user = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {out['access_token']}"},
    ).json()
    github_username = gh_user["login"]
    github_email = gh_user["email"]
    logger.info(
        f"Received GitHub user {github_username} with email: {github_email}"
    )
    if github_email is None:
        logger.info("Looking up private GitHub email")
        github_email = requests.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {out['access_token']}"},
        ).json()[0]["email"]
        logger.info(f"Found GitHub email: {github_email}")
    if settings.ENVIRONMENT == "staging" and github_username not in [
        "petebachant",
        "pbachant",
        "abachant",
    ]:
        logger.warning(
            f"GitHub user {github_username} attempting to log in on staging"
        )
        raise HTTPException(403, "Please log in at calkit.io")
    # First check to find user based on their GitHub username
    user = users.get_user_by_github_username(
        session=session, github_username=github_username
    )
    if user is None:
        logger.info("Creating new user")
        user = users.create_user(
            session=session,
            user_create=UserCreate(
                email=github_email,
                full_name=gh_user["name"],
                github_username=github_username,
                # Generate random password for this user, which they can reset
                # later
                password=secrets.token_urlsafe(16),
            ),
        )
        mixpanel.user_signed_up(user)
    else:
        logger.info(f"Found existing user with email: {user.email}")
    if user.github_username != github_username:
        logger.info("GitHub usernames do not match")
        # Check that GitHub username matches, else fail
        raise HTTPException(400, "GitHub usernames do not match")
    if not user.is_active:
        logger.info("User is not active")
        raise HTTPException(401, "User is not active")
    # Save the user's GitHub token for later
    users.save_github_token(session=session, user=user, github_resp=out)
    # Lastly, generate an access token for this user
    mixpanel.user_logged_in(user)
    access_token, raw_refresh, refresh_db = _make_tokens(
        user.id, description="GitHub login"
    )
    session.add(refresh_db)
    session.commit()
    return Token(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh,
    )


@router.post("/login/google")
def login_with_google(req: OAuthCodeExchange, session: SessionDep) -> Token:
    """Log in (or sign up) a user via Google.

    New users created this way are GitHub-less (no linked GitHub account); they
    can connect GitHub later. Mirrors ``login_with_github`` but resolves the
    account by verified Google email.
    """
    logger.info("Requesting Google access token")
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data=dict(
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            grant_type="authorization_code",
            code=req.code,
            redirect_uri=req.redirect_uri,
        ),
    )
    if resp.status_code != 200:
        try:
            msg = resp.json().get(
                "error_description", "Google authentication failed"
            )
        except Exception:
            msg = "Google authentication failed"
        logger.error(f"Google auth failed: {msg}")
        raise HTTPException(400, msg)
    google_resp = resp.json()
    userinfo = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {google_resp['access_token']}"},
    )
    if userinfo.status_code != 200:
        raise HTTPException(400, "Could not fetch your Google profile")
    profile = userinfo.json()
    email = profile.get("email")
    if not email or not profile.get("email_verified"):
        raise HTTPException(400, "A verified Google email is required")
    full_name = profile.get("name")
    user = users.get_user_by_email(session=session, email=email)
    if user is None:
        if settings.ENVIRONMENT == "staging":
            logger.warning(
                f"Google user {email} attempting to sign up on staging"
            )
            raise HTTPException(403, "Please log in at calkit.io")
        logger.info("Creating new GitHub-less user via Google")
        try:
            user = users.create_user(
                session=session,
                user_create=UserCreate(
                    email=email,
                    full_name=full_name,
                    password=secrets.token_urlsafe(16),
                ),
            )
        except HTTPException as e:
            # The email-derived account name may be taken or reserved; retry
            # once with a random suffix so signup still succeeds.
            if e.status_code != 422:
                raise
            user = users.create_user(
                session=session,
                user_create=UserCreate(
                    email=email,
                    full_name=full_name,
                    password=secrets.token_urlsafe(16),
                    account_name=f"{email.split('@')[0]}-{secrets.token_hex(3)}",
                ),
            )
        mixpanel.user_signed_up(user)
    else:
        logger.info(f"Found existing user with email: {user.email}")
    if not user.is_active:
        raise HTTPException(401, "User is not active")
    # Persist the Google credential so the account shows as connected.
    users.save_google_token(
        session=session, user=user, google_resp=google_resp
    )
    mixpanel.user_logged_in(user)
    access_token, raw_refresh, refresh_db = _make_tokens(
        user.id, description="Google login"
    )
    session.add(refresh_db)
    session.commit()
    return Token(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh,
    )


@router.post("/login/github-oidc")
def login_with_github_oidc(
    session: SessionDep,
    authorization: str | None = Header(default=None),
) -> Token:
    """Authenticate using an OIDC token from GitHub Actions or Codespaces.

    This endpoint validates the OIDC token from GitHub Actions or GitHub
    Codespaces and returns a Calkit access token. The OIDC token's claims
    are verified to ensure it's from a trusted repository.

    The token must be provided in the Authorization header as: "Bearer <token>"

    For GitHub Actions, the token should be obtained using:

    ```yaml
    permissions:
      id-token: write
    ```

    For GitHub Codespaces, the token is available via the
    ACTIONS_ID_TOKEN_REQUEST_URL environment variable.
    """
    # Extract token from Authorization header
    if not authorization:
        raise HTTPException(
            400, "Authorization header with Bearer token is required"
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(400, "Authorization header must use Bearer scheme")
    token = authorization[7:]  # Remove "Bearer " prefix
    if not token:
        raise HTTPException(400, "OIDC token cannot be empty")
    logger.info("Validating GitHub OIDC token")
    # Supported GitHub OIDC token issuers
    github_actions_issuer = "https://token.actions.githubusercontent.com"
    github_codespaces_issuer = "https://vstoken.actions.githubusercontent.com"
    try:
        # First, decode without verification to get the header and claims
        unverified_header = jwt.get_unverified_header(token)
        unverified_claims = jwt.decode(
            token, options={"verify_signature": False}
        )
        issuer = unverified_claims.get("iss")
        logger.info(f"OIDC token issuer: {issuer}")
        logger.info(f"OIDC token subject: {unverified_claims.get('sub')}")
        logger.info(
            f"OIDC token repository: {unverified_claims.get('repository')}"
        )
        # Verify the issuer is from GitHub Actions or Codespaces
        if issuer not in [github_actions_issuer, github_codespaces_issuer]:
            raise HTTPException(400, "Invalid OIDC token issuer")
        # Determine if this is from Actions or Codespaces
        is_codespace = issuer == github_codespaces_issuer
        source = "Codespace" if is_codespace else "GitHub Actions"
        logger.info(f"Authenticating from {source}")
        # Get GitHub's OIDC JWKS (JSON Web Key Set) to verify the signature
        jwks_url = f"{issuer}/.well-known/jwks"
        jwks_response = requests.get(jwks_url)
        if jwks_response.status_code != 200:
            raise HTTPException(500, "Failed to fetch GitHub JWKS")
        jwks = jwks_response.json()
        # Find the key matching the token's kid (key ID)
        kid = unverified_header.get("kid")
        signing_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                signing_key = key
                break
        if not signing_key:
            raise HTTPException(400, "Unable to find signing key")
        # Convert JWK to PEM format for PyJWT
        public_key = RSAAlgorithm.from_jwk(signing_key)
        # Verify and decode the token with signature validation
        # Use the domain as the audience
        claims = jwt.decode(
            token,
            key=public_key,  # type: ignore
            algorithms=["RS256"],
            audience=settings.DOMAIN,
            issuer=issuer,
        )
        logger.info(
            f"Successfully validated OIDC token for repository: "
            f"{claims.get('repository')}"
        )
        # Extract repository information
        repository = claims.get("repository")  # e.g., "owner/repo"
        repository_owner = claims.get("repository_owner")
        # Log Codespace-specific information if available
        if is_codespace:
            codespace_name = unverified_claims.get("codespace_name")
            logger.info(f"Codespace name: {codespace_name}")
        if not repository:
            raise HTTPException(400, "Repository claim not found in token")
        # The person who triggered the workflow run. Works for both user-owned
        # and org-owned repositories.
        github_username = claims.get("actor")
        if not github_username:
            raise HTTPException(400, "No actor in token")
        logger.info(
            f"Looking up user for GitHub username: {github_username} "
            f"(repository: {repository}, owner: {repository_owner})"
        )
        # Find the user by GitHub username
        user = users.get_user_by_github_username(
            session=session, github_username=github_username
        )
        if not user:
            logger.warning(
                f"No user found for GitHub username: {github_username}"
            )
            raise HTTPException(
                404,
                f"No user associated with GitHub account: {github_username}",
            )
        # Bind the actor to the repo the token was minted in. ``actor`` is
        # merely whoever triggered the run, so a workflow in *someone else's*
        # repo (e.g. an issue_comment or watch trigger, which run with
        # actor=whoever-interacted) could otherwise mint a token carrying a
        # victim's actor and be replayed here to log in as them. Require the
        # repository owner to be the actor's own namespace or a Calkit org they
        # belong to, so the run had to occur in a repo the user controls.
        owner = (repository_owner or "").lower()
        allowed_owners = {github_username.lower()}
        for membership in user.org_memberships:
            org_github_name = membership.org.account.github_name
            if org_github_name:
                allowed_owners.add(org_github_name.lower())
        if owner not in allowed_owners:
            logger.warning(
                f"OIDC actor {github_username} is not authorized for "
                f"repository owner {repository_owner}"
            )
            raise HTTPException(
                403,
                "The OIDC token's repository owner does not match the "
                "authenticated GitHub user or an organization they belong to.",
            )
        if not user.is_active:
            logger.info(f"User {user.email} is not active")
            raise HTTPException(401, "User is not active")
        # Generate access token with different expiration based on source
        if is_codespace:
            # Longer expiration for interactive Codespace sessions
            access_token_expires = timedelta(hours=8)
            logger.info(
                f"Generating 8-hour access token for {user.email} "
                f"from Codespace"
            )
        else:
            # Shorter expiration for CI/CD workflows
            access_token_expires = timedelta(minutes=60)
            workflow = claims.get("workflow")
            logger.info(
                f"Generating 1-hour access token for {user.email} "
                f"from workflow: {workflow}"
            )
        return Token(
            access_token=security.create_access_token(
                subject=user.id,
                expires_delta=access_token_expires,
            )
        )
    except InvalidTokenError as e:
        logger.error(f"JWT validation error: {str(e)}")
        raise HTTPException(400, f"Invalid OIDC token: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating OIDC token: {str(e)}")
        raise HTTPException(500, f"Failed to validate OIDC token: {str(e)}")


@router.post("/login/github-token")
def login_with_github_token(
    session: SessionDep,
    authorization: str | None = Header(default=None),
) -> Token:
    """Authenticate using a GitHub token, e.g., from a Codespace."""
    # Extract token from Authorization header
    if not authorization:
        raise HTTPException(
            400, "Authorization header with Bearer token is required"
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(400, "Authorization header must use Bearer scheme")
    token = authorization[7:]  # Remove "Bearer " prefix
    if not token:
        raise HTTPException(400, "OIDC token cannot be empty")
    response = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.status_code == 200:
        raise HTTPException(401, "Failed to authenticate with GitHub")
    user_data = response.json()
    github_username = user_data.get("login")
    if not github_username:
        raise HTTPException(400, "No username found in token")
    # Find the user by GitHub username
    user = users.get_user_by_github_username(
        session=session, github_username=github_username
    )
    if not user:
        logger.warning(f"No user found for GitHub username: {github_username}")
        raise HTTPException(
            404,
            f"No user associated with GitHub account: {github_username}",
        )
    if not user.is_active:
        logger.info(f"User {user.email} is not active")
        raise HTTPException(401, "User is not active")
    access_token_expires = timedelta(hours=24)
    logger.info(f"Generating 24-hour access token for {user.email}")
    return Token(
        access_token=security.create_access_token(
            subject=user.id,
            expires_delta=access_token_expires,
        )
    )


# Device authorization flow (RFC 8628-inspired)
CLI_AUTH_EXPIRES_MINUTES = 15
CLI_AUTH_POLL_INTERVAL_SECONDS = 5


class DeviceAuthRequest(BaseModel):
    hostname: str | None = None


class DeviceAuthResponse(BaseModel):
    device_code: str
    verification_uri: str
    expires_in: int
    interval: int


class DeviceTokenRequest(BaseModel):
    device_code: str


class DeviceTokenPendingResponse(BaseModel):
    detail: str


class DeviceAuthorizeRequest(BaseModel):
    device_code: str


@router.post("/login/device")
def post_login_device(
    session: SessionDep,
    req: DeviceAuthRequest | None = None,
) -> DeviceAuthResponse:
    """Initiate a CLI device authorization flow.

    The CLI calls this endpoint, which returns a device_code and a URL for
    the user to visit in their browser to authorize the CLI. The CLI then
    polls ``/login/device/token`` with the device_code to receive the access
    token once the user has authorized it.
    """
    if req is None:
        req = DeviceAuthRequest()
    device_code = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(minutes=CLI_AUTH_EXPIRES_MINUTES)
    # Clean up expired auth requests with a single bulk delete
    session.exec(delete(DeviceAuth).where(DeviceAuth.expires < utcnow()))  # type: ignore
    auth_request = DeviceAuth(
        device_code=device_code,
        expires=expires,
        hostname=req.hostname,
    )
    session.add(auth_request)
    session.commit()
    verification_uri = (
        f"{settings.frontend_host}/login/device?device_code={device_code}"
    )
    return DeviceAuthResponse(
        device_code=device_code,
        verification_uri=verification_uri,
        expires_in=CLI_AUTH_EXPIRES_MINUTES * 60,
        interval=CLI_AUTH_POLL_INTERVAL_SECONDS,
    )


@router.post("/login/device/authorize")
def post_login_device_authorize(
    session: SessionDep,
    current_user: CurrentUser,
    req: DeviceAuthorizeRequest,
) -> Message:
    """Authorize a pending CLI device auth request.

    The user must be authenticated. This endpoint is called by the frontend
    after the user has logged in and clicked "Authorize".
    """
    auth_request = session.exec(
        select(DeviceAuth).where(DeviceAuth.device_code == req.device_code)
    ).first()
    if auth_request is None:
        raise HTTPException(404, "Device code not found")
    if auth_request.expired:
        raise HTTPException(400, "Device code has expired")
    if auth_request.user_id is not None:
        raise HTTPException(400, "Device code already authorized")
    auth_request.user_id = current_user.id
    session.add(auth_request)
    session.commit()
    logger.info(
        f"User {current_user.email} authorized CLI device code "
        f"(hostname: {auth_request.hostname})"
    )
    return Message(message="CLI access authorized")


@router.post(
    "/login/device/token",
    responses={202: {"model": DeviceTokenPendingResponse}},
)
def post_login_device_token(
    session: SessionDep,
    req: DeviceTokenRequest,
    response: Response,
) -> Token | DeviceTokenPendingResponse:
    """Poll for a CLI access token after device authorization.

    The CLI calls this endpoint repeatedly until it receives a token or
    the request expires. Returns 202 while authorization is still pending.
    """
    auth_request = session.exec(
        select(DeviceAuth)
        .where(DeviceAuth.device_code == req.device_code)
        .with_for_update()
    ).first()
    if auth_request is None:
        raise HTTPException(404, "Device code not found")
    if auth_request.expired:
        raise HTTPException(400, "Device code has expired")
    if auth_request.user_id is None:
        response.status_code = 202
        return DeviceTokenPendingResponse(
            detail="Authorization pending",
        )
    # Authorization confirmed — issue short-lived access + refresh token pair
    user_id = auth_request.user_id
    hostname = auth_request.hostname
    description = "CLI login"
    if hostname:
        description = f"CLI login from {hostname}"
    access_token, raw_refresh, refresh_db = _make_tokens(
        user_id, description=description
    )
    session.add(refresh_db)
    session.delete(auth_request)
    session.commit()
    return Token(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        refresh_token=raw_refresh,
    )

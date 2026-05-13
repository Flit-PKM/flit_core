from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from limiter import limiter
from turnstile import TurnstileVerificationError, verify_turnstile_token
from schemas.user import UserCreate, UserRead, UserLogin, GoogleIdTokenLogin, Token
from service.revoked_jwt import revoke_jti
from service.user import create_user, get_user_by_email, touch_last_login
from auth.password import get_password_hash, verify_password
from auth.username_from_email import derive_username_from_email
from auth.google_id_token import verify_google_login_id_token
from jose import jwt as jose_jwt

from auth.jwt import create_access_token, decode_login_token_claims
from config import settings
from logging_config import get_logger
from models.user import User

logger = get_logger(__name__)

bearer_scheme = HTTPBearer()

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> User:
    """Authenticate a user by email and password.
    
    Args:
        db: Database session
        email: User email
        password: Plain text password
        
    Returns:
        User object if authentication succeeds
        
    Raises:
        HTTPException: If authentication fails
    """
    user = await get_user_by_email(db, email)
    if not user:
        logger.warning(f"Login failed - user not found: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.password_hash is None:
        logger.warning(f"Login failed - password login not available for OAuth-only user: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(password, user.password_hash):
        logger.warning(f"Login failed - invalid password for user: {email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def create_login_response(user: User) -> dict:
    """Create a login response with access token.
    
    Args:
        user: Authenticated user
        
    Returns:
        Dictionary with access_token and token_type
    """
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    user: UserCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """Register a new user."""
    logger.info(f"Registration attempt for email: {user.email}")

    # Turnstile verification when TURNSTILE_SECRET is set
    if settings.TURNSTILE_SECRET:
        client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
        if client_ip and "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host
        try:
            await verify_turnstile_token(user.cf_turnstile_response, client_ip)
        except TurnstileVerificationError as exc:
            logger.warning("Turnstile verification failed for registration %s: %s", user.email, exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Human verification failed. Please try again.",
            )

    # Check if user already exists
    existing_user = await get_user_by_email(db, user.email)
    if existing_user:
        logger.warning(f"Registration failed - email already exists: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Generate username from email if not provided
    if not user.username:
        user.username = derive_username_from_email(user.email)
        logger.debug(f"Auto-generated username: {user.username}")

    # Hash the password
    hashed_password = get_password_hash(user.password)

    # Create user with hashed password
    user_data = user.model_dump()
    user_data["password_hash"] = hashed_password
    user_data.pop("password")  # Remove plain password
    user_data.pop("cf_turnstile_response", None)  # Not a user column

    # Create the user
    db_user = await create_user(db, user_data)
    logger.info(f"User registered successfully: {db_user.id} - {db_user.email} - {db_user.username}")
    return db_user


@router.post("/login", response_model=Token)
@limiter.limit("30/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_session),
):
    """Login and get access token."""
    logger.info(f"Login attempt for email: {form_data.username}")

    # Get user by email
    user = await get_user_by_email(db, form_data.username)
    if not user:
        logger.warning(f"Login failed - user not found: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.password_hash is None:
        logger.warning(
            "Login failed - password login not available for OAuth-only user: %s",
            form_data.username,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        logger.warning(f"Login failed - invalid password for user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    await touch_last_login(db, user.id)

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    logger.info(f"User logged in successfully: {user.id} - {user.email}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login-json", response_model=Token)
@limiter.limit("30/minute")
async def login_json(
    request: Request,
    user_credentials: UserLogin,
    db: AsyncSession = Depends(get_async_session),
):
    """Login with JSON payload (alternative to OAuth2 form)."""
    logger.info(f"JSON login attempt for email: {user_credentials.email}")
    
    user = await authenticate_user(db, user_credentials.email, user_credentials.password)
    await touch_last_login(db, user.id)
    logger.info(f"User logged in successfully via JSON: {user.id} - {user.email}")

    return create_login_response(user)


@router.post("/login-google", response_model=Token)
@limiter.limit("30/minute")
async def login_google(
    request: Request,
    body: GoogleIdTokenLogin,
    db: AsyncSession = Depends(get_async_session),
):
    """Sign in or register using a Google ID token (Sign In With Google)."""
    client_id = (settings.GOOGLE_OAUTH_CLIENT_ID or "").strip()
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Sign-In is not configured on this server",
        )

    try:
        claims = verify_google_login_id_token(body.id_token, client_id)
    except ValueError as exc:
        logger.warning("Google ID token rejected: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google credentials",
        ) from exc

    email = claims["email"].lower().strip()
    user = await get_user_by_email(db, email)

    if user:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Inactive user",
            )
    else:
        user_data = {
            "email": email,
            "username": derive_username_from_email(email),
            "password_hash": None,
            "is_active": True,
            "is_verified": bool(claims.get("email_verified")),
        }
        user = await create_user(db, user_data)
        logger.info("User registered via Google Sign-In: %s - %s", user.id, user.email)

    await touch_last_login(db, user.id)
    logger.info("User logged in via Google: %s - %s", user.id, user.email)
    return create_login_response(user)


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_async_session),
):
    """Revoke the current login JWT server-side (jti denylist) until expiry."""
    token = credentials.credentials
    payload = decode_login_token_claims(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw = jose_jwt.get_unverified_claims(token)
    jti = raw.get("jti") or payload.get("jti")
    exp = payload.get("exp")
    if not jti or exp is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing jti or exp",
            headers={"WWW-Authenticate": "Bearer"},
        )
    exp_dt = datetime.fromtimestamp(int(float(exp)), tz=timezone.utc)
    await revoke_jti(db, str(jti), exp_dt)
    return {"status": "logged_out"}
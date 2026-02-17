from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session
from turnstile import TurnstileVerificationError, verify_turnstile_token
from schemas.user import UserCreate, UserRead, UserLogin, Token
from service.user import create_user, get_user_by_email
from auth.password import get_password_hash, verify_password
from auth.jwt import create_access_token
from config import settings
from logging_config import get_logger
from models.user import User

logger = get_logger(__name__)

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
        import re
        
        # Extract local part of email (before @)
        email_local = user.email.split('@')[0]
        
        # Sanitize: remove invalid characters, keep only alphanumeric and common chars
        username = re.sub(r'[^a-zA-Z0-9_-]', '', email_local)
        
        # Ensure minimum length (if too short, use email local part with numbers)
        if len(username) < 3:
            username = email_local[:47] + "123"  # Ensure min 3 chars, max 50
        
        # Truncate to max length
        username = username[:50]
        
        user.username = username
        logger.debug(f"Auto-generated username: {username}")

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
async def login(
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

    # Verify password
    if not verify_password(form_data.password, user.password_hash):
        logger.warning(f"Login failed - invalid password for user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    logger.info(f"User logged in successfully: {user.id} - {user.email}")
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/login-json", response_model=Token)
async def login_json(
    user_credentials: UserLogin,
    db: AsyncSession = Depends(get_async_session),
):
    """Login with JSON payload (alternative to OAuth2 form)."""
    logger.info(f"JSON login attempt for email: {user_credentials.email}")
    
    user = await authenticate_user(db, user_credentials.email, user_credentials.password)
    logger.info(f"User logged in successfully via JSON: {user.id} - {user.email}")
    
    return create_login_response(user)
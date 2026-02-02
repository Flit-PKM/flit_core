from passlib.hash import pbkdf2_sha256
import logging

logger = logging.getLogger(__name__)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    try:
        result = pbkdf2_sha256.verify(plain_password, hashed_password)
        return result
    except Exception as e:
        logger.error("Password verification failed", exc_info=True)
        raise


def get_password_hash(password: str) -> str:
    """Hash a password using pbkdf2_sha256."""
    try:
        result = pbkdf2_sha256.hash(password)
        return result
    except Exception as e:
        logger.error("Password hashing failed", exc_info=True)
        raise
"""Custom exception hierarchy for the application."""

from typing import Optional


class BaseAppException(Exception):
    """Base exception for all application exceptions."""
    
    def __init__(self, message: str, detail: Optional[str] = None):
        self.message = message
        self.detail = detail or message
        super().__init__(self.message)


class NotFoundError(BaseAppException):
    """Raised when a requested resource is not found."""
    pass


class ValidationError(BaseAppException):
    """Raised when input validation fails."""
    pass


class AuthenticationError(BaseAppException):
    """Raised when authentication fails."""
    pass


class AuthorizationError(BaseAppException):
    """Raised when authorization fails (user lacks permission)."""
    pass


class ConflictError(BaseAppException):
    """Raised when a resource conflict occurs (e.g., duplicate entry)."""
    pass


class BusinessLogicError(BaseAppException):
    """Raised when business logic validation fails."""
    pass

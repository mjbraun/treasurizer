# ABOUTME: Custom exception hierarchy for Treasurizer
# ABOUTME: Provides structured error handling for PayHOA operations


class TreasurizerError(Exception):
    """Base exception for all Treasurizer errors."""


class AuthenticationError(TreasurizerError):
    """Failed to authenticate with PayHOA."""


class SessionExpiredError(AuthenticationError):
    """Session token expired, re-auth needed."""


class CredentialsNotFoundError(AuthenticationError):
    """Credentials not found in environment or 1Password."""


class TransactionNotFoundError(TreasurizerError):
    """Transaction ID doesn't exist."""


class AccountNotFoundError(TreasurizerError):
    """Account ID doesn't exist."""


class ValidationError(TreasurizerError):
    """Invalid input provided to a tool."""


class APIError(TreasurizerError):
    """Unexpected error from PayHOA API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(TreasurizerError):
    """Too many requests to PayHOA API."""

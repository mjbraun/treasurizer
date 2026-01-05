# ABOUTME: PayHOA client management with caching and retry logic
# ABOUTME: Provides thread-safe client factory for tools

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

from treasurizer.auth import PayHOASession, clear_session
from treasurizer.exceptions import AuthenticationError, SessionExpiredError

logger = logging.getLogger(__name__)

# Module-level client cache with lock for thread safety
_session: PayHOASession | None = None
_session_lock = asyncio.Lock()

F = TypeVar("F", bound=Callable[..., Any])


async def get_client() -> PayHOASession:
    """
    Get or create an authenticated PayHOA session.

    Thread-safe singleton pattern - creates session on first call,
    returns cached session on subsequent calls.

    Returns:
        Authenticated PayHOASession instance
    """
    global _session

    async with _session_lock:
        if _session is None:
            logger.info("Creating new PayHOA session")
            _session = PayHOASession()
            await _session.ensure_authenticated()
        return _session


async def invalidate_client() -> None:
    """
    Invalidate the cached client (e.g., on auth failure).

    Clears both in-memory cache and persisted session.
    """
    global _session

    async with _session_lock:
        if _session:
            await _session.close()
            _session = None
        clear_session()
        logger.info("Invalidated PayHOA session")


def _is_auth_error(exc: Exception) -> bool:
    """
    Check if an exception indicates an authentication failure.

    Args:
        exc: The exception to check

    Returns:
        True if this looks like an auth error
    """
    if isinstance(exc, (AuthenticationError, SessionExpiredError)):
        return True

    # Check for HTTP 401/403 responses
    # TODO: Add checks for PayHOA-specific error responses
    error_str = str(exc).lower()
    return any(
        indicator in error_str
        for indicator in ["401", "403", "unauthorized", "session expired", "not authenticated"]
    )


def with_auth_retry(func: F) -> F:
    """
    Decorator that retries on authentication failures.

    If a function fails with an auth error, this will:
    1. Invalidate the current session
    2. Retry the function once with a fresh session

    Usage:
        @with_auth_retry
        async def my_tool_function(...):
            client = await get_client()
            # ... use client
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            if _is_auth_error(exc):
                logger.warning(f"Auth error in {func.__name__}, retrying with fresh session")
                await invalidate_client()
                return await func(*args, **kwargs)
            raise

    return wrapper  # type: ignore

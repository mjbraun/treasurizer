# ABOUTME: Authentication module for PayHOA
# ABOUTME: Handles login, session management, and credential retrieval

import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

import httpx

from treasurizer.exceptions import AuthenticationError, CredentialsNotFoundError

logger = logging.getLogger(__name__)

# Session storage location
SESSION_DIR = Path.home() / ".treasurizer"
SESSION_FILE = SESSION_DIR / "session.json"


def get_credentials_from_1password() -> tuple[str, str]:
    """
    Retrieve PayHOA credentials from 1Password CLI.

    Returns:
        Tuple of (username, password)

    Raises:
        CredentialsNotFoundError: If credentials cannot be retrieved
    """
    try:
        username = subprocess.run(
            ["op", "read", "op://Private/app.payhoa.com/username"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        password = subprocess.run(
            ["op", "read", "op://Private/app.payhoa.com/password"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        return username, password
    except subprocess.CalledProcessError as e:
        raise CredentialsNotFoundError(
            f"Failed to retrieve credentials from 1Password: {e.stderr}"
        ) from e
    except FileNotFoundError:
        raise CredentialsNotFoundError(
            "1Password CLI (op) not found. Install it or set PAYHOA_EMAIL/PAYHOA_PASSWORD env vars."
        )


def get_credentials() -> tuple[str, str]:
    """
    Get PayHOA credentials from environment or 1Password.

    Environment variables take precedence:
      - PAYHOA_EMAIL
      - PAYHOA_PASSWORD

    Falls back to 1Password CLI if env vars not set.

    Returns:
        Tuple of (email, password)

    Raises:
        CredentialsNotFoundError: If credentials cannot be found
    """
    email = os.environ.get("PAYHOA_EMAIL")
    password = os.environ.get("PAYHOA_PASSWORD")

    if email and password:
        logger.debug("Using credentials from environment variables")
        return email, password

    logger.debug("Attempting to retrieve credentials from 1Password")
    return get_credentials_from_1password()


def load_session() -> dict | None:
    """
    Load saved session from disk.

    Returns:
        Session data dict or None if not found/invalid
    """
    if not SESSION_FILE.exists():
        return None

    try:
        with open(SESSION_FILE) as f:
            session = json.load(f)
        logger.debug("Loaded existing session from disk")
        return session
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load session file: {e}")
        return None


def save_session(session: dict) -> None:
    """
    Save session data to disk.

    Args:
        session: Session data to persist
    """
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.chmod(0o600) if SESSION_FILE.exists() else None

    with open(SESSION_FILE, "w") as f:
        json.dump(session, f)

    SESSION_FILE.chmod(0o600)
    logger.debug("Saved session to disk")


def clear_session() -> None:
    """Remove saved session from disk."""
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        logger.debug("Cleared session from disk")


class PayHOASession:
    """
    Manages an authenticated session with PayHOA.

    This is a placeholder that will be implemented once we
    understand PayHOA's authentication flow via traffic inspection.
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._session_data: dict | None = None

    async def login(self) -> None:
        """
        Authenticate with PayHOA.

        TODO: Implement once we understand the auth flow via mitmproxy.
        """
        email, password = get_credentials()

        # TODO: Implement actual login flow
        # This will involve:
        # 1. GET login page to get CSRF token
        # 2. POST credentials
        # 3. Handle any 2FA if needed
        # 4. Extract session cookies/tokens

        raise NotImplementedError(
            "PayHOA login not yet implemented. "
            "We need to discover their API via traffic inspection first."
        )

    async def is_valid(self) -> bool:
        """
        Check if the current session is still valid.

        Returns:
            True if session is valid, False otherwise
        """
        if not self._session_data:
            return False

        # TODO: Implement session validation
        # Likely involves making a lightweight API call
        return False

    async def ensure_authenticated(self) -> None:
        """
        Ensure we have a valid authenticated session.

        Loads cached session if available, otherwise performs login.
        """
        # Try loading existing session
        self._session_data = load_session()

        if self._session_data and await self.is_valid():
            logger.info("Using cached session")
            return

        # Need fresh login
        logger.info("Performing fresh login to PayHOA")
        await self.login()
        save_session(self._session_data or {})

    @property
    def client(self) -> httpx.AsyncClient:
        """Get the authenticated HTTP client."""
        if not self._client:
            self._client = httpx.AsyncClient(
                base_url="https://app.payhoa.com",
                follow_redirects=True,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

# ABOUTME: Authentication module for PayHOA
# ABOUTME: Handles login via HTTP API, session management, and API access

import base64
import json
import logging
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any

import httpx

from treasurizer.exceptions import AuthenticationError, CredentialsNotFoundError

logger = logging.getLogger(__name__)

# Session storage location
SESSION_DIR = Path.home() / ".treasurizer"
SESSION_FILE = SESSION_DIR / "session.json"

# PayHOA API base URL
API_BASE_URL = "https://core.payhoa.com"
APP_URL = "https://app.payhoa.com"

# Required headers for API calls
LEGFI_SITE_ID = "2"


def get_credentials_from_1password() -> tuple[str, str]:
    """Retrieve PayHOA credentials from 1Password CLI."""
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
    """Get PayHOA credentials from environment or 1Password."""
    email = os.environ.get("PAYHOA_EMAIL")
    password = os.environ.get("PAYHOA_PASSWORD")

    if email and password:
        logger.debug("Using credentials from environment variables")
        return email, password

    logger.debug("Attempting to retrieve credentials from 1Password")
    return get_credentials_from_1password()


def load_session() -> dict | None:
    """Load saved session from disk."""
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
    """Save session data to disk with restricted permissions."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)

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

    Uses direct HTTP API login to obtain JWT token for API access.
    """

    def __init__(self, org_id: int | None = None) -> None:
        self._client: httpx.AsyncClient | None = None
        self._session_data: dict | None = None
        self._org_id: int | None = org_id

    @property
    def org_id(self) -> int:
        """Get the organization ID for API calls."""
        if self._org_id:
            return self._org_id
        if self._session_data and "org_id" in self._session_data:
            return self._session_data["org_id"]
        raise AuthenticationError("Organization ID not available - login first")

    def _decode_jwt(self, token: str) -> dict:
        """Decode JWT payload without verification."""
        payload_b64 = token.split(".")[1]
        # Add padding if needed
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))

    async def login(self) -> None:
        """
        Authenticate with PayHOA via HTTP API.

        First obtains a CSRF token, then posts credentials to get a JWT token.
        Preserves session cookies for subsequent API calls.
        """
        email, password = get_credentials()

        logger.info("Logging in to PayHOA...")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # First, get the CSRF token by making a request that sets the cookie
            init_response = await client.get(
                f"{API_BASE_URL}/sanctum/csrf-cookie",
                headers={
                    "Accept": "application/json",
                    "Origin": APP_URL,
                    "Referer": f"{APP_URL}/",
                },
            )

            # Extract XSRF-TOKEN from cookies (it's URL-encoded)
            xsrf_token = None
            for cookie in client.cookies.jar:
                if cookie.name == "XSRF-TOKEN":
                    xsrf_token = urllib.parse.unquote(cookie.value)
                    break

            if not xsrf_token:
                raise AuthenticationError("Failed to obtain CSRF token")

            # Now login with the CSRF token
            response = await client.post(
                f"{API_BASE_URL}/login",
                json={"email": email, "password": password, "siteId": 2},
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "x-legfi-site-id": LEGFI_SITE_ID,
                    "x-xsrf-token": xsrf_token,
                    "Origin": APP_URL,
                    "Referer": f"{APP_URL}/",
                },
            )

            if response.status_code != 200:
                raise AuthenticationError(
                    f"Login failed with status {response.status_code}: {response.text}"
                )

            data = response.json()
            jwt_token = data.get("token")

            if not jwt_token:
                raise AuthenticationError("Login response did not contain a token")

            # Extract cookies from the client (they were updated by the login response)
            cookies = {}
            for cookie in client.cookies.jar:
                if "payhoa" in cookie.domain:
                    cookies[cookie.name] = cookie.value

        # Extract org_id from JWT payload
        org_id = None
        try:
            payload = self._decode_jwt(jwt_token)
            org_id = payload.get("legfi", {}).get("orgId")
        except Exception as e:
            logger.warning(f"Failed to decode JWT: {e}")

        self._session_data = {
            "jwt_token": jwt_token,
            "cookies": cookies,
            "org_id": org_id,
        }

        if org_id:
            self._org_id = org_id

        logger.info(f"Successfully logged in to PayHOA (org_id: {org_id})")

    async def is_valid(self) -> bool:
        """Check if the current session is still valid."""
        if not self._session_data or not self._session_data.get("jwt_token"):
            return False

        # Try a lightweight API call to verify
        try:
            client = self._get_client()
            response = await client.get(f"/organizations/{self.org_id}?with=preferences")
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"Session validation failed: {e}")
            return False

    async def ensure_authenticated(self) -> None:
        """Ensure we have a valid authenticated session."""
        # Try loading existing session
        self._session_data = load_session()

        if self._session_data:
            self._org_id = self._session_data.get("org_id")
            if await self.is_valid():
                logger.info("Using cached session")
                return

        # Need fresh login
        logger.info("Cached session invalid, performing fresh login")
        await self.login()
        save_session(self._session_data or {})

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the authenticated HTTP client."""
        if self._client is None:
            if not self._session_data:
                raise AuthenticationError("Not authenticated - call ensure_authenticated() first")

            jwt_token = self._session_data.get("jwt_token", "")
            cookies = self._session_data.get("cookies", {})

            self._client = httpx.AsyncClient(
                base_url=API_BASE_URL,
                follow_redirects=True,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "x-legfi-site-id": LEGFI_SITE_ID,
                    "Accept": "application/json",
                    "Origin": APP_URL,
                    "Referer": f"{APP_URL}/",
                },
                cookies=cookies,
            )
        return self._client

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make an authenticated GET request."""
        client = self._get_client()
        # Prepend org_id to path if it starts with /
        if path.startswith("/") and not path.startswith("/organizations"):
            path = f"/organizations/{self.org_id}{path}"
        return await client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make an authenticated POST request."""
        client = self._get_client()
        if path.startswith("/") and not path.startswith("/organizations"):
            path = f"/organizations/{self.org_id}{path}"
        return await client.post(path, **kwargs)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

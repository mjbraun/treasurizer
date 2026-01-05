# ABOUTME: Authentication module for PayHOA
# ABOUTME: Handles login via Playwright, session management, and API access

import asyncio
import json
import logging
import os
import subprocess
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

    Uses Playwright to automate browser login and extract JWT token
    and cookies for API access.
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

    async def login(self) -> None:
        """
        Authenticate with PayHOA using Playwright browser automation.

        Opens a browser, navigates to login page, enters credentials,
        and captures the JWT token and cookies.
        """
        from playwright.async_api import async_playwright

        email, password = get_credentials()

        logger.info("Starting browser login to PayHOA...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            # Navigate to login
            await page.goto(f"{APP_URL}/login")

            # Wait for login form
            await page.wait_for_selector('input[type="email"], input[name="email"]')

            # Fill credentials
            await page.fill('input[type="email"], input[name="email"]', email)
            await page.fill('input[type="password"], input[name="password"]', password)

            # Submit
            await page.click('button[type="submit"]')

            # Wait for navigation to dashboard (indicates successful login)
            try:
                await page.wait_for_url("**/dashboard**", timeout=30000)
            except Exception:
                # Try waiting for any authenticated page
                await page.wait_for_selector('[class*="dashboard"], [class*="nav"]', timeout=30000)

            # Extract JWT from localStorage or from an API request
            jwt_token = None

            # Try to capture JWT from a network request
            async def capture_jwt(route):
                nonlocal jwt_token
                request = route.request
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    jwt_token = auth_header[7:]
                await route.continue_()

            await context.route("**/core.payhoa.com/**", capture_jwt)

            # Trigger an API call to capture the token
            await page.goto(f"{APP_URL}/dashboard")
            await asyncio.sleep(2)  # Wait for API calls

            # Get cookies
            cookies = await context.cookies()

            # Extract org_id from JWT if we got one
            org_id = None
            if jwt_token:
                try:
                    import base64
                    # Decode JWT payload (middle part)
                    payload_b64 = jwt_token.split(".")[1]
                    # Add padding if needed
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    org_id = payload.get("legfi", {}).get("orgId")
                except Exception as e:
                    logger.warning(f"Failed to decode JWT: {e}")

            await browser.close()

        if not jwt_token:
            raise AuthenticationError("Failed to capture JWT token during login")

        self._session_data = {
            "jwt_token": jwt_token,
            "cookies": {c["name"]: c["value"] for c in cookies if "payhoa" in c.get("domain", "")},
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

# ABOUTME: Pytest fixtures for Treasurizer tests
# ABOUTME: Provides mock PayHOA session fixture

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def mock_payhoa_session():
    """Create a mock PayHOA session with canned responses."""
    session = MagicMock()
    session.is_valid = AsyncMock(return_value=True)
    session.ensure_authenticated = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_get_client(mock_payhoa_session):
    """Create an async factory that returns the mock session."""

    async def _get_client():
        return mock_payhoa_session

    return _get_client

# ABOUTME: Pytest fixtures for Treasurizer tests
# ABOUTME: Provides mock PayHOA session and MCP server fixtures

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP

from treasurizer.server import create_server


@pytest.fixture
def mock_payhoa_session():
    """Create a mock PayHOA session with canned responses."""
    session = MagicMock()
    session.is_valid = AsyncMock(return_value=True)
    session.ensure_authenticated = AsyncMock()
    session.close = AsyncMock()

    # TODO: Add mock API responses as we discover the API structure
    # session.get_bank_accounts = AsyncMock(return_value=[...])
    # session.get_ledger_accounts = AsyncMock(return_value=[...])
    # session.get_transactions = AsyncMock(return_value=[...])

    return session


@pytest.fixture
def mock_get_client(mock_payhoa_session):
    """Create an async factory that returns the mock session."""

    async def _get_client():
        return mock_payhoa_session

    return _get_client


@pytest.fixture
def mcp_server(mock_get_client):
    """Create an MCP server with all tools registered."""
    # Use the real server factory
    mcp = create_server()

    # TODO: Once tools are implemented, we can inject the mock client
    # For now, just return the server as-is

    return mcp

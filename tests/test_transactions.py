# ABOUTME: Tests for transaction mutation tools
# ABOUTME: Covers update_transaction payload construction and field filtering

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from treasurizer.tools.transactions import update_transaction


@pytest.mark.asyncio
async def test_update_transaction_sends_all_fields(mock_payhoa_session, mock_get_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_payhoa_session.patch = AsyncMock(return_value=mock_response)

    with patch("treasurizer.tools.transactions.get_client", mock_get_client):
        result = await update_transaction(
            transaction_id=123,
            category_id=854774,
            memo="Hallway repair",
            approved=True,
        )

    mock_payhoa_session.patch.assert_called_once_with(
        "/transactions/123",
        json={"categoryId": 854774, "memo": "Hallway repair", "approved": True},
    )
    assert result["updated"] is True
    assert result["transaction_id"] == 123


@pytest.mark.asyncio
async def test_update_transaction_omits_none_fields(mock_payhoa_session, mock_get_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_payhoa_session.patch = AsyncMock(return_value=mock_response)

    with patch("treasurizer.tools.transactions.get_client", mock_get_client):
        await update_transaction(transaction_id=456, memo="Just a memo")

    mock_payhoa_session.patch.assert_called_once_with(
        "/transactions/456",
        json={"memo": "Just a memo"},
    )


@pytest.mark.asyncio
async def test_update_transaction_approve_only(mock_payhoa_session, mock_get_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_payhoa_session.patch = AsyncMock(return_value=mock_response)

    with patch("treasurizer.tools.transactions.get_client", mock_get_client):
        result = await update_transaction(transaction_id=789, approved=True)

    mock_payhoa_session.patch.assert_called_once_with(
        "/transactions/789",
        json={"approved": True},
    )
    assert result["updated"] is True

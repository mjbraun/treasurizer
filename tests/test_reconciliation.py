# ABOUTME: Tests for reconciliation helper tools
# ABOUTME: Covers unmatched-deposit detection and per-unit audit

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from treasurizer.tools.reconciliation import find_unmatched_deposits

# Amounts in cents; originalAmount negative = credit (money in)
TRANSACTIONS_PAGE_1 = {
    "data": [
        {
            "id": 1,
            "transactionDate": "2025-04-07T00:00:00Z",
            "amount": 100000,
            "originalAmount": -100000,
            "description": "DEPOSIT ID NUMBER 331291",
            "categoryId": None,
        },
        {
            "id": 2,
            "transactionDate": "2025-03-10T00:00:00Z",
            "amount": 100000,
            "originalAmount": -100000,
            "description": "CREDIT / DEPOSIT",
            "categoryId": 854772,
        },
        {
            "id": 3,
            "transactionDate": "2025-05-07T00:00:00Z",
            "amount": 99805,
            "originalAmount": -99805,
            "description": "PayHOA Deposit",
            "categoryId": None,
        },
        {
            "id": 4,
            "transactionDate": "2025-04-14T00:00:00Z",
            "amount": 112683,
            "originalAmount": 112683,
            "description": "ORIG CO NAME:PEOPLES GAS",
            "categoryId": 854780,
        },
    ],
    "last_page": 1,
}

PAYMENT_GROUPS_PAGE_1 = {
    "data": [
        {
            "id": 101,
            "payorId": 523336,
            "net": 100000,
            "gross": 100000,
            "paymentMethodType": "OfflineCheck",
            "createdAt": "2025-04-07T12:00:00.000000Z",
        },
        {
            "id": 102,
            "payorId": 523335,
            "net": 99805,
            "gross": 100000,
            "paymentMethodType": "StripeBankAccount",
            "createdAt": "2025-05-07T12:00:00.000000Z",
        },
    ],
    "meta": {"lastPage": 1},
}


@pytest.mark.asyncio
async def test_find_unmatched_deposits_returns_deposits_without_pg(
    mock_payhoa_session, mock_get_client
):
    """Bank deposits with no matching payment-group should be returned."""
    empty_txns = {"data": [], "last_page": 1}
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}
    txn_mock = MagicMock()
    txn_mock.json = MagicMock(return_value=TRANSACTIONS_PAGE_1)
    empty_txn_mock = MagicMock()
    empty_txn_mock.json = MagicMock(return_value=empty_txns)
    pg_mock = MagicMock()
    pg_mock.json = MagicMock(return_value=PAYMENT_GROUPS_PAGE_1)
    empty_pg_mock = MagicMock()
    empty_pg_mock.json = MagicMock(return_value=empty_pgs)

    # Endpoint dispatch based on URL
    async def fake_get(url, params=None):
        if "transactions" in url:
            page = (params or {}).get("page", 1)
            return txn_mock if page == 1 else empty_txn_mock
        if "payment-groups" in url:
            page = (params or {}).get("page", 1)
            return pg_mock if page == 1 else empty_pg_mock
        raise AssertionError(f"unexpected url {url}")

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)

    with patch("treasurizer.tools.reconciliation.get_client", mock_get_client):
        unmatched = await find_unmatched_deposits()

    # Transaction 1 (April 7) matches PG 101 (same date, $1000)
    # Transaction 3 (May 7) matches PG 102 (same date, $998.05 net)
    # Transaction 2 (March 10) has no PG match -> unmatched
    # Transaction 4 is a debit (gas bill), not a deposit -> skipped
    assert len(unmatched) == 1
    assert unmatched[0]["id"] == 2
    assert unmatched[0]["amount"] == 1000.00
    assert unmatched[0]["date"] == "2025-03-10"


@pytest.mark.asyncio
async def test_find_unmatched_deposits_date_tolerance(mock_payhoa_session, mock_get_client):
    """A PG within +/-3 days of a bank deposit should match."""
    txns = {
        "data": [
            {
                "id": 10,
                "transactionDate": "2025-06-05T00:00:00Z",
                "amount": 100000,
                "originalAmount": -100000,
                "description": "CREDIT / DEPOSIT",
                "categoryId": 854772,
            },
        ],
        "last_page": 1,
    }
    # PG 3 days earlier -- should still match
    pgs = {
        "data": [
            {
                "id": 201,
                "payorId": 523336,
                "net": 100000,
                "gross": 100000,
                "paymentMethodType": "OfflineCheck",
                "createdAt": "2025-06-02T12:00:00.000000Z",
            },
        ],
        "meta": {"lastPage": 1},
    }
    empty_txns = {"data": [], "last_page": 1}
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}
    txn_mock = MagicMock()
    txn_mock.json = MagicMock(return_value=txns)
    empty_txn_mock = MagicMock()
    empty_txn_mock.json = MagicMock(return_value=empty_txns)
    pg_mock = MagicMock()
    pg_mock.json = MagicMock(return_value=pgs)
    empty_pg_mock = MagicMock()
    empty_pg_mock.json = MagicMock(return_value=empty_pgs)

    async def fake_get(url, params=None):
        if "transactions" in url:
            return txn_mock if (params or {}).get("page", 1) == 1 else empty_txn_mock
        if "payment-groups" in url:
            return pg_mock if (params or {}).get("page", 1) == 1 else empty_pg_mock
        raise AssertionError(url)

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)
    with patch("treasurizer.tools.reconciliation.get_client", mock_get_client):
        unmatched = await find_unmatched_deposits()
    assert unmatched == []


@pytest.mark.asyncio
async def test_find_unmatched_deposits_excludes_withdrawals(mock_payhoa_session, mock_get_client):
    """Debit transactions (money out) must not appear in results."""
    txns = {
        "data": [
            {
                "id": 20,
                "transactionDate": "2025-04-14T00:00:00Z",
                "amount": 112683,
                "originalAmount": 112683,
                "description": "ORIG CO NAME:PEOPLES GAS",
                "categoryId": 854780,
            },
        ],
        "last_page": 1,
    }
    empty_txns = {"data": [], "last_page": 1}
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}
    txn_mock = MagicMock()
    txn_mock.json = MagicMock(return_value=txns)
    empty_txn_mock = MagicMock()
    empty_txn_mock.json = MagicMock(return_value=empty_txns)
    empty_pg_mock = MagicMock()
    empty_pg_mock.json = MagicMock(return_value=empty_pgs)

    async def fake_get(url, params=None):
        if "transactions" in url:
            return txn_mock if (params or {}).get("page", 1) == 1 else empty_txn_mock
        return empty_pg_mock

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)
    with patch("treasurizer.tools.reconciliation.get_client", mock_get_client):
        unmatched = await find_unmatched_deposits()
    assert unmatched == []


@pytest.mark.asyncio
async def test_find_unmatched_deposits_same_pg_not_double_matched(
    mock_payhoa_session, mock_get_client
):
    """Two identical bank deposits with only one PG should flag one as unmatched."""
    txns = {
        "data": [
            {
                "id": 30,
                "transactionDate": "2025-11-06T00:00:00Z",
                "amount": 100000,
                "originalAmount": -100000,
                "description": "CREDIT / DEPOSIT",
                "categoryId": 854772,
            },
            {
                "id": 31,
                "transactionDate": "2025-12-08T00:00:00Z",
                "amount": 100000,
                "originalAmount": -100000,
                "description": "CREDIT / DEPOSIT",
                "categoryId": 854772,
            },
        ],
        "last_page": 1,
    }
    pgs = {
        "data": [
            {
                "id": 301,
                "payorId": 523336,
                "net": 100000,
                "gross": 100000,
                "paymentMethodType": "OfflineCheck",
                "createdAt": "2025-11-06T12:00:00.000000Z",
            },
        ],
        "meta": {"lastPage": 1},
    }
    empty_txns = {"data": [], "last_page": 1}
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}
    txn_mock = MagicMock()
    txn_mock.json = MagicMock(return_value=txns)
    empty_txn_mock = MagicMock()
    empty_txn_mock.json = MagicMock(return_value=empty_txns)
    pg_mock = MagicMock()
    pg_mock.json = MagicMock(return_value=pgs)
    empty_pg_mock = MagicMock()
    empty_pg_mock.json = MagicMock(return_value=empty_pgs)

    async def fake_get(url, params=None):
        if "transactions" in url:
            return txn_mock if (params or {}).get("page", 1) == 1 else empty_txn_mock
        if "payment-groups" in url:
            return pg_mock if (params or {}).get("page", 1) == 1 else empty_pg_mock
        raise AssertionError(url)

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)
    with patch("treasurizer.tools.reconciliation.get_client", mock_get_client):
        unmatched = await find_unmatched_deposits()

    # PG 301 consumed by the 11/06 deposit -> 12/08 deposit has no match
    assert len(unmatched) == 1
    assert unmatched[0]["id"] == 31


@pytest.mark.asyncio
async def test_find_unmatched_deposits_skips_unrelated_uncategorized(
    mock_payhoa_session, mock_get_client
):
    """Uncategorized transactions whose description isn't deposit-like should be ignored."""
    txns = {
        "data": [
            {
                "id": 40,
                "transactionDate": "2025-04-01T00:00:00Z",
                "amount": 46,
                "originalAmount": -46,
                "description": "ACCTVERIFY JPMorgan Chase",
                "categoryId": None,
            },
        ],
        "last_page": 1,
    }
    empty_txns = {"data": [], "last_page": 1}
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}
    txn_mock = MagicMock()
    txn_mock.json = MagicMock(return_value=txns)
    empty_txn_mock = MagicMock()
    empty_txn_mock.json = MagicMock(return_value=empty_txns)
    empty_pg_mock = MagicMock()
    empty_pg_mock.json = MagicMock(return_value=empty_pgs)

    async def fake_get(url, params=None):
        if "transactions" in url:
            return txn_mock if (params or {}).get("page", 1) == 1 else empty_txn_mock
        return empty_pg_mock

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)
    with patch("treasurizer.tools.reconciliation.get_client", mock_get_client):
        unmatched = await find_unmatched_deposits()
    assert unmatched == []

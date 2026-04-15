# ABOUTME: Tests for unit balance and payment history tools
# ABOUTME: Covers balance parsing, charge template extraction, and payment filtering

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from treasurizer.tools.units import audit_unit, get_unit_payments, get_units

UNITS_RESPONSE = {
    "data": [
        {
            "id": 427031,
            "title": "Unit 1",
            "balance": 0,
            "pastDueBalance": 0,
            "recurringChargeTemplates": [
                {"chargeAmount": 100000, "title": "Monthly Assessments(monthly)"}
            ],
            "owners": [
                {
                    "id": 523335,
                    "membership": {"profile": {"givenNames": "Alice", "familyName": "Smith"}},
                }
            ],
        },
        {
            "id": 427032,
            "title": "Unit 2",
            "balance": 400000,
            "pastDueBalance": 400000,
            "recurringChargeTemplates": [
                {"chargeAmount": 100000, "title": "Monthly Assessments(monthly)"}
            ],
            "owners": [
                {
                    "id": 523336,
                    "membership": {"profile": {"givenNames": "Thanasis", "familyName": "Economou"}},
                }
            ],
        },
    ]
}

PAYMENT_GROUPS_RESPONSE = {
    "data": [
        {
            "id": 7311102,
            "payorId": 523336,
            "net": 100000,
            "gross": 100000,
            "paymentMethodType": "OfflineCheck",
            "createdAt": "2026-03-05T12:00:00.000000Z",
        },
        {
            "id": 7221316,
            "payorId": 523335,
            "net": 99755,
            "gross": 100000,
            "paymentMethodType": "StripeBankAccount",
            "createdAt": "2026-04-01T12:00:00.000000Z",
        },
        {
            "id": 7311101,
            "payorId": 523336,
            "net": 100000,
            "gross": 100000,
            "paymentMethodType": "OfflineCheck",
            "createdAt": "2026-02-05T12:00:00.000000Z",
        },
    ],
    "last_page": 1,
}


@pytest.mark.asyncio
async def test_get_units_returns_balance_and_dues(mock_payhoa_session, mock_get_client):
    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value=UNITS_RESPONSE)
    mock_payhoa_session.get = AsyncMock(return_value=mock_response)

    with patch("treasurizer.tools.units.get_client", mock_get_client):
        units = await get_units()

    assert len(units) == 2
    u2 = next(u for u in units if u.id == 427032)
    assert u2.title == "Unit 2"
    assert float(u2.balance) == 4000.00
    assert float(u2.past_due_balance) == 4000.00
    assert float(u2.monthly_dues) == 1000.00
    assert u2.owner_names == ["Thanasis Economou"]


@pytest.mark.asyncio
async def test_get_units_zero_balance(mock_payhoa_session, mock_get_client):
    mock_response = MagicMock()
    mock_response.json = MagicMock(return_value=UNITS_RESPONSE)
    mock_payhoa_session.get = AsyncMock(return_value=mock_response)

    with patch("treasurizer.tools.units.get_client", mock_get_client):
        units = await get_units()

    u1 = next(u for u in units if u.id == 427031)
    assert float(u1.balance) == 0.0
    assert u1.owner_names == ["Alice Smith"]


@pytest.mark.asyncio
async def test_get_unit_payments_filters_by_owner(mock_payhoa_session, mock_get_client):
    units_mock = MagicMock()
    units_mock.json = MagicMock(return_value=UNITS_RESPONSE)
    payments_mock = MagicMock()
    payments_mock.json = MagicMock(return_value=PAYMENT_GROUPS_RESPONSE)
    mock_payhoa_session.get = AsyncMock(side_effect=[units_mock, payments_mock])

    with patch("treasurizer.tools.units.get_client", mock_get_client):
        payments = await get_unit_payments(unit_id=427032)

    # Only Thanasis's payments (payorId=523336), not Unit 1's
    assert len(payments) == 2
    assert all(p["payor_id"] == 523336 for p in payments)
    assert payments[0]["amount"] == 1000.00
    assert payments[0]["date"] == date(2026, 3, 5)
    assert payments[0]["method"] == "OfflineCheck"


@pytest.mark.asyncio
async def test_audit_unit_matches_pg_to_bank_deposits(mock_payhoa_session, mock_get_client):
    """audit_unit should show matched PGs, unmatched PGs, and global suspect deposits."""
    units_mock = MagicMock()
    units_mock.json = MagicMock(return_value=UNITS_RESPONSE)

    # Tom's two PGs
    pgs = {
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
                "payorId": 523336,
                "net": 100000,
                "gross": 100000,
                "paymentMethodType": "OfflineCheck",
                "createdAt": "2025-05-08T12:00:00.000000Z",
            },
        ],
        "meta": {"lastPage": 1},
    }
    empty_pgs = {"data": [], "meta": {"lastPage": 1}}

    # Bank has: deposit matching PG 101, unrelated withdrawal, and an unmatched $1k check
    txns = {
        "data": [
            {
                "id": 1,
                "transactionDate": "2025-04-07T00:00:00Z",
                "amount": 100000,
                "originalAmount": -100000,
                "description": "CREDIT / DEPOSIT",
                "categoryId": 854772,
            },
            # No bank deposit for PG 102 (May 8)
            # Unmatched $1k check on Nov 6 - not linked to any PG
            {
                "id": 2,
                "transactionDate": "2025-11-06T00:00:00Z",
                "amount": 100000,
                "originalAmount": -100000,
                "description": "CREDIT / DEPOSIT",
                "categoryId": 854772,
            },
        ],
        "last_page": 1,
    }
    empty_txns = {"data": [], "last_page": 1}
    pgs_mock = MagicMock()
    pgs_mock.json = MagicMock(return_value=pgs)
    empty_pgs_mock = MagicMock()
    empty_pgs_mock.json = MagicMock(return_value=empty_pgs)
    txns_mock = MagicMock()
    txns_mock.json = MagicMock(return_value=txns)
    empty_txns_mock = MagicMock()
    empty_txns_mock.json = MagicMock(return_value=empty_txns)

    async def fake_get(url, params=None):
        p = params or {}
        if "units" in url:
            return units_mock
        if "payment-groups" in url:
            return pgs_mock if p.get("page", 1) == 1 else empty_pgs_mock
        if "transactions" in url:
            return txns_mock if p.get("page", 1) == 1 else empty_txns_mock
        raise AssertionError(url)

    mock_payhoa_session.get = AsyncMock(side_effect=fake_get)
    with patch("treasurizer.tools.units.get_client", mock_get_client):
        audit = await audit_unit(unit_id=427032)

    assert audit["unit_id"] == 427032
    assert audit["unit_title"] == "Unit 2"

    # PG 101 matches bank txn 1
    assert len(audit["matched"]) == 1
    assert audit["matched"][0]["pg_id"] == 101
    assert audit["matched"][0]["bank_txn_id"] == 1

    # PG 102 has no bank deposit
    assert len(audit["unmatched_pgs"]) == 1
    assert audit["unmatched_pgs"][0]["pg_id"] == 102

    # Global unmatched $1k check on Nov 6 is a suspect for this unit
    assert len(audit["suspect_deposits"]) == 1
    assert audit["suspect_deposits"][0]["id"] == 2
    assert audit["suspect_deposits"][0]["amount"] == 1000.0


@pytest.mark.asyncio
async def test_get_unit_payments_respects_limit(mock_payhoa_session, mock_get_client):
    units_mock = MagicMock()
    units_mock.json = MagicMock(return_value=UNITS_RESPONSE)
    payments_mock = MagicMock()
    payments_mock.json = MagicMock(return_value=PAYMENT_GROUPS_RESPONSE)
    mock_payhoa_session.get = AsyncMock(side_effect=[units_mock, payments_mock])

    with patch("treasurizer.tools.units.get_client", mock_get_client):
        payments = await get_unit_payments(unit_id=427032, limit=1)

    assert len(payments) == 1

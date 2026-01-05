# ABOUTME: Tests for Treasurizer type definitions
# ABOUTME: Validates cents_to_decimal and Pydantic model behavior

from datetime import date, datetime
from decimal import Decimal

import pytest

from treasurizer.types import (
    BankAccount,
    BalanceDiscrepancy,
    LedgerEntry,
    Reconciliation,
    Transaction,
    cents_to_decimal,
)


class TestCentsToDecimal:
    """Test the cents_to_decimal conversion function."""

    def test_converts_cents_to_dollars(self):
        assert cents_to_decimal(2301777) == Decimal("23017.77")
        assert cents_to_decimal(100) == Decimal("1.00")
        assert cents_to_decimal(1) == Decimal("0.01")

    def test_handles_zero(self):
        assert cents_to_decimal(0) == Decimal("0.00")

    def test_handles_none(self):
        assert cents_to_decimal(None) == Decimal("0.00")

    def test_handles_negative(self):
        assert cents_to_decimal(-5000) == Decimal("-50.00")


class TestBankAccount:
    """Test the BankAccount model."""

    def test_creates_with_required_fields(self):
        account = BankAccount(
            id=34311,
            name="Chase Checking",
            plaid_balance=Decimal("23017.77"),
            ledger_balance=Decimal("23015.77"),
        )
        assert account.id == 34311
        assert account.name == "Chase Checking"
        assert account.plaid_balance == Decimal("23017.77")
        assert account.ledger_balance == Decimal("23015.77")

    def test_defaults_for_optional_fields(self):
        account = BankAccount(
            id=1,
            name="Test",
            plaid_balance=Decimal("100.00"),
            ledger_balance=Decimal("100.00"),
        )
        assert account.last4 is None
        assert account.institution is None
        assert account.pending_funds == Decimal("0.00")
        assert account.unreviewed_count == 0
        assert account.last_synced is None


class TestDiscrepancyCalculation:
    """Test the discrepancy calculation logic."""

    def test_detects_positive_discrepancy(self):
        """Bank balance higher than ledger."""
        bank = cents_to_decimal(2301777)  # $23,017.77
        ledger = cents_to_decimal(2301577)  # $23,015.77
        diff = bank - ledger
        assert diff == Decimal("2.00")

    def test_detects_negative_discrepancy(self):
        """Ledger balance higher than bank."""
        bank = cents_to_decimal(1000000)  # $10,000.00
        ledger = cents_to_decimal(1010000)  # $10,100.00
        diff = bank - ledger
        assert diff == Decimal("-100.00")

    def test_no_discrepancy_when_balanced(self):
        bank = cents_to_decimal(1000000)
        ledger = cents_to_decimal(1000000)
        diff = bank - ledger
        assert diff == Decimal("0.00")


class TestTransaction:
    """Test the Transaction model."""

    def test_creates_transaction(self):
        txn = Transaction(
            id=12345,
            date=date(2025, 1, 1),
            amount=Decimal("-150.00"),
            description="Electric Bill",
            bank_account_id=34311,
        )
        assert txn.id == 12345
        assert txn.amount == Decimal("-150.00")
        assert txn.is_pending is False
        assert txn.is_reconciled is False


class TestReconciliation:
    """Test the Reconciliation model."""

    def test_creates_reconciliation(self):
        rec = Reconciliation(
            id=100,
            start_date=date(2024, 12, 1),
            end_date=date(2024, 12, 31),
            starting_balance=Decimal("20000.00"),
            ending_balance=Decimal("23015.77"),
            total_deposits=Decimal("5000.00"),
            total_payments=Decimal("1984.23"),
        )
        assert rec.id == 100
        assert rec.end_date == date(2024, 12, 31)


class TestBalanceDiscrepancy:
    """Test the BalanceDiscrepancy model."""

    def test_creates_discrepancy_record(self):
        disc = BalanceDiscrepancy(
            bank_balance=Decimal("23017.77"),
            ledger_balance=Decimal("23015.77"),
            difference=Decimal("2.00"),
            as_of_date=date(2025, 1, 5),
            possible_causes=["Rounding in fee calculations"],
        )
        assert disc.difference == Decimal("2.00")
        assert len(disc.possible_causes) == 1

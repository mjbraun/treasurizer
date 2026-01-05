# ABOUTME: Pydantic models for Treasurizer tool I/O
# ABOUTME: Defines Account, Transaction, LedgerEntry, and related types

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


def cents_to_decimal(cents: int | None) -> Decimal:
    """Convert cents (integer) to Decimal dollars."""
    if cents is None:
        return Decimal("0.00")
    return Decimal(cents) / 100


class BankAccount(BaseModel):
    """A bank account connected to PayHOA via Plaid."""

    id: int
    name: str
    last4: str | None = None
    institution: str | None = None
    plaid_balance: Decimal = Field(description="Balance from Plaid (bank)")
    ledger_balance: Decimal = Field(description="Balance in PayHOA ledger")
    pending_funds: Decimal = Field(default=Decimal("0.00"), description="Funds in transit")
    unreviewed_count: int = Field(default=0, description="Unreviewed transactions")
    last_synced: datetime | None = None


class Reconciliation(BaseModel):
    """A completed bank reconciliation."""

    id: int
    start_date: date
    end_date: date
    starting_balance: Decimal
    ending_balance: Decimal
    total_deposits: Decimal
    total_payments: Decimal
    completed_at: datetime | None = None


class Transaction(BaseModel):
    """A financial transaction in PayHOA."""

    id: int
    date: date
    amount: Decimal
    description: str
    memo: str | None = None
    category_id: int | None = None
    bank_account_id: int
    is_pending: bool = False
    is_approved: bool = True
    is_reconciled: bool = False
    reconciliation_id: int | None = None


class LedgerEntry(BaseModel):
    """An entry in the general ledger."""

    id: str
    date: date
    description: str
    debit_account_id: str | None = None
    debit_account_name: str | None = None
    credit_account_id: str | None = None
    credit_account_name: str | None = None
    amount: Decimal
    reference: str | None = None
    memo: str | None = None


class Owner(BaseModel):
    """A unit owner in the condo association."""

    id: str
    name: str
    unit: str
    email: str | None = None
    phone: str | None = None
    balance_due: Decimal = Field(default=Decimal("0.00"))


class Payment(BaseModel):
    """A payment from an owner."""

    id: str
    owner_id: str
    owner_name: str
    unit: str
    date: date
    amount: Decimal
    payment_method: str | None = None
    reference: str | None = None
    status: str  # Posted, Pending, Failed


class BalanceDiscrepancy(BaseModel):
    """A discrepancy between bank and ledger balances."""

    bank_balance: Decimal
    ledger_balance: Decimal
    difference: Decimal
    as_of_date: date
    possible_causes: list[str] = Field(default_factory=list)

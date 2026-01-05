# ABOUTME: Pydantic models for Treasurizer tool I/O
# ABOUTME: Defines Account, Transaction, LedgerEntry, and related types

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class BankAccount(BaseModel):
    """A bank account connected to PayHOA."""

    id: str
    name: str
    account_number_last4: str | None = None
    institution: str | None = None
    balance: Decimal
    as_of_date: date | None = None


class LedgerAccount(BaseModel):
    """A ledger/GL account in PayHOA."""

    id: str
    name: str
    account_number: str | None = None
    account_type: str  # Asset, Liability, Equity, Income, Expense
    balance: Decimal


class Transaction(BaseModel):
    """A financial transaction in PayHOA."""

    id: str
    date: date
    amount: Decimal
    description: str
    memo: str | None = None
    category: str | None = None
    account_id: str
    account_name: str
    is_pending: bool = False
    check_number: str | None = None


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

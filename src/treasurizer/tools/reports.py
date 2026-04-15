# ABOUTME: Financial report tools for PayHOA
# ABOUTME: Balance sheet, general ledger, and reconciliation reports

from datetime import date, datetime
from decimal import Decimal

from treasurizer.client import get_client, with_auth_retry
from treasurizer.types import LedgerEntry, cents_to_decimal


def _parse_balance_sheet_section(section: dict) -> dict:
    """Recursively parse balance sheet section into readable format."""
    result: dict = {
        "name": section.get("name", ""),
        "balance": float(cents_to_decimal(section.get("balance"))),
    }

    if section.get("children"):
        result["children"] = [_parse_balance_sheet_section(child) for child in section["children"]]
    if section.get("accounts"):
        result["accounts"] = [
            {
                "name": acc.get("name", ""),
                "balance": float(cents_to_decimal(acc.get("balance"))),
            }
            for acc in section["accounts"]
        ]

    return result


@with_auth_retry
async def get_balance_sheet(as_of_date: str | None = None) -> dict:
    """Get the balance sheet as of a specific date."""
    session = await get_client()

    if as_of_date is None:
        as_of_date = date.today().isoformat()

    response = await session.get("/reports/balance-sheet/0", params={"asOfDate": as_of_date})
    data = response.json()

    result: dict = {
        "as_of_date": as_of_date,
        "sections": [],
    }

    for section in data:
        result["sections"].append(_parse_balance_sheet_section(section))

    return result


@with_auth_retry
async def get_general_ledger(
    start_date: str,
    end_date: str,
    page: int = 0,
    page_size: int = 50,
) -> dict:
    """Get general ledger entries for a date range."""
    session = await get_client()

    response = await session.post(
        "/reports/general-ledger/json",
        json={
            "startDate": start_date,
            "endDate": end_date,
            "pageSize": min(page_size, 100),
            "page": page,
            "showMemoColumn": True,
        },
    )
    data = response.json()

    entries = []
    for entry in data.get("data", []):
        entry_date = None
        if entry.get("date"):
            try:
                entry_date = datetime.fromisoformat(entry["date"].replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                pass

        entries.append(
            LedgerEntry(
                id=str(entry.get("id", "")),
                date=entry_date or date.today(),
                description=entry.get("description", ""),
                debit_account_id=str(entry.get("debitAccountId", ""))
                if entry.get("debitAccountId")
                else None,
                debit_account_name=entry.get("debitAccountName"),
                credit_account_id=str(entry.get("creditAccountId", ""))
                if entry.get("creditAccountId")
                else None,
                credit_account_name=entry.get("creditAccountName"),
                amount=cents_to_decimal(entry.get("amount")),
                reference=entry.get("reference"),
                memo=entry.get("memo"),
            )
        )

    return {
        "entries": [e.model_dump() for e in entries],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": data.get("total", len(entries)),
        },
    }


@with_auth_retry
async def get_reconciliation_report(reconciliation_id: int) -> dict:
    """Get details of a specific bank reconciliation."""
    session = await get_client()

    response = await session.get(
        "/reports/reconciliations/0",
        params={"reconciliation": reconciliation_id},
    )
    data = response.json()

    start_date = None
    end_date = None
    if data.get("startDate"):
        try:
            start_date = datetime.fromisoformat(data["startDate"].replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass
    if data.get("endDate"):
        try:
            end_date = datetime.fromisoformat(data["endDate"].replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            pass

    result: dict = {
        "reconciliation_id": reconciliation_id,
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "starting_balance": float(cents_to_decimal(data.get("startingBalance"))),
        "ending_balance": float(cents_to_decimal(data.get("endingBalance"))),
        "total_deposits": float(cents_to_decimal(data.get("totalDeposits"))),
        "total_payments": float(cents_to_decimal(data.get("totalPayments"))),
        "cleared_count": data.get("clearedCount", 0),
    }

    if data.get("clearedTransactions"):
        result["cleared_transactions"] = [
            {
                "id": txn.get("id"),
                "date": txn.get("transactionDate"),
                "description": txn.get("description"),
                "amount": float(cents_to_decimal(txn.get("amount"))),
            }
            for txn in data["clearedTransactions"]
        ]

    return result


@with_auth_retry
async def get_account_balances_summary() -> dict:
    """Get a summary of all account balances comparing bank vs ledger."""
    session = await get_client()

    response = await session.get("/bank-accounts")
    accounts_data = response.json()

    today = date.today().isoformat()
    bs_response = await session.get("/reports/balance-sheet/0", params={"asOfDate": today})
    bs_response.json()  # Fetched for cross-reference; balance sheet data unused here

    total_bank = Decimal("0.00")
    total_ledger = Decimal("0.00")
    accounts = []

    for acc in accounts_data:
        deposit = acc.get("depositBankAccount") or {}
        plaid_balance = cents_to_decimal(acc.get("plaidBalance"))
        ledger_balance = cents_to_decimal(
            (acc.get("fixedAsset") or {}).get("balance") or deposit.get("internalBalance")
        )
        difference = plaid_balance - ledger_balance

        total_bank += plaid_balance
        total_ledger += ledger_balance

        accounts.append(
            {
                "id": acc["id"],
                "name": acc.get("friendlyName", "Unknown"),
                "bank_balance": float(plaid_balance),
                "ledger_balance": float(ledger_balance),
                "difference": float(difference),
                "has_discrepancy": difference != Decimal("0.00"),
            }
        )

    total_diff = total_bank - total_ledger

    return {
        "as_of_date": today,
        "total_bank_balance": float(total_bank),
        "total_ledger_balance": float(total_ledger),
        "total_difference": float(total_diff),
        "has_discrepancies": total_diff != Decimal("0.00"),
        "accounts": accounts,
    }

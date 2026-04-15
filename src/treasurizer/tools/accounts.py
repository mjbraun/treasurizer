# ABOUTME: Bank account tools for PayHOA
# ABOUTME: Query bank accounts, balances, and Plaid sync status

import json
from datetime import datetime
from decimal import Decimal

from treasurizer.client import get_client, with_auth_retry
from treasurizer.types import BankAccount, Reconciliation, cents_to_decimal


async def _compute_ledger_balance(session, account_id: int) -> Decimal:
    """Compute ledger balance as negative sum of approved transaction originalAmounts.

    PayHOA sign convention: originalAmount negative = credit (money in), positive = debit (money out).
    For Plaid-connected accounts with full transaction history, ledger = -sum(originalAmount).
    """
    total_cents = 0
    page = 1
    while True:
        r = await session.get(
            "/transactions",
            params={
                "filters": json.dumps({"account": account_id, "approved": True}),
                "perPage": 100,
                "page": page,
                "column": "transactionDate",
                "direction": "asc",
            },
        )
        data = r.json()
        txns = data.get("data", [])
        for t in txns:
            total_cents += t.get("originalAmount") or 0
        if page >= data.get("last_page", 1):
            break
        page += 1
    return cents_to_decimal(-total_cents)


@with_auth_retry
async def get_bank_accounts() -> list[BankAccount]:
    """List all bank accounts connected to PayHOA."""
    session = await get_client()
    response = await session.get("/bank-accounts")
    data = response.json()

    accounts = []
    for acc in data:
        # Parse Plaid sync time
        last_synced = None
        plaid_token = acc.get("plaidToken") or {}
        if plaid_token.get("transactionsLastPulled"):
            try:
                last_synced = datetime.fromisoformat(
                    plaid_token["transactionsLastPulled"].replace(" ", "T")
                )
            except (ValueError, TypeError):
                pass

        # Get institution name from Plaid token
        institution = (plaid_token.get("institution") or {}).get("name")

        # Compute ledger balance from starting balance + approved transactions
        ledger_balance = await _compute_ledger_balance(session, acc["id"])

        deposit = acc.get("depositBankAccount") or {}
        # Get pending funds
        pending = cents_to_decimal(deposit.get("pendingFunds"))

        accounts.append(
            BankAccount(
                id=acc["id"],
                name=acc.get("friendlyName", "Unknown"),
                last4=acc.get("last4"),
                institution=institution,
                plaid_balance=cents_to_decimal(acc.get("plaidBalance")),
                ledger_balance=ledger_balance,
                pending_funds=pending,
                unreviewed_count=acc.get("unreviewedTransactionsCount", 0),
                last_synced=last_synced,
            )
        )

    return accounts


@with_auth_retry
async def get_balance_discrepancy(account_id: int | None = None) -> dict:
    """Compare bank balance vs ledger balance to find discrepancies."""
    session = await get_client()
    response = await session.get("/bank-accounts")
    data = response.json()

    discrepancies = []
    for acc in data:
        if account_id and acc["id"] != account_id:
            continue

        deposit = acc.get("depositBankAccount") or {}
        plaid_balance = cents_to_decimal(acc.get("plaidBalance"))
        ledger_balance = await _compute_ledger_balance(session, acc["id"])
        pending = cents_to_decimal(deposit.get("pendingFunds"))

        diff = plaid_balance - ledger_balance

        if diff != Decimal("0.00"):
            possible_causes = []

            if pending > Decimal("0.00"):
                possible_causes.append(f"Pending funds in transit: ${pending:.2f}")

            if abs(diff - pending) < Decimal("0.01"):
                possible_causes.append("Difference matches pending funds - likely timing issue")

            if abs(diff) < Decimal("1.00"):
                possible_causes.append("Small difference may be rounding in fee calculations")

            unreviewed = acc.get("unreviewedTransactionsCount", 0)
            if unreviewed > 0:
                possible_causes.append(f"{unreviewed} unreviewed transactions may affect balance")

            if not possible_causes:
                possible_causes.append("Unknown cause - manual investigation recommended")

            discrepancies.append(
                {
                    "account_id": acc["id"],
                    "account_name": acc.get("friendlyName", "Unknown"),
                    "bank_balance": float(plaid_balance),
                    "ledger_balance": float(ledger_balance),
                    "difference": float(diff),
                    "pending_funds": float(pending),
                    "possible_causes": possible_causes,
                }
            )

    return {
        "total_accounts": len(data),
        "accounts_with_discrepancy": len(discrepancies),
        "discrepancies": discrepancies,
    }


@with_auth_retry
async def get_reconciliation_history(account_id: int) -> list[Reconciliation]:
    """Get past bank reconciliations for an account."""
    session = await get_client()
    response = await session.get("/bank-accounts")
    data = response.json()

    account = None
    for acc in data:
        if acc["id"] == account_id:
            account = acc
            break

    if not account:
        return []

    reconciliations = []
    for rec in account.get("reconciliations", []):
        completed_at = None
        if rec.get("completedAt"):
            try:
                completed_at = datetime.fromisoformat(rec["completedAt"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

        start_date = None
        end_date = None
        if rec.get("startDate"):
            try:
                start_date = datetime.fromisoformat(rec["startDate"].replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                pass
        if rec.get("endDate"):
            try:
                end_date = datetime.fromisoformat(rec["endDate"].replace("Z", "+00:00")).date()
            except (ValueError, TypeError):
                pass

        if start_date and end_date:
            reconciliations.append(
                Reconciliation(
                    id=rec["id"],
                    start_date=start_date,
                    end_date=end_date,
                    starting_balance=cents_to_decimal(rec.get("startingBalance")),
                    ending_balance=cents_to_decimal(rec.get("endingBalance")),
                    total_deposits=cents_to_decimal(rec.get("totalDeposits")),
                    total_payments=cents_to_decimal(rec.get("totalPayments")),
                    completed_at=completed_at,
                )
            )

    reconciliations.sort(key=lambda r: r.end_date, reverse=True)
    return reconciliations

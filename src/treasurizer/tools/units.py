# ABOUTME: Unit and owner tools for PayHOA
# ABOUTME: Query unit balances, dues, and owner payment history

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from treasurizer.client import get_client, with_auth_retry
from treasurizer.tools.reconciliation import (
    _fetch_all_pages,
    _is_dues_deposit,
    _parse_iso_date,
)
from treasurizer.types import cents_to_decimal


class Unit(BaseModel):
    """A condo unit with its current balance and dues info."""

    id: int
    title: str
    balance: Decimal
    past_due_balance: Decimal
    monthly_dues: Decimal | None = None
    owner_names: list[str] = []


def _parse_unit(u: dict) -> Unit:
    templates = u.get("recurringChargeTemplates") or []
    monthly_dues = None
    if templates:
        monthly_dues = cents_to_decimal(templates[0].get("chargeAmount"))

    owner_names = []
    for owner in u.get("owners") or []:
        profile = (owner.get("membership") or {}).get("profile") or {}
        given = profile.get("givenNames", "")
        family = profile.get("familyName", "")
        name = f"{given} {family}".strip()
        if name:
            owner_names.append(name)

    return Unit(
        id=u["id"],
        title=u.get("title", ""),
        balance=cents_to_decimal(u.get("balance")),
        past_due_balance=cents_to_decimal(u.get("pastDueBalance")),
        monthly_dues=monthly_dues,
        owner_names=owner_names,
    )


@with_auth_retry
async def get_units() -> list[Unit]:
    """List all units with current balance, past-due amount, and monthly dues."""
    session = await get_client()
    response = await session.get(
        "/units",
        params={"with": "balance,owners,recurringChargeTemplates"},
    )
    data = response.json()
    units_data = data.get("data", data) if isinstance(data, dict) else data
    return [_parse_unit(u) for u in units_data if isinstance(u, dict)]


@with_auth_retry
async def audit_unit(
    unit_id: int,
    start_date: str | None = None,
    date_tolerance_days: int = 10,
) -> dict:
    """Audit a unit by reconciling its payment-groups with bank deposits.

    Returns a dict with:
      - matched: PGs that have a corresponding bank deposit
      - unmatched_pgs: PGs with no bank deposit trail (rare; investigate manually)
      - suspect_deposits: global unmatched bank deposits that may belong to this unit
        (the caller decides whether to attribute them, since bank deposits don't
        record payor identity beyond the owner's own deposit records).
    """
    session = await get_client()

    units_response = await session.get("/units", params={"with": "owners"})
    units_data = units_response.json()
    units_list = units_data.get("data", units_data) if isinstance(units_data, dict) else units_data
    unit = next((u for u in units_list if isinstance(u, dict) and u.get("id") == unit_id), None)
    if not unit:
        return {"error": f"Unit {unit_id} not found"}

    owner_ids = {o["id"] for o in (unit.get("owners") or [])}
    unit_title = unit.get("title", "")

    pg_items = await _fetch_all_pages(
        session,
        "/payment-groups",
        {"perPage": 100, "column": "createdAt", "direction": "asc"},
    )
    unit_pgs = []
    for pg in pg_items:
        if pg.get("payorId") not in owner_ids:
            continue
        d = _parse_iso_date(pg.get("createdAt"))
        if d is None:
            continue
        if start_date and d < date.fromisoformat(start_date):
            continue
        unit_pgs.append(
            {
                "id": pg["id"],
                "date": d,
                "net_cents": int(pg.get("net") or 0),
                "gross_cents": int(pg.get("gross") or 0),
                "method": pg.get("paymentMethodType"),
            }
        )

    txn_params = {"perPage": 100, "column": "transactionDate", "direction": "asc"}
    all_txns = await _fetch_all_pages(session, "/transactions", txn_params)

    deposits = []
    for t in all_txns:
        if not _is_dues_deposit(t):
            continue
        d = _parse_iso_date(t.get("transactionDate"))
        if d is None:
            continue
        if start_date and d < date.fromisoformat(start_date):
            continue
        deposits.append(
            {
                "id": t["id"],
                "date": d,
                "amount_cents": abs(int(t.get("originalAmount") or 0)),
                "description": t.get("description", ""),
                "category_id": t.get("categoryId"),
            }
        )

    pg_items_all = []
    for pg in pg_items:
        d = _parse_iso_date(pg.get("createdAt"))
        if d is None:
            continue
        pg_items_all.append({"id": pg["id"], "date": d, "net_cents": int(pg.get("net") or 0)})

    globally_matched_pg_ids: set[int] = set()
    deposit_to_pg: dict[int, int] = {}
    for dep in deposits:
        for pg in pg_items_all:
            if pg["id"] in globally_matched_pg_ids:
                continue
            if pg["net_cents"] != dep["amount_cents"]:
                continue
            if abs((pg["date"] - dep["date"]).days) > date_tolerance_days:
                continue
            globally_matched_pg_ids.add(pg["id"])
            deposit_to_pg[dep["id"]] = pg["id"]
            break

    matched = []
    unmatched_pgs = []
    pg_to_deposit = {v: k for k, v in deposit_to_pg.items()}
    for pg in unit_pgs:
        if pg["id"] in pg_to_deposit:
            dep_id = pg_to_deposit[pg["id"]]
            dep = next(d for d in deposits if d["id"] == dep_id)
            matched.append(
                {
                    "pg_id": pg["id"],
                    "pg_date": pg["date"].isoformat(),
                    "amount": float(cents_to_decimal(pg["net_cents"])),
                    "bank_txn_id": dep["id"],
                    "bank_date": dep["date"].isoformat(),
                    "method": pg["method"],
                }
            )
        else:
            unmatched_pgs.append(
                {
                    "pg_id": pg["id"],
                    "pg_date": pg["date"].isoformat(),
                    "amount": float(cents_to_decimal(pg["net_cents"])),
                    "method": pg["method"],
                }
            )

    suspect_deposits = []
    for dep in deposits:
        if dep["id"] in deposit_to_pg:
            continue
        suspect_deposits.append(
            {
                "id": dep["id"],
                "date": dep["date"].isoformat(),
                "amount": float(cents_to_decimal(dep["amount_cents"])),
                "description": dep["description"],
                "category_id": dep["category_id"],
            }
        )

    return {
        "unit_id": unit_id,
        "unit_title": unit_title,
        "matched": matched,
        "unmatched_pgs": unmatched_pgs,
        "suspect_deposits": suspect_deposits,
    }


@with_auth_retry
async def get_unit_payments(unit_id: int, limit: int = 50) -> list[dict]:
    """Get payment history for the owner(s) of a unit."""
    session = await get_client()

    # Find the owner IDs for this unit
    units_response = await session.get(
        "/units",
        params={"with": "owners"},
    )
    units_data = units_response.json()
    units_list = units_data.get("data", units_data) if isinstance(units_data, dict) else units_data
    unit = next((u for u in units_list if isinstance(u, dict) and u.get("id") == unit_id), None)
    if not unit:
        return []

    owner_ids = {o["id"] for o in (unit.get("owners") or [])}
    if not owner_ids:
        return []

    # Fetch payment groups and filter client-side by owner
    payments = []
    page = 1
    while len(payments) < limit:
        response = await session.get(
            "/payment-groups",
            params={
                "perPage": 100,
                "page": page,
                "column": "createdAt",
                "direction": "desc",
            },
        )
        data = response.json()
        page_data = data.get("data", []) if isinstance(data, dict) else data
        meta = (data.get("meta") or {}) if isinstance(data, dict) else {}
        last_page = int(meta.get("lastPage") or data.get("last_page") or 1)

        for pg in page_data:
            if not isinstance(pg, dict):
                continue
            if pg.get("payorId") not in owner_ids:
                continue
            payment_date = None
            if pg.get("createdAt"):
                try:
                    payment_date = datetime.fromisoformat(
                        pg["createdAt"].replace("Z", "+00:00")
                    ).date()
                except (ValueError, TypeError):
                    pass

            payments.append(
                {
                    "id": pg["id"],
                    "date": payment_date,
                    "amount": float(cents_to_decimal(pg.get("net"))),
                    "gross_amount": float(cents_to_decimal(pg.get("gross"))),
                    "method": pg.get("paymentMethodType"),
                    "payor_id": pg.get("payorId"),
                }
            )

        if page >= last_page:
            break
        page += 1

    return payments[:limit]

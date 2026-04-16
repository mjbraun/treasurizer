# Treasurizer - Project Guide

Treasurizer is a CLI tool for managing **1357 Madison Park Condo Association** finances via the PayHOA API. It provides commands for reviewing bank transactions, managing unit owner balances, and generating reports.

## Development

```bash
# Install for CLI use (after code changes, always use --no-cache --force)
uv tool install --no-cache --force .

# Run tests
uv run pytest tests/ -p no:playwright

# TDD workflow: write failing test -> confirm failure -> implement -> confirm pass
```

**Important**: `uv tool install --force` alone reuses the cached wheel and won't pick up code changes. Always use `--no-cache --force`.

## CLI Reference

```bash
# Bank accounts
treasurizer accounts list
treasurizer accounts balance [--account ACCOUNT_ID]
treasurizer accounts reconciliation-history ACCOUNT_ID

# Transactions
treasurizer transactions list [--account ID] [--from DATE] [--to DATE] [--page N] [--per-page N]
treasurizer transactions unreviewed [--account ID] [--limit N]
treasurizer transactions unreconciled ACCOUNT_ID [--from DATE] [--to DATE]
treasurizer transactions search QUERY [--account ID] [--from DATE] [--to DATE]
treasurizer transactions update TXN_ID [--category ID] [--memo TEXT] [--approve | --no-approve]
treasurizer transactions detail TXN_ID

# Units and owners
treasurizer units list                                   # all units with balance/dues/owners
treasurizer units payments UNIT_ID [--limit N]           # payment history for a unit's owner
treasurizer units audit UNIT_ID [--from DATE] [--tolerance-days N]  # reconcile unit PGs vs bank deposits

# Reports
treasurizer reports balance-sheet [--date YYYY-MM-DD]
treasurizer reports general-ledger START_DATE END_DATE [--page N] [--page-size N]
treasurizer reports reconciliation RECONCILIATION_ID
treasurizer reports account-balances

# Reconciliation helpers
treasurizer reconciliation find-by-amount AMOUNT [--tolerance N] [--account ID]
treasurizer reconciliation sign-errors [--account ID] [--from DATE] [--to DATE]
treasurizer reconciliation compare-totals ACCOUNT_ID START_DATE END_DATE
treasurizer reconciliation unmatched-deposits [--from DATE] [--to DATE] [--tolerance-days N]
```

## One-off scripts

```bash
# Chase PDF audit: parses 1357's Chase statement archive and finds deposits
# never credited to a unit in PayHOA. Reads PDFs from
# ~/Documents/Personal/1357 Statements/account-dump/statements/ by default.
uv run python scripts/chase_audit.py [--from DATE] [--json] [--tolerance-days N]
```

## Known IDs

### Organization
- **Org ID**: 18707 (1357 Madison Park Condo Association)

### Bank Accounts
| Name | ID | Last4 | Notes |
|------|----|-------|-------|
| Axos Checking | 56797 | 0979 | Primary operating account |
| Axos Savings | 59010 | 0987 | Savings/reserves |

### Units and Owners
| Unit | Unit ID | Owner | Owner ID | Notes |
|------|---------|-------|----------|-------|
| Unit 1 | 427031 | Matthew Braun | 523335 | Auto-pay enabled |
| Unit 2 | 427032 | Thanasis & Dina Economou | 523336 | Manual payments; teec@uchicago.edu |
| Unit 3 | 427033 | James Robinson & Angela Jaffray | 523338 | |

Monthly dues: **$1,000/unit/month** (charge template ID 39201, bills on the 1st)

### Transaction Categories
| ID | Name |
|----|------|
| 854772 | Assessments (unit dues/payments in) |
| 854773 | Bank Fees |
| 854774 | Building Repairs |
| 854777 | Electricity |
| 854780 | Gas |
| 854782 / 854783 | Insurance |
| 854791 | Licenses & Permits |
| 854793 | Miscellaneous (use for transfers, interest, unclassified) |
| 854797 | Plumbing |
| 854798 | Professional Services |
| 854801 | Software |
| 854807 | Water |
| 989904 | Special Assessments |
| 1453924 | CapEx |
| 1454904 | Master Association Dues |
| 2006642 | Interest Income |

## PayHOA API Notes

### Base URL and Auth
- Base: `https://core.payhoa.com`
- All routes: `GET /organizations/18707/...`
- Auth: JWT Bearer token + `x-xsrf-token` header (URL-decoded from XSRF-TOKEN cookie)
- The `x-xsrf-token` header is **required for all mutating requests** (PATCH, POST). Without it, requests return 200 but silently do nothing.
- Session cached at `~/.treasurizer/session.json`

### Ledger Balance Computation
`fixedAsset.balance` is not returned by the API. Compute ledger balance as:

```
ledger_balance = -sum(originalAmount for all approved transactions)
```

**Sign convention for `originalAmount`**:
- **Negative** = credit (money coming into the account, e.g., deposits, unit payments)
- **Positive** = debit (money going out, e.g., expenses, transfers out)

This is the opposite of intuitive - a deposit has a negative `originalAmount`. The `amount` field is always positive (absolute value); use `originalAmount` for sign.

### Working Endpoints (as of April 2026)
```
GET  /organizations/{org}/bank-accounts              - list accounts (with fixedAsset)
GET  /organizations/{org}/transactions               - requires: page, perPage, column, direction
                                                       filters JSON: {account, approved, reviewed, reconciled, startDate, endDate}
PATCH /organizations/{org}/transactions/{id}         - update categoryId, memo, approved
GET  /organizations/{org}/payment-groups             - requires: page, perPage, column, direction
                                                       NOTE: filters by payor ID do NOT work server-side; filter client-side
GET  /organizations/{org}/payment-groups/{id}        - single payment group detail
GET  /organizations/{org}/units                      - list units; use with=owners,recurringChargeTemplates for balance/dues
POST /organizations/{org}/reports/balance-sheet/0    - balance sheet report
POST /organizations/{org}/reports/reconciliations/0  - reconciliation report
POST /organizations/{org}/reports/general-ledger/json - GL report
```

### Notable Non-Working / Gotchas
- `PATCH /bank-accounts/{id}` with `startingBalance` - returns 200 but does NOT update fixedAsset. Use the "Update Starting Balance" UI button instead.
- `POST /payment-groups` - 405 (not supported). Record unit payments through the PayHOA UI.
- `fixedAsset.startingBalanceDate` for new accounts defaults to creation date (today). Set it to account opening date via UI for correct ledger balance.
- AI tagging: all transactions have `aiSuggestion.isPending: true` - PayHOA's AI has never auto-applied any categories. Don't rely on AI-suggested categories.

## Check-payment reconciliation gap (important)

PayHOA has two ledgers that don't auto-sync for check deposits:
1. **Bank transaction feed** (Plaid) - captures all deposits automatically.
2. **Payment-groups** (unit ledger) - tracks who has paid.

For ACH and credit-card payments processed through PayHOA, both sides auto-record.
For **check deposits at the bank, a manual payment-group entry must be created in the PayHOA UI** to credit the correct unit. Missing that manual step means the bank shows the deposit but the unit's balance never decreases.

Today, Unit 2 (Thanasis) is the only check payer and therefore the only unit exposed to this gap. Run `treasurizer reconciliation unmatched-deposits` periodically - or after accepting any check - to catch missed entries.

## External evidence archive

- **Chase statements (2019-01 through 2026-03)**: `/Users/mjbraun/Documents/Personal/1357 Statements/account-dump/statements/` - 87 monthly PDFs. Use `scripts/chase_audit.py` to parse them and reconcile against PayHOA.
- Chase account `*1291` was closed 2026-04-06; final balance $2,121.68 swept to Axos. April 2026 statement is not in the archive.

## Current Account State (as of April 2026)

### Axos Checking (56797)
- Plaid balance: $4,232.90
- Ledger balance: $4,232.90 (matches)
- Starting balance: $3,700 as of 2026-01-16

### Axos Savings (59010)
- Plaid balance: $17,142.52
- Ledger balance: $17,142.52 (matches)
- Starting balance: $0 as of 2026-01-12
- History: funded Jan 13, 2026 with $19,000 from Chase consolidation

### Unit Balances
- Unit 1: $0 (current)
- Unit 2 (Thanasis): **$4,000 past due** - Nov/Dec 2025 and likely other months
- Unit 3 (James/Angela): **$2,000 past due**

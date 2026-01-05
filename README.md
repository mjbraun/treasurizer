# Treasurizer

MCP server for PayHOA condo association accounting.

## Overview

Treasurizer provides AI agents with access to PayHOA for financial management tasks:

- Query bank accounts and balances
- View general ledger entries
- Find discrepancies between bank and ledger balances
- Track owner payments and assessments

## Setup

```bash
# Install dependencies
uv sync

# Run the server
uv run treasurizer
```

## Configuration

Credentials can be provided via environment variables:

```bash
export PAYHOA_EMAIL="your-email@example.com"
export PAYHOA_PASSWORD="your-password"
```

Or retrieved automatically from 1Password:

```bash
# Uses op://Private/app.payhoa.com/username and /password
uv run treasurizer
```

## Development Status

This MCP server is under development. We're currently reverse-engineering the PayHOA API through traffic inspection.

# Unusual Whales API Rules

This project must never invent Unusual Whales endpoints. Use only the whitelist below.

## Critical Rules

- Base URL: `https://api.unusualwhales.com`
- API prefix used by code: `https://api.unusualwhales.com/api`
- Authentication: `Authorization: Bearer <API_TOKEN>`
- Client header: `UW-CLIENT-API-ID: 100001`
- Method: `GET` only
- Never use query params like `apiKey` or `api_key`.
- Never use `/api/v1/` or `/api/v2/`.

## Blacklisted Hallucinated Endpoints

- `/api/options/flow`
- `/api/flow`
- `/api/flow/live`
- `/api/stock/{ticker}/flow`
- `/api/stock/{ticker}/options`
- `/api/unusual-activity`

## Valid Endpoints Used By Antigravity

### Flow

- `/api/option-trades/flow-alerts`
- `/api/screener/option-contracts`
- `/api/stock/{ticker}/flow-recent`

### Sentiment

- `/api/market/market-tide`
- `/api/stock/{ticker}/net-prem-ticks`

### Dark Pool

- `/api/darkpool/recent`
- `/api/darkpool/{ticker}`

### Options And Greeks

- `/api/stock/{ticker}/option-contracts`
- `/api/stock/{ticker}/greeks`
- `/api/stock/{ticker}/greek-exposure/strike`
- `/api/stock/{ticker}/spot-exposures/strike`
- `/api/stock/{ticker}/interpolated-iv`
- `/api/stock/{ticker}/options-volume`

### Fundamentals And News

- `/api/news/headlines`
- `/api/stock/{ticker}/financials`
- `/api/stock/{ticker}/income-statements`
- `/api/stock/{ticker}/balance-sheets`
- `/api/stock/{ticker}/cash-flows`
- `/api/stock/{ticker}/earnings`

### Other

- `/api/insider/transactions`
- `/api/congress/recent-trades`
- `/api/stock/{ticker}/technical-indicator/{function}`

## Current Institutional Flow Filter

Antigravity uses `/api/screener/option-contracts` for the professional Live Flow style filter:

- `min_ask_perc=0.7`
- `vol_greater_oi=true`
- `max_multileg_volume_ratio=0.1`
- `min_premium=100000`
- `issue_types[]=Common Stock`
- `issue_types[]=ADR`
- `issue_types[]=ETF`

This catches ask-side dominant contracts where volume is greater than old open interest and multileg activity is low.


# yFinance GCP

Financial data pipeline that downloads prices and fundamentals from Yahoo Finance, stores them in BigQuery, and runs a quantitative screener to surface the top 20 stock opportunities every trading day.

## Architecture

```
Yahoo Finance (yfinance)
        │
        ├─ weekly_companies  ──► companies                (fundamentals + metadata)
        └─ daily_prices      ──► daily_prices             (raw OHLCV)
                                        │
                                 daily_enrich  ──────────────────────────────────► enriched_prices_table
                                 (enrich_prices.bsql)                              (prices + technical indicators)
                                                                                            │
                                                                                     daily_picks ──► daily_picks
                                                                                     (daily_picks.bsql)
```

**Stack:** Python 3.11+ · BigQuery (google-cloud-bigquery) · GitHub Actions · Cloud Scheduler

---

## Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `weekly_companies` | Weekly (Sunday) | Refreshes the stock universe (~2,700 symbols from S&P 500, Russell 2000, STOXX 600). Validates availability on Yahoo Finance and stores fundamentals (sector, market cap, ratios, analyst consensus). MERGE by `(symbol, updated_at)`. |
| `daily_prices` | Daily (Mon–Fri) | Downloads OHLCV prices. Backfills 5 years on first run; otherwise loads only the requested date. MERGE by `(date, symbol)` — never duplicates. |
| `daily_enrich` | Daily, after `daily_prices` | Rebuilds `enriched_prices_table` via `enrich_prices.bsql`: calculates RSI, SMA 50/200, MACD, Bollinger Bands, momentum, and joins with fundamentals. Falls back to incremental MERGE when the table is up to date. |
| `daily_picks` | Daily, after `daily_enrich` | Runs the Daily Picks screener and upserts top 20 opportunities into `daily_picks` via MERGE by `(date, symbol)`. |

---

## Daily Picks Screener

Every trading day the screener selects the **top 20 stocks** across two opportunity types:

- **ALCISTA** — stocks in a confirmed uptrend with healthy momentum. Entry in trend.
- **DIP** — stocks with a solid uptrend that have dropped 5–25% in 5 days due to macro factors. Discounted entry.

**Strict filters (both types):**
- Market cap ≥ $5B
- Bullish trend today and 3 months ago
- Analyst consensus: `buy` or `strong_buy` only
- Max −35% from 52-week high (no broken stocks)
- Within 10% of SMA200

**Score 0–100 (same structure for both types):**

| Component | Pts | ALCISTA | DIP |
|-----------|-----|---------|-----|
| A — Momentum / Prior strength | 25 | 10d momentum (+3%→0, +15%→25) | 1y performance before dip (+10%→0, +100%→25) |
| B — RSI timing | 25 | Bell curve centered at RSI 58 (range 45–70) | Oversold RSI (50→0pts, 20→25pts) |
| C — Structural health | 25 | Distance above SMA200 (0%→0, +20%→25) | Same |
| D — Analyst consensus | 25 | `strong_buy`=25, `buy`=15 | Same |

Each row in `daily_picks` includes a `reason` field with a plain-English explanation:

```
rank 1 | DIP | ASML.AS
"Macro dip -11.3% in 5d on confirmed uptrend. Prior strength: +58.4% in 1y before dip.
 RSI 34 (oversold). 8.2% above SMA200. Analysts: strong_buy."

rank 2 | ALCISTA | MSFT
"Confirmed uptrend (Bullish now & 3m ago). Momentum +8.4% in 10d.
 RSI 58 (healthy zone). 12.1% above SMA200. -8.3% from 52w high. Analysts: buy."
```

---

## BigQuery Tables

| Table | Description |
|-------|-------------|
| `daily_picks` | **Main output.** Top 20 daily opportunities with score 0–100 and reason text |
| `enriched_prices_table` | Full price history with technical indicators and fundamentals |
| `daily_prices` | Raw OHLCV prices |
| `companies` | Company fundamentals, one snapshot per symbol per week |

Full column-level schema: [`docs/bigquery_schema.md`](docs/bigquery_schema.md)

---

## Requirements

- Python 3.11+
- GCP project with BigQuery enabled
- GCP credentials: `gcloud auth application-default login` or `service-account.json` in `src/config/`

```bash
pip install -r requirements.txt
```

---

## Configuration

GCP credentials are resolved in this order:
1. `src/config/service-account.json` (if present and contains a valid key)
2. `GOOGLE_APPLICATION_CREDENTIALS` environment variable
3. `gcloud auth application-default login`

---

## Usage

```bash
# Refresh company universe (weekly)
python -m src.jobs.weekly_companies

# Download prices (daily)
python -m src.jobs.daily_prices                        # yesterday
python -m src.jobs.daily_prices 2025-01-15             # specific date
python -m src.jobs.daily_prices 2025-01-01 2025-01-31  # date range

# Rebuild enriched table
python -m src.jobs.daily_enrich

# Generate daily picks
python -m src.jobs.daily_picks

# Limit to N companies (for testing)
python -m src.jobs.weekly_companies 5
```

### Execution order

```
Sunday:   weekly_companies → daily_enrich
Mon–Fri:  daily_prices → daily_enrich → daily_picks
```

---

## GitHub Actions

Pipelines run automatically via Cloud Scheduler (triggers GitHub Actions workflows):

- **Daily** (`daily.yml`): Mon–Fri — `daily_prices` → `daily_enrich` → `daily_picks`
- **Weekly** (`weekly.yml`): Sundays — `weekly_companies` → `daily_enrich`

GCP credentials are injected from the `GCP_SERVICE_ACCOUNT_KEY` secret (Settings → Secrets → Actions).

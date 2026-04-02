# yFinance GCP

Financial data pipeline that downloads prices and fundamentals from Yahoo Finance, stores them in BigQuery, and surfaces daily investment opportunities per sector for educational front-ends.

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
                                                                              daily_sector_opportunities
                                                                              (sector_opportunities_incremental.bsql)
                                                                                            │
                                                                                 sector_daily_opportunities
```

**Stack:** Python 3.11+ · BigQuery (google-cloud-bigquery) · Cloud Run Jobs · Cloud Scheduler

---

## Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `weekly_companies` | Weekly (Sunday) | Refreshes the stock universe (~2,700 symbols from S&P 500, Russell 2000, STOXX 600). Validates availability on Yahoo Finance and stores fundamentals (sector, market cap, ratios, analyst consensus). MERGE by `(symbol, updated_at)`. |
| `daily_prices` | Daily (Mon–Fri) | Downloads OHLCV prices. Backfills 5 years on first run; otherwise loads only the requested date. MERGE by `(date, symbol)` — never duplicates. |
| `daily_enrich` | Daily, after `daily_prices` | Rebuilds `enriched_prices_table` via `enrich_prices.bsql`: calculates RSI, SMA 50/200, MACD, Bollinger Bands, momentum, and joins with fundamentals. Falls back to incremental MERGE when the table is up to date. |
| `daily_sector_opportunities` | Daily, after `daily_enrich` | Runs the sector screener and writes up to 10 opportunities per sector × 3 setup types into `sector_daily_opportunities`. DELETE + INSERT on max_date (idempotent). |

---

## Sector Opportunities Screener

Every trading day the screener selects up to **10 stocks per sector** in three setup categories:

- **Dip (Tendencia Alcista)** — confirmed Bullish trend, RSI 30–45 (oversold), negative momentum. Entry in dip within uptrend.
- **Momentum (Líderes)** — sector leaders within 10% of 52-week high, RSI 55–75, momentum >+2% in 10d.
- **Value Reversal** — deep corrections (>−30% from 52w high), PE ratio 0–20, analyst buy/strong_buy consensus.

**Base filters (all categories):** close > $5 · market cap > $2B · sector not null.

**Score 0–100 (4 components × 25 pts):**

| Component | Dip | Momentum | Value Reversal |
|-----------|-----|----------|----------------|
| A | RSI oversold depth | Momentum 10d strength | PE quality (lower = better) |
| B | Health vs SMA200 | RSI sweet spot (bell at 65) | Upside potential depth |
| C | Analyst consensus | Closeness to 52w high | Analyst consensus |
| D | Market cap quality | Analyst consensus | Market cap quality |

Each row includes a `reason` field with a plain-English explanation:

```
sector: Technology | setup: Dip (Tendencia Alcista) | rank 1 | ASML.AS
"Bullish trend with RSI 34 in oversold zone. Momentum -6.2% in 10d (dip). 8.1% above SMA200. Analysts: strong_buy."

sector: Technology | setup: Momentum (Líderes) | rank 1 | NVDA
"Momentum +9.4% in 10d. RSI 67 (momentum zone). -3.1% from 52w high. Analysts: strong_buy."

sector: Healthcare | setup: Value Reversal | rank 1 | PFE
"-44.2% from 52w high (deep correction). PE ratio: 9.3x. RSI 28. Analysts: buy."
```

---

## BigQuery Tables

| Table | Description |
|-------|-------------|
| `sector_daily_opportunities` | **Main output.** Up to 10 opportunities per sector × 3 setup types, score 0–100, reason text |
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

# Generate sector opportunities
python -m src.jobs.daily_sector_opportunities

# Limit to N companies (for testing)
python -m src.jobs.weekly_companies 5
```

### Execution order

```
Sunday:   weekly_companies → daily_enrich
Mon–Fri:  daily_prices → daily_enrich → daily_sector_opportunities
```

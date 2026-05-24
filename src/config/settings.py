# src/config/settings.py

# ─────────────────────────────────────────────
# GCP / BigQuery
# ─────────────────────────────────────────────
PROJECT_ID = "yfinance-gcp"
DATASET = "yfinance_raw"
GCS_BUCKET = "yfinance-cache"

# Tables (fully-qualified)
COMPANIES_TABLE = f"{PROJECT_ID}.{DATASET}.companies"
DAILY_PRICES_TABLE = f"{PROJECT_ID}.{DATASET}.daily_prices"
ENRICHED_PRICES_TABLE = f"{PROJECT_ID}.{DATASET}.enriched_prices_table"
SECTOR_OPPORTUNITIES_TABLE = f"{PROJECT_ID}.{DATASET}.sector_daily_opportunities"
ANOMALY_RADAR_TABLE        = f"{PROJECT_ID}.{DATASET}.anomaly_radar"
COMPANY_NEWS_TABLE         = f"{PROJECT_ID}.{DATASET}.company_news"
MARKET_INSIGHTS_TABLE      = f"{PROJECT_ID}.{DATASET}.market_insights"

# ─────────────────────────────────────────────
# Yahoo Finance
# ─────────────────────────────────────────────
# Backfill window when prices table is empty
YAHOO_DAILY_BACKFILL_YEARS = 5

# ─────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────
DEFAULT_LIMIT = None   # for local testing
BATCH_SIZE = 100       # download batch size

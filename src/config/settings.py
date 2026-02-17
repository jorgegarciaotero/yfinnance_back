# src/config/settings.py

# ─────────────────────────────────────────────
# GCP / BigQuery
# ─────────────────────────────────────────────
PROJECT_ID = "yfinance-gcp"
DATASET = "yfinance_raw"

# Tables (fully-qualified)
COMPANIES_TABLE = f"{PROJECT_ID}.{DATASET}.companies"
DAILY_PRICES_TABLE = f"{PROJECT_ID}.{DATASET}.daily_prices"
ENRICHED_PRICES_TABLE = f"{PROJECT_ID}.{DATASET}.enriched_prices_table"
AI_INSIGHTS_TABLE = f"{PROJECT_ID}.{DATASET}.ai_insights"

# ─────────────────────────────────────────────
# Yahoo Finance
# ─────────────────────────────────────────────
# Backfill window when prices table is empty
YAHOO_DAILY_BACKFILL_YEARS = 5

# ─────────────────────────────────────────────
# Jobs
# ─────────────────────────────────────────────
DEFAULT_LIMIT = None   # para pruebas locales
BATCH_SIZE = 100      # para descargas por lotes

# src/jobs/weekly_companies.py
"""
Weekly job:
- Refresh index universe
- Validate Yahoo availability
- Enrich companies with stable Yahoo metadata
- MERGE into BigQuery companies table
"""

from datetime import datetime, date, timezone
import sys
import logging
import pandas as pd
import yfinance as yf
from google.cloud import bigquery

from src.ingest.companies import get_companies_universe
from src.ingest.yfinance_client import is_yahoo_symbol_valid
from src.config.settings import (
    PROJECT_ID,
    DATASET,
    COMPANIES_TABLE,
)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("weekly_companies")


# ─────────────────────────────────────────────
# BigQuery helpers
# ─────────────────────────────────────────────
def ensure_dataset() -> None:
    client = bigquery.Client(project=PROJECT_ID)
    dataset_id = f"{PROJECT_ID}.{DATASET}"
    try:
        client.get_dataset(dataset_id)
    except Exception:
        ds = bigquery.Dataset(dataset_id)
        ds.location = "EU"
        client.create_dataset(ds)


def ensure_table() -> None:
    client = bigquery.Client(project=PROJECT_ID)

    schema = [
        # Keys
        bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED"),

        # Status
        bigquery.SchemaField("provider", "STRING"),
        bigquery.SchemaField("is_active", "BOOL"),
        bigquery.SchemaField("last_checked", "TIMESTAMP"),
        bigquery.SchemaField("last_seen", "DATE"),

        # Identity
        bigquery.SchemaField("quote_type", "STRING"),
        bigquery.SchemaField("exchange", "STRING"),
        bigquery.SchemaField("exchange_timezone", "STRING"),
        bigquery.SchemaField("currency", "STRING"),
        bigquery.SchemaField("market", "STRING"),
        bigquery.SchemaField("country", "STRING"),

        # Classification
        bigquery.SchemaField("sector", "STRING"),
        bigquery.SchemaField("industry", "STRING"),

        # Size / liquidity snapshot
        bigquery.SchemaField("market_cap", "INT64"),
        bigquery.SchemaField("shares_outstanding", "INT64"),
        bigquery.SchemaField("float_shares", "INT64"),
        bigquery.SchemaField("avg_volume_3m", "INT64"),
        bigquery.SchemaField("avg_volume_10d", "INT64"),
        bigquery.SchemaField("beta", "FLOAT64"),

        bigquery.SchemaField("updated_at", "TIMESTAMP"),
    ]

    try:
        client.get_table(COMPANIES_TABLE)
    except Exception:
        client.create_table(bigquery.Table(COMPANIES_TABLE, schema=schema))


# ─────────────────────────────────────────────
# Yahoo helpers
# ─────────────────────────────────────────────
def extract_yahoo_metadata(symbol: str) -> dict:
    try:
        ticker = yf.Ticker(symbol)

        info_fast = ticker.fast_info or {}
        info_full = ticker.info or {}

        def to_int(v):
            try:
                return int(v) if v is not None else None
            except Exception:
                return None

        def to_float(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        return {
            "provider": "yahoo",
            "quote_type": info_full.get("quoteType"),
            "exchange": info_fast.get("exchange"),
            "exchange_timezone": info_fast.get("timezone"),
            "currency": info_fast.get("currency"),
            "market": info_full.get("market"),
            "country": info_full.get("country"),
            "sector": info_full.get("sector"),
            "industry": info_full.get("industry"),
            "market_cap": to_int(info_full.get("marketCap")),
            "shares_outstanding": to_int(info_full.get("sharesOutstanding")),
            "float_shares": to_int(info_full.get("floatShares")),
            "avg_volume_3m": to_int(info_full.get("averageVolume")),
            "avg_volume_10d": to_int(info_full.get("averageVolume10days")),
            "beta": to_float(info_full.get("beta")),
        }
    except Exception as e:
        logger.warning("metadata error for %s: %s", symbol, e)
        return {}


# ─────────────────────────────────────────────
# DataFrame casting (CRITICAL)
# ─────────────────────────────────────────────
INT_COLUMNS = [
    "market_cap",
    "shares_outstanding",
    "float_shares",
    "avg_volume_3m",
    "avg_volume_10d",
]

FLOAT_COLUMNS = ["beta"]


def cast_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    for col in INT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in FLOAT_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ─────────────────────────────────────────────
# Merge
# ─────────────────────────────────────────────
def merge_companies(df: pd.DataFrame) -> None:
    client = bigquery.Client(project=PROJECT_ID)
    stage = f"{PROJECT_ID}.{DATASET}._companies_stage"

    df = cast_dataframe(df)

    client.load_table_from_dataframe(
        df,
        stage,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE"
        ),
    ).result()

    merge_sql = f"""
    MERGE `{COMPANIES_TABLE}` t
    USING `{stage}` s
      ON t.symbol = s.symbol
     AND t.source = s.source

    WHEN MATCHED THEN UPDATE SET
        provider            = s.provider,
        is_active            = s.is_active,
        last_checked         = s.last_checked,
        last_seen            = s.last_seen,
        quote_type           = s.quote_type,
        exchange             = s.exchange,
        exchange_timezone    = s.exchange_timezone,
        currency             = s.currency,
        market               = s.market,
        country              = s.country,
        sector               = s.sector,
        industry             = s.industry,
        market_cap           = s.market_cap,
        shares_outstanding   = s.shares_outstanding,
        float_shares         = s.float_shares,
        avg_volume_3m        = s.avg_volume_3m,
        avg_volume_10d       = s.avg_volume_10d,
        beta                 = s.beta,
        updated_at           = s.updated_at

    WHEN NOT MATCHED THEN
      INSERT (
        symbol, source, provider, is_active,
        last_checked, last_seen,
        quote_type, exchange, exchange_timezone, currency,
        market, country, sector, industry,
        market_cap, shares_outstanding, float_shares,
        avg_volume_3m, avg_volume_10d, beta,
        updated_at
      )
      VALUES (
        s.symbol, s.source, s.provider, s.is_active,
        s.last_checked, s.last_seen,
        s.quote_type, s.exchange, s.exchange_timezone, s.currency,
        s.market, s.country, s.sector, s.industry,
        s.market_cap, s.shares_outstanding, s.float_shares,
        s.avg_volume_3m, s.avg_volume_10d, s.beta,
        s.updated_at
      )
    """
    client.query(merge_sql).result()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main(limit: int | None = None) -> None:
    logger.info("starting weekly_companies")

    ensure_dataset()
    ensure_table()

    base_df = get_companies_universe()
    if limit:
        base_df = base_df.head(limit)

    now = datetime.now(timezone.utc)
    today = date.today()

    rows = []

    for _, row in base_df.iterrows():
        symbol = row["symbol"]
        source = row["source"]

        is_active = is_yahoo_symbol_valid(symbol)
        meta = extract_yahoo_metadata(symbol) if is_active else {}

        rows.append({
            "symbol": symbol,
            "source": source,
            "is_active": is_active,
            "last_checked": now,
            "last_seen": today if is_active else None,
            "updated_at": now,
            **meta,
        })

    df = pd.DataFrame(rows)
    merge_companies(df)

    logger.info("weekly_companies finished | rows=%d", len(df))


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit)

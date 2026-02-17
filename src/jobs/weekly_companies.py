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
import os
import logging
import pandas as pd
import yfinance as yf
import time
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
    """
    Ensure BigQuery dataset exists. If not, create it.
    """
    client = bigquery.Client(project=PROJECT_ID)
    dataset_id = f"{PROJECT_ID}.{DATASET}"
    try:
        client.get_dataset(dataset_id)
    except Exception:
        ds = bigquery.Dataset(dataset_id)
        ds.location = "EU"
        client.create_dataset(ds)


def ensure_table() -> None:
    """
    Ensure BigQuery table exists. If not, create it.
    """
    client = bigquery.Client(project=PROJECT_ID)

    schema = [
        # Keys
        bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED"),

        bigquery.SchemaField("short_name", "STRING"),
        bigquery.SchemaField("long_name", "STRING"),
        bigquery.SchemaField("business_summary", "STRING"),

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

        bigquery.SchemaField("trailing_eps", "FLOAT64"),       
        bigquery.SchemaField("forward_eps", "FLOAT64"),       
        bigquery.SchemaField("book_value", "FLOAT64"),        
        bigquery.SchemaField("dividend_rate", "FLOAT64"),     
        bigquery.SchemaField("ex_dividend_date", "INT64"),   
        
        # Ratios precalculated by yahoo
        bigquery.SchemaField("forward_pe", "FLOAT64"),        
        bigquery.SchemaField("dividend_yield", "FLOAT64"),    
        bigquery.SchemaField("return_on_equity", "FLOAT64"),  
        bigquery.SchemaField("target_mean_price", "FLOAT64"), 
        bigquery.SchemaField("recommendation_key", "STRING"), 

        bigquery.SchemaField("updated_at", "DATE"),
    ]

    try:
        client.get_table(COMPANIES_TABLE)
    except Exception:
        client.create_table(bigquery.Table(COMPANIES_TABLE, schema=schema))


# ─────────────────────────────────────────────
# Yahoo helpers
# ─────────────────────────────────────────────
def extract_yahoo_metadata(symbol: str, logger: logging.Logger) -> dict:
    """
    Extract stable metadata from Yahoo Finance for a given symbol. This is used to enrich the companies table with 
    fundamental and classification data.

    ARGS:
        symbol: Stock ticker symbol (e.g. AAPL)
    RETURNS:
        Dictionary with metadata fields. Empty if symbol is invalid or data is missing.
    """
    try:
        logger.info("Extracting Yahoo metadata for %s", symbol)
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
            "short_name": info_full.get("shortName"),
            "long_name": info_full.get("longName"),
            "business_summary": info_full.get("longBusinessSummary"),
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
            "trailing_eps": to_float(info_full.get("trailingEps")),
            "forward_eps": to_float(info_full.get("forwardEps")),
            "book_value": to_float(info_full.get("bookValue")),
            "dividend_rate": to_float(info_full.get("dividendRate")),
            "ex_dividend_date": to_int(info_full.get("exDividendDate")),

            "beta": to_float(info_full.get("beta")),
            "forward_pe": to_float(info_full.get("forwardPE")),
            "dividend_yield": to_float(info_full.get("dividendYield")),
            "return_on_equity": to_float(info_full.get("returnOnEquity")),
            "target_mean_price": to_float(info_full.get("targetMeanPrice")),
            "recommendation_key": info_full.get("recommendationKey"),
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
    "ex_dividend_date",
]

FLOAT_COLUMNS = [
    "beta", 
    "trailing_eps",
    "forward_eps",
    "book_value",
    "dividend_rate",
    "forward_pe", 
    "dividend_yield", 
    "return_on_equity", 
    "target_mean_price"
]

ALL_METADATA_COLS = [
    "short_name", "long_name", "business_summary", "quote_type", "exchange",
    "exchange_timezone", "currency", "market", "country", "sector", "industry",
    "market_cap", "shares_outstanding", "float_shares", "avg_volume_3m", "avg_volume_10d",
    "beta", "trailing_eps", "forward_eps", "book_value", "dividend_rate", "ex_dividend_date",
    "forward_pe", "dividend_yield", "return_on_equity", "target_mean_price", "recommendation_key"
]

def cast_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cast DataFrame columns to correct types for BigQuery loading. This is critical to avoid load errors and ensure data quality.
    ARGS:
        df: Input DataFrame with raw metadata
    RETURNS:
        DataFrame with columns cast to correct types
    """
    # 1. Asegurar que todas las columnas existan (rellenar con None si faltan)
    # Esto evita errores en el MERGE si Yahoo no devolvió datos para alguna columna
    for col in ALL_METADATA_COLS:
        if col not in df.columns:
            df[col] = None

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
    """ 
    Merge the enriched companies DataFrame into the BigQuery companies table using a MERGE statement. 
    This will update existing records and insert new ones based on the symbol and source keys.
    ARGS:
        df: DataFrame with enriched company metadata, must include 'symbol' and 'source' columns
    RETURNS:
        None
    """
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
      AND CAST(t.updated_at AS DATE) = CAST(s.updated_at AS DATE)

    WHEN MATCHED THEN UPDATE SET
        provider            = s.provider,
        is_active           = s.is_active,
        last_checked        = s.last_checked,
        last_seen           = s.last_seen,
        -- New Identity fields
        short_name          = s.short_name,
        long_name           = s.long_name,
        business_summary    = s.business_summary,
        -- Technical fields
        quote_type          = s.quote_type,
        exchange            = s.exchange,
        exchange_timezone   = s.exchange_timezone,
        currency            = s.currency,
        market              = s.market,
        country             = s.country,
        sector              = s.sector,
        industry            = s.industry,
        market_cap          = s.market_cap,
        shares_outstanding  = s.shares_outstanding,
        float_shares        = s.float_shares,
        avg_volume_3m       = s.avg_volume_3m,
        avg_volume_10d      = s.avg_volume_10d,
        beta                = s.beta,
        -- New Fundamental fields
        trailing_eps        = s.trailing_eps,
        forward_eps         = s.forward_eps,
        book_value          = s.book_value,
        dividend_rate       = s.dividend_rate,
        ex_dividend_date    = s.ex_dividend_date,
        forward_pe          = s.forward_pe,
        dividend_yield      = s.dividend_yield,
        return_on_equity    = s.return_on_equity,
        target_mean_price   = s.target_mean_price,
        recommendation_key  = s.recommendation_key,
        updated_at          = s.updated_at

    WHEN NOT MATCHED THEN
      INSERT (
        symbol, source, provider, is_active, last_checked, last_seen,
        short_name, long_name, business_summary,
        quote_type, exchange, exchange_timezone, currency,
        market, country, sector, industry,
        market_cap, shares_outstanding, float_shares,
        avg_volume_3m, avg_volume_10d, beta,
        trailing_eps, forward_eps, book_value, dividend_rate, ex_dividend_date,
        forward_pe, dividend_yield, return_on_equity, target_mean_price, recommendation_key,
        updated_at
      )
      VALUES (
        s.symbol, s.source, s.provider, s.is_active, s.last_checked, s.last_seen,
        s.short_name, s.long_name, s.business_summary,
        s.quote_type, s.exchange, s.exchange_timezone, s.currency,
        s.market, s.country, s.sector, s.industry,
        s.market_cap, s.shares_outstanding, s.float_shares,
        s.avg_volume_3m, s.avg_volume_10d, s.beta,
        s.trailing_eps, s.forward_eps, s.book_value, s.dividend_rate, s.ex_dividend_date,
        s.forward_pe, s.dividend_yield, s.return_on_equity, s.target_mean_price, s.recommendation_key,
        s.updated_at
      )
    """

    client.query(merge_sql).result()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main(limit: int | None = None) -> None:
    logger.info("starting weekly_companies")

    json_path = os.path.join("src", "config", "service-account.json")
    
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        logger.info("Loading credentials from: %s", json_path)
    else:
        logger.info("Not found service-account.json, using default credentials")

    ensure_dataset()
    ensure_table()

    base_df = get_companies_universe()
    if limit:
        base_df = base_df.head(limit)

    now = datetime.now(timezone.utc)
    today = date.today()
    

    rows = []
    total_stocks = len(base_df)

    for i, (_, row) in enumerate(base_df.iterrows(), 1):
        symbol = row["symbol"]
        source = row["source"]
        logger.info(f"Processing {i}/{total_stocks}: {symbol}...")
       
        is_active = is_yahoo_symbol_valid(symbol)
        meta = extract_yahoo_metadata(symbol,logger) if is_active else {}

        rows.append({
            "symbol": symbol,
            "source": source,
            "is_active": is_active,
            "last_checked": now,
            "last_seen": today if is_active else None,
            "updated_at": today,
            **meta,
        })
        time.sleep(2)  # Sleep to avoid hitting Yahoo rate limits
    df = pd.DataFrame(rows)
    merge_companies(df)
    logger.info("weekly_companies finished | rows=%d", len(df))


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=limit)

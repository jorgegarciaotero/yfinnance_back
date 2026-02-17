# src/jobs/daily_prices.py
"""
Daily job:
- Fetch DAILY prices from Yahoo Finance
- Only for active companies (is_active = TRUE)
- If prices table is empty -> backfill N years
- Else -> load a single requested date
"""
import sys
import os
sys.path.append(os.getcwd())

from datetime import date, datetime, timedelta
import logging
import pandas as pd
import yfinance as yf
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    COMPANIES_TABLE,
    DAILY_PRICES_TABLE,
    YAHOO_DAILY_BACKFILL_YEARS,
    DEFAULT_LIMIT,
)

from src.config import settings



# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_prices")



def ensure_table() -> None:
    client = bigquery.Client(project=PROJECT_ID)

    schema = [
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("open", "FLOAT"),
        bigquery.SchemaField("high", "FLOAT"),
        bigquery.SchemaField("low", "FLOAT"),
        bigquery.SchemaField("close", "FLOAT"),
        bigquery.SchemaField("adj_close", "FLOAT"),
        bigquery.SchemaField("volume", "INTEGER"),
    ]

    try:
        client.get_table(DAILY_PRICES_TABLE)
        logger.info("daily_prices table exists")
    except Exception:
        client.create_table(bigquery.Table(DAILY_PRICES_TABLE, schema=schema))
        logger.info("daily_prices table created")


def prices_table_is_empty() -> bool:
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
        SELECT COUNT(1) AS cnt
        FROM `{DAILY_PRICES_TABLE}`
    """

    row = next(client.query(query).result())
    empty = row.cnt == 0

    logger.info("daily_prices empty: %s", empty)
    return empty


def get_active_symbols(limit: int | None) -> list[str]:
    client = bigquery.Client(project=PROJECT_ID)

    limit_sql = f"LIMIT {limit}" if limit else ""

    query = f"""
        SELECT DISTINCT symbol
        FROM `{COMPANIES_TABLE}`
        WHERE is_active = TRUE
          AND symbol IS NOT NULL
        {limit_sql}
    """

    symbols = [r.symbol for r in client.query(query).result()]
    logger.info("active symbols retrieved: %d", len(symbols))

    return symbols


def fetch_daily_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        df = yf.download(
            symbol,
            start=start,
            end=end,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            logger.warning("no data for %s", symbol)
            return pd.DataFrame()

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        df = (
            df.reset_index()
            .rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            })
        )

        df["symbol"] = symbol

        logger.info("downloaded %d rows for %s", len(df), symbol)

        return df[[
            "date", "symbol",
            "open", "high", "low", "close", "adj_close", "volume"
        ]]

    except Exception as e:
        logger.error("error downloading %s: %s", symbol, e)
        return pd.DataFrame()


def load_prices(df: pd.DataFrame) -> None:
    client = bigquery.Client(project=PROJECT_ID)

    logger.info("loading %d rows into BigQuery", len(df))

    client.load_table_from_dataframe(
        df,
        DAILY_PRICES_TABLE,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND"
        ),
    ).result()

    logger.info("load completed")


def main(
    run_date: str | None = None,
    end_date_arg: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
) -> None:
    logger.info("starting daily_prices job")

    json_path = os.path.join("src", "config", "service-account.json")
    
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        logger.info("Loading credentials from: %s", json_path)
    else:
        logger.info("Not found service-account.json, using default credentials")

    ensure_table()

    symbols = get_active_symbols(limit)

    if prices_table_is_empty():
        start_date = (
            date.today() - timedelta(days=365 * YAHOO_DAILY_BACKFILL_YEARS)
        ).isoformat()
        end_date = date.today().isoformat()
        logger.info("backfill mode | %s -> %s", start_date, end_date)
    elif run_date and end_date_arg:
        start_date = run_date
        end_date = (
            datetime.fromisoformat(end_date_arg) + timedelta(days=1)
        ).date().isoformat()
        logger.info("range mode | %s -> %s (adjusted for inclusion)", start_date, end_date_arg)
    elif run_date:
        start_date = run_date
        end_date = (
            datetime.fromisoformat(run_date) + timedelta(days=1)
        ).date().isoformat()
        logger.info("daily mode | date = %s", run_date)
    else:
        run_date = (date.today() - timedelta(days=1)).isoformat()
        start_date = run_date
        end_date = (
            datetime.fromisoformat(run_date) + timedelta(days=1)
        ).date().isoformat()
        logger.info("cron mode (automatic) | date = %s", run_date)

    all_data: list[pd.DataFrame] = []

    for symbol in symbols:
        logger.info("processing %s", symbol)
        df = fetch_daily_prices(symbol, start_date, end_date)
        if not df.empty:
            all_data.append(df)

    if all_data:
        prices_df = pd.concat(all_data, ignore_index=True)
        load_prices(prices_df)
    else:
        logger.warning("no price data collected")

    logger.info("daily_prices job finished")



def test_bigquery_connection() -> None:
    """
    Validates the connection to BigQuery by attempting to read 
    the first record from the companies table.
    """
    logger.info(f"Attempting to connect to project: {PROJECT_ID}...")
    client = bigquery.Client(project=PROJECT_ID)
    
    # Attempt to read only 1 row from the companies table
    query = f"SELECT symbol FROM `{COMPANIES_TABLE}` LIMIT 1"
    
    try:
        query_job = client.query(query)
        results = list(query_job.result())
        
        if len(results) > 0:
            logger.info("✅ SUCCESS! Connection established.")
            logger.info(f"Successfully retrieved the first ticker: {results[0].symbol}")
        else:
            logger.warning("⚠️ Connection successful, but the companies table appears to be empty.")
            
    except Exception as e:
        logger.error(f"❌ Connection ERROR: {e}")




if __name__ == "__main__":
    json_path = os.path.join("src", "config", "service-account.json")
    # sys.argv[0] is the script name
    # sys.argv[1] is the first argument (start_date / run_date)
    # sys.argv[2] is the second argument (end_date_arg)
    arg1 = sys.argv[1] if len(sys.argv) > 1 else None
    arg2 = sys.argv[2] if len(sys.argv) > 2 else None
    # Examples:
    # 1. Automatic (Yesterday): python -m src.jobs.daily_prices
    # 2. Single Day:           python -m src.jobs.daily_prices 2024-01-01
    # 3. Date Range:           python -m src.jobs.daily_prices 2024-01-01 2024-01-31
    main(run_date=arg1, end_date_arg=arg2, limit=None)
    # test_bigquery_connection()

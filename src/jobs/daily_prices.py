# src/jobs/daily_prices.py
"""
Daily job:
- Fetch DAILY prices from Yahoo Finance
- Only for active companies (is_active = TRUE)
- If prices table is empty -> backfill N years
- Else -> load a single requested date
"""

from datetime import date, datetime, timedelta
import sys
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
    limit: int | None = DEFAULT_LIMIT,
) -> None:
    logger.info("starting daily_prices job")

    ensure_table()

    symbols = get_active_symbols(limit)

    if prices_table_is_empty():
        start_date = (
            date.today() - timedelta(days=365 * YAHOO_DAILY_BACKFILL_YEARS)
        ).isoformat()
        end_date = date.today().isoformat()
        logger.info("backfill mode | %s -> %s", start_date, end_date)
    else:
        if run_date is None:
            raise ValueError(
                "run_date (YYYY-MM-DD) is required when daily_prices is not empty"
            )

        start_date = run_date
        end_date = (
            datetime.fromisoformat(run_date) + timedelta(days=1)
        ).date().isoformat()
        logger.info("daily mode | date = %s", run_date)

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


if __name__ == "__main__":
    run_date = sys.argv[1] if len(sys.argv) > 1 else None
    # Ejemplos:
    # python -m src.jobs.daily_prices
    # python -m src.jobs.daily_prices 2024-09-02
    main(run_date=run_date)

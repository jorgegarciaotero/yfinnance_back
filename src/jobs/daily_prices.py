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
        table = bigquery.Table(DAILY_PRICES_TABLE, schema=schema)
        table.time_partitioning = bigquery.TimePartitioning(field="date")
        table.clustering_fields = ["symbol"]
        client.create_table(table)
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


def get_symbols_without_history(all_symbols: list[str]) -> list[str]:
    """Returns symbols that have no rows at all in daily_prices (need backfill)."""
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
        SELECT DISTINCT symbol
        FROM `{DAILY_PRICES_TABLE}`
    """
    existing = {r.symbol for r in client.query(query).result()}
    new_symbols = [s for s in all_symbols if s not in existing]
    if new_symbols:
        logger.info("symbols with no history (will backfill): %s", new_symbols)
    return new_symbols


def get_active_symbols(limit: int | None) -> list[str]:
    client = bigquery.Client(project=PROJECT_ID)

    limit_sql = f"LIMIT {limit}" if limit else ""

    query = f"""
        WITH latest AS (
            SELECT symbol, is_active,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY updated_at DESC) AS rn
            FROM `{COMPANIES_TABLE}`
            WHERE symbol IS NOT NULL
        )
        SELECT symbol
        FROM latest
        WHERE rn = 1 AND is_active = TRUE
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

    logger.info("loading %d rows into BigQuery via MERGE", len(df))

    staging_table = f"{DAILY_PRICES_TABLE}_staging"

    client.load_table_from_dataframe(
        df,
        staging_table,
        job_config=bigquery.LoadJobConfig(
            write_disposition="WRITE_TRUNCATE"
        ),
    ).result()

    merge_sql = f"""
        MERGE `{DAILY_PRICES_TABLE}` T
        USING `{staging_table}` S
        ON T.date = DATE(S.date) AND T.symbol = S.symbol
        WHEN NOT MATCHED THEN
            INSERT (date, symbol, open, high, low, close, adj_close, volume)
            VALUES (DATE(S.date), S.symbol, S.open, S.high, S.low, S.close, S.adj_close, S.volume)
    """

    client.query(merge_sql).result()
    client.delete_table(staging_table)

    logger.info("load completed")


def main(
    run_date: str | None = None,
    end_date_arg: str | None = None,
    limit: int | None = DEFAULT_LIMIT,
) -> None:
    logger.info("starting daily_prices job")
    ensure_table()

    symbols = get_active_symbols(limit)

    # ── Determine incremental date range ─────────────────────────────────────
    if prices_table_is_empty():
        incr_start = (
            date.today() - timedelta(days=365 * YAHOO_DAILY_BACKFILL_YEARS)
        ).isoformat()
        incr_end = date.today().isoformat()
        logger.info("backfill mode (table empty) | %s -> %s", incr_start, incr_end)
        new_symbols = []   # all symbols covered by full backfill
    elif run_date and end_date_arg:
        incr_start = run_date
        incr_end = (
            datetime.fromisoformat(end_date_arg) + timedelta(days=1)
        ).date().isoformat()
        logger.info("range mode | %s -> %s", incr_start, end_date_arg)
        new_symbols = get_symbols_without_history(symbols)
    elif run_date:
        incr_start = run_date
        incr_end = (
            datetime.fromisoformat(run_date) + timedelta(days=1)
        ).date().isoformat()
        logger.info("daily mode | date = %s", run_date)
        new_symbols = get_symbols_without_history(symbols)
    else:
        run_date = (date.today() - timedelta(days=1)).isoformat()
        incr_start = run_date
        incr_end = (
            datetime.fromisoformat(run_date) + timedelta(days=1)
        ).date().isoformat()
        logger.info("cron mode | date = %s", run_date)
        new_symbols = get_symbols_without_history(symbols)

    all_data: list[pd.DataFrame] = []

    # ── 1. Backfill for brand-new symbols (no history at all) ─────────────────
    if new_symbols:
        backfill_start = (
            date.today() - timedelta(days=365 * YAHOO_DAILY_BACKFILL_YEARS)
        ).isoformat()
        backfill_end = date.today().isoformat()
        logger.info(
            "backfilling %d new symbols from %s to %s",
            len(new_symbols), backfill_start, backfill_end,
        )
        for symbol in new_symbols:
            df = fetch_daily_prices(symbol, backfill_start, backfill_end)
            if not df.empty:
                all_data.append(df)

    # ── 2. Incremental update for all symbols ─────────────────────────────────
    incremental_symbols = symbols if not new_symbols else [
        s for s in symbols if s not in new_symbols
    ]
    for symbol in incremental_symbols:
        df = fetch_daily_prices(symbol, incr_start, incr_end)
        if not df.empty:
            all_data.append(df)

    if all_data:
        prices_df = pd.concat(all_data, ignore_index=True)
        load_prices(prices_df)
    else:
        logger.warning("no price data collected")

    logger.info("daily_prices job finished")



if __name__ == "__main__":
    #python -m src.jobs.daily_prices --date 2026-06-17 2026-06-28

    # 1. Configurar credenciales ANTES de cualquier llamada a la API de Google
    # Usamos una ruta absoluta para asegurar que se encuentre el archivo sin importar desde dónde se ejecute el script.
    # __file__ -> daily_prices.py | .parents[2] -> src/ | "config" | "service-account.json"
    json_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'service-account.json')
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        logger.info("Loading credentials from: %s", json_path)
    else:
        logger.info("Not found service-account.json, using default credentials")

    # 2. Parsear argumentos de línea de comandos
    run_date = None
    end_date = None
    if "--date" in sys.argv:
        try:
            date_index = sys.argv.index("--date") + 1
            run_date = sys.argv[date_index]
            if date_index + 1 < len(sys.argv) and not sys.argv[date_index + 1].startswith('--'):
                end_date = sys.argv[date_index + 1]
        except (ValueError, IndexError):
            logger.error("El argumento --date debe ir seguido de una fecha en formato YYYY-MM-DD.")
            sys.exit(1)

    # 3. Ejecutar la lógica principal
    main(run_date=run_date, end_date_arg=end_date, limit=None)

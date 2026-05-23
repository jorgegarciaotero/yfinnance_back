# src/jobs/daily_sector_opportunities.py
"""
Daily job:
- Runs sector_opportunities_incremental.bsql against enriched_prices_table
- Produces up to 3 stock opportunities per (sector, setup_type), hard-capped at 75/day
- Score floor of 60/100 — rows below that quality are dropped entirely
- Momentum setup only fires when market breadth (% Bullish in universe) >= 50%
- Liquidity gate: close × volume > $10M/day
- DELETE + INSERT on max_date (idempotent)
- Runs AFTER daily_enrich
"""

import os
import sys
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    DATASET,
    SECTOR_OPPORTUNITIES_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_sector_opportunities")

SECTOR_SQL = Path(__file__).parents[1] / "sql" / "sector_opportunities_incremental.bsql"

SCHEMA = [
    bigquery.SchemaField("date",               "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("sector",             "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("industry",           "STRING"),
    bigquery.SchemaField("symbol",             "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("setup_type",         "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("close",              "FLOAT64"),
    bigquery.SchemaField("market_cap_bn",      "FLOAT64"),
    bigquery.SchemaField("rsi_14",             "FLOAT64"),
    bigquery.SchemaField("momentum_10d_pct",   "FLOAT64"),
    bigquery.SchemaField("dist_sma200_pct",    "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_high",  "FLOAT64"),
    bigquery.SchemaField("pct_from_52w_low",   "FLOAT64"),
    bigquery.SchemaField("pe_ratio",           "FLOAT64"),
    bigquery.SchemaField("recommendation_key", "STRING"),
    bigquery.SchemaField("score",              "FLOAT64"),
    bigquery.SchemaField("rank_in_sector",     "INT64"),
    bigquery.SchemaField("reason",             "STRING"),
    bigquery.SchemaField("company_name",       "STRING"),
    bigquery.SchemaField("company_url",        "STRING"),
    bigquery.SchemaField("company_summary",    "STRING"),
    bigquery.SchemaField("top_news_title",     "STRING"),
    bigquery.SchemaField("top_news_url",       "STRING"),
    bigquery.SchemaField("narrative",          "STRING"),
]


def ensure_table(client: bigquery.Client) -> None:
    try:
        table = client.get_table(SECTOR_OPPORTUNITIES_TABLE)
        existing_fields = {f.name for f in table.schema}
        new_fields = [f for f in SCHEMA if f.name not in existing_fields]
        if new_fields:
            table.schema = list(table.schema) + new_fields
            client.update_table(table, ["schema"])
            logger.info("sector_daily_opportunities table schema updated (+%d fields)", len(new_fields))
        else:
            logger.info("sector_daily_opportunities table exists")
    except Exception:
        table = bigquery.Table(SECTOR_OPPORTUNITIES_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="date")
        table.clustering_fields = ["sector", "setup_type"]
        client.create_table(table)
        logger.info("sector_daily_opportunities table created")


def run_sql(client: bigquery.Client, target_date: str | None = None) -> None:
    sql = SECTOR_SQL.read_text(encoding="utf-8")
    if target_date:
        sql = sql.replace(
            "SET max_date = (\n  SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.enriched_prices_table`\n);",
            f"SET max_date = DATE '{target_date}';",
        )
        logger.info("backfill mode: target_date=%s", target_date)
    logger.info("running sector_opportunities query...")
    job = client.query(sql)
    job.result()
    logger.info("sector_opportunities job completed (job_id=%s)", job.job_id)


def main() -> None:
    target_date = None
    if "--date" in sys.argv:
        target_date = sys.argv[sys.argv.index("--date") + 1]

    logger.info("starting daily_sector_opportunities")

    json_path = os.path.join("src", "config", "service-account.json")
    if os.path.exists(json_path):
        try:
            import json as _json
            with open(json_path) as f:
                creds = _json.load(f)
            if creds.get("private_key") and creds.get("client_email"):
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
        except Exception:
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

    client = bigquery.Client(project=PROJECT_ID)
    ensure_table(client)
    run_sql(client, target_date)

    logger.info("daily_sector_opportunities finished")


if __name__ == "__main__":
    main()

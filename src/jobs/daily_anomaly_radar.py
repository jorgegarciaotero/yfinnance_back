# src/jobs/daily_anomaly_radar.py
"""
Daily job: Anomaly Radar
- Detects 3 anomaly types across all sectors:
    Volume/Price Spike  |  Critical Oversold  |  Confirmed Momentum
- Scans only the last 40 days of enriched_prices_table (minimum cost).
- Computes 1d/3d/7d/30d changes with LAG(). Top 5 per sector and type.
- DELETE + INSERT on max_date (idempotent).
- Runs AFTER daily_enrich.
"""

import os
import sys
import logging
from pathlib import Path
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    DATASET,
    ANOMALY_RADAR_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_anomaly_radar")

ANOMALY_SQL = Path(__file__).parents[1] / "sql" / "anomaly_radar.bsql"

SCHEMA = [
    bigquery.SchemaField("date",           "DATE",    mode="REQUIRED"),
    bigquery.SchemaField("sector",         "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("industry",       "STRING"),
    bigquery.SchemaField("symbol",         "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("anomaly_type",   "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("close",          "FLOAT64"),
    bigquery.SchemaField("market_cap_bn",  "FLOAT64"),
    bigquery.SchemaField("rsi_14",         "FLOAT64"),
    bigquery.SchemaField("change_1d_pct",  "FLOAT64"),
    bigquery.SchemaField("change_3d_pct",  "FLOAT64"),
    bigquery.SchemaField("change_7d_pct",  "FLOAT64"),
    bigquery.SchemaField("change_30d_pct", "FLOAT64"),
    bigquery.SchemaField("volume_ratio",   "FLOAT64"),
    bigquery.SchemaField("score",           "FLOAT64"),
    bigquery.SchemaField("rank_in_sector",  "INT64"),
    bigquery.SchemaField("reason",          "STRING"),
    bigquery.SchemaField("company_name",    "STRING"),
    bigquery.SchemaField("cap_category",    "STRING"),
    bigquery.SchemaField("company_url",     "STRING"),
    bigquery.SchemaField("company_summary", "STRING"),
    bigquery.SchemaField("top_news_title",  "STRING"),
    bigquery.SchemaField("top_news_url",    "STRING"),
    bigquery.SchemaField("narrative",       "STRING"),
]


def ensure_table(client: bigquery.Client) -> None:
    try:
        table = client.get_table(ANOMALY_RADAR_TABLE)
        existing_fields = {f.name for f in table.schema}
        new_fields = [f for f in SCHEMA if f.name not in existing_fields]
        if new_fields:
            table.schema = list(table.schema) + new_fields
            client.update_table(table, ["schema"])
            logger.info("anomaly_radar table schema updated (+%d fields)", len(new_fields))
        else:
            logger.info("anomaly_radar table exists")
    except Exception:
        table = bigquery.Table(ANOMALY_RADAR_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(field="date")
        table.clustering_fields = ["anomaly_type", "sector"]
        client.create_table(table)
        logger.info("anomaly_radar table created")


def run_sql(client: bigquery.Client, target_date: str | None = None) -> None:
    sql = ANOMALY_SQL.read_text(encoding="utf-8")
    if target_date:
        sql = sql.replace(
            "SET max_date = (\n  SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.enriched_prices_table`\n);",
            f"SET max_date = DATE '{target_date}';",
        )
        logger.info("backfill mode: target_date=%s", target_date)
    logger.info("running anomaly_radar query...")
    job = client.query(sql)
    
    try:
        job.result()
        logger.info("anomaly_radar job completed (job_id=%s)", job.job_id)
    except Exception as e:
        logger.error("BigQuery job failed: %s", e)
        if getattr(job, "errors", None):
            logger.error("Job errors: %s", job.errors)
        # Forzamos que el Traceback final muestre el error exacto del SQL
        raise RuntimeError(f"BigQuery SQL Error: {getattr(job, 'errors', e)}") from e


def main() -> None:
    target_date = None
    if "--date" in sys.argv:
        target_date = sys.argv[sys.argv.index("--date") + 1]

    logger.info("starting daily_anomaly_radar")

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

    logger.info("daily_anomaly_radar finished")


if __name__ == "__main__":
    main()

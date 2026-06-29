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
    DAILY_PRICES_TABLE,
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
    bigquery.SchemaField("performance_1w_pct", "FLOAT64"),
    bigquery.SchemaField("performance_1m_pct", "FLOAT64"),
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
    
    try:
        job.result()
        logger.info("sector_opportunities job completed (job_id=%s)", job.job_id)
    except Exception as e:
        logger.error("BigQuery job failed: %s", e)
        if getattr(job, "errors", None):
            logger.error("Job errors: %s", job.errors)
        raise

def update_forward_performance(client: bigquery.Client) -> None:
    logger.info("updating forward performance (1w, 1m) for past opportunities...")
    # Utilizamos ventanas estrechas (BETWEEN) para no escanear toda la historia y ahorrar costes
    sql = f"""
    MERGE `{SECTOR_OPPORTUNITIES_TABLE}` O
    USING (
      SELECT 
        date AS opp_date,
        symbol,
        close AS opp_close,
        (
          SELECT P.close
          FROM `{DAILY_PRICES_TABLE}` P
          WHERE P.symbol = O.symbol 
            AND P.date >= DATE_ADD(O.date, INTERVAL 7 DAY)
            AND P.date <= DATE_ADD(O.date, INTERVAL 14 DAY)
          ORDER BY P.date ASC
          LIMIT 1
        ) AS close_1w,
        (
          SELECT P.close
          FROM `{DAILY_PRICES_TABLE}` P
          WHERE P.symbol = O.symbol 
            AND P.date >= DATE_ADD(O.date, INTERVAL 30 DAY)
            AND P.date <= DATE_ADD(O.date, INTERVAL 40 DAY)
          ORDER BY P.date ASC
          LIMIT 1
        ) AS close_1m
      FROM `{SECTOR_OPPORTUNITIES_TABLE}` O
      WHERE (performance_1w_pct IS NULL AND DATE_DIFF(CURRENT_DATE(), date, DAY) BETWEEN 7 AND 15)
         OR (performance_1m_pct IS NULL AND DATE_DIFF(CURRENT_DATE(), date, DAY) BETWEEN 30 AND 40)
    ) S
    ON O.date = S.opp_date AND O.symbol = S.symbol
    WHEN MATCHED THEN
      UPDATE SET 
        performance_1w_pct = COALESCE(O.performance_1w_pct, IF(S.close_1w IS NOT NULL, (S.close_1w - S.opp_close) / S.opp_close * 100, NULL)),
        performance_1m_pct = COALESCE(O.performance_1m_pct, IF(S.close_1m IS NOT NULL, (S.close_1m - S.opp_close) / S.opp_close * 100, NULL))
    """
    try:
        job = client.query(sql)
        job.result()
        logger.info("forward performance updated successfully")
    except Exception as e:
        logger.error("error updating forward performance: %s", e)


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
    update_forward_performance(client)

    logger.info("daily_sector_opportunities finished")


if __name__ == "__main__":
    main()

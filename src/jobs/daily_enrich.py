# src/jobs/daily_enrich.py
"""
Daily job:
- Si enriched_prices_table no existe o tiene datos muy antiguos: carga completa
  (CREATE OR REPLACE TABLE particionada por date).
- En caso normal: MERGE incremental sobre ventana de 30 días.
  Solo lee 260 días de daily_prices en lugar de los 13M de la tabla completa.
- Debe correr DESPUÉS de daily_prices.py
"""

import os
import logging
from datetime import date, timedelta
from pathlib import Path
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

from src.config.settings import PROJECT_ID, ENRICHED_PRICES_TABLE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_enrich")

SQL_FULL        = Path(__file__).parents[1] / "sql" / "enrich_prices.bsql"
SQL_INCREMENTAL = Path(__file__).parents[1] / "sql" / "enrich_prices_incremental.bsql"

# Si la tabla está más de N días desactualizada, hacemos carga completa
FULL_LOAD_THRESHOLD_DAYS = 7


def needs_full_load(client: bigquery.Client) -> bool:
    try:
        result = list(client.query(
            f"SELECT MAX(date) as max_date FROM `{ENRICHED_PRICES_TABLE}`"
        ).result())
        max_date = result[0].max_date
        if max_date is None:
            logger.info("tabla vacía → carga completa")
            return True
        days_behind = (date.today() - max_date).days
        if days_behind > FULL_LOAD_THRESHOLD_DAYS:
            logger.info("tabla desactualizada (%d días) → carga completa", days_behind)
            return True
        logger.info("tabla al día (último dato: %s) → incremental", max_date)
        return False
    except NotFound:
        logger.info("tabla no existe → carga completa")
        return True


def main() -> None:
    logger.info("starting daily_enrich")

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

    if needs_full_load(client):
        logger.info("ejecutando carga completa (enrich_prices.bsql)...")
        sql = SQL_FULL.read_text(encoding="utf-8")
    else:
        logger.info("ejecutando incremental (enrich_prices_incremental.bsql)...")
        sql = SQL_INCREMENTAL.read_text(encoding="utf-8")

    client.query(sql).result()
    logger.info("daily_enrich finished")


if __name__ == "__main__":
    main()

"""
Daily job: Export Cache (Fase 6)
- Se ejecuta al final del pipeline diario.
- Extrae los últimos datos de las tablas de BigQuery (Radar, Oportunidades, Macro).
- Los guarda como archivos JSON estáticos en un bucket de Google Cloud Storage.
- El frontend consumirá estos archivos JSON, evitando golpear BigQuery y reduciendo la latencia a milisegundos.
"""

import os
import json
import logging
import concurrent.futures
from datetime import date
from google.cloud import bigquery, storage

from src.config.settings import (
    PROJECT_ID,
    ANOMALY_RADAR_TABLE,
    SECTOR_OPPORTUNITIES_TABLE,
    MARKET_INSIGHTS_TABLE,
    COMPANY_NEWS_TABLE,
    DAILY_PRICES_TABLE,
    COMPANIES_TABLE
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_export_cache")

CACHE_BUCKET = "yfinance-cache"  # Asegúrate de que este bucket existe y tiene lectura pública

def _setup_credentials() -> None:
    json_path = os.path.join("src", "config", "service-account.json")
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path

def default_serializer(obj):
    """Serializador para fechas y datetimes que devuelve BigQuery"""
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def query_to_json(client: bigquery.Client, query: str) -> str:
    """Ejecuta una consulta y devuelve el resultado como string JSON."""
    rows = client.query(query).result()
    data = [dict(row) for row in rows]
    return json.dumps(data, default=default_serializer, ensure_ascii=False)

def upload_to_gcs(bucket_name: str, filename: str, content: str) -> None:
    """Sube el contenido JSON a Google Cloud Storage."""
    try:
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(filename)
        
        blob.upload_from_string(content, content_type="application/json")
        logger.info(f"✅ Archivo subido con éxito: gs://{bucket_name}/{filename}")
    except Exception as e:
        logger.error(f"❌ Error subiendo a GCS {filename}: {e}")

def upload_worker(args):
    """Función helper para subir archivos en paralelo"""
    upload_to_gcs(*args)

def main() -> None:
    logger.info("Starting daily_export_cache...")
    _setup_credentials()

    bq_client = bigquery.Client(project=PROJECT_ID)

    # 1. Exportar Anomaly Radar
    logger.info("Exportando Anomaly Radar...")
    query_radar = f"""
        SELECT * FROM `{ANOMALY_RADAR_TABLE}`
        WHERE date = (SELECT MAX(date) FROM `{ANOMALY_RADAR_TABLE}`)
        ORDER BY anomaly_type, score DESC
    """
    radar_json = query_to_json(bq_client, query_radar)
    upload_to_gcs(CACHE_BUCKET, "api/radar/latest.json", radar_json)

    # 2. Exportar Sector Opportunities
    logger.info("Exportando Sector Opportunities...")
    query_opps = f"""
        SELECT * FROM `{SECTOR_OPPORTUNITIES_TABLE}`
        WHERE date = (SELECT MAX(date) FROM `{SECTOR_OPPORTUNITIES_TABLE}`)
        ORDER BY sector, setup_type, rank_in_sector
    """
    opps_json = query_to_json(bq_client, query_opps)
    upload_to_gcs(CACHE_BUCKET, "api/opportunities/latest.json", opps_json)

    # 3. Exportar Market Insights (Termómetro Macro)
    logger.info("Exportando Market Insights...")
    query_macro = f"""
        SELECT * FROM `{MARKET_INSIGHTS_TABLE}`
        WHERE date = (SELECT MAX(date) FROM `{MARKET_INSIGHTS_TABLE}`)
        ORDER BY source_type, source_name
    """
    macro_json = query_to_json(bq_client, query_macro)
    upload_to_gcs(CACHE_BUCKET, "api/macro/latest.json", macro_json)

    # 4. Exportar Noticias agrupadas por símbolo (Patrón 1 archivo = 1 endpoint)
    logger.info("Exportando Company News por símbolo...")
    query_news = f"""
        SELECT symbol, source, title, url, published_at, summary, publisher
        FROM `{COMPANY_NEWS_TABLE}`
        WHERE date = (SELECT MAX(date) FROM `{COMPANY_NEWS_TABLE}`)
    """
    news_rows = bq_client.query(query_news).result()
    
    news_by_symbol = {}
    for row in news_rows:
        sym = row["symbol"]
        if sym not in news_by_symbol:
            news_by_symbol[sym] = []
        news_by_symbol[sym].append(dict(row))
        
    for sym, items in news_by_symbol.items():
        # Cada símbolo tendrá su propio archivo, ej: api/news/NVDA.json
        file_path = f"api/news/{sym}.json"
        content = json.dumps(items, default=default_serializer, ensure_ascii=False)
        upload_to_gcs(CACHE_BUCKET, file_path, content)

    # 5. Exportar Catálogo de Compañías (Para el buscador global del frontend)
    logger.info("Exportando lista completa de compañías...")
    query_companies = f"""
        SELECT symbol, short_name as company_name, sector, industry, market_cap
        FROM `{COMPANIES_TABLE}`
        WHERE is_active = TRUE
    """
    companies_json = query_to_json(bq_client, query_companies)
    upload_to_gcs(CACHE_BUCKET, "api/companies/latest.json", companies_json)

    # 6. Exportar Histórico de Precios (1 año) por símbolo (Vista Detalle para Gráficos)
    logger.info("Extrayendo histórico de precios de BigQuery (último año para TODAS las compañías)...")
    query_history = f"""
        SELECT symbol, date, close, volume
        FROM `{DAILY_PRICES_TABLE}`
        WHERE date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1 YEAR)
    """
    history_rows = bq_client.query(query_history).result()
    
    history_by_symbol = {}
    for row in history_rows:
        sym = row["symbol"]
        if sym not in history_by_symbol:
            history_by_symbol[sym] = []
        # Solo exportamos lo necesario para el gráfico para minimizar el peso
        history_by_symbol[sym].append({
            "date": row["date"].isoformat(),
            "close": row["close"],
            "volume": row["volume"]
        })

    logger.info(f"Subiendo históricos a GCS en paralelo para {len(history_by_symbol)} empresas...")
    upload_tasks = []
    for sym, items in history_by_symbol.items():
        file_path = f"api/history/{sym}.json"
        content = json.dumps(items, ensure_ascii=False) # items ya tiene ISO strings
        upload_tasks.append((CACHE_BUCKET, file_path, content))
        
    # Subir en paralelo usando 50 hilos (sube los ~2700 archivos a GCS en segundos)
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        executor.map(upload_worker, upload_tasks)

    # (Opcional) Guardar un timestamp de última actualización
    metadata = {"last_updated": date.today().isoformat(), "status": "ok"}
    upload_to_gcs(CACHE_BUCKET, "api/status.json", json.dumps(metadata))

    logger.info("daily_export_cache finished.")

if __name__ == "__main__":
    main()

# src/jobs/daily_newsletter.py
"""
Job Diario: Inteligencia Macro y "Termómetro de Mercado"
- Obtiene los últimos vídeos de analistas clave de YouTube mediante RSS.
- Extrae transcripciones con youtube-transcript-api.
- Analiza el texto con Gemini 2.5 Flash (Vertex AI) para extraer insights estructurados en JSON.
- Escribe los resultados en yfinance_raw.market_insights de forma idempotente.
"""

import os
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import feedparser


def _normalize_timestamp(value) -> str | None:
    """Convert any common timestamp representation to BigQuery-compatible
    'YYYY-MM-DD HH:MM:SS' UTC. Returns None if value can't be parsed."""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        dt = None
        # Try ISO 8601 first (YouTube format)
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            pass
        # Try RFC 2822 (RSS format: 'Sat, 23 May 2026 12:32:36 GMT')
        if dt is None:
            try:
                dt = parsedate_to_datetime(s)
            except (TypeError, ValueError):
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
from google.cloud import bigquery
from youtube_transcript_api import YouTubeTranscriptApi
from google import genai
from google.genai import types

from src.config.settings import PROJECT_ID, DATASET, MARKET_INSIGHTS_TABLE

VERTEX_LOCATION = "europe-west1"

logger = logging.getLogger("daily_newsletter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

SCHEMA = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("source_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("title", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("url", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("published_at", "TIMESTAMP", mode="NULLABLE"),
    bigquery.SchemaField("market_bias", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("macro_event", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("smart_money_signals", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("key_levels", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("mentioned_tickers", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("tesis_principal", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("raw_text_length", "INTEGER", mode="NULLABLE"),
]

CHANNELS = [
    # Grupo Hispanohablante
    {"id": "UC4NCu44AQXnhscxeDrdgvow", "name": "Alberto Iturralde", "profile": "Foco en psicología de masas, 'manos fuertes' (engaños de mercado) y niveles técnicos clave."},
    {"id": "UC_jlKkXfh49iBLbS9cbddpQ", "name": "Gustavo Martínez", "profile": "Foco en macroeconomía, tipos de interés reales, oro, bitcoin y ciclo económico."},
    {"id": "UCll9xzATuTnqGv68xK8tpJg", "name": "Negocios TV", "profile": "Foco en resumen de noticias geopolíticas, bancos centrales y flujo diario."},
    # Grupo Anglosajón
    {"id": "UCFk1qCySNf2FIzIidVVW81A", "name": "The Macro Compass", "profile": "Foco en análisis de liquidez bancaria global, repo market y modelos macroeconómicos institucionales."},
    {"id": "UCZ-J2m1AUSLnifUEKam5_dA", "name": "Verified Investing", "profile": "Foco en análisis técnico puro, niveles de precios psicológicos, conteo de ciclos y sentimiento extremo."},
    {"id": "UCu0L0QCubkYD3Cd9jSdxTNQ", "name": "42 Macro",          "profile": "Foco en regímenes de mercado (Goldilocks, Deflation, Inflation, Reflation) y flujos de capital institucionales."},
]

RSS_FEEDS = [
    {"id": "https://www.cnbc.com/id/20910258/device/rss/rss.html",                       "name": "CNBC Economy",        "profile": "Foco en indicadores económicos globales, inflación y bancos centrales."},
    {"id": "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed",             "name": "WSJ Economy",         "profile": "Análisis profundo de política monetaria, mercados laborales y geopolítica económica."},
    {"id": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse",                "name": "MarketWatch Markets", "profile": "Pulso diario de mercados: renta variable, materias primas, divisas y bonos."},
]

class GlobalMarketAnalyzer:
    SYSTEM_PROMPT_TEMPLATE = (
        'Eres el motor de análisis de un "Hedge Fund" cuantitativo. Tu tarea es extraer inteligencia de mercado pura y accionable del siguiente texto proporcionado por la fuente: {source_name}.\n\n'
        'Contexto de la fuente: {source_profile}\n\n'
        'Instrucción de Idioma Crítica: Independientemente de si el texto original está en inglés, español u otro idioma, debes generar toda tu respuesta en ESPAÑOL.\n\n'
        'Analiza el texto y devuelve ÚNICAMENTE un JSON válido con la siguiente estructura. No incluyas markdown ni texto fuera del JSON:\n'
        '{{\n'
        '  "market_bias": "Bullish | Bearish | Neutral | N/A",\n'
        '  "macro_event": "Evento económico clave mencionado (ej. Fed, IPC, Nóminas). N/A si no hay.",\n'
        '  "smart_money_signals": "Resumen en 1 frase sobre flujos institucionales, engaños de mercado o liquidez.",\n'
        '  "key_levels": [{{"activo": "SP500", "soporte": 5100, "resistencia": 5200}}],\n'
        '  "activos_mencionados": ["SP500", "Oro", "NVDA"],\n'
        '  "tesis_principal": "Resumen profundo y detallado de la tesis principal (3 a 5 frases), explicando el por qué de su visión y su contexto."\n'
        '}}\n'
    )
    
    MODEL_NAME = "gemini-2.5-flash"

    def __init__(self):
        try:
            self.client = genai.Client(vertexai=True, project=PROJECT_ID, location=VERTEX_LOCATION)
        except Exception as e:
            logger.warning(f"No se pudo inicializar Vertex AI Gemini: {e}. Análisis LLM omitido.")
            self.client = None

    def _get_latest_video_rss(self, channel_id: str):
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                xml_data = response.read()
            root = ET.fromstring(xml_data)
            ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
            entry = root.find('atom:entry', ns)
            if entry is not None:
                return (entry.find('yt:videoId', ns).text, entry.find('atom:title', ns).text, entry.find('atom:published', ns).text)
        except Exception as e:
            logger.error(f"Error leyendo RSS del canal {channel_id}: {e}")
        return None, None, None

    _yt_api = YouTubeTranscriptApi()

    def _get_transcript(self, video_id: str) -> str:
        try:
            fetched = self._yt_api.fetch(video_id, languages=['es', 'en'])
            return " ".join(snippet.text for snippet in fetched.snippets)
        except Exception as e:
            logger.warning(f"transcript fail for {video_id}: {e}")
            return ""

    def analyze_video(self, channel: dict) -> dict:
        video_id, title, published_str = self._get_latest_video_rss(channel["id"])
        if not video_id: return None

        logger.info(f"Analizando último vídeo de {channel['name']}: {title}")
        transcript = self._get_transcript(video_id)
        if not transcript or not self.client: return None

        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(source_name=channel["name"], source_profile=channel["profile"])

        try:
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=f"Transcripción:\n\n{transcript[:20000]}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            parsed = json.loads(response.text)
            return {
                "source_name": channel["name"], "title": title, "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": _normalize_timestamp(published_str), "raw_text_length": len(transcript),
                "market_bias": parsed.get("market_bias", "N/A"), "macro_event": parsed.get("macro_event", "N/A"),
                "smart_money_signals": parsed.get("smart_money_signals"), "tesis_principal": parsed.get("tesis_principal"),
                "key_levels": json.dumps(parsed.get("key_levels", []), ensure_ascii=False),
                "mentioned_tickers": ",".join(parsed.get("activos_mencionados", []))
            }
        except Exception as e:
            logger.error(f"Error procesando LLM para {channel['name']}: {e}")
            return None

    def analyze_rss(self, feed: dict) -> dict:
        logger.info(f"Analizando RSS de {feed['name']}...")
        parsed = feedparser.parse(feed["id"])
        if getattr(parsed, 'bozo', 0) == 1 or not parsed.entries:
            logger.warning(f"No se pudo leer RSS de {feed['name']}")
            return None

        combined_text = ""
        for i, entry in enumerate(parsed.entries[:3]):
            combined_text += f"Noticia {i+1}: {entry.get('title', '')}\nResumen: {entry.get('summary', '')}\n\n"

        if not combined_text or not self.client: return None

        system_prompt = self.SYSTEM_PROMPT_TEMPLATE.format(source_name=feed["name"], source_profile=feed["profile"])

        try:
            response = self.client.models.generate_content(
                model=self.MODEL_NAME,
                contents=f"Titulares y resúmenes:\n\n{combined_text[:10000]}",
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=2048,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                ),
            )
            parsed_json = json.loads(response.text)

            return {
                "source_name": feed["name"], "title": "Top Noticias Macro", "url": feed["id"],
                "published_at": _normalize_timestamp(parsed.entries[0].get("published")) or _normalize_timestamp(datetime.now(timezone.utc)),
                "raw_text_length": len(combined_text),
                "market_bias": parsed_json.get("market_bias", "N/A"), "macro_event": parsed_json.get("macro_event", "N/A"),
                "smart_money_signals": parsed_json.get("smart_money_signals"), "tesis_principal": parsed_json.get("tesis_principal"),
                "key_levels": json.dumps(parsed_json.get("key_levels", []), ensure_ascii=False),
                "mentioned_tickers": ",".join(parsed_json.get("activos_mencionados", []))
            }
        except Exception as e:
            logger.error(f"Error procesando LLM para RSS {feed['name']}: {e}")
            return None

def ensure_table(client: bigquery.Client):
    try:
        client.get_table(MARKET_INSIGHTS_TABLE)
    except Exception:
        logger.info(f"Creando tabla {MARKET_INSIGHTS_TABLE} en BigQuery...")
        table = bigquery.Table(MARKET_INSIGHTS_TABLE, schema=SCHEMA)
        table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="date")
        table.clustering_fields = ["source_type", "source_name"]
        client.create_table(table)

def main():
    json_path = os.path.join("src", "config", "service-account.json")
    if os.path.exists(json_path):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path

    client = bigquery.Client(project=PROJECT_ID)
    ensure_table(client)
    
    analyzer = GlobalMarketAnalyzer()
    today_str = date.today().isoformat()
    rows_to_insert = []
    
    for channel in CHANNELS:
        data = analyzer.analyze_video(channel)
        if not data: continue
        rows_to_insert.append({"date": today_str, "source_type": "youtube", **data})

    for feed in RSS_FEEDS:
        data = analyzer.analyze_rss(feed)
        if not data: continue
        rows_to_insert.append({"date": today_str, "source_type": "rss", **data})
        
    if rows_to_insert:
        # Idempotent: delete today's rows, then batch-insert (load job, no streaming buffer).
        delete_query = f"DELETE FROM `{MARKET_INSIGHTS_TABLE}` WHERE date = '{today_str}' AND source_type IN ('youtube', 'rss')"
        client.query(delete_query).result()
        logger.info(f"Limpiados datos previos del día ({len(rows_to_insert)} listos para insertar).")

        load_config = bigquery.LoadJobConfig(
            schema=SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        job = client.load_table_from_json(rows_to_insert, MARKET_INSIGHTS_TABLE, job_config=load_config)
        job.result()
        if job.errors:
            logger.error(f"Errores cargando en BQ: {job.errors}")
        else:
            logger.info(f"✅ Éxito: {len(rows_to_insert)} insights insertados.")

if __name__ == "__main__":
    main()
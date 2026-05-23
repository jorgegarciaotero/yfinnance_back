# src/jobs/daily_newsletter.py
"""
Job Diario: Inteligencia Macro y "Termómetro de Mercado"
- Obtiene los últimos vídeos de analistas clave de YouTube mediante RSS.
- Extrae transcripciones con youtube-transcript-api.
- Analiza el texto con Claude Haiku para extraer insights estructurados en JSON.
- Escribe los resultados en yfinance_raw.market_insights de forma idempotente.
"""

import os
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
import feedparser
from google.cloud import bigquery
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

from src.config.settings import PROJECT_ID, DATASET

logger = logging.getLogger("daily_newsletter")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

MARKET_INSIGHTS_TABLE = f"{PROJECT_ID}.{DATASET}.market_insights"

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
    {"id": "UC-r4G3OAgI-w_i_M5cK2b-g", "name": "Bolsacava", "profile": "Foco en liquidez de la Fed, niveles del S&P 500 y pautas estacionales."},
    {"id": "UCrp_2r_a2ekZc38G3s-xT-A", "name": "Alberto Iturralde", "profile": "Foco en psicología de masas, 'manos fuertes' (engaños de mercado) y niveles técnicos clave."},
    {"id": "UCkAN2Ffg1-51oX92AI2-p2g", "name": "Gustavo Martínez", "profile": "Foco en macroeconomía, tipos de interés reales, oro, bitcoin y ciclo económico."},
    {"id": "UC6s06S22l9iL2aX-q7t_Y-w", "name": "Negocios TV", "profile": "Foco en resumen de noticias geopolíticas, bancos centrales y flujo diario."},
    # Grupo Anglosajón
    {"id": "UCpT2WayH_V3-CFmF1KIO3GQ", "name": "The Macro Compass", "profile": "Foco en análisis de liquidez bancaria global, repo market y modelos macroeconómicos institucionales."},
    {"id": "UC_G53K_pl-T2fG3J1i2L-AQ", "name": "Lyn Alden", "profile": "Foco en macroeconomía estructural, crisis de deuda, energía, divisas y activos refugio."},
    {"id": "UC8k19-rEah29R-2A45XwVfQ", "name": "Verified Investing", "profile": "Foco en análisis técnico puro, niveles de precios psicológicos, conteo de ciclos y sentimiento extremo."},
    {"id": "UCFN32012CIk_i13n2fQ5vjQ", "name": "42 Macro", "profile": "Foco en regímenes de mercado (Goldilocks, Deflation, Inflation, Reflation) y flujos de capital institucionales."}
]

RSS_FEEDS = [
    {"id": "https://finance.yahoo.com/news/rssindex", "name": "Yahoo Finance Macro", "profile": "Foco en noticias macroeconómicas generales, bolsa y decisiones de la Fed."},
    {"id": "https://search.cnbc.com/rs/search/combinedcms/view.xml?profile=12000000&id=10000664", "name": "CNBC Economy", "profile": "Foco en indicadores económicos globales, inflación y bancos centrales."}
]

class GlobalMarketAnalyzer:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            logger.warning("No se encontró ANTHROPIC_API_KEY. El análisis con LLM será omitido.")
        self.client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else None

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

    def _get_transcript(self, video_id: str) -> str:
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['es', 'en'])
            return " ".join([entry['text'] for entry in transcript_list])
        except Exception:
            return ""

    def analyze_video(self, channel: dict) -> dict:
        video_id, title, published_str = self._get_latest_video_rss(channel["id"])
        if not video_id: return None

        logger.info(f"Analizando último vídeo de {channel['name']}: {title}")
        transcript = self._get_transcript(video_id)
        if not transcript or not self.client: return None

        system_prompt = (
            'Eres el motor de análisis de un "Hedge Fund" cuantitativo. Tu tarea es extraer inteligencia de mercado pura y accionable del siguiente texto proporcionado por la fuente: {source_name}.\n\n'
            'Contexto de la fuente: {source_profile}\n\n'
            'Instrucción de Idioma Crítica: Independientemente de si el texto original está en inglés, español u otro idioma, debes generar toda tu respuesta en ESPAÑOL.\n\n'
            'Analiza el texto y devuelve ÚNICAMENTE un JSON válido con la siguiente estructura. No incluyas markdown ni texto fuera del JSON:\n'
            '{\n'
            '  "market_bias": "Bullish | Bearish | Neutral | N/A",\n'
            '  "macro_event": "Evento económico clave mencionado (ej. Fed, IPC, Nóminas). N/A si no hay.",\n'
            '  "smart_money_signals": "Resumen en 1 frase sobre flujos institucionales, engaños de mercado o liquidez.",\n'
            '  "key_levels": [{"activo": "SP500", "soporte": 5100, "resistencia": 5200}],\n'
            '  "activos_mencionados": ["SP500", "Oro", "NVDA"],\n'
            '  "tesis_principal": "Resumen ejecutivo de alto valor en máximo 2 frases."\n'
            '}'
        ).format(source_name=channel["name"], source_profile=channel["profile"])

        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307", max_tokens=1024, system=system_prompt,
                messages=[{"role": "user", "content": f"Transcripción:\n\n{transcript[:20000]}"}]
            )
            content = response.content[0].text
            start, end = content.find('{'), content.rfind('}') + 1
            if start == -1 or end == 0: raise ValueError("JSON no encontrado en la respuesta del LLM")
            
            parsed = json.loads(content[start:end])
            return {
                "source_name": channel["name"], "title": title, "url": f"https://www.youtube.com/watch?v={video_id}",
                "published_at": published_str, "raw_text_length": len(transcript),
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

        system_prompt = (
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
            '  "tesis_principal": "Resumen ejecutivo de alto valor en máximo 2 frases."\n'
            '}}'
        ).format(source_name=feed["name"], source_profile=feed["profile"])

        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307", max_tokens=1024, system=system_prompt,
                messages=[{"role": "user", "content": f"Titulares y resúmenes:\n\n{combined_text[:10000]}"}]
            )
            content = response.content[0].text
            start, end = content.find('{'), content.rfind('}') + 1
            if start == -1 or end == 0: raise ValueError("JSON no encontrado")
            
            parsed_json = json.loads(content[start:end])
            
            return {
                "source_name": feed["name"], "title": "Top Noticias Macro", "url": feed["id"],
                "published_at": parsed.entries[0].get("published", datetime.now(timezone.utc).isoformat()), 
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
            
        try:
            dt = datetime.fromisoformat(data["published_at"].replace('Z', '+00:00'))
        except Exception:
            dt = datetime.now(timezone.utc)
            
        rows_to_insert.append({
            "date": today_str, "source_type": "youtube", **data
        })
        
    for feed in RSS_FEEDS:
        data = analyzer.analyze_rss(feed)
        if not data: continue
            
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(data["published_at"])
        except Exception:
            dt = datetime.now(timezone.utc)
            
        rows_to_insert.append({
            "date": today_str, "source_type": "rss", **data
        })
        
    if rows_to_insert:
        # Operación idempotente: Borramos SOLO los datos de HOY antes de insertar para evitar 
        # filas duplicadas si el script se ejecuta varias veces. Los días anteriores NO se tocan.
        delete_query = f"DELETE FROM `{MARKET_INSIGHTS_TABLE}` WHERE date = '{today_str}' AND source_type IN ('youtube', 'rss')"
        client.query(delete_query).result()
        logger.info(f"Limpiados datos previos del día ({len(rows_to_insert)} listos para insertar).")
        
        errors = client.insert_rows_json(MARKET_INSIGHTS_TABLE, rows_to_insert)
        if errors:
            logger.error(f"Errores insertando en BQ: {errors}")
        else:
            logger.info(f"✅ Éxito: {len(rows_to_insert)} insights insertados.")

if __name__ == "__main__":
    main()
# src/jobs/daily_narrative.py
"""
Daily job: Narrative Enrichment (Phase 4)
- Runs AFTER daily_news_enrich
- For each symbol in today's anomaly_radar + sector_daily_opportunities:
    1. Picks the top 3 news articles from company_news (Yahoo Finance first)
    2. Calls Claude Haiku to generate a 3-sentence dealflow narrative
- MERGEs top_news_title, top_news_url, narrative into both output tables
- Cost-optimised: only calls LLM for symbols already selected by the radar/sector jobs
"""

import os
import time
import logging
from datetime import date

from google import genai
from google.genai import types
from google.cloud import bigquery

from src.config.settings import (
    PROJECT_ID,
    ANOMALY_RADAR_TABLE,
    SECTOR_OPPORTUNITIES_TABLE,
    COMPANY_NEWS_TABLE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("daily_narrative")

# ── Config ────────────────────────────────────────────────────────────────────

MODEL           = "gemini-2.5-flash"
VERTEX_LOCATION = "europe-west1"
MAX_NEWS        = 2     # Reduced context to save input tokens
LLM_DELAY       = 0.3   # seconds between API calls

SYSTEM_PROMPT = (
    "You are a concise financial analyst writing dealflow notes for institutional investors. "
    "Write in plain English. Be specific and data-driven. No fluff."
)

USER_TEMPLATE = """\
Stock: {company_name} ({symbol})
Signal type: {signal_type}
Technical data: {reason}
Business: {company_summary}

Recent news:
{news_block}

Write a 3-sentence narrative (max 70 words) that explains the KEY CATALYST driving this stock. \
Start with the main market driver, then supporting evidence, then risk/outlook. \
Use the news headlines as primary evidence — do not repeat the technical data."""


# ── BigQuery helpers ──────────────────────────────────────────────────────────

def _setup_credentials() -> None:
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


def get_today_symbols(client: bigquery.Client) -> tuple[dict[str, dict], str, str]:
    """
    Returns ({symbol: {company_name, reason, company_summary, signal_type}}, max_date_radar, max_date_opps).
    radar and opps may have different MAX(date); each merge needs its own.
    """
    sql = f"""
    WITH radar AS (
      SELECT symbol, company_name, company_summary, reason,
             anomaly_type AS signal_type, CAST(date AS STRING) AS row_date,
             'radar' AS src
      FROM `{ANOMALY_RADAR_TABLE}`
      WHERE date = (SELECT MAX(date) FROM `{ANOMALY_RADAR_TABLE}`)
    ),
    opps AS (
      SELECT symbol, company_name, company_summary, reason,
             setup_type AS signal_type, CAST(date AS STRING) AS row_date,
             'opps' AS src
      FROM `{SECTOR_OPPORTUNITIES_TABLE}`
      WHERE date = (SELECT MAX(date) FROM `{SECTOR_OPPORTUNITIES_TABLE}`)
    )
    SELECT * FROM radar UNION ALL SELECT * FROM opps
    """
    rows = list(client.query(sql).result())
    if not rows:
        return {}, "", ""

    max_date_radar = ""
    max_date_opps = ""
    symbols: dict[str, dict] = {}
    for r in rows:
        if r["src"] == "radar" and not max_date_radar:
            max_date_radar = r["row_date"]
        if r["src"] == "opps" and not max_date_opps:
            max_date_opps = r["row_date"]
        sym = r["symbol"]
        if sym not in symbols:          # first occurrence wins (radar UNION first)
            symbols[sym] = {
                "company_name":    r["company_name"] or sym,
                "company_summary": (r["company_summary"] or "")[:250],
                "reason":          r["reason"] or "",
                "signal_type":     r["signal_type"] or "",
            }
    return symbols, max_date_radar, max_date_opps


def get_news_for_symbols(
    client: bigquery.Client,
    symbols: list[str],
    max_date: str,
) -> dict[str, list[dict]]:
    """Returns {symbol: [{"title", "url", "summary", "source"}]}."""
    if not symbols:
        return {}

    sym_list = ", ".join(f"'{s}'" for s in symbols)
    sql = f"""
    SELECT symbol, source, title, url, summary, published_at
    FROM `{COMPANY_NEWS_TABLE}`
    WHERE date = '{max_date}'
      AND symbol IN ({sym_list})
      AND title IS NOT NULL
      AND url IS NOT NULL
    ORDER BY
      symbol,
      CASE source WHEN 'yahoo_finance' THEN 0 ELSE 1 END,
      published_at DESC
    """
    result: dict[str, list[dict]] = {}
    for r in client.query(sql).result():
        sym = r["symbol"]
        if sym not in result:
            result[sym] = []
        if len(result[sym]) < MAX_NEWS:
            result[sym].append({
                "title":   r["title"],
                "url":     r["url"],
                "summary": (r["summary"] or "")[:200],
                "source":  r["source"],
            })
    return result


# ── Claude narrative generation ───────────────────────────────────────────────

def _build_news_block(news_items: list[dict]) -> str:
    if not news_items:
        return "(no recent news available)"
    lines = []
    for i, item in enumerate(news_items, 1):
        title = item["title"]
        summary = item["summary"]
        source = item["source"]
        line = f"{i}. [{source}] {title}"
        if summary:
            line += f": {summary}"
        lines.append(line)
    return "\n".join(lines)


def generate_narrative(
    llm_client: genai.Client,
    symbol: str,
    data: dict,
    news_items: list[dict],
) -> str:
    if not news_items:
        return "Purely technical or speculative movement. No recent news detected as a catalyst."

    news_block = _build_news_block(news_items)
    user_msg = USER_TEMPLATE.format(
        company_name    = data["company_name"],
        symbol          = symbol,
        signal_type     = data["signal_type"],
        reason          = data["reason"],
        company_summary = data["company_summary"] or "N/A",
        news_block      = news_block,
    )
    try:
        response = llm_client.models.generate_content(
            model=MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=500,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return (response.text or "").strip()
    except Exception as exc:
        logger.warning("[gemini] %s — %s", symbol, exc)
        return ""


# ── BigQuery MERGE ────────────────────────────────────────────────────────────

def merge_narratives(
    client: bigquery.Client,
    table: str,
    narratives: list[dict],  # [{symbol, top_news_title, top_news_url, narrative}]
    max_date: str,
) -> None:
    """
    Merges narrative columns into the target table for max_date.
    Uses parameterised query (ARRAY<STRUCT>) to avoid SQL-injection / escaping bugs.
    """
    if not narratives:
        return

    struct_type = bigquery.StructQueryParameterType(
        bigquery.ScalarQueryParameterType("STRING", name="symbol"),
        bigquery.ScalarQueryParameterType("STRING", name="top_news_title"),
        bigquery.ScalarQueryParameterType("STRING", name="top_news_url"),
        bigquery.ScalarQueryParameterType("STRING", name="narrative"),
    )
    rows = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("symbol",         "STRING", n["symbol"]),
            bigquery.ScalarQueryParameter("top_news_title", "STRING", n["top_news_title"] or ""),
            bigquery.ScalarQueryParameter("top_news_url",   "STRING", n["top_news_url"] or ""),
            bigquery.ScalarQueryParameter("narrative",      "STRING", n["narrative"] or ""),
        )
        for n in narratives
    ]
    sql = f"""
    MERGE `{table}` T
    USING UNNEST(@narratives) S
      ON T.date = @max_date AND T.symbol = S.symbol
    WHEN MATCHED THEN UPDATE SET
      T.top_news_title = S.top_news_title,
      T.top_news_url   = S.top_news_url,
      T.narrative      = S.narrative
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("narratives", struct_type, rows),
                bigquery.ScalarQueryParameter("max_date", "DATE", max_date),
            ],
        ),
    )
    job.result()
    logger.info("merged narratives into %s (%d rows)", table, len(narratives))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("starting daily_narrative")
    _setup_credentials()

    bq = bigquery.Client(project=PROJECT_ID)
    ac = genai.Client(vertexai=True, project=PROJECT_ID, location=VERTEX_LOCATION)

    # 1. Get today's symbols from both output tables (each may have its own max_date)
    symbols_data, max_date_radar, max_date_opps = get_today_symbols(bq)
    if not symbols_data:
        logger.info("no symbols found for today — skipping")
        return
    logger.info("found %d unique symbols (radar=%s, opps=%s)",
                len(symbols_data), max_date_radar, max_date_opps)

    # 2. Fetch news using the most recent date between both tables
    news_date = max(d for d in (max_date_radar, max_date_opps) if d)
    news_by_symbol = get_news_for_symbols(bq, list(symbols_data.keys()), news_date)
    logger.info("news available for %d/%d symbols", len(news_by_symbol), len(symbols_data))

    # 3. Generate narratives
    narratives: list[dict] = []
    total = len(symbols_data)
    for i, (symbol, data) in enumerate(symbols_data.items(), 1):
        news_items = news_by_symbol.get(symbol, [])
        logger.info("[%d/%d] generating narrative for %s (%d news items)",
                    i, total, symbol, len(news_items))

        narrative = generate_narrative(ac, symbol, data, news_items)

        top_news = news_items[0] if news_items else {}
        narratives.append({
            "symbol":         symbol,
            "top_news_title": top_news.get("title", ""),
            "top_news_url":   top_news.get("url", ""),
            "narrative":      narrative,
        })

        if LLM_DELAY:
            time.sleep(LLM_DELAY)

    # 4. Merge into each table with its own max_date
    if max_date_radar:
        merge_narratives(bq, ANOMALY_RADAR_TABLE, narratives, max_date_radar)
    if max_date_opps:
        merge_narratives(bq, SECTOR_OPPORTUNITIES_TABLE, narratives, max_date_opps)

    logger.info("daily_narrative finished — %d narratives written", len(narratives))


if __name__ == "__main__":
    main()

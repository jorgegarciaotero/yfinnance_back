# src/jobs/ai_analyst.py
"""
AI Analyst job:
- Filter top 10 stock candidates from enriched_prices_table
- Analyze recent YouTube videos about each ticker
- Generate AI-powered insights (sentiment, price targets, risks)
- Store results in ai_insights table
"""

import sys
import os
sys.path.append(os.getcwd())

from datetime import datetime, date, timedelta, timezone
import logging
import pandas as pd
from google.cloud import bigquery
from youtube_transcript_api import YouTubeTranscriptApi
from googleapiclient.discovery import build
import anthropic
import time
from dotenv import load_dotenv

from src.config.settings import PROJECT_ID, DATASET

# Load environment variables from .env file
load_dotenv()

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("ai_analyst")

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
ENRICHED_PRICES_TABLE = f"{PROJECT_ID}.{DATASET}.enriched_prices_table"
AI_INSIGHTS_TABLE = f"{PROJECT_ID}.{DATASET}.ai_insights"

# YouTube API (usar variable de entorno YOUTUBE_API_KEY)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

# Anthropic API (buscar en múltiples ubicaciones)
# Prioridad: ANTHROPIC_API_KEY > API_KEY (Claude Code) > archivo de config
ANTHROPIC_API_KEY = (
    os.environ.get("ANTHROPIC_API_KEY") or
    os.environ.get("API_KEY") or  # Claude Code usa esta variable
    None
)


# ─────────────────────────────────────────────
# BigQuery helpers
# ─────────────────────────────────────────────
def ensure_table() -> None:
    """
    Ensure BigQuery ai_insights table exists. If not, create it.
    """
    client = bigquery.Client(project=PROJECT_ID)

    schema = [
        bigquery.SchemaField("analysis_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),

        # Market data context
        bigquery.SchemaField("current_price", "FLOAT64"),
        bigquery.SchemaField("volume", "INT64"),
        bigquery.SchemaField("market_cap", "INT64"),
        bigquery.SchemaField("rsi_14", "FLOAT64"),
        bigquery.SchemaField("momentum_10d", "FLOAT64"),

        # AI Analysis results
        bigquery.SchemaField("sentiment", "STRING"),  # Bullish/Bearish/Neutral
        bigquery.SchemaField("target_price", "FLOAT64"),
        bigquery.SchemaField("risks", "STRING"),
        bigquery.SchemaField("summary", "STRING"),

        # Video sources
        bigquery.SchemaField("video_count", "INT64"),
        bigquery.SchemaField("video_titles", "STRING"),

        bigquery.SchemaField("created_at", "TIMESTAMP"),
    ]

    try:
        client.create_table(
            bigquery.Table(AI_INSIGHTS_TABLE, schema=schema),
            exists_ok=True,
        )
        logger.info("ai_insights table ready")
    except Exception as e:
        logger.error(f"Error creating table: {e}")
        raise


def get_top_candidates(limit: int = 10) -> pd.DataFrame:
    """
    Query enriched_prices_table to get top stock candidates based on:
    - High liquidity (volume > 500000)
    - Technical opportunity (rsi_14 < 30 OR momentum_10d > 0.05)
    - Large market cap (for reliability)

    Returns:
        DataFrame with top candidates
    """
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT
        symbol,
        date,
        close as current_price,
        volume,
        market_cap,
        rsi_14,
        momentum_10d,
        sector,
        industry
    FROM `{ENRICHED_PRICES_TABLE}`
    WHERE date = (SELECT MAX(date) FROM `{ENRICHED_PRICES_TABLE}`)
      AND volume > 500000
      AND (rsi_14 < 30 OR momentum_10d > 0.05)
      AND market_cap IS NOT NULL
    ORDER BY market_cap DESC
    LIMIT {limit}
    """

    logger.info("Querying top candidates from enriched_prices_table...")
    df = client.query(query).to_dataframe()
    logger.info(f"Found {len(df)} candidates")

    return df


# ─────────────────────────────────────────────
# YouTube helpers
# ─────────────────────────────────────────────
def search_youtube_videos(symbol: str, max_results: int = 3) -> list[dict]:
    """
    Search for recent YouTube videos about a stock ticker.

    Args:
        symbol: Stock ticker symbol
        max_results: Maximum number of videos to return

    Returns:
        List of video metadata dicts with video_id, title, published_at
    """
    if not YOUTUBE_API_KEY:
        logger.warning("YOUTUBE_API_KEY not set, skipping YouTube search")
        return []

    try:
        youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

        # Search for videos published in last 24 hours
        published_after = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

        search_query = f"{symbol} stock analysis"

        request = youtube.search().list(
            part="snippet",
            q=search_query,
            type="video",
            publishedAfter=published_after,
            order="relevance",
            maxResults=max_results,
            relevanceLanguage="en"
        )

        response = request.execute()

        videos = []
        for item in response.get('items', []):
            videos.append({
                'video_id': item['id']['videoId'],
                'title': item['snippet']['title'],
                'published_at': item['snippet']['publishedAt'],
                'channel': item['snippet']['channelTitle']
            })

        logger.info(f"Found {len(videos)} YouTube videos for {symbol}")
        return videos

    except Exception as e:
        logger.warning(f"YouTube search error for {symbol}: {e}")
        return []


def get_video_transcript(video_id: str) -> str:
    """
    Get transcript text from a YouTube video.

    Args:
        video_id: YouTube video ID

    Returns:
        Transcript text as string
    """
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id).find_transcript(['en']).fetch()
        transcript_text = " ".join([item['text'] for item in transcript_list])
        return transcript_text
    except Exception as e:
        logger.warning(f"Transcript error for video {video_id}: {e}")
        return ""


# ─────────────────────────────────────────────
# AI Analysis with Claude
# ─────────────────────────────────────────────
def analyze_with_claude(symbol: str, videos: list[dict], market_data: dict) -> dict:
    """
    Use Claude API to analyze video transcripts and generate insights.

    Args:
        symbol: Stock ticker
        videos: List of video metadata with transcripts
        market_data: Current market data for context

    Returns:
        Dict with sentiment, target_price, risks, summary
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, skipping AI analysis")
        return {
            "sentiment": "Unknown",
            "target_price": None,
            "risks": "No analysis available",
            "summary": "API key not configured"
        }

    # Prepare context with video transcripts
    video_context = ""
    for i, video in enumerate(videos, 1):
        video_context += f"\n\n--- Video {i}: {video['title']} ---\n"
        video_context += f"Channel: {video['channel']}\n"
        video_context += f"Transcript: {video.get('transcript', 'N/A')[:2000]}\n"  # Limit length

    if not video_context.strip():
        video_context = "No video transcripts available."

    # Build analysis prompt
    prompt = f"""Analyze the following information about {symbol} stock:

CURRENT MARKET DATA:
- Price: ${market_data.get('current_price', 'N/A')}
- Volume: {market_data.get('volume', 'N/A'):,}
- Market Cap: ${market_data.get('market_cap', 0):,}
- RSI (14): {market_data.get('rsi_14', 'N/A')}
- 10-Day Momentum: {market_data.get('momentum_10d', 'N/A')}
- Sector: {market_data.get('sector', 'N/A')}
- Industry: {market_data.get('industry', 'N/A')}

RECENT YOUTUBE ANALYSIS:
{video_context}

Based on this information, provide:
1. Overall Sentiment (respond with exactly one word: "Bullish", "Bearish", or "Neutral")
2. Price Target (if mentioned, provide single number or "None")
3. Main Risks (list 2-3 key risks in a concise paragraph)
4. Summary (brief 2-3 sentence analysis)

Format your response EXACTLY as:
SENTIMENT: [Bullish/Bearish/Neutral]
TARGET_PRICE: [number or None]
RISKS: [concise paragraph]
SUMMARY: [2-3 sentences]
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        response_text = message.content[0].text

        # Parse structured response
        sentiment = "Neutral"
        target_price = None
        risks = ""
        summary = ""

        for line in response_text.split('\n'):
            line = line.strip()
            if line.startswith("SENTIMENT:"):
                sentiment = line.replace("SENTIMENT:", "").strip()
            elif line.startswith("TARGET_PRICE:"):
                price_str = line.replace("TARGET_PRICE:", "").strip()
                try:
                    target_price = float(price_str) if price_str.lower() != "none" else None
                except:
                    target_price = None
            elif line.startswith("RISKS:"):
                risks = line.replace("RISKS:", "").strip()
            elif line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()

        logger.info(f"Claude analysis for {symbol}: {sentiment}")

        return {
            "sentiment": sentiment,
            "target_price": target_price,
            "risks": risks,
            "summary": summary
        }

    except Exception as e:
        logger.error(f"Claude API error for {symbol}: {e}")
        return {
            "sentiment": "Error",
            "target_price": None,
            "risks": f"Analysis failed: {str(e)}",
            "summary": "Unable to complete analysis"
        }


# ─────────────────────────────────────────────
# Insert results
# ─────────────────────────────────────────────
def insert_insights(insights_df: pd.DataFrame) -> None:
    """
    Insert AI insights into BigQuery table.

    Args:
        insights_df: DataFrame with analysis results
    """
    # Use pandas.to_gbq for more robust insertion
    insights_df.to_gbq(
        destination_table=f"{DATASET}.ai_insights",
        project_id=PROJECT_ID,
        if_exists='append',
        progress_bar=False
    )

    logger.info(f"Inserted {len(insights_df)} insights into {AI_INSIGHTS_TABLE}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main(limit: int = 10) -> None:
    """
    Main AI analyst workflow.

    Args:
        limit: Number of top candidates to analyze
    """
    logger.info("Starting AI analyst job")

    # Setup credentials
    json_path = os.path.join("src", "config", "service-account.json")

    # Check if service-account.json exists and is valid
    use_service_account = False
    if os.path.exists(json_path):
        try:
            import json
            with open(json_path, 'r') as f:
                creds = json.load(f)
                # Check if credentials are filled (not empty strings)
                if creds.get('private_key') and creds.get('client_email'):
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = json_path
                    logger.info("Loading credentials from: %s", json_path)
                    use_service_account = True
                else:
                    logger.info("service-account.json is empty, using default credentials")
        except Exception as e:
            logger.info("Could not load service-account.json: %s, using default credentials", e)

    if not use_service_account:
        logger.info("Using default Google Cloud credentials (gcloud auth)")
        # Remove the env var if it was set before
        if "GOOGLE_APPLICATION_CREDENTIALS" in os.environ:
            del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]

    # Ensure table exists
    ensure_table()

    # Get top candidates
    candidates_df = get_top_candidates(limit=limit)

    if candidates_df.empty:
        logger.warning("No candidates found matching criteria")
        return

    logger.info(f"Analyzing {len(candidates_df)} candidates...")

    # Analyze each candidate
    results = []
    today = date.today()
    now = datetime.now(timezone.utc)

    for idx, row in candidates_df.iterrows():
        symbol = row['symbol']
        logger.info(f"Processing {idx+1}/{len(candidates_df)}: {symbol}")

        # Search YouTube videos
        videos = search_youtube_videos(symbol, max_results=3)

        # Get transcripts
        for video in videos:
            video['transcript'] = get_video_transcript(video['video_id'])
            time.sleep(1)  # Rate limiting

        # Prepare market data context
        market_data = {
            'current_price': row['current_price'],
            'volume': row['volume'],
            'market_cap': row['market_cap'],
            'rsi_14': row['rsi_14'],
            'momentum_10d': row['momentum_10d'],
            'sector': row['sector'],
            'industry': row['industry']
        }

        # Analyze with Claude
        analysis = analyze_with_claude(symbol, videos, market_data)

        # Compile results
        video_titles = " | ".join([v['title'] for v in videos]) if videos else "No videos found"

        results.append({
            'analysis_date': today,
            'symbol': symbol,
            'current_price': row['current_price'],
            'volume': int(row['volume']),
            'market_cap': int(row['market_cap']) if pd.notna(row['market_cap']) else None,
            'rsi_14': row['rsi_14'],
            'momentum_10d': row['momentum_10d'],
            'sentiment': analysis['sentiment'],
            'target_price': analysis['target_price'],
            'risks': analysis['risks'],
            'summary': analysis['summary'],
            'video_count': len(videos),
            'video_titles': video_titles,
            'created_at': now
        })

        # Rate limiting between stocks
        time.sleep(2)

    # Insert into BigQuery
    if results:
        results_df = pd.DataFrame(results)
        insert_insights(results_df)
        logger.info(f"AI analyst job finished | analyzed={len(results)} stocks")
    else:
        logger.warning("No results to insert")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Stock Analyst")
    parser.add_argument("--limit", type=int, default=10, help="Number of top candidates to analyze")
    args = parser.parse_args()

    main(limit=args.limit)

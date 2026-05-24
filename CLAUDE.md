# CLAUDE.md — yfinnance_back

Proyecto de inteligencia financiera educativa. Backend Python + BigQuery + Cloud Run.
El objetivo es producir señales diarias curadas (no ruido) para un frontend educativo de inversión.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Cómputo | Google Cloud Run Jobs (`europe-west1`) |
| Base de datos | BigQuery — dataset `yfinance-gcp.yfinance_raw` |
| Almacenamiento | GCS bucket `yfinance-cache` |
| Datos de mercado | `yfinance` (Yahoo Finance, sin API key) |
| Fuentes sociales | Reddit public JSON API (sin API key) |
| Narrativas LLM | Gemini 2.5 Flash (`gemini-2.5-flash` vía Vertex AI) |
| Runtime | Python 3.13, imagen Docker en Artifact Registry |

---

## Pipeline — orden de ejecución diario

```
daily-prices-job → daily-enrich-job → daily-sector-job  ┐
                                    └→ daily-anomaly-job ┴→ daily-news-job → daily-narrative-job
```

Ejecución semanal (domingos): `weekly-companies`

| Job Cloud Run | Script | Qué hace |
|--------------|--------|----------|
| `daily-prices-job` | `src/jobs/daily_prices.py` | OHLCV de Yahoo para ~2700 tickers. MERGE por `(date, symbol)`. |
| `daily-enrich-job` | `src/jobs/daily_enrich.py` | Indicadores técnicos + fundamentales. Incremental (30d) o full load si >7d desactualizado. |
| `daily-sector-job` | `src/jobs/daily_sector_opportunities.py` | Top 10 picks × 3 setups por sector. DELETE+INSERT idempotente. |
| `daily-anomaly-job` | `src/jobs/daily_anomaly_radar.py` | Detecta 3 tipos de anomalías. Escanea solo 40d con LAG(). DELETE+INSERT idempotente. |
| `daily-news-job` | `src/jobs/daily_news_enrich.py` | Yahoo Finance news + Reddit posts para símbolos del día. DELETE+INSERT. |
| `daily-narrative-job` | `src/jobs/daily_narrative.py` | Llama a Gemini 2.5 Flash para generar narrativa dealflow por símbolo. MERGE en ambas tablas. |
| `weekly-companies` | `src/jobs/weekly_companies.py` | Refresca universo de empresas (S&P500, Russell 2000, STOXX 600, commodities, bonos). |

---

## Tablas BigQuery

### `companies` — metadatos de empresa (semanal, acumula histórico)
Clave: `(symbol, updated_at)`. Columnas clave: `symbol`, `short_name`, `business_summary`, `sector`, `industry`, `market_cap`, `beta`, `trailing_eps`, `recommendation_key`, `is_active`.

### `daily_prices` — OHLCV crudo
Clave: `(date, symbol)`. Columnas: `open`, `high`, `low`, `close`, `adj_close`, `volume`.

### `enriched_prices_table` — precios + indicadores técnicos/fundamentales
Clave: `(date, symbol)`. Indicadores: `rsi_14`, `bollinger_*`, `macd_line`, `momentum_10d`, `dist_sma_200`, `long_term_trend` (Bullish/Bearish), `pct_from_52w_high`, `pct_from_52w_low`, `pe_ratio`.

### `anomaly_radar` — salida diaria del radar de anomalías
Particionada por `date`, clusterizada por `(anomaly_type, sector)`.
Tipos: `Volume/Price Spike`, `Critical Oversold`, `Confirmed Momentum`. Top 5 por sector+tipo.
Columnas output clave: `symbol`, `sector`, `industry`, `anomaly_type`, `score` (0-100), `rank_in_sector`, `reason`, `company_name`, `company_url`, `company_summary`, `top_news_title`, `top_news_url`, `narrative`.

### `sector_daily_opportunities` — setups de inversión por sector
Particionada por `date`, clusterizada por `(sector, setup_type)`.
Setups: `Dip (Bullish Trend)`, `Momentum (Leaders)`, `Value Reversal`. Top 15 por sector+setup.
Columnas output clave: `symbol`, `sector`, `setup_type`, `score` (0-100), `rank_in_sector`, `reason`, `company_name`, `company_url`, `company_summary`, `top_news_title`, `top_news_url`, `narrative`.

### `company_news` — noticias y posts sociales
Particionada por `date`, clusterizada por `(symbol, source)`.
Fuentes: `yahoo_finance`, `reddit`. Columnas: `title`, `url`, `published_at`, `summary`, `score`, `num_comments`, `publisher`.

---

## Patrones de código — MUY IMPORTANTE seguir estos patrones

### 1. Estructura de un nuevo job
```python
# src/jobs/daily_foo.py
"""Docstring: qué hace, cuándo corre, de qué depende."""

import os, logging
from pathlib import Path
from google.cloud import bigquery
from src.config.settings import PROJECT_ID, DATASET, FOO_TABLE

logger = logging.getLogger("daily_foo")

SCHEMA = [
    bigquery.SchemaField("date",   "DATE",   mode="REQUIRED"),
    bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
    # ... resto de campos
]

def ensure_table(client): ...   # crea tabla si no existe

def main():
    # 1. Detectar service account local (dev)
    json_path = os.path.join("src", "config", "service-account.json")
    if os.path.exists(json_path): ...   # carga credenciales

    client = bigquery.Client(project=PROJECT_ID)
    ensure_table(client)
    # lógica principal

if __name__ == "__main__":
    main()
```

### 2. Idempotencia — DELETE + INSERT sobre max_date
Todos los jobs de output usan DELETE + INSERT sobre la fecha más reciente (nunca TRUNCATE).
Las queries SQL viven en `src/sql/*.bsql` y se leen con `Path(...).read_text()`.

### 3. SQL en ficheros .bsql
```python
SQL_FILE = Path(__file__).parents[1] / "sql" / "foo.bsql"

def run_sql(client):
    sql = SQL_FILE.read_text(encoding="utf-8")
    job = client.query(sql)
    job.result()
```

### 4. Añadir tabla nueva a settings.py
```python
# src/config/settings.py
FOO_TABLE = f"{PROJECT_ID}.{DATASET}.foo_table"
```

### 5. Añadir job nuevo a deploy.sh
```bash
if gcloud run jobs describe daily-foo-job ...; then
  gcloud run jobs update daily-foo-job --image "$IMAGE" --command python \
    --args "src/jobs/daily_foo.py" --region "$REGION" --project "$PROJECT_ID"
else
  gcloud run jobs create daily-foo-job --image "$IMAGE" --command python \
    --args "src/jobs/daily_foo.py" --region "$REGION" --project "$PROJECT_ID" \
    --service-account "$SA"
fi
```

---

## Configuración GCP

- **Proyecto**: `yfinance-gcp`
- **Dataset**: `yfinance_raw`
- **Región**: `europe-west1`
- **Service Account**: `425504558294-compute@developer.gserviceaccount.com`
- **Imagen Docker**: `europe-west1-docker.pkg.dev/yfinance-gcp/stock-jobs/stock-jobs:latest`
- **Credenciales locales**: `src/config/service-account.json` (gitignoreado)

---

## Universo de datos

- **Renta variable**: S&P 500 + Russell 2000 + STOXX 600 ≈ 2700 tickers
- **Commodities ETFs**: GLD, SLV, USO, CPER, PPLT, URA (`source = "commodities"`)
- **Bonos ETFs**: TLT, IEF (`source = "bonds"`)
- **Filtros mínimos en outputs**: `close > 5`, `market_cap > 500M` (radar) / `2B` (sector ops)

---

## Estado de fases (2026-04-04)

| Fase | Estado |
|------|--------|
| Fase 1 — Core datos cuantitativos | ✅ Completada |
| Fase 2 — Screener sectorial + Setups | ✅ Completada |
| Fase 3 — Radar de Anomalías | ✅ Completada |
| Fase 4 — Narrativas (LLM + noticias) | ✅ Completada — `daily_narrative.py` desplegado en prod (2026-04-04) |
| Fase 5 — Frontend | 🔴 Pendiente |
| Fase 6 — Infraestructura + gobernanza costes | 🔴 Pendiente |
| Fase 7 — Monetización + portfolio | 🔴 Pendiente |

---

## Costes y restricciones

- BigQuery: **nunca** hacer full scan de `enriched_prices_table` (~13M filas). Siempre filtrar por `date` o usar ventanas limitadas (40d para anomaly radar).
- Vertex AI Gemini: **solo** llamar para símbolos ya seleccionados por radar/oportunidades (~50-150/día). Usar Gemini 2.5 Flash.
- Reddit: respetar delay de 1.2s entre requests (límite público 60 req/min).
- El frontend **nunca** debe consultar tablas raw — solo tablas de resultados pre-calculados.

# Frontend Data Contract — yfinnance

> **Para el equipo frontend.** Este documento describe exactamente qué datos produce el backend, cómo consultarlos de forma eficiente, y qué secciones implementar en cada fase.

---

## Principio clave: nunca consultes tablas raw

El frontend **solo** consulta las tablas de resultados pre-calculados.
Todas están particionadas por `date` — **siempre filtra por `date = MAX(date)`** para leer solo el último día (coste mínimo en BigQuery).

---

## Tablas disponibles para el frontend

### 1. `anomaly_radar` — El Radar Diario

**Cuándo se actualiza:** una vez al día, después del cierre de mercado.
**Qué contiene:** las acciones con comportamiento anómalo detectado hoy.

```sql
SELECT *
FROM `yfinance-gcp.yfinance_raw.anomaly_radar`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.anomaly_radar`)
ORDER BY anomaly_type, sector, rank_in_sector
```

**Schema completo:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `date` | DATE | Fecha de generación |
| `sector` | STRING | Sector bursátil (ej. "Technology") |
| `industry` | STRING | Industria dentro del sector |
| `symbol` | STRING | Ticker (ej. "NVDA", "ASML.AS") |
| `anomaly_type` | STRING | `"Volume/Price Spike"` \| `"Critical Oversold"` \| `"Confirmed Momentum"` |
| `close` | FLOAT | Precio de cierre |
| `market_cap_bn` | FLOAT | Capitalización en miles de millones USD |
| `rsi_14` | FLOAT | RSI 14 períodos (0–100) |
| `change_1d_pct` | FLOAT | Cambio % en 1 día |
| `change_3d_pct` | FLOAT | Cambio % en 3 días |
| `change_7d_pct` | FLOAT | Cambio % en 7 días |
| `change_30d_pct` | FLOAT | Cambio % en ~30 días |
| `volume_ratio` | FLOAT | Volumen hoy / media 20d (1.0 = normal) |
| `score` | FLOAT | Puntuación 0–100 (mayor = más relevante) |
| `rank_in_sector` | INTEGER | Posición dentro de sector+tipo (1 = mejor) |
| `reason` | STRING | Explicación técnica en una línea |
| `company_name` | STRING | Nombre corto de la empresa |
| `company_url` | STRING | `https://finance.yahoo.com/quote/{symbol}` |
| `company_summary` | STRING | Descripción del negocio (máx 500 chars) |
| `top_news_title` | STRING | Titular de la noticia más relevante del día |
| `top_news_url` | STRING | Enlace directo a esa noticia |
| `narrative` | STRING | Narrativa dealflow 3 frases generada por IA: catalizador → evidencia → outlook |

---

### 2. `sector_daily_opportunities` — Setups de Inversión

**Cuándo se actualiza:** una vez al día.
**Qué contiene:** hasta 15 empresas por sector × 3 tipos de setup.

```sql
SELECT *
FROM `yfinance-gcp.yfinance_raw.sector_daily_opportunities`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.sector_daily_opportunities`)
ORDER BY sector, setup_type, rank_in_sector
```

**Schema completo:**

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `date` | DATE | Fecha de generación |
| `sector` | STRING | Sector bursátil |
| `industry` | STRING | Industria |
| `symbol` | STRING | Ticker |
| `setup_type` | STRING | `"Dip (Bullish Trend)"` \| `"Momentum (Leaders)"` \| `"Value Reversal"` |
| `close` | FLOAT | Precio de cierre |
| `market_cap_bn` | FLOAT | Capitalización en miles de millones USD |
| `rsi_14` | FLOAT | RSI 14 (0–100). <30 sobrevendido, >70 sobrecomprado |
| `momentum_10d_pct` | FLOAT | Cambio % en 10 días de trading |
| `dist_sma200_pct` | FLOAT | % por encima/debajo de la media 200 |
| `pct_from_52w_high` | FLOAT | % caída desde máximo 52 semanas (valor negativo) |
| `pct_from_52w_low` | FLOAT | % subida desde mínimo 52 semanas |
| `pe_ratio` | FLOAT | Price/Earnings ratio |
| `recommendation_key` | STRING | Consenso analistas: `strong_buy` \| `buy` \| `hold` \| `underperform` \| `sell` |
| `score` | FLOAT | Puntuación 0–100 |
| `rank_in_sector` | INTEGER | Posición dentro de sector+setup (1 = mejor) |
| `reason` | STRING | Explicación técnica en una línea |
| `company_name` | STRING | Nombre corto |
| `company_url` | STRING | `https://finance.yahoo.com/quote/{symbol}` |
| `company_summary` | STRING | Descripción del negocio (máx 500 chars) |
| `top_news_title` | STRING | Titular de la noticia más relevante |
| `top_news_url` | STRING | Enlace a la noticia |
| `narrative` | STRING | Narrativa dealflow 3 frases (IA) |
| `performance_1w_pct` | FLOAT | Rendimiento a 1 semana de haberse detectado la oportunidad |
| `performance_1m_pct` | FLOAT | Rendimiento a 1 mes de haberse detectado la oportunidad |

---

### 3. `company_news` — Noticias y Menciones Sociales

**Cuándo se actualiza:** una vez al día.
**Qué contiene:** noticias de Yahoo Finance y posts de Reddit para cada símbolo del radar.

```sql
SELECT *
FROM `yfinance-gcp.yfinance_raw.company_news`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.company_news`)
  AND symbol = 'NVDA'   -- filtrar por símbolo
ORDER BY source, published_at DESC
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `date` | DATE | Fecha de fetch |
| `symbol` | STRING | Ticker |
| `source` | STRING | `"yahoo_finance"` \| `"reddit"` |
| `title` | STRING | Titular del artículo o post |
| `url` | STRING | Enlace directo |
| `published_at` | TIMESTAMP | Fecha de publicación (UTC) |
| `summary` | STRING | Resumen o cuerpo del post (máx 600 chars) |
| `score` | INTEGER | Upvotes en Reddit; NULL para Yahoo |
| `num_comments` | INTEGER | Comentarios en Reddit; NULL para Yahoo |
| `publisher` | STRING | Nombre del medio (Yahoo) o subreddit (Reddit) |

---

### 4. `market_insights` — Termómetro de Mercado (YouTube & Macro)

**Cuándo se actualiza:** una vez al día.
**Qué contiene:** análisis estructurados con IA de vídeos de YouTube financieros y feeds RSS de noticias.

```sql
SELECT *
FROM `yfinance-gcp.yfinance_raw.market_insights`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.market_insights`)
ORDER BY source_type, source_name
```

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `date` | DATE | Fecha del análisis |
| `source_type` | STRING | `"youtube"` \| `"rss"` |
| `source_name` | STRING | Canal (ej. "Bolsacava", "The Macro Compass") |
| `title` | STRING | Título original del vídeo o resumen de noticias |
| `url` | STRING | Enlace al vídeo o al feed original (usar para botón "Ir a la fuente") |
| `market_bias` | STRING | Sesgo general: `"Bullish"`, `"Bearish"`, `"Neutral"`, `"N/A"` |
| `macro_event` | STRING | Evento clave mencionado (ej. "Dato del IPC") |
| `smart_money_signals` | STRING | Resumen de 1 frase sobre engaños o liquidez |
| `key_levels` | STRING | Array JSON serializado (ej. `[{"activo": "SP500", "soporte": 5100}]`) |
| `mentioned_tickers` | STRING | Activos mencionados separados por comas (ej. "SP500,ORO,NVDA") |
| `tesis_principal` | STRING | Resumen detallado de la tesis principal (3 a 5 frases) |

---

## UI Copy — Títulos y Descripciones

Los textos de cada sección (títulos, descripciones, labels por tipo) están centralizados en **`docs/ui_copy.json`**. El frontend debe cargar ese archivo como fuente de verdad para toda la copia UI, no hardcodear strings.

Estructura:
```
ui_copy.json
└── sections
    ├── daily_radar          → title, subtitle, description + per anomaly_type
    ├── sector_opportunities → title, subtitle, description + per setup_type
    └── macro                → title, subtitle, description + per ETF (name + signal)
```

---

## Secciones del Frontend a implementar

### Sección 1 — "Radar Diario" (Fase 5, prioridad alta)

**Fuente:** `anomaly_radar`

**Diseño sugerido:**
- 3 pestañas o columnas: `Volume/Price Spike` | `Critical Oversold` | `Confirmed Momentum`
- Por cada tipo: lista de tarjetas ordenadas por `score DESC`
- **Tarjeta de empresa** muestra:
  - `company_name` + `symbol` (enlaza a `company_url`)
  - `sector` / `industry`
  - Badge coloreado por `anomaly_type`
  - Métricas clave según tipo:
    - Spike: `change_1d_pct`, `change_3d_pct`, `volume_ratio`
    - Oversold: `rsi_14`, `change_3d_pct`, `change_7d_pct`
    - Momentum: `change_30d_pct`, `change_7d_pct`, `score`
  - `reason` (texto técnico, tipografía mono pequeña)
  - `narrative` (texto IA en caja destacada — el "por qué")
  - `top_news_title` enlazando a `top_news_url`
  - Barra de `score` visual (0-100)

**Query recomendada:**
```sql
SELECT *
FROM `yfinance-gcp.yfinance_raw.anomaly_radar`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.anomaly_radar`)
ORDER BY anomaly_type, score DESC
```

---

### Sección 2 — "Oportunidades Sectoriales" (Fase 5)

**Fuente:** `sector_daily_opportunities`

**Diseño sugerido:**
- Selector de sector (dropdown o pills) → filtra las 3 columnas de setup
- 3 columnas: `Dip (Bullish Trend)` | `Momentum (Leaders)` | `Value Reversal`
- Tarjeta similar al Radar con métricas específicas del setup:
  - Dip: `rsi_14`, `dist_sma200_pct`, `recommendation_key`
  - Momentum: `momentum_10d_pct`, `pct_from_52w_high`, `rsi_14`
  - Value Reversal: `pct_from_52w_high`, `pe_ratio`, `recommendation_key`

**Sectores disponibles** (valores reales en la tabla):
`Communication Services`, `Consumer Cyclical`, `Consumer Defensive`,
`Energy`, `Financial Services`, `Healthcare`, `Industrials`,
`Real Estate`, `Technology`, `Utilities`, `Basic Materials`

---

### Sección 3 — "Macro & Materias Primas" (Fase 5)

**Fuente:** `anomaly_radar` filtrado por ETFs de commodities y bonos.

Los ETFs especiales aparecen en el radar con su sector asignado. Para identificarlos, filtra por `symbol IN ('GLD','SLV','USO','CPER','PPLT','URA','TLT','IEF')`.

**Semáforo macro sugerido:**

| ETF | Activo | Señal |
|-----|--------|-------|
| `GLD` | Oro | Refugio / inflación |
| `SLV` | Plata | Industrial / inflación |
| `USO` | Petróleo | Energía / geopolítica |
| `CPER` | Cobre | Ciclo industrial / China |
| `PPLT` | Platino | Automoción / verde |
| `URA` | Uranio | Nuclear / energía verde |
| `TLT` | Bono 20a | Tipos de interés largo plazo |
| `IEF` | Bono 7-10a | Tipos medios |

**Query:**
```sql
SELECT symbol, anomaly_type, change_1d_pct, change_7d_pct, change_30d_pct,
       volume_ratio, score, narrative, top_news_title, top_news_url
FROM `yfinance-gcp.yfinance_raw.anomaly_radar`
WHERE date = (SELECT MAX(date) FROM `yfinance-gcp.yfinance_raw.anomaly_radar`)
  AND symbol IN ('GLD','SLV','USO','CPER','PPLT','URA','TLT','IEF')
ORDER BY symbol
```

---

### Sección 4 — "Termómetro de Mercado" (Macro Insights)

**Fuente:** `market_insights`

**Diseño sugerido:**
- **Cabecera (Dashboard):** Un indicador visual (Gauge/Velocímetro) que sume cuántas fuentes están `Bullish` vs `Bearish` ese día.
- **Nube de Activos:** Extraer y agrupar los tickers de `mentioned_tickers` (ej. si 4 analistas hablan del "Oro", destacarlo).
- **Feed de Analistas (Tarjetas):** Una cuadrícula (Grid) o lista con una tarjeta por cada fuente (`source_name`).
  - Destacar la `tesis_principal` como texto principal.
  - Píldoras (Badges) con el `market_bias` (Verde/Rojo) y el `macro_event`.
  - Un Callout destacado para las `smart_money_signals`.

---

## TypeScript Types

```typescript
export type AnomalyType =
  | 'Volume/Price Spike'
  | 'Critical Oversold'
  | 'Confirmed Momentum'

export type SetupType =
  | 'Dip (Bullish Trend)'
  | 'Momentum (Leaders)'
  | 'Value Reversal'

export type RecommendationKey =
  | 'strong_buy' | 'buy' | 'hold' | 'underperform' | 'sell'

export type NewsSource = 'yahoo_finance' | 'reddit'

export interface AnomalyRadarItem {
  date: string                  // 'YYYY-MM-DD'
  sector: string
  industry: string | null
  symbol: string
  anomaly_type: AnomalyType
  close: number
  market_cap_bn: number | null
  rsi_14: number | null
  change_1d_pct: number | null
  change_3d_pct: number | null
  change_7d_pct: number | null
  change_30d_pct: number | null
  volume_ratio: number | null
  score: number
  rank_in_sector: number
  reason: string | null
  company_name: string | null
  company_url: string           // Yahoo Finance URL
  company_summary: string | null
  top_news_title: string | null
  top_news_url: string | null
  narrative: string | null      // 3-sentence LLM dealflow narrative
}

export interface SectorOpportunityItem {
  date: string
  sector: string
  industry: string | null
  symbol: string
  setup_type: SetupType
  close: number
  market_cap_bn: number | null
  rsi_14: number | null
  momentum_10d_pct: number | null
  dist_sma200_pct: number | null
  pct_from_52w_high: number | null
  pct_from_52w_low: number | null
  pe_ratio: number | null
  recommendation_key: RecommendationKey | null
  score: number
  rank_in_sector: number
  reason: string | null
  company_name: string | null
  company_url: string
  company_summary: string | null
  top_news_title: string | null
  top_news_url: string | null
  narrative: string | null
  performance_1w_pct: number | null
  performance_1m_pct: number | null
}

export interface CompanyNewsItem {
  date: string
  symbol: string
  source: NewsSource
  title: string
  url: string
  published_at: string | null   // ISO 8601 UTC
  summary: string | null
  score: number | null          // Reddit upvotes; null for Yahoo
  num_comments: number | null
  publisher: string | null
}

export interface MarketInsightItem {
  date: string;
  source_type: 'youtube' | 'rss';
  source_name: string;
  title: string | null;
  url: string | null;
  market_bias: 'Bullish' | 'Bearish' | 'Neutral' | 'N/A';
  macro_event: string | null;
  smart_money_signals: string | null;
  key_levels: string | null;      // JSON stringified array
  mentioned_tickers: string | null; // Comma separated
  tesis_principal: string | null;
}
```

---

## Arquitectura de API recomendada (Fase 6)

El frontend **no** debe conectarse directamente a BigQuery. La arquitectura objetivo es:

```
BigQuery → [batch job nocturno] → Cache (Redis/SQLite/JSON en GCS)
                                          ↓
                              API Backend (FastAPI / Next.js API routes)
                                          ↓
                                       Frontend
```

**Endpoints mínimos a implementar:**

| Endpoint | Fuente | Descripción |
|----------|--------|-------------|
| `GET /api/radar` | `anomaly_radar` | Todos los tipos del día |
| `GET /api/radar/:type` | `anomaly_radar` | Filtrado por `anomaly_type` |
| `GET /api/opportunities` | `sector_daily_opportunities` | Todos los setups |
| `GET /api/opportunities/:sector` | `sector_daily_opportunities` | Filtrado por sector |
| `GET /api/macro` | `anomaly_radar` | Solo ETFs de commodities/bonos |
| `GET /api/news/:symbol` | `company_news` | Noticias de un símbolo concreto |
| `GET /api/status` | — | Última fecha de actualización de cada tabla |

Todos los endpoints devuelven los datos del día más reciente disponible (`MAX(date)`).
Rate limiting recomendado: 60 req/min por IP.

---

## Datos de ejemplo reales

**anomaly_radar** — ejemplo de fila:
```json
{
  "date": "2026-04-04",
  "sector": "Technology",
  "industry": "Semiconductors",
  "symbol": "NVDA",
  "anomaly_type": "Volume/Price Spike",
  "close": 875.50,
  "market_cap_bn": 2150.3,
  "rsi_14": 68.2,
  "change_1d_pct": 4.8,
  "change_3d_pct": 9.2,
  "change_7d_pct": 12.1,
  "change_30d_pct": 22.4,
  "volume_ratio": 2.8,
  "score": 78.5,
  "rank_in_sector": 1,
  "reason": "1d: +4.8% | 3d: +9.2% | 7d: +12.1%. Vol x2.8. RSI 68.",
  "company_name": "NVIDIA Corp",
  "company_url": "https://finance.yahoo.com/quote/NVDA",
  "company_summary": "NVIDIA designs GPUs for gaming, data centers and AI...",
  "top_news_title": "NVIDIA surges on record data center demand from hyperscalers",
  "top_news_url": "https://finance.yahoo.com/news/nvidia-data-center-q4-2024",
  "narrative": "NVIDIA is surging on unprecedented demand from cloud hyperscalers expanding AI inference capacity. Blackwell GPU orders are reportedly 6-9 months backlogged, driving upward revisions to FY2026 estimates. Near-term risk is valuation at 35x forward earnings, but the structural AI capex cycle remains intact."
}
```

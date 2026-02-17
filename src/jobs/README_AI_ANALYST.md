# AI Analyst Job

Este script analiza automáticamente las acciones más prometedoras del día usando inteligencia artificial.

## ¿Qué hace?

1. **Filtra candidatos** de la tabla `enriched_prices_table`:
   - Liquidez alta (volumen > 500,000)
   - Oportunidades técnicas (RSI < 30 o momentum 10d > 5%)
   - Prioriza empresas grandes (por market cap)
   - Devuelve Top 10

2. **Busca en YouTube** videos recientes (últimas 24h) sobre cada ticker

3. **Analiza con Claude AI**:
   - Extrae transcripts de los videos
   - Genera insights: Sentimiento, Precio objetivo, Riesgos
   - Resume la información clave

4. **Guarda resultados** en tabla `ai_insights` de BigQuery

## Requisitos previos

### 1. API Keys necesarias

Debes configurar dos API keys como variables de entorno:

#### YouTube Data API v3
1. Ve a [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Crea un proyecto o selecciona uno existente
3. Habilita "YouTube Data API v3"
4. Crea credenciales (API key)
5. Copia la API key

#### Anthropic Claude API
1. Ve a [Anthropic Console](https://console.anthropic.com/)
2. Crea una cuenta si no tienes
3. Ve a "API Keys"
4. Crea una nueva API key
5. Copia la API key

### 2. Configurar variables de entorno

Crea un archivo `.env` en la raíz del proyecto:

```bash
cp .env.example .env
```

Edita `.env` y añade tus API keys:

```bash
YOUTUBE_API_KEY=tu_api_key_aqui
ANTHROPIC_API_KEY=tu_api_key_aqui
```

### 3. Instalar dependencias

```bash
pip install -r requirements.txt
```

Las dependencias nuevas son:
- `anthropic==0.45.0` (para Claude API)
- `youtube-transcript-api==1.2.4` (ya instalada)
- `google-api-python-client` (ya instalada)

## Uso

### Ejecución básica (Top 10)

```bash
python src/jobs/ai_analyst.py
```

### Personalizar número de candidatos

```bash
python src/jobs/ai_analyst.py --limit 5
```

### Configurar como Cloud Run job

Añade las variables de entorno en Cloud Run:
- `YOUTUBE_API_KEY`
- `ANTHROPIC_API_KEY`

## Estructura de la tabla ai_insights

```sql
CREATE TABLE `yfinance-gcp.yfinance_raw.ai_insights` (
  analysis_date DATE,
  symbol STRING,
  current_price FLOAT64,
  volume INT64,
  market_cap INT64,
  rsi_14 FLOAT64,
  momentum_10d FLOAT64,
  sentiment STRING,        -- Bullish/Bearish/Neutral
  target_price FLOAT64,    -- Precio objetivo según análisis
  risks STRING,            -- Riesgos principales
  summary STRING,          -- Resumen de la IA
  video_count INT64,
  video_titles STRING,
  created_at TIMESTAMP
);
```

## Ejemplo de consulta

Ver los últimos insights generados:

```sql
SELECT
  symbol,
  sentiment,
  target_price,
  current_price,
  ROUND((target_price - current_price) / current_price * 100, 2) as upside_pct,
  risks,
  summary
FROM `yfinance-gcp.yfinance_raw.ai_insights`
WHERE analysis_date = CURRENT_DATE()
ORDER BY market_cap DESC;
```

## Costos estimados

- **YouTube API**: 100 cuotas/día gratis (cada búsqueda = 100 cuotas)
  - 10 tickers = 1,000 cuotas/día
  - Recomendación: ejecutar 1 vez al día

- **Claude API**: ~$0.003 por 1K tokens
  - Análisis de 10 tickers ≈ $0.10-0.30 por ejecución

## Troubleshooting

### Error: YOUTUBE_API_KEY not set
Verifica que la variable de entorno esté configurada correctamente.

### Error: Quota exceeded
Has superado el límite diario de YouTube API. Espera 24h o reduce el número de candidatos.

### Error: Transcript not available
Algunos videos no tienen transcripts disponibles. El script los saltará automáticamente.

### Error: ANTHROPIC_API_KEY not set
Verifica que tu API key de Anthropic esté configurada.

## Próximas mejoras

- [ ] Caché de transcripts para evitar búsquedas duplicadas
- [ ] Análisis de Twitter/X además de YouTube
- [ ] Dashboard de visualización de insights
- [ ] Alertas automáticas cuando sentiment == "Bullish"

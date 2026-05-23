# ⚙️ Roadmap Backend & Data: Market Atelier

Este documento refleja el estado actual del backend de datos (BigQuery + Python) y las futuras vías de desarrollo para la plataforma de inteligencia financiera. 
Para el estado de la interfaz de usuario y visualización, consulta `ROADMAP_FRONT.md`.

---

## 🟢 FASE 1: Core de Datos Cuantitativos (Completada)
**Objetivo:** Disponer de una base de datos limpia, automatizada y barata de mantener con el histórico del mercado.

- [x] **`companies`**: Extracción semanal de metadatos y fundamentales (S&P 500, Russell 2000, STOXX 600).
- [x] **`daily_prices`**: Ingesta diaria incremental de precios OHLCV desde Yahoo Finance.
- [x] **`enriched_prices_table`**: Cálculo incremental de indicadores técnicos (SMA200, RSI, MACD, Bollinger, Momentum) y ratios fundamentales (PER).
- [x] **Depreciación de `daily_picks`**: `daily-scanner-job` y `daily-scanner-cron` eliminados de Cloud Run y Cloud Scheduler (2026-05-07).

---

## 🟢 FASE 2: Screener Sectorial y Setups Educativos (Completada)
**Objetivo:** Clasificar el mercado por sectores para enseñar a identificar patrones recurrentes (Setups) en lugar de perseguir "hot stocks".

- [x] **Creación de `sector_daily_opportunities`**: Tabla particionada que guarda el Top 10 diario por sector.
- [x] **Implementación de Setups**: 
    - *Dip (Tendencia Alcista)*: Comprar correcciones en mercados fuertes.
    - *Momentum (Líderes)*: Seguir la fuerza relativa y roturas de máximos.
    - *Value Reversal*: Identificar giros al alza en empresas muy castigadas pero con buenos fundamentales.

---

## 🟡 FASE 3: Radar de Anomalías (Completada)
**Objetivo:** Identificar oportunidades reales descartando el ruido del mercado mediante detección y clasificación de anomalías en multiples horizontes temporales.

- [x] **Ingesta de ETFs de Commodities**: Añadidos a `companies` con `source = "commodities"`: Oro `GLD`, Plata `SLV`, Petróleo `USO`, Cobre `CPER`, Platino `PPLT`, Uranio `URA`.
- [x] **Bonos**: Añadidos `TLT` (bono 20a) e `IEF` (bono 7-10a) a `companies` con `source = "bonds"`.
- [x] **Ranking de Anomalías Sectoriales** → tabla `anomaly_radar`: Motor que detecta en 1d/3d/7d/30d descartando activos planos. Top 5 por sector en 3 tipos:
    - *Spike Volumen/Precio*: Impulso ≥3% en 1d o ≥7% en 3d, con volumen ≥1.5× media 20d.
    - *Sobrevendido Crítico*: RSI < 30 + caída ≥8% en 3d o ≥12% en 7d. Candidatos a rebote.
    - *Inercia Confirmada*: +8% en 30d, +2% en 7d, sin reversión en 3d. Líderes sostenidos.
    - **Coste**: escanea solo 40 días de `enriched_prices_table` con LAG(). Score 0-100 por tipo.
- [x] **Backfill por fecha**: `daily_anomaly_radar.py` y `daily_sector_opportunities.py` aceptan `--date YYYY-MM-DD` para reprocesar cualquier día histórico.

---

## 🔵 FASE 4: Narrativas de Movimiento (Completada)
**Objetivo:** Cruzar los datos técnicos del Radar de Anomalías con la narrativa real que mueve el mercado ("El Por Qué"). Aportar un nivel de curación alto que genere *engagement* diario **optimizando costes de API**.

- [x] **Fuentes de noticias**: Yahoo Finance news (vía yfinance) y Reddit (r/stocks, r/investing, r/wallstreetbets) sin API key. Almacenadas en tabla `company_news`. Job: `daily-news-job`.
- [x] **Columnas de narrativa**: `top_news_title`, `top_news_url` y `narrative` añadidas a `anomaly_radar` y `sector_daily_opportunities`.
- [x] **Resúmenes con LLMs**: Job `daily-narrative-job` desplegado en Cloud Run. Llama a Claude Haiku únicamente para los símbolos seleccionados por el radar (~50-150/día). Genera narrativa de 3 frases estilo *Dealflow*: catalizador → evidencia → outlook. Coste estimado <0.01 USD/día.
- [ ] **Fuentes adicionales pendientes** (mejora futura):
    - Substack & Newsletters financieras vía RSS.
    - FinTwit / X (si la API resulta viable económicamente).

---

## 🔵 FASE 4.5: Inteligencia Macro y "Newsletter" (Nuevo)
**Objetivo:** Recopilar visión general del mercado (no solo por ticker) resumiendo canales de YouTube financieros clave y noticias macro, sirviendo como contenido diario para la portada o una newsletter.

- [x] **Tabla BigQuery `market_insights`**: Crear tabla para almacenar los análisis estructurados (bias, tesis, niveles clave) de cada fuente.
- [x] **Ingesta de YouTube (`youtube-transcript-api`)**: Extraer subtítulos de los últimos vídeos de una lista curada de canales de YouTube financieros sin usar API Keys que limiten por cuota.
- [x] **Ingesta de Noticias Macro (RSS)**: Leer feeds RSS públicos gratuitos (CNBC, Yahoo Finance Macro, Substacks seleccionados) usando la librería `feedparser`.
- [x] **Resumen con LLM (Claude Haiku)**: Nuevo Cloud Run Job (`daily-newsletter-job`) que procese las transcripciones y las noticias del día para generar resúmenes ejecutivos ("Qué ha pasado hoy en el mercado").

---

## � FASE 5: Producto Final (Front-end)
*Nota: Todos los hitos de interfaz de usuario, experiencia y visualización de datos han sido movidos a `ROADMAP_FRONT.md` para ser gestionados por el equipo frontend.*

---

## 🟣 FASE 6: Infraestructura, Back-end y Producción
**Objetivo:** Desplegar la aplicación de forma económica, segura y controlada para evitar costes desorbitados y poder medir el uso real.

- [x] **Cloud Scheduler completo** (2026-05-07): 7 triggers configurados en `europe-west1` (Madrid). Pipeline completo automatizado lun-vie:
    - 05:00 `daily-prices-cron` → 05:30 `daily-enrich-cron` → 07:00 `daily-sector-cron` + `daily-anomaly-cron` → 08:00 `daily-news-cron` → 09:00 `daily-narrative-cron`
    - Domingo 10:00 `weekly-companies-cron`
    - `deploy.sh` actualizado para gestionar schedulers en cada despliegue.
- [ ] **Hosting y Dominio (Low-Cost)**: Despliegue en plataformas de bajo coste o capa gratuita (ej. Render, Railway, Fly.io, PythonAnywhere).
- [ ] **Gobernanza de Costes BigQuery** (Crítico):
    - Implementar **límite de facturación estricto de 100€/mes** en GCP con alertas automáticas.
    - **Arquitectura de Tablas de Resultados Pre-calculados**: Crear una tabla resumen diaria (caché en BigQuery) que contenga los rankings del Radar de Anomalías, indicadores técnicos condensados y narrativas generadas.
    - Batch jobs nocturnos (scheduled queries) que actualizan la tabla caché una sola vez al día, amortizando costes.
- [ ] **Despliegue y CI/CD básico**: Configurar GitHub Actions para que los despliegues a producción se hagan de forma automática y segura tras cada cambio validado en el código.
- [ ] **Monitorización Back-end**: Integración con herramientas (ej. Sentry gratuitas) para capturar *tracebacks* y fallos de conexión a APIs en el lado del servidor.

---

## 🟤 FASE 7: Monetización y Proyecto de Portfolio
**Objetivo:** Preparar el proyecto como una carta de presentación profesional de alto nivel y explorar vías de sostenibilidad.

- [ ] **Showcase Técnico (Portfolio)**: Crear una sección "Acerca de / Arquitectura" en la propia web que explique gráficamente el pipeline de datos y el stack (BigQuery + Python + LLMs) pensado para reclutadores.
- [ ] **SEO (Search Engine Optimization)**: Optimización de meta-etiquetas, URLs semánticas y generación de *Sitemaps* dinámicos para que los buscadores indexen páginas de tickers específicos y atraigan tráfico orgánico.
- [ ] **Integración de Anuncios / Afiliación**: Añadir espacios no intrusivos para Google AdSense o banners de afiliados (brokers, plataformas de inversión) para intentar cubrir los costes de servidor.

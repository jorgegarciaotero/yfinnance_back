# 🎨 Roadmap Front-end: Market Atelier

Este documento refleja el estado de la interfaz de usuario, visualización de datos y experiencia del usuario (Jinja2 + Tailwind + JS). Para el pipeline de datos, consulta el proyecto Backend.

---

## 🔌 CONTRATOS DE API (Lo que provee el Backend)
- `/api/companies`: Universo de acciones disponibles.
- `/api/companies-snapshot`: Último snapshot enriquecido de todas las compañías.
- `/api/commodities`: ETFs y datos macro de materias primas/bonos.
- `/api/picks`: Oportunidades por Setup (Dip, Momentum, Value Reversal). **Incluye: `narrative`, `top_news_title`, `top_news_url`.**
- `/api/radar`: Motor de anomalías (Spike, Sobrevendido, Inercia). **Incluye: `narrative`, `top_news_title`, `top_news_url`.**
- `/api/stock/{symbol}`: Histórico 260d OHLCV + Indicadores Técnicos + Fundamentales.
- `/api/insights`: Termómetro de mercado diario (Resúmenes de YouTube y RSS Macro).

---

## 🔴 FASE 5: Producto Final (UI/UX)
**Objetivo:** Interfaz limpia y legible con un "Signal-to-Noise ratio" altísimo.
- [x] **Dashboard General**: Resumen de mercado y oportunidades diarias.
- [x] **Detalle de Acción (Stock)**: Gráficos interactivos (Lightweight Charts) con RSI, Bollinger y MACD.
- [x] **Sección "Radar Diario"**: Tabla interactiva de anomalías con filtrado y paginación.
- [x] **Sección "Macro & Materias Primas"**: Semáforo visual de la economía con gráficos de Bonos y Commodities.
- [x] **Refinamiento UI/UX**: Unificación de estilo oscuro en componentes de filtrado, traducción al inglés de tipos de anomalías en la vista y limpieza visual de tablas usando texto semántico en color para evitar fatiga visual.
- [ ] **Integración de Narrativas (Dealflow)**: Incorporar en Radar y Dashboard los resúmenes LLM de mercado y noticias (`narrative` y `top_news_title`). *(DESBLOQUEADO: Fase 4 del Back-end completada)*.
- [ ] **Sección "Morning Briefing / Insights"**: Dashboard con el Termómetro de Mercado general (Bullish/Bearish), nube de activos mencionados y resúmenes diarios curados de YouTube y noticias. *(DESBLOQUEADO: Fase 4.5 del Back-end completada)*.

---

## 🟣 FASE 6: Monitorización y Analítica (Front-end)
- [x] **Rate Limiting (UX)**: Aumento del límite de visualización de detalles de acciones de 20 a 150 símbolos únicos cada 12 horas.
- [ ] **Monitorización UI**: Integrar Sentry (Browser/JS) para capturar bugs que los usuarios sufran en el navegador.
- [ ] **Analítica Web Privada**: Integrar herramientas tipo Plausible Analytics o Umami para medir tráfico y retención sin cookies invasivas.

---

## 🟤 FASE 7: Monetización y Proyecto de Portfolio
- [ ] **Showcase Técnico (Portfolio)**: Crear página "Acerca de / Arquitectura" que explique gráficamente el pipeline de GCP + LLMs a reclutadores.
- [ ] **SEO (Search Engine Optimization)**: Meta-etiquetas dinámicas por Ticker y generación de `sitemap.xml` para indexación en buscadores.
- [ ] **Integración de Anuncios / Afiliación**: Añadir espacios no intrusivos para Google AdSense o banners de afiliados (brokers).
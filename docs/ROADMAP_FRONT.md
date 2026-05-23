# 🎨 Roadmap Front-end: Market Atelier

Este documento refleja el estado de la interfaz de usuario, visualización de datos y experiencia del usuario (Jinja2 + Tailwind + JS). Para el pipeline de datos, consulta el proyecto Backend.

---

## 🔌 CONTRATOS DE API (Lo que provee el Backend)
- `/api/companies`: Universo de acciones disponibles.
- `/api/picks`: Oportunidades por Setup (Dip, Momentum, Value Reversal).
- `/api/radar`: Motor de anomalías (Spike, Sobrevendido, Inercia).
- `/api/stock/{symbol}`: Histórico 260d OHLCV + Indicadores Técnicos + Fundamentales.

---

## 🔴 FASE 5: Producto Final (UI/UX)
**Objetivo:** Interfaz limpia y legible con un "Signal-to-Noise ratio" altísimo.
- [x] **Dashboard General**: Resumen de mercado y oportunidades diarias.
- [x] **Detalle de Acción (Stock)**: Gráficos interactivos (Lightweight Charts) con RSI, Bollinger y MACD.
- [x] **Sección "Radar Diario"**: Tabla interactiva de anomalías con filtrado y paginación.
- [ ] **Sección "Macro & Materias Primas"**: Semáforo visual de la economía (Commodities/Bonos).
- [ ] **Sección "Narrativa Semanal"**: UI para mostrar resúmenes de por qué sube el mercado (BLOQUEADO: Esperando Fase 4 del Back-end).

---

## 🟣 FASE 6: Monitorización y Analítica (Front-end)
- [ ] **Monitorización UI**: Integrar Sentry (Browser/JS) para capturar bugs que los usuarios sufran en el navegador.
- [ ] **Analítica Web Privada**: Integrar herramientas tipo Plausible Analytics o Umami para medir tráfico y retención sin cookies invasivas.

---

## 🟤 FASE 7: Monetización y Proyecto de Portfolio
- [ ] **Showcase Técnico (Portfolio)**: Crear página "Acerca de / Arquitectura" que explique gráficamente el pipeline de GCP + LLMs a reclutadores.
- [ ] **SEO (Search Engine Optimization)**: Meta-etiquetas dinámicas por Ticker y generación de `sitemap.xml` para indexación en buscadores.
- [ ] **Integración de Anuncios / Afiliación**: Añadir espacios no intrusivos para Google AdSense o banners de afiliados (brokers).

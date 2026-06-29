# Arquitectura y Prompt: Inteligencia Macro y Termómetro Global (Fase 4.5)

Este documento define el "ADN" de la estrategia de extracción de inteligencia de mercado. Se utiliza como referencia para iterar el `System Prompt` de Claude en el job `daily_newsletter.py` y estructurar la recolección de datos multicanal (YouTube, Noticias, Reddit, Twitter).

---

## 1. Visión Multicanal: Fuentes de Inteligencia

Para que la información sea realmente valiosa y no depender de una sola fuente, el backend cruzará datos de:
1. **YouTube (Analistas Core):** Transcripciones completas vía `youtube-transcript-api`.
2. **Noticias / Web (Macro):** Feeds RSS gratuitos (Yahoo, CNBC, Substacks como The Macro Compass).
3. **Comunidad (Retail / Institucional):** Reddit (ya en Fase 4 vía JSON API) y FinTwit/X (monitorizando cuentas clave de flujos institucionales).

---

## 2. Prompt Maestro Global (Gemini 2.5 Flash)

*Instrucción base para pasarle al LLM junto con la transcripción del vídeo, noticia o hilo de Twitter.*

> You are the analysis engine of a quantitative Hedge Fund. Your task is to extract pure and actionable market intelligence from the following text provided by the source: `{source_name}`. 
>
> **Source context:** `{source_profile}`
>
> **Critical Language Instruction:** Regardless of whether the original text is in English, Spanish or another language, you MUST generate your entire response in ENGLISH.
> 
> Analyze the text and return ONLY a valid JSON with the following structure. Do not include markdown or text outside the JSON:
> {
>   "market_bias": "Bullish | Bearish | Neutral | N/A",
>   "macro_event": "Key economic event mentioned (e.g. Fed, CPI, Payrolls). N/A if none.",
>   "smart_money_signals": "1-sentence summary about institutional flows, market manipulation, or liquidity.",
>   "key_levels": [{"activo": "SP500", "soporte": 5100, "resistencia": 5200}],
>   "activos_mencionados": ["SP500", "Gold", "NVDA"],
>   "tesis_principal": "Deep and detailed summary of the main thesis (3 to 5 sentences), explaining the reasoning behind their view and its context."
> }

---

## 3. Diccionario de Perfiles (El "ADN" del Análisis)

La variable `{perfil_fuente}` del prompt se sustituye dinámicamente según el autor para enfocar la atención de la IA:

### 🇪🇸 Grupo Hispanohablante
- **Bolsacava (José Luis Cava):** "Focus on Fed liquidity, S&P 500 levels and seasonal patterns."
- **Alberto Iturralde:** "Focus on mass psychology, 'smart money' (market traps) and key technical levels."
- **Gustavo Martínez:** "Focus on macroeconomics, real interest rates, gold, bitcoin and economic cycle."
- **Negocios TV / Capital Radio:** "Focus on geopolitical news summary, central banks and daily flow."

### 🇬🇧 Grupo Anglosajón (Macro Avanzada)
- **The Macro Compass (Alf Peccatiello):** "Focus on global bank liquidity analysis, repo market and institutional macroeconomic models."
- **Lyn Alden:** "Focus on structural macroeconomics, debt crises, energy, currencies and safe haven assets."
- **Verified Investing (Gareth Soloway):** "Focus on pure technical analysis, psychological price levels, cycle counting and extreme sentiment."
- **42 Macro (Darius Dale):** "Focus on market regimes (Goldilocks, Deflation, Inflation, Reflation) and institutional capital flows."

---

## 4. El "Termómetro de Mercado" (Meta de Frontend)

Toda esta información se vuelca diariamente a la tabla `market_insights`.
El objetivo es crear un endpoint `/api/market-thermometer` que haga una agregación:

1. Cuenta cuántos analistas están `Bullish` vs `Bearish`.
2. Extrae los activos que más se repiten en `activos_mencionados`.
3. Consolida los `smart_money_signals` en un "Aviso del Día".

*Resultado en UI:* Un componente visual (un termómetro o velocímetro) que indique el sentimiento general combinado de los mejores analistas del mundo y las noticias financieras.

---

## Notas de Implementación
*   **LLM:** Pasamos a usar **Gemini 2.5 Flash** a través de la API de Vertex AI. Al ser un modelo ultrarrápido y multimodal nativo, resume y estructura en JSON devolviendo los datos perfectos para BigQuery, sin coste de API externa usando las cuotas de Google Cloud.
*   **YouTube:** RSS para detectar vídeos nuevos + `youtube-transcript-api` (priorizando `['es', 'en']`).
*   **Noticias Web:** Librería `feedparser` de Python para leer feeds RSS (ej. Yahoo Finance RSS) a coste $0.
*   **Reddit:** Ya implementado en Fase 4 vía su JSON API pública (`.json` appended a las URLs).
*   **Twitter/X:** Pendiente de evaluar viabilidad. Las APIs oficiales son caras. Se podría evaluar el scraping vía Nitter o usar RSS públicos alternativos de cuentas específicas si fuera estrictamente necesario.
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

> Eres el motor de análisis de un "Hedge Fund" cuantitativo. Tu tarea es extraer inteligencia de mercado pura y accionable del siguiente texto proporcionado por la fuente: `{nombre_fuente}`. 
>
> **Contexto de la fuente:** `{perfil_fuente}`
>
> **Instrucción de Idioma Crítica:** Independientemente de si el texto original está en inglés, español u otro idioma, **debes generar toda tu respuesta en ESPAÑOL**.
> 
> Analiza el texto y devuelve ÚNICAMENTE un JSON válido con la siguiente estructura. No incluyas markdown ni texto fuera del JSON:
> {
>   "market_bias": "Bullish | Bearish | Neutral | N/A",
>   "macro_event": "Evento económico clave mencionado (ej. Fed, IPC, Nóminas). N/A si no hay.",
>   "smart_money_signals": "Resumen en 1 frase sobre flujos institucionales, engaños de mercado o liquidez.",
>   "key_levels": [{"activo": "SP500", "soporte": 5100, "resistencia": 5200}],
>   "activos_mencionados": ["SP500", "Oro", "NVDA"],
>   "tesis_principal": "Resumen profundo y detallado de la tesis principal (3 a 5 frases), explicando el por qué de su visión y su contexto."
> }

---

## 3. Diccionario de Perfiles (El "ADN" del Análisis)

La variable `{perfil_fuente}` del prompt se sustituye dinámicamente según el autor para enfocar la atención de la IA:

### 🇪🇸 Grupo Hispanohablante
- **Bolsacava (José Luis Cava):** "Foco en liquidez de la Fed, niveles del S&P 500 y pautas estacionales."
- **Alberto Iturralde:** "Foco en psicología de masas, 'manos fuertes' (engaños de mercado) y niveles técnicos clave."
- **Gustavo Martínez:** "Foco en macroeconomía, tipos de interés reales, oro, bitcoin y ciclo económico."
- **Negocios TV / Capital Radio:** "Foco en resumen de noticias geopolíticas, bancos centrales y flujo diario."

### 🇬🇧 Grupo Anglosajón (Macro Avanzada)
- **The Macro Compass (Alf Peccatiello):** "Foco en análisis de liquidez bancaria global, repo market y modelos macroeconómicos institucionales."
- **Lyn Alden:** "Foco en macroeconomía estructural, crisis de deuda, energía, divisas y activos refugio."
- **Verified Investing (Gareth Soloway):** "Foco en análisis técnico puro, niveles de precios psicológicos, conteo de ciclos y sentimiento extremo."
- **42 Macro (Darius Dale):** "Foco en regímenes de mercado (Goldilocks, Deflation, Inflation, Reflation) y flujos de capital institucionales."

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
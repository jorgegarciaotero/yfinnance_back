# BigQuery Dataset: `yfinance-gcp.yfinance_raw`

Financial data pipeline sourcing from Yahoo Finance. Covers ~2,700 stocks from S&P 500, Russell 2000 and STOXX 600.

---

## `sector_daily_opportunities` — Sector-based daily investment setups

**The main output table.** Updated every trading day after market close. For each sector, extracts up to 10 companies in three distinct setup categories, each with a composite score (0–100) and a plain-English reason. Partitioned by `date`, clustered by `sector` and `setup_type` for efficient queries.

**Setup categories:**
- `Dip (Tendencia Alcista)` — confirmed Bullish trend with RSI in oversold zone (30–45) and negative momentum. Best dip-buying entries within an uptrend.
- `Momentum (Líderes)` — sector leaders near their 52-week highs with strong momentum (>+2% in 10d) and RSI in momentum zone (55–75).
- `Value Reversal` — deep corrections (>−30% from 52w high) with low PE ratio (<20) and analyst buy/strong_buy consensus.

**Score (0–100, 4 components × 25 pts):**

| Setup | A | B | C | D |
|-------|---|---|---|---|
| Dip | RSI oversold depth | Health vs SMA200 | Analyst consensus | Market cap quality |
| Momentum | Momentum 10d strength | RSI sweet spot (bell at 65) | Closeness to 52w high | Analyst consensus |
| Value Reversal | PE quality (lower = better) | Upside potential depth | Analyst consensus | Market cap quality |

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Date the opportunities were generated (partition key) |
| `sector` | STRING | Sector (e.g. Technology, Financials) |
| `industry` | STRING | Industry within the sector |
| `symbol` | STRING | Stock ticker (e.g. AAPL, ASML.AS) |
| `setup_type` | STRING | `Dip (Tendencia Alcista)`, `Momentum (Líderes)`, or `Value Reversal` |
| `close` | FLOAT | Closing price |
| `market_cap_bn` | FLOAT | Market capitalisation in billions USD |
| `rsi_14` | FLOAT | RSI 14-period (0–100). <30 oversold, >70 overbought |
| `momentum_10d_pct` | FLOAT | Price change % over last 10 trading days |
| `dist_sma200_pct` | FLOAT | % distance from SMA200 (positive = above) |
| `pct_from_52w_high` | FLOAT | % drop from 52-week high (negative value) |
| `pct_from_52w_low` | FLOAT | % gain from 52-week low (positive value) |
| `pe_ratio` | FLOAT | Price-to-earnings ratio (close / trailing_eps) |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `score` | FLOAT | Composite score 0–100 (higher = better opportunity within its category) |
| `rank_in_sector` | INTEGER | Rank within its sector + setup_type (1 = best, max 10) |
| `reason` | STRING | Plain-English explanation of why this stock was selected |

---

## `enriched_prices_table` — Prices + technical & fundamental indicators

Full price history for all tracked stocks enriched with technical indicators and fundamental data. Updated daily. Source for `sector_daily_opportunities`.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Trading date |
| `symbol` | STRING | Stock ticker |
| `close` | FLOAT | Closing price |
| `volume` | INTEGER | Volume traded |
| `sector` | STRING | Sector (from companies) |
| `industry` | STRING | Industry (from companies) |
| `market_cap` | INTEGER | Market capitalisation in USD |
| `shares_outstanding` | INTEGER | Total shares outstanding |
| `trailing_eps` | FLOAT | Earnings per share (last 12 months) |
| `pe_ratio` | FLOAT | Price-to-earnings ratio (close / trailing_eps) |
| `beta` | FLOAT | Volatility relative to the market |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `rsi_14` | FLOAT | RSI 14-period (0–100) |
| `pct_from_52w_high` | FLOAT | % drop from 52-week high (negative) |
| `pct_from_52w_low` | FLOAT | % gain from 52-week low (positive) |
| `bollinger_high` | FLOAT | Bollinger upper band |
| `bollinger_low` | FLOAT | Bollinger lower band |
| `bollinger_pct` | FLOAT | Position within Bollinger bands (0 = lower band, 1 = upper band) |
| `long_term_trend` | STRING | `Bullish` if SMA50 > SMA200, `Bearish` otherwise |
| `macd_line` | FLOAT | MACD proxy (SMA12 – SMA26). Positive = bullish momentum |
| `momentum_10d` | FLOAT | Return over last 10 trading days (decimal, e.g. 0.08 = +8%) |
| `dist_sma_200` | FLOAT | Distance from SMA200 (decimal, e.g. 0.10 = 10% above) |

---

## `daily_prices` — Raw OHLCV prices

Raw price data downloaded daily from Yahoo Finance. One row per stock per trading day. No indicators — source for all technical calculations in `enriched_prices_table`.

| Column | Type | Description |
|--------|------|-------------|
| `date` | DATE | Trading date |
| `symbol` | STRING | Stock ticker |
| `open` | FLOAT | Opening price |
| `high` | FLOAT | Daily high |
| `low` | FLOAT | Daily low |
| `close` | FLOAT | Closing price |
| `adj_close` | FLOAT | Adjusted closing price (accounts for splits and dividends) |
| `volume` | INTEGER | Volume traded |

---

## `companies` — Company fundamentals

Fundamental metadata for each tracked company, refreshed every Sunday. Accumulates one snapshot per week per symbol (historical record). Used to enrich `enriched_prices_table` with fundamentals.

| Column | Type | Description |
|--------|------|-------------|
| `symbol` | STRING | Stock ticker |
| `source` | STRING | Index source: `sp500`, `russell2000`, `stoxx600` |
| `short_name` | STRING | Short company name |
| `long_name` | STRING | Full legal company name |
| `business_summary` | STRING | Business description from Yahoo Finance |
| `provider` | STRING | Data provider (always `yahoo`) |
| `is_active` | BOOLEAN | Whether the symbol is currently active on Yahoo Finance |
| `last_checked` | TIMESTAMP | Last time the symbol was validated |
| `last_seen` | DATE | Last date the symbol was seen active |
| `quote_type` | STRING | Instrument type (e.g. `EQUITY`) |
| `exchange` | STRING | Exchange code (e.g. `NMS`, `LSE`) |
| `exchange_timezone` | STRING | Exchange timezone (e.g. `America/New_York`) |
| `currency` | STRING | Trading currency (e.g. `USD`, `EUR`) |
| `market` | STRING | Market identifier |
| `country` | STRING | Country of incorporation |
| `sector` | STRING | Sector (e.g. Technology, Financials) |
| `industry` | STRING | Industry within the sector |
| `market_cap` | INTEGER | Market capitalisation in USD |
| `shares_outstanding` | INTEGER | Total shares outstanding |
| `float_shares` | INTEGER | Floating shares (publicly tradeable) |
| `avg_volume_3m` | INTEGER | Average daily volume over last 3 months |
| `avg_volume_10d` | INTEGER | Average daily volume over last 10 days |
| `beta` | FLOAT | Volatility relative to the market |
| `trailing_eps` | FLOAT | Earnings per share (last 12 months) |
| `forward_eps` | FLOAT | Estimated earnings per share (next 12 months) |
| `book_value` | FLOAT | Book value per share |
| `dividend_rate` | FLOAT | Annual dividend per share |
| `ex_dividend_date` | INTEGER | Ex-dividend date (Unix timestamp) |
| `forward_pe` | FLOAT | Forward price-to-earnings ratio |
| `dividend_yield` | FLOAT | Dividend yield (decimal, e.g. 0.03 = 3%) |
| `return_on_equity` | FLOAT | Return on equity (ROE) |
| `target_mean_price` | FLOAT | Analyst mean price target |
| `recommendation_key` | STRING | Analyst consensus: `strong_buy`, `buy`, `hold`, `underperform`, `sell` |
| `updated_at` | DATE | Date of this weekly snapshot |

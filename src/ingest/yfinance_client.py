# src/ingest/yfinance_client.py
"""
Yahoo Finance client helpers.

Rules:
- A symbol is VALID only if Yahoo returns real OHLCV rows.
- fast_info / info are NOT trusted.
- Empty history == invalid.
"""

import yfinance as yf
import pandas as pd


def get_prices(symbol: str, period: str = "5d") -> pd.DataFrame:
    """
    Download OHLCV prices from Yahoo.

    Returns:
        DataFrame with data, empty if symbol is invalid.
    """
    try:
        df = yf.Ticker(symbol).history(
            period=period,
            auto_adjust=False,
            actions=False
        )
        if df.empty:
            return df

        df = df.reset_index()
        df["symbol"] = symbol
        return df
    except Exception:
        return pd.DataFrame()


def is_yahoo_symbol_valid(symbol: str) -> bool:
    """
    Hard validation of Yahoo symbol.

    Logic:
    - Fetch 5d history
    - VALID only if at least 1 OHLC row exists
    """
    try:
        df = yf.Ticker(symbol).history(
            period="5d",
            auto_adjust=False,
            actions=False
        )
        return not df.empty
    except Exception:
        return False

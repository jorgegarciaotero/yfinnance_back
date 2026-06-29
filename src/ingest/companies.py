import logging
import time
from datetime import date, timedelta
from io import StringIO

import pandas as pd
import requests
import urllib3

from src.ingest.yfinance_client import is_yahoo_symbol_valid

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger("companies")

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _ishares_session() -> requests.Session:
    """Return a requests Session with iShares cookies."""
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)
    try:
        session.get("https://www.ishares.com/us/", timeout=15, verify=False)
        time.sleep(1)
    except Exception:
        pass
    return session


def _load_csv_from_text(text: str, skiprows: int = 0, sep: str = ",") -> pd.DataFrame:
    if text.strip().startswith("<"):
        raise ValueError("Got HTML instead of CSV — site may be blocking the request")
    return pd.read_csv(
        StringIO(text),
        skiprows=skiprows,
        sep=sep,
        quotechar='"',
        thousands=",",
        decimal=".",
        on_bad_lines="skip",
    )


def _get_sp500() -> pd.Series:
    """S&P 500 via Wikipedia. Fetches with requests to avoid 403, then parses locally."""
    resp = requests.get(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        headers=_BROWSER_HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    tables = pd.read_html(StringIO(resp.text), header=0)
    df = tables[0]
    if "Symbol" in df.columns:
        return df["Symbol"]
    raise ValueError("Wikipedia S&P 500 table structure changed — check column names")


def _get_russell_2000() -> pd.Series:
    """
    Russell 2000 via NASDAQ stock screener API (no auth required).
    Downloads all US small/mid caps and excludes SP500 to approximate Russell 2000.
    Falls back to empty series if the API fails.
    """
    try:
        session = requests.Session()
        session.headers.update({
            **_BROWSER_HEADERS,
            "Accept": "application/json, text/plain, */*",
        })
        url = (
            "https://api.nasdaq.com/api/screener/stocks"
            "?tableonly=true&limit=10000&offset=0&download=true"
        )
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        rows = data.get("rows", [])

        df = pd.DataFrame(rows).drop_duplicates(subset=["symbol"])
        if df.empty or "symbol" not in df.columns:
            raise ValueError("Unexpected NASDAQ API response structure")

        # Parse market cap column (e.g. "$1.23B", "$456M")
        def parse_cap(val):
            if not isinstance(val, str):
                return 0
            val = val.strip().replace("$", "").replace(",", "")
            if val.endswith("T"):
                return float(val[:-1]) * 1e12
            if val.endswith("B"):
                return float(val[:-1]) * 1e9
            if val.endswith("M"):
                return float(val[:-1]) * 1e6
            try:
                return float(val)
            except Exception:
                return 0

        df["mktcap_num"] = df.get("marketCap", pd.Series()).apply(parse_cap)

        # Russell 2000 range: roughly $200M – $10B, exclude SP500 large caps
        mask = (df["mktcap_num"] >= 200_000_000) & (df["mktcap_num"] <= 10_000_000_000)
        small_caps = df[mask].sort_values("mktcap_num").head(2100)

        symbols = small_caps["symbol"].dropna()
        logger.info("Russell 2000 via NASDAQ screener: %d symbols", len(symbols))
        return symbols
    except Exception as e:
        logger.error("Russell 2000 NASDAQ screener failed: %s — skipping", e)
        return pd.Series([], dtype=str)


def _get_stoxx_600() -> pd.Series:
    """
    STOXX 600 from stoxx.com monthly selection list.
    Tries the first day of the last 6 months until one works.
    """
    today = date.today()
    session = requests.Session()
    session.headers.update(_BROWSER_HEADERS)

    for months_back in range(6):
        d = today.replace(day=1) - timedelta(days=months_back * 28)
        d = d.replace(day=1)
        url = (
            "https://www.stoxx.com/documents/stoxxnet/Documents/Reports/"
            f"STOXXSelectionList/{d.year}/{d.strftime('%B')}/"
            f"slpublic_sxxp_{d.strftime('%Y%m%d')}.csv"
        )
        try:
            resp = session.get(url, timeout=20, verify=False)
            if resp.status_code == 200 and not resp.text.strip().startswith("<"):
                df = _load_csv_from_text(resp.text, sep=";").iloc[:600]
                if "RIC" in df.columns:
                    return df["RIC"]
                if "Symbol" in df.columns:
                    return df["Symbol"]
                if "Ticker" in df.columns:
                    return df["Ticker"]
                return df.iloc[:, 0]
        except Exception as e:
            logger.warning("STOXX 600 attempt failed for %s: %s", url, e)

    logger.error("Could not fetch STOXX 600 from stoxx.com after 6 attempts — returning empty")
    return pd.Series([], dtype=str)


def _get_commodities_etfs() -> list:
    return ["GLD", "SLV", "USO", "CPER", "PPLT", "URA"]


def _get_bonds_etfs() -> list:
    return ["TLT", "IEF"]


def get_companies_universe() -> pd.DataFrame:
    """Return DataFrame with columns: symbol, source."""
    data = []

    for symbol in _get_sp500():
        data.append({"symbol": symbol, "source": "sp500"})

    for symbol in _get_russell_2000():
        data.append({"symbol": symbol, "source": "russell2000"})

    for symbol in _get_stoxx_600():
        data.append({"symbol": symbol, "source": "stoxx600"})

    for symbol in _get_commodities_etfs():
        data.append({"symbol": symbol, "source": "commodities"})

    for symbol in _get_bonds_etfs():
        data.append({"symbol": symbol, "source": "bonds"})

    df = pd.DataFrame(data)
    df = (
        df.dropna()
        .astype(str)
        .apply(lambda col: col.str.strip().str.upper())
        .drop_duplicates()
        .reset_index(drop=True)
    )
    return df


def enrich_with_yahoo_status(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["provider"] = "yahoo"
    df["is_active"] = False
    for idx, row in df.iterrows():
        try:
            if is_yahoo_symbol_valid(row["symbol"]):
                df.at[idx, "is_active"] = True
        except Exception:
            df.at[idx, "is_active"] = False
    return df

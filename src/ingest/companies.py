import pandas as pd
import requests
from io import StringIO

from src.ingest.yfinance_client import is_yahoo_symbol_valid
 

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _load_csv(url: str, skiprows: int = 0, sep: str = ",") -> pd.DataFrame:
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()

    return pd.read_csv(
        StringIO(response.text),
        skiprows=skiprows,
        sep=sep,
        quotechar='"',
        thousands=",",
        decimal=".",
        on_bad_lines="skip",
    )


def _get_sp500() -> pd.Series:
    url = (
        "https://www.ishares.com/us/products/239726/"
        "ishares-core-sp-500-etf/1467271812596.ajax"
        "?fileType=csv&fileName=IVV_holdings&dataType=fund"
    )
    df = _load_csv(url, skiprows=9).iloc[:-2]
    return df["Ticker"]


def _get_russell_2000() -> pd.Series:
    url = (
        "https://www.ishares.com/us/products/239710/"
        "ishares-russell-2000-etf/1467271812596.ajax"
        "?fileType=csv&fileName=IWM_holdings&dataType=fund"
    )
    df = _load_csv(url, skiprows=9).iloc[:-2]
    return df["Ticker"]


def _get_stoxx_600() -> pd.Series:
    url = (
        "https://www.stoxx.com/documents/stoxxnet/Documents/Reports/"
        "STOXXSelectionList/2025/April/slpublic_sxxp_20250401.csv"
    )
    df = _load_csv(url, sep=";").iloc[:600]
    return df["RIC"]


def get_companies_universe() -> pd.DataFrame:
    """
    Return DataFrame with columns:
    - symbol
    - source
    """
    data = []

    for symbol in _get_sp500():
        data.append({"symbol": symbol, "source": "sp500"})

    for symbol in _get_russell_2000():
        data.append({"symbol": symbol, "source": "russell2000"})

    for symbol in _get_stoxx_600():
        data.append({"symbol": symbol, "source": "stoxx600"})

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
    """
    Add yahoo provider and is_active flag.
    """
    df = df.copy()

    df["provider"] = "yahoo"
    df["is_active"] = False

    for idx, row in df.iterrows():
        symbol = row["symbol"]
        try:
            if is_yahoo_symbol_valid(symbol):
                df.at[idx, "is_active"] = True
        except Exception:
            df.at[idx, "is_active"] = False

    return df


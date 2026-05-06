from __future__ import annotations

from datetime import datetime
from http.client import RemoteDisconnected
from typing import Annotated

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from stockstats import wrap


class AkShareUnsupportedSymbolError(ValueError):
    pass


class AkShareConnectionError(ConnectionError):
    pass


_INDICATOR_DESCRIPTIONS = {
    "close_50_sma": "50 SMA: A medium-term trend indicator.",
    "close_200_sma": "200 SMA: A long-term trend benchmark.",
    "close_10_ema": "10 EMA: A responsive short-term average.",
    "macd": "MACD: Computes momentum via differences of EMAs.",
    "macds": "MACD Signal: An EMA smoothing of the MACD line.",
    "macdh": "MACD Histogram: Shows the gap between the MACD line and its signal.",
    "rsi": "RSI: Measures momentum to flag overbought/oversold conditions.",
    "boll": "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands.",
    "boll_ub": "Bollinger Upper Band: Typically 2 standard deviations above the middle line.",
    "boll_lb": "Bollinger Lower Band: Typically 2 standard deviations below the middle line.",
    "atr": "ATR: Averages true range to measure volatility.",
    "vwma": "VWMA: A moving average weighted by volume.",
    "mfi": "MFI: The Money Flow Index measures buying and selling pressure using price and volume.",
}


def get_stock_data(
    symbol: Annotated[str, "ticker symbol of the company"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    normalized_symbol = normalize_a_share_symbol(symbol)
    data = _fetch_akshare_history(normalized_symbol, start_date, end_date)
    if data.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    data = _to_ohlcv(data)
    csv_string = data.to_csv(index=False)
    header = f"# Stock data for {normalized_symbol} from {start_date} to {end_date}\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + csv_string


def get_indicators(
    symbol: Annotated[str, "ticker symbol of the company"],
    indicator: Annotated[str, "technical indicator to get the analysis and report of"],
    curr_date: Annotated[str, "The current trading date you are trading on, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    if indicator not in _INDICATOR_DESCRIPTIONS:
        raise ValueError(
            f"Indicator {indicator} is not supported. Please choose from: {list(_INDICATOR_DESCRIPTIONS.keys())}"
        )

    curr_date_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    before = curr_date_dt - relativedelta(days=look_back_days)
    warmup_start = curr_date_dt - relativedelta(days=max(look_back_days + 260, 320))
    normalized_symbol = normalize_a_share_symbol(symbol)
    data = _fetch_akshare_history(
        normalized_symbol,
        warmup_start.strftime("%Y-%m-%d"),
        curr_date,
    )
    if data.empty:
        return f"No data found for symbol '{symbol}' before {curr_date}"

    df = wrap(_to_ohlcv(data))
    df[indicator]
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    values = dict(zip(df["Date"], df[indicator]))

    current_dt = curr_date_dt
    lines = []
    while current_dt >= before:
        date_str = current_dt.strftime("%Y-%m-%d")
        value = values.get(date_str)
        if value is None or pd.isna(value):
            value_text = "N/A: Not a trading day (weekend or holiday)"
        else:
            value_text = str(value)
        lines.append(f"{date_str}: {value_text}")
        current_dt = current_dt - relativedelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + _INDICATOR_DESCRIPTIONS[indicator]
    )


def normalize_a_share_symbol(symbol: str) -> str:
    raw = symbol.strip().upper()
    if raw.endswith((".SZ", ".SS", ".SH")):
        raw = raw.split(".", 1)[0]
    elif raw.startswith(("SZ", "SH")) and len(raw) == 8:
        raw = raw[2:]

    if not (raw.isdigit() and len(raw) == 6):
        raise AkShareUnsupportedSymbolError(f"AkShare A-share vendor only supports 6-digit A-share symbols, got '{symbol}'")
    return raw


def _fetch_akshare_history(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    start = datetime.strptime(start_date, "%Y-%m-%d").strftime("%Y%m%d")
    end = datetime.strptime(end_date, "%Y-%m-%d").strftime("%Y%m%d")
    try:
        return ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
    except (requests.RequestException, ConnectionError, RemoteDisconnected) as exc:
        raise AkShareConnectionError(f"AkShare connection failed for {symbol}: {exc}") from exc


def _to_ohlcv(data: pd.DataFrame) -> pd.DataFrame:
    column_map = {
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
    }
    missing = [column for column in column_map if column not in data.columns]
    if missing:
        raise ValueError(f"AkShare data missing required columns: {missing}")

    result = data[list(column_map)].rename(columns=column_map).copy()
    result["Date"] = pd.to_datetime(result["Date"])
    numeric_columns = ["Open", "High", "Low", "Close", "Volume"]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    for column in ["Open", "High", "Low", "Close"]:
        result[column] = result[column].round(2)
    result = result.dropna(subset=["Open", "High", "Low", "Close"])
    result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
    return result[["Date", "Open", "High", "Low", "Close", "Volume"]]

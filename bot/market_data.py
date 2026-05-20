from __future__ import annotations

import pandas as pd
import yfinance as yf


def download_ohlc(symbol: str, period: str = "6mo", interval: str = "1h") -> pd.DataFrame:
    df = yf.download(symbol, period=period, interval=interval, auto_adjust=True, progress=False)

    if df.empty:
        raise RuntimeError(
            f"โหลด Yahoo Finance ไม่สำเร็จ symbol={symbol}, period={period}, interval={interval}. "
            "ลองลด period, เปลี่ยน interval, หรือเช็กอินเทอร์เน็ต"
        )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.rename(columns=str.lower)

    needed = {"open", "high", "low", "close"}
    if not needed.issubset(set(df.columns)):
        raise RuntimeError(f"ข้อมูล OHLC ไม่ครบ ได้ columns={list(df.columns)}")

    cols = ["open", "high", "low", "close"]
    if "volume" in df.columns:
        cols.append("volume")

    df = df[cols].dropna()
    df.index = pd.to_datetime(df.index)
    df.index.name = "datetime"
    return df

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def add_chart_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    out["ret_1"] = out["close"].pct_change()
    out["ret_3"] = out["close"].pct_change(3)
    out["ret_6"] = out["close"].pct_change(6)

    out["ema_20"] = out["close"].ewm(span=20, adjust=False).mean()
    out["ema_50"] = out["close"].ewm(span=50, adjust=False).mean()
    out["ema_200"] = out["close"].ewm(span=200, adjust=False).mean()

    out["ema_20_slope"] = out["ema_20"].pct_change(3)
    out["ema_50_slope"] = out["ema_50"].pct_change(3)
    out["ema_spread_50_200"] = (out["ema_50"] - out["ema_200"]) / out["close"]

    out["rsi_14"] = rsi(out["close"], 14)
    out["atr_14"] = atr(out, 14)
    out["atr_pct"] = out["atr_14"] / out["close"]

    out["range_pct"] = (out["high"] - out["low"]) / out["close"]
    out["body_pct"] = (out["close"] - out["open"]).abs() / out["close"]

    prev_open = out["open"].shift(1)
    prev_close = out["close"].shift(1)

    out["bullish_engulfing"] = (
        (out["close"] > out["open"])
        & (prev_close < prev_open)
        & (out["open"] <= prev_close)
        & (out["close"] >= prev_open)
    ).astype(int)

    out["bearish_engulfing"] = (
        (out["close"] < out["open"])
        & (prev_close > prev_open)
        & (out["open"] >= prev_close)
        & (out["close"] <= prev_open)
    ).astype(int)

    out["above_ema_200"] = (out["close"] > out["ema_200"]).astype(int)
    out["ema_50_above_200"] = (out["ema_50"] > out["ema_200"]).astype(int)

    return out


def make_target(df: pd.DataFrame, horizon: int = 3, min_move_atr: float = 0.0) -> pd.DataFrame:
    out = df.copy()
    out["future_close"] = out["close"].shift(-horizon)
    out["future_ret"] = (out["future_close"] - out["close"]) / out["close"]
    future_move = out["future_close"] - out["close"]
    if min_move_atr > 0 and "atr_14" in out.columns:
        min_move = out["atr_14"] * float(min_move_atr)
        out["target_up"] = np.where(
            future_move > min_move,
            1,
            np.where(future_move < -min_move, 0, np.nan),
        )
    else:
        out["target_up"] = (out["future_ret"] > 0).astype(int)
    return out


def feature_columns(df: pd.DataFrame) -> list[str]:
    cols = [
        "ret_1",
        "ret_3",
        "ret_6",
        "ema_20_slope",
        "ema_50_slope",
        "ema_spread_50_200",
        "rsi_14",
        "atr_pct",
        "range_pct",
        "body_pct",
        "bullish_engulfing",
        "bearish_engulfing",
        "above_ema_200",
        "ema_50_above_200",
    ]

    if "news_sentiment" in df.columns:
        cols.append("news_sentiment")

    return cols

from __future__ import annotations

from typing import Any, Dict, Iterable

import pandas as pd

from .features import add_chart_features, make_target
from .market_data import download_ohlc
from .news_sentiment import add_live_news_score, build_news_query


def parse_symbols(symbols: str | Iterable[str]) -> list[str]:
    if isinstance(symbols, str):
        parts = symbols.replace("\n", ",").split(",")
    else:
        parts = list(symbols)
    return [str(part).strip() for part in parts if str(part).strip()]


def build_dataset_for_symbol(cfg: Dict[str, Any], symbol: str):
    raw = download_ohlc(symbol, cfg["period"], cfg["interval"])

    if cfg.get("use_news_filter", True):
        query = build_news_query(symbol) if cfg.get("auto_news_query", True) else cfg.get("news_query", symbol)
        raw = add_live_news_score(
            raw,
            query,
            int(cfg.get("max_news_items", 12)),
        )

    feat = add_chart_features(raw)
    labeled = make_target(
        feat,
        int(cfg["horizon_candles"]),
        float(cfg.get("min_target_move_atr", 0.35)),
    )
    labeled["symbol"] = symbol
    return labeled


def build_dataset(cfg: Dict[str, Any]):
    symbols = parse_symbols(cfg["symbol"])
    if not symbols:
        raise ValueError("config symbol ว่าง")

    frames = [build_dataset_for_symbol(cfg, symbol) for symbol in symbols]
    if len(frames) == 1:
        return frames[0]

    return pd.concat(frames, axis=0).sort_index()

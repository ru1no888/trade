from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .risk import build_trade_plan


def make_signal(latest_row: pd.Series, model_bundle: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    model = model_bundle["model"]
    features = model_bundle["features"]

    X = latest_row[features].to_frame().T
    proba_up = float(model.predict_proba(X)[0, 1])

    close = float(latest_row["close"])
    ema50 = float(latest_row["ema_50"])
    ema200 = float(latest_row["ema_200"])
    rsi14 = float(latest_row["rsi_14"])
    atr14 = float(latest_row["atr_14"])
    news_score = float(latest_row["news_sentiment"]) if "news_sentiment" in latest_row else 0.0

    threshold = float(cfg["min_model_probability"])
    bad_news_threshold = float(cfg.get("bad_news_threshold", -0.25))
    pause_on_bad_news = bool(cfg.get("pause_on_bad_news", True))
    force_trade_mode = bool(cfg.get("force_trade_mode", False))
    force_min_probability = float(cfg.get("force_min_probability", 0.52))
    force_respect_trend = bool(cfg.get("force_respect_trend", True))
    strict_signal_mode = bool(cfg.get("strict_signal_mode", False))
    if strict_signal_mode:
        force_min_probability = max(force_min_probability, min(threshold, 0.70))

    trend_up = close > ema200 and ema50 > ema200
    trend_down = close < ema200 and ema50 < ema200
    market_pause = pause_on_bad_news and news_score <= bad_news_threshold

    news_ok_buy = news_score > -0.15
    news_ok_sell = news_score < 0.15

    signal = "WAIT"
    force_trade = False
    reason = []
    suggested_side = "WAIT"
    suggested_probability = 0.0

    if trend_down or proba_up <= (1 - threshold):
        suggested_side = "SELL"
        suggested_probability = 1 - proba_up
    elif trend_up or proba_up >= threshold:
        suggested_side = "BUY"
        suggested_probability = proba_up

    if market_pause:
        reason.append("ข่าวลบแรง -> หยุดเปิดไม้ใหม่")
    elif proba_up >= threshold and trend_up and rsi14 < 72 and news_ok_buy:
        signal = "BUY"
        reason.append("model bullish + trend up + RSI ok + news ok")
    elif proba_up <= (1 - threshold) and trend_down and rsi14 > 28 and news_ok_sell:
        signal = "SELL"
        reason.append("model bearish + trend down + RSI ok + news ok")
    elif force_trade_mode and suggested_side in {"BUY", "SELL"} and suggested_probability >= force_min_probability:
        force_allowed_by_trend = (
            not force_respect_trend
            or (suggested_side == "BUY" and trend_up)
            or (suggested_side == "SELL" and trend_down)
        )
        if force_allowed_by_trend:
            signal = suggested_side
            force_trade = True
            reason.append("force trade mode -> เปิดตามฝั่งที่ AI เอนเอียง")
        else:
            reason.append("force trade blocked -> ไม่เปิดสวนเทรนด์")
    else:
        reason.append("เงื่อนไขยังไม่ครบ -> WAIT")

    result: Dict[str, Any] = {
        "symbol": cfg["symbol"],
        "signal": signal,
        "suggested_side": suggested_side,
        "suggested_probability": round(suggested_probability, 4),
        "force_trade": force_trade,
        "market_pause": market_pause,
        "probability_up": round(proba_up, 4),
        "probability_down": round(1 - proba_up, 4),
        "close": round(close, 6),
        "ema_50": round(ema50, 6),
        "ema_200": round(ema200, 6),
        "rsi_14": round(rsi14, 2),
        "atr_14": round(atr14, 6),
        "news_sentiment": round(news_score, 4),
        "reason": reason,
    }

    if signal in {"BUY", "SELL"}:
        plan = build_trade_plan(
            symbol=cfg["symbol"],
            side=signal,
            entry=close,
            atr=atr14,
            balance=float(cfg["account_balance"]),
            risk_percent=float(cfg["risk_percent"]),
            reward_risk=float(cfg["reward_risk"]),
            atr_sl_multiplier=float(cfg["atr_sl_multiplier"]),
        )
        result["trade_plan"] = plan.__dict__

    return result

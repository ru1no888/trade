from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from bot.config import load_config, save_config
from bot.dataset import build_dataset, build_dataset_for_symbol, parse_symbols
from bot.features import feature_columns
from bot.model import load_model, train_classifier
from bot.news_sentiment import build_news_query, fetch_live_news_brief
from bot.paper_trader import PaperTrader
from bot.presets import PRESETS
from bot.risk import apply_risk_mode
from bot.signal_engine import make_signal
from bot.trade_picker import pick_trade_candidate


app = FastAPI(title="Auto FX Web Paper Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

_state_lock = threading.Lock()
_auto_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


@app.get("/")
def index():
    return FileResponse("static/index.html")


def _get_trader() -> PaperTrader:
    cfg = load_config()
    return PaperTrader(cfg)


def _primary_symbol(cfg: Dict[str, Any]) -> str:
    symbols = parse_symbols(cfg["symbol"])
    if not symbols:
        raise ValueError("config symbol ว่าง")
    return symbols[0]


def _candles_from_df(df):
    clean = df.dropna(subset=["open", "high", "low", "close", "ema_50", "ema_200"])
    if clean.empty:
        raise RuntimeError("ข้อมูลไม่พอสำหรับสร้างกราฟ")

    candles = clean.tail(220).reset_index()
    candles["datetime"] = candles["datetime"].astype(str)
    return candles[["datetime", "open", "high", "low", "close", "ema_50", "ema_200"]].to_dict("records")


def _data_delay_seconds(index_value) -> Optional[int]:
    try:
        ts = index_value.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - ts.astimezone(UTC)).total_seconds()))
    except Exception:
        return None


def _prepare_signal(cfg: Dict[str, Any], preferred_symbol: Optional[str] = None) -> Dict[str, Any]:
    bundle = load_model(cfg["model_path"])
    features = bundle["features"]
    candidates = []

    symbols = [preferred_symbol] if preferred_symbol else parse_symbols(cfg["symbol"])
    for symbol in symbols:
        if not symbol:
            continue
        scan_cfg = dict(cfg)
        scan_cfg["symbol"] = symbol
        scan_cfg["news_query"] = build_news_query(symbol) if cfg.get("auto_news_query", True) else cfg.get("news_query", symbol)
        df = build_dataset_for_symbol(scan_cfg, symbol)
        clean = df.dropna(subset=features + ["close", "ema_50", "ema_200", "rsi_14", "atr_14"])
        if clean.empty:
            continue
        latest = clean.iloc[-1]
        signal = make_signal(latest, bundle, scan_cfg)
        candidates.append({
            "signal": signal,
            "candles": _candles_from_df(clean),
            "chart_symbol": symbol,
            "latest_candle_time": str(clean.index[-1]),
            "latest_row": latest,
        })

    if not candidates:
        raise RuntimeError("ข้อมูลไม่พอสำหรับสร้างสัญญาณ")

    if cfg.get("auto_trade_best_symbol", True):
        return pick_trade_candidate(candidates)
    return candidates[0]


def run_one_bot_step() -> Dict[str, Any]:
    with _state_lock:
        cfg = load_config()
        trader = PaperTrader(cfg)
        state_before = trader.load_state()
        open_symbol = None
        if state_before.get("open_position"):
            open_symbol = state_before["open_position"].get("symbol")
        prepared = _prepare_signal(cfg, open_symbol)

        result = trader.step(
            signal=prepared["signal"],
            latest_row=prepared["latest_row"],
            candle_time=prepared["latest_candle_time"],
        )

        state = trader.load_state()
        result.update({
            "candles": prepared["candles"],
            "chart_symbol": prepared["chart_symbol"],
            "data_delay_seconds": _data_delay_seconds(prepared["latest_row"].name),
            "signal": prepared["signal"],
            "state": state,
        })
        return result


def _auto_loop():
    while not _stop_event.is_set():
        try:
            cfg = load_config()
            if cfg.get("auto_enabled", False):
                run_one_bot_step()
            wait_s = max(5, int(cfg.get("auto_refresh_seconds", 30)))
        except Exception:
            wait_s = 15

        _stop_event.wait(wait_s)


@app.get("/api/config")
def api_get_config():
    return load_config()


@app.get("/api/presets")
def api_presets():
    return PRESETS


@app.post("/api/config")
def api_save_config(payload: Dict[str, Any]):
    cfg = load_config()
    allowed = {
        "symbol", "period", "interval", "horizon_candles", "account_balance", "risk_mode", "rapid_target_usd",
        "risk_percent", "reward_risk", "atr_sl_multiplier", "min_model_probability",
        "use_news_filter", "auto_news_query", "auto_trade_best_symbol", "rapid_paper_mode", "news_query", "max_news_items", "min_target_move_atr", "auto_refresh_seconds",
        "max_trades_per_day", "cooldown_candles", "max_loss_usd", "max_profit_usd",
        "pause_on_bad_news", "bad_news_threshold", "force_trade_mode",
        "force_min_probability", "force_respect_trend", "strict_signal_mode", "auto_risk_mode",
        "auto_risk_min_percent", "auto_risk_max_percent", "max_consecutive_losses",
    }

    for key, value in payload.items():
        if key in allowed:
            cfg[key] = value
    if cfg.get("rapid_paper_mode", False):
        cfg["risk_mode"] = "rapid_1usd"

    # Keep paper-test values inside sane bounds.
    cfg["risk_percent"] = float(min(max(float(cfg.get("risk_percent", 0.5)), 0.01), 5.0))
    cfg["rapid_target_usd"] = float(min(max(float(cfg.get("rapid_target_usd", 1.0)), 0.01), 100000.0))
    cfg["reward_risk"] = float(min(max(float(cfg.get("reward_risk", 2.0)), 0.5), 10.0))
    cfg["min_model_probability"] = float(min(max(float(cfg.get("min_model_probability", 0.58)), 0.50), 0.95))
    cfg["min_target_move_atr"] = float(min(max(float(cfg.get("min_target_move_atr", 0.35)), 0.0), 3.0))
    cfg["auto_refresh_seconds"] = int(min(max(int(cfg.get("auto_refresh_seconds", 30)), 5), 3600))
    cfg["max_trades_per_day"] = int(min(max(int(cfg.get("max_trades_per_day", 5)), 1), 100))
    cfg["max_consecutive_losses"] = int(min(max(int(cfg.get("max_consecutive_losses", 3)), 0), 100))
    cfg["max_loss_usd"] = float(min(max(float(cfg.get("max_loss_usd", 1.0)), 0.01), 100000.0))
    cfg["max_profit_usd"] = float(min(max(float(cfg.get("max_profit_usd", 1.0)), 0.01), 100000.0))
    cfg["bad_news_threshold"] = float(min(max(float(cfg.get("bad_news_threshold", -0.25)), -1.0), 0.0))
    cfg["force_min_probability"] = float(min(max(float(cfg.get("force_min_probability", 0.52)), 0.50), 0.95))
    cfg["auto_risk_min_percent"] = float(min(max(float(cfg.get("auto_risk_min_percent", 0.1)), 0.01), 5.0))
    cfg["auto_risk_max_percent"] = float(min(max(float(cfg.get("auto_risk_max_percent", 1.0)), cfg["auto_risk_min_percent"]), 5.0))

    cfg = apply_risk_mode(cfg)

    save_config(cfg)
    return {"ok": True, "config": cfg}


@app.post("/api/chart")
def api_chart():
    try:
        cfg = load_config()
        symbol = _primary_symbol(cfg)
        df = build_dataset_for_symbol(cfg, symbol)
        return {
            "ok": True,
            "chart_symbol": symbol,
            "candles": _candles_from_df(df),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/live")
def api_live():
    try:
        cfg = load_config()
        trader = PaperTrader(cfg)
        state = trader.load_state()
        open_position = state.get("open_position")
        symbol = str(open_position.get("symbol")) if open_position else _primary_symbol(cfg)
        df = build_dataset_for_symbol(cfg, symbol)
        candles = _candles_from_df(df)
        clean = df.dropna(subset=["close"])
        if clean.empty:
            raise RuntimeError("ข้อมูลราคา live ไม่พอ")

        latest = clean.iloc[-1]
        candle_time = str(clean.index[-1])
        current_price = float(latest["close"])
        state = trader.mark_to_market(state, current_price, candle_time, symbol=symbol)
        trader.save_state(state)

        return {
            "ok": True,
            "chart_symbol": symbol,
            "candles": candles,
            "state": state,
            "current_price": round(current_price, 6),
            "current_price_time": candle_time,
            "data_delay_seconds": _data_delay_seconds(clean.index[-1]),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/train")
def api_train():
    try:
        cfg = load_config()
        df = build_dataset(cfg)
        features = feature_columns(df)
        metrics = train_classifier(
            df,
            features,
            cfg["model_path"],
            min_probability=float(cfg.get("min_model_probability", 0.58)),
        )
        return {"ok": True, "metrics": metrics}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/scan")
def api_scan():
    try:
        cfg = load_config()
        bundle = load_model(cfg["model_path"])
        features = bundle["features"]
        rows = []

        for symbol in parse_symbols(cfg["symbol"]):
            scan_cfg = dict(cfg)
            scan_cfg["symbol"] = symbol
            scan_cfg["news_query"] = build_news_query(symbol) if cfg.get("auto_news_query", True) else cfg.get("news_query", symbol)
            df = build_dataset_for_symbol(scan_cfg, symbol)
            clean = df.dropna(subset=features + ["close", "ema_50", "ema_200", "rsi_14", "atr_14"])
            if clean.empty:
                continue
            signal = make_signal(clean.iloc[-1], bundle, scan_cfg)
            rows.append({
                "symbol": symbol,
                "signal": signal["signal"],
                "suggested_side": signal["suggested_side"],
                "market_pause": signal["market_pause"],
                "probability_up": signal["probability_up"],
                "probability_down": signal["probability_down"],
                "news_sentiment": signal["news_sentiment"],
                "news_query": scan_cfg["news_query"],
                "close": signal["close"],
                "reason": signal["reason"],
            })

        down = sorted(
            [row for row in rows if row["suggested_side"] == "SELL"],
            key=lambda row: (row["market_pause"], row["probability_down"], -row["news_sentiment"]),
            reverse=True,
        )
        return {
            "ok": True,
            "rows": rows,
            "best_down": down[0] if down else None,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"{e} - กด Train Model ก่อน")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/news")
def api_news():
    try:
        cfg = load_config()
        rows = [
            fetch_live_news_brief(symbol, int(cfg.get("max_news_items", 6)))
            for symbol in parse_symbols(cfg["symbol"])
        ]
        negative = [row for row in rows if row["bias"] == "negative"]
        return {
            "ok": True,
            "auto_news_query": bool(cfg.get("auto_news_query", True)),
            "rows": rows,
            "risk_note": "negative news -> bot may pause new trades" if negative else "no strong negative news found",
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/reload")
def api_reload():
    try:
        return run_one_bot_step()
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=f"{e} - กด Train Model ก่อน")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/state")
def api_state():
    trader = _get_trader()
    return trader.load_state()


@app.post("/api/start")
def api_start():
    global _auto_thread
    cfg = load_config()
    cfg["auto_enabled"] = True
    save_config(cfg)

    if _auto_thread is None or not _auto_thread.is_alive():
        _stop_event.clear()
        _auto_thread = threading.Thread(target=_auto_loop, daemon=True)
        _auto_thread.start()

    return {"ok": True, "auto_enabled": True}


@app.post("/api/stop")
def api_stop():
    cfg = load_config()
    cfg["auto_enabled"] = False
    save_config(cfg)
    return {"ok": True, "auto_enabled": False}


@app.post("/api/reset")
def api_reset():
    with _state_lock:
        cfg = load_config()
        trader = PaperTrader(cfg)
        trader.reset()
        return {"ok": True, "state": trader.load_state()}


@app.post("/api/close")
def api_close():
    with _state_lock:
        cfg = load_config()
        trader = PaperTrader(cfg)
        state_before = trader.load_state()
        open_symbol = None
        if state_before.get("open_position"):
            open_symbol = state_before["open_position"].get("symbol")
        prepared = _prepare_signal(cfg, open_symbol)
        state = trader.close_position_market(prepared["latest_row"], prepared["latest_candle_time"], reason="MANUAL_CLOSE")
        return {"ok": True, "state": state}


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    Path("models").mkdir(exist_ok=True)
    if not Path("config.json").exists():
        Path("config.json").write_text(Path("config.example.json").read_text(encoding="utf-8"), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=8000)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_PATH = "config.json"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        example = Path("config.example.json")
        if example.exists():
            p.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            raise FileNotFoundError("ไม่พบ config.json และ config.example.json")

    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    defaults = {
        "model_path": "models/model.joblib",
        "paper_state_path": "data/paper_state.json",
        "auto_refresh_seconds": 30,
        "auto_enabled": False,
        "risk_mode": "safe_balanced",
        "rapid_target_usd": 1.0,
        "rapid_paper_mode": False,
        "auto_trade_best_symbol": True,
        "max_trades_per_day": 5,
        "cooldown_candles": 1,
        "use_news_filter": True,
        "auto_news_query": True,
        "max_news_items": 12,
        "min_target_move_atr": 0.35,
        "max_loss_usd": 1.0,
        "max_profit_usd": 1.0,
        "pause_on_bad_news": True,
        "bad_news_threshold": -0.25,
        "force_trade_mode": False,
        "force_min_probability": 0.52,
        "force_respect_trend": True,
        "strict_signal_mode": True,
        "auto_risk_mode": True,
        "auto_risk_min_percent": 0.1,
        "auto_risk_max_percent": 1.0,
        "max_consecutive_losses": 3,
    }
    for k, v in defaults.items():
        cfg.setdefault(k, v)

    required = [
        "symbol", "period", "interval", "horizon_candles",
        "account_balance", "risk_percent", "reward_risk",
        "atr_sl_multiplier", "min_model_probability",
        "model_path", "paper_state_path",
    ]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"config.json ขาดค่า: {missing}")

    return cfg


def save_config(cfg: Dict[str, Any], path: str = DEFAULT_CONFIG_PATH) -> None:
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

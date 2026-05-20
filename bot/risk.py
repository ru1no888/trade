from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class TradePlan:
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_amount: float
    sl_distance: float
    rr: float
    approx_lot: float
    note: str


def pip_size_for_symbol(symbol: str) -> float:
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    return 0.0001


def calc_approx_lot(symbol: str, risk_amount: float, entry: float, stop_loss: float) -> float:
    pip_size = pip_size_for_symbol(symbol)
    sl_pips = abs(entry - stop_loss) / pip_size
    if sl_pips <= 0:
        return 0.0

    pip_value_per_standard_lot = 10.0
    lot = risk_amount / (sl_pips * pip_value_per_standard_lot)
    return max(0.0, round(lot, 3))


def compute_auto_risk_percent(trades: list[Dict[str, Any]], cfg: Dict[str, Any]) -> float:
    base = float(cfg.get("risk_percent", 0.5))
    min_risk = float(cfg.get("auto_risk_min_percent", 0.1))
    max_risk = float(cfg.get("auto_risk_max_percent", 1.0))

    recent_three = trades[-3:]
    recent_two = trades[-2:]
    if len(recent_three) == 3 and all(float(t.get("pnl", 0)) < 0 for t in recent_three):
        risk = base * 0.5
    elif len(recent_two) == 2 and all(float(t.get("pnl", 0)) > 0 for t in recent_two):
        risk = base * 1.25
    else:
        risk = base

    return round(min(max(risk, min_risk), max_risk), 3)


def _target_percent(balance: float, target_usd: float) -> float:
    if balance <= 0:
        return 0.1
    return round(min(max((target_usd / balance) * 100.0, 0.01), 5.0), 3)


def apply_risk_mode(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(cfg)
    mode = str(out.get("risk_mode", "safe_balanced") or "safe_balanced")
    balance = float(out.get("account_balance", 1000) or 1000)
    target_usd = float(out.get("rapid_target_usd", 1.0) or 1.0)

    if mode == "rapid_1usd":
        pct = _target_percent(balance, target_usd)
        out.update({
            "risk_percent": pct,
            "reward_risk": 1.0,
            "max_loss_usd": target_usd,
            "max_profit_usd": target_usd,
            "max_trades_per_day": 100,
            "max_consecutive_losses": 0,
            "auto_risk_mode": False,
            "auto_trade_best_symbol": True,
            "force_trade_mode": True,
            "force_min_probability": 0.5,
            "force_respect_trend": True,
            "strict_signal_mode": False,
            "min_model_probability": 0.55,
            "auto_refresh_seconds": 5,
        })
    elif mode == "aggressive":
        out.update({
            "risk_percent": 1.0,
            "reward_risk": 1.2,
            "max_loss_usd": max(1.0, round(balance * 0.01, 2)),
            "max_profit_usd": max(1.0, round(balance * 0.012, 2)),
            "max_trades_per_day": 30,
            "max_consecutive_losses": 3,
            "auto_risk_mode": True,
            "auto_risk_min_percent": 0.25,
            "auto_risk_max_percent": 1.0,
            "auto_trade_best_symbol": True,
            "force_trade_mode": True,
            "force_min_probability": 0.58,
            "force_respect_trend": True,
            "strict_signal_mode": False,
            "min_model_probability": 0.58,
            "auto_refresh_seconds": 10,
        })
    elif mode == "strict95":
        out.update({
            "risk_percent": 0.1,
            "reward_risk": 2.0,
            "max_loss_usd": max(1.0, round(balance * 0.001, 2)),
            "max_profit_usd": max(1.0, round(balance * 0.002, 2)),
            "max_trades_per_day": 2,
            "max_consecutive_losses": 1,
            "auto_risk_mode": True,
            "auto_risk_min_percent": 0.05,
            "auto_risk_max_percent": 0.1,
            "auto_trade_best_symbol": True,
            "force_trade_mode": False,
            "force_respect_trend": True,
            "strict_signal_mode": True,
            "min_model_probability": 0.95,
            "auto_refresh_seconds": 30,
        })
    else:
        out.update({
            "risk_mode": "safe_balanced",
            "risk_percent": 0.25,
            "reward_risk": 1.5,
            "max_loss_usd": max(1.0, round(balance * 0.0025, 2)),
            "max_profit_usd": max(1.0, round(balance * 0.00375, 2)),
            "max_trades_per_day": 5,
            "max_consecutive_losses": 3,
            "auto_risk_mode": True,
            "auto_risk_min_percent": 0.05,
            "auto_risk_max_percent": 0.25,
            "auto_trade_best_symbol": True,
            "force_trade_mode": False,
            "force_respect_trend": True,
            "strict_signal_mode": True,
            "min_model_probability": 0.75,
            "auto_refresh_seconds": 15,
        })

    return out


def build_trade_plan(
    symbol: str,
    side: str,
    entry: float,
    atr: float,
    balance: float,
    risk_percent: float,
    reward_risk: float,
    atr_sl_multiplier: float,
) -> TradePlan:
    risk_amount = balance * (risk_percent / 100.0)
    sl_distance = max(atr * atr_sl_multiplier, entry * 0.0005)

    if side == "BUY":
        sl = entry - sl_distance
        tp = entry + sl_distance * reward_risk
    elif side == "SELL":
        sl = entry + sl_distance
        tp = entry - sl_distance * reward_risk
    else:
        raise ValueError("side must be BUY or SELL")

    lot = calc_approx_lot(symbol, risk_amount, entry, sl)

    return TradePlan(
        side=side,
        entry=round(entry, 6),
        stop_loss=round(sl, 6),
        take_profit=round(tp, 6),
        risk_amount=round(risk_amount, 2),
        sl_distance=round(sl_distance, 6),
        rr=round(reward_risk, 2),
        approx_lot=lot,
        note="Paper lot estimate. Check broker pip value/contract size before real money.",
    )

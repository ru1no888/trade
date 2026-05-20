from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .risk import calc_approx_lot, compute_auto_risk_percent


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class PaperTrader:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.path = Path(cfg.get("paper_state_path", "data/paper_state.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def default_state(self) -> Dict[str, Any]:
        return {
            "balance": float(self.cfg.get("account_balance", 1000)),
            "start_balance": float(self.cfg.get("account_balance", 1000)),
            "open_position": None,
            "trades": [],
            "equity_curve": [],
            "last_signal": None,
            "last_action_candle_time": None,
            "last_step_at": None,
            "status": "ready",
        }

    def load_state(self) -> Dict[str, Any]:
        if not self.path.exists():
            state = self.default_state()
            self.save_state(state)
            return state

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            state = self.default_state()
            self.save_state(state)
            return state

    def save_state(self, state: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def reset(self) -> None:
        self.save_state(self.default_state())

    def calc_pnl(self, pos: Dict[str, Any], exit_price: float) -> float:
        side = pos["side"]
        entry = float(pos["entry"])
        sl = float(pos["stop_loss"])
        risk_amount = float(pos["risk_amount"])

        if side == "BUY":
            risk_distance = max(entry - sl, 1e-12)
            r_multiple = (exit_price - entry) / risk_distance
        else:
            risk_distance = max(sl - entry, 1e-12)
            r_multiple = (entry - exit_price) / risk_distance

        return round(risk_amount * r_multiple, 2)

    def close_position(self, state: Dict[str, Any], exit_price: float, candle_time: str, reason: str) -> Dict[str, Any]:
        pos = state.get("open_position")
        if not pos:
            return state

        pnl = self.calc_pnl(pos, exit_price)
        state["balance"] = round(float(state["balance"]) + pnl, 2)

        trade = {
            **pos,
            "exit": round(float(exit_price), 6),
            "closed_at": candle_time,
            "close_reason": reason,
            "pnl": pnl,
            "balance_after": state["balance"],
        }
        state["trades"].append(trade)
        state["open_position"] = None
        state["equity_curve"].append({
            "time": candle_time,
            "balance": state["balance"],
            "pnl": pnl,
            "reason": reason,
        })
        state["status"] = f"closed {reason}"
        return state

    def close_position_market(self, latest_row: pd.Series, candle_time: str, reason: str = "MANUAL_CLOSE") -> Dict[str, Any]:
        state = self.load_state()
        pos = state.get("open_position")
        if pos:
            pos_symbol = str(pos.get("symbol", "") or "")
            row_symbol = str(latest_row.get("symbol", "") or "") if hasattr(latest_row, "get") else ""
            if pos_symbol and row_symbol and pos_symbol != row_symbol:
                state["status"] = f"holding {pos_symbol}; skipped wrong symbol {row_symbol}"
                self.save_state(state)
                return state
            state = self.close_position(state, float(latest_row["close"]), candle_time, reason)
            self.save_state(state)
        return state

    def mark_to_market(self, state: Dict[str, Any], current_price: float, candle_time: str, symbol: str | None = None) -> Dict[str, Any]:
        if state.get("open_position"):
            pos_symbol = str(state["open_position"].get("symbol", "") or "")
            if pos_symbol and symbol and pos_symbol != symbol:
                state.setdefault("unrealized_pnl", 0.0)
                state["equity"] = round(float(state["balance"]) + float(state.get("unrealized_pnl", 0.0)), 2)
                state["status"] = f"holding {pos_symbol}; skipped wrong symbol {symbol}"
                return state
            unrealized = self.calc_pnl(state["open_position"], float(current_price))
        else:
            unrealized = 0.0

        state["current_price"] = round(float(current_price), 6)
        state["current_price_time"] = candle_time
        state["unrealized_pnl"] = unrealized
        state["equity"] = round(float(state["balance"]) + unrealized, 2)
        return state

    def check_exit(self, state: Dict[str, Any], latest_row: pd.Series, candle_time: str) -> Dict[str, Any]:
        pos = state.get("open_position")
        if not pos:
            return state

        pos_symbol = str(pos.get("symbol", "") or "")
        row_symbol = str(latest_row.get("symbol", "") or "") if hasattr(latest_row, "get") else ""
        if pos_symbol and row_symbol and pos_symbol != row_symbol:
            state["status"] = f"holding {pos_symbol}; skipped wrong symbol {row_symbol}"
            return state

        high = float(latest_row["high"])
        low = float(latest_row["low"])
        close = float(latest_row["close"])

        side = pos["side"]
        sl = float(pos["stop_loss"])
        tp = float(pos["take_profit"])
        max_loss_usd = float(self.cfg.get("max_loss_usd", 0) or 0)
        max_profit_usd = float(self.cfg.get("max_profit_usd", 0) or 0)

        # If one candle hits both SL and TP, use SL first. Conservative paper sim.
        if side == "BUY":
            if low <= sl:
                return self.close_position(state, sl, candle_time, "STOP_LOSS")
            if high >= tp:
                return self.close_position(state, tp, candle_time, "TAKE_PROFIT")
        else:
            if high >= sl:
                return self.close_position(state, sl, candle_time, "STOP_LOSS")
            if low <= tp:
                return self.close_position(state, tp, candle_time, "TAKE_PROFIT")

        pnl_at_close = self.calc_pnl(pos, close)
        if max_loss_usd > 0 and pnl_at_close <= -max_loss_usd:
            return self.close_position(state, close, candle_time, "MAX_LOSS_USD")
        if max_profit_usd > 0 and pnl_at_close >= max_profit_usd:
            return self.close_position(state, close, candle_time, "MAX_PROFIT_USD")

        return state

    def consecutive_losses(self, state: Dict[str, Any]) -> int:
        losses = 0
        for trade in reversed(state.get("trades", [])):
            if float(trade.get("pnl", 0) or 0) < 0:
                losses += 1
            else:
                break
        return losses

    def can_open_new_trade(self, state: Dict[str, Any], candle_time: str) -> bool:
        if state.get("open_position"):
            return False
        if state.get("last_action_candle_time") == candle_time:
            return False

        max_consecutive_losses = int(self.cfg.get("max_consecutive_losses", 0))
        if max_consecutive_losses > 0 and self.consecutive_losses(state) >= max_consecutive_losses:
            state["status"] = "loss streak pause"
            return False

        max_trades = int(self.cfg.get("max_trades_per_day", 5))
        today = candle_time[:10]
        trades_today = [
            t for t in state.get("trades", [])
            if str(t.get("opened_at", "")).startswith(today)
        ]
        if len(trades_today) >= max_trades:
            state["status"] = "max trades per day reached"
            return False

        return True

    def open_position(self, state: Dict[str, Any], signal: Dict[str, Any], candle_time: str) -> Dict[str, Any]:
        if signal.get("market_pause"):
            state["status"] = "paused by bad news"
            return state
        if signal.get("signal") not in {"BUY", "SELL"}:
            return state
        if "trade_plan" not in signal:
            return state
        if not self.can_open_new_trade(state, candle_time):
            return state

        plan = signal["trade_plan"]
        risk_percent = float(self.cfg.get("risk_percent", 0.5))
        risk_amount = float(plan["risk_amount"])
        approx_lot = float(plan["approx_lot"])
        if self.cfg.get("auto_risk_mode", False):
            risk_percent = compute_auto_risk_percent(state.get("trades", []), self.cfg)
            risk_amount = round(float(state["balance"]) * (risk_percent / 100.0), 2)
            approx_lot = calc_approx_lot(
                str(signal.get("symbol") or self.cfg.get("symbol", "")),
                risk_amount,
                float(plan["entry"]),
                float(plan["stop_loss"]),
            )

        pos = {
            "symbol": signal.get("symbol") or self.cfg.get("symbol"),
            "side": plan["side"],
            "entry": float(plan["entry"]),
            "stop_loss": float(plan["stop_loss"]),
            "take_profit": float(plan["take_profit"]),
            "risk_amount": risk_amount,
            "risk_percent": risk_percent,
            "rr": float(plan["rr"]),
            "approx_lot": approx_lot,
            "opened_at": candle_time,
            "probability_up": signal.get("probability_up"),
            "news_sentiment": signal.get("news_sentiment"),
        }

        state["open_position"] = pos
        state["last_action_candle_time"] = candle_time
        state["status"] = f"opened {pos['side']}"
        return state

    def step(self, signal: Dict[str, Any], latest_row: pd.Series, candle_time: str) -> Dict[str, Any]:
        state = self.load_state()

        state["last_step_at"] = now_iso()
        state["last_signal"] = signal

        state = self.check_exit(state, latest_row, candle_time)
        if signal.get("market_pause") and state.get("open_position"):
            state = self.close_position(state, float(latest_row["close"]), candle_time, "BAD_NEWS_PAUSE")
        state = self.open_position(state, signal, candle_time)

        row_symbol = str(latest_row.get("symbol", "") or "") if hasattr(latest_row, "get") else None
        state = self.mark_to_market(state, float(latest_row["close"]), candle_time, symbol=row_symbol)

        self.save_state(state)

        return {
            "ok": True,
            "message": state.get("status", "step done"),
            "candle_time": candle_time,
        }

import unittest

import numpy as np
import pandas as pd

from bot.dataset import parse_symbols
from bot.features import feature_columns, make_target
from bot.model import train_classifier
from bot.news_sentiment import build_news_query
from bot.paper_trader import PaperTrader
from bot.presets import PRESETS
from bot.risk import apply_risk_mode, compute_auto_risk_percent
from bot.signal_engine import make_signal


class TrainingPipelineTests(unittest.TestCase):
    def test_presets_keep_ui_from_requiring_manual_typing(self):
        self.assertGreaterEqual(len(PRESETS["market_packs"]), 3)
        self.assertGreaterEqual(len(PRESETS["timeframes"]), 3)
        self.assertGreaterEqual(len(PRESETS["risk_modes"]), 3)

        for pack in PRESETS["market_packs"]:
            self.assertGreaterEqual(len(parse_symbols(pack["symbols"])), 1)

        live = [row for row in PRESETS["timeframes"] if row["id"] == "minute_live"][0]
        self.assertEqual(live["interval"], "1m")
        self.assertLessEqual(live["auto_refresh_seconds"], 60)

    def test_parse_symbols_accepts_string_or_list(self):
        self.assertEqual(parse_symbols("EURUSD=X, AAPL, MSFT"), ["EURUSD=X", "AAPL", "MSFT"])
        self.assertEqual(parse_symbols(["EURUSD=X", " AAPL ", "", "MSFT"]), ["EURUSD=X", "AAPL", "MSFT"])

    def test_build_news_query_from_symbol_without_manual_typing(self):
        self.assertIn("EUR USD forex", build_news_query("EURUSD=X"))
        self.assertIn("AAPL stock", build_news_query("AAPL"))
        self.assertIn("gold futures", build_news_query("GC=F"))
        self.assertIn("bitcoin", build_news_query("BTC-USD"))

    def test_trade_picker_uses_actionable_signal_instead_of_wait_first_symbol(self):
        from bot.trade_picker import pick_trade_candidate

        rows = [
            {"signal": {"symbol": "EURUSD=X", "signal": "WAIT", "suggested_probability": 0.72}},
            {"signal": {"symbol": "GBPUSD=X", "signal": "BUY", "suggested_probability": 0.53}},
            {"signal": {"symbol": "JPY=X", "signal": "SELL", "suggested_probability": 0.61}},
        ]

        picked = pick_trade_candidate(rows)

        self.assertEqual(picked["signal"]["symbol"], "JPY=X")
        self.assertEqual(picked["signal"]["signal"], "SELL")

    def test_train_classifier_reports_threshold_signal_quality(self):
        rows = 420
        x = np.linspace(-1, 1, rows)
        target = (x > 0).astype(int)
        df = pd.DataFrame(
            {
                "ret_1": x,
                "ret_3": x,
                "ret_6": x,
                "ema_20_slope": x,
                "ema_50_slope": x,
                "ema_spread_50_200": x,
                "rsi_14": np.where(target == 1, 60, 40),
                "atr_pct": 0.01,
                "range_pct": 0.01,
                "body_pct": 0.005,
                "bullish_engulfing": target,
                "bearish_engulfing": 1 - target,
                "above_ema_200": target,
                "ema_50_above_200": target,
                "target_up": target,
            }
        )

        features = feature_columns(df)
        metrics = train_classifier(df, features, "models/test_model.joblib", min_probability=0.7)

        self.assertIn("signal_accuracy", metrics)
        self.assertIn("signal_coverage", metrics)
        self.assertGreater(metrics["signal_trades"], 0)
        self.assertGreaterEqual(metrics["signal_accuracy"], 0.9)

    def test_make_target_drops_noise_moves_with_atr_deadzone(self):
        df = pd.DataFrame({
            "close": [100.0, 100.02, 100.01, 100.8, 100.1, 99.2],
            "atr_14": [1.0] * 6,
        })

        out = make_target(df, horizon=1, min_move_atr=0.5)

        self.assertTrue(pd.isna(out.loc[0, "target_up"]))
        self.assertEqual(out.loc[2, "target_up"], 1)
        self.assertEqual(out.loc[3, "target_up"], 0)

    def test_paper_trader_closes_when_max_loss_usd_is_hit(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_loss_usd": 1.0,
            "max_trades_per_day": 10,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "side": "BUY",
            "entry": 100.0,
            "stop_loss": 90.0,
            "take_profit": 120.0,
            "risk_amount": 10.0,
            "rr": 2.0,
            "approx_lot": 1.0,
            "opened_at": "2026-05-20T00:00:00Z",
        }
        row = pd.Series({"open": 100.0, "high": 100.0, "low": 98.0, "close": 98.5})

        closed = trader.check_exit(state, row, "2026-05-20T00:15:00Z")

        self.assertIsNone(closed["open_position"])
        self.assertEqual(closed["trades"][-1]["close_reason"], "MAX_LOSS_USD")
        self.assertLessEqual(closed["trades"][-1]["pnl"], -1.0)

    def test_paper_trader_closes_when_max_profit_usd_is_hit(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_profit_usd": 1.0,
            "max_trades_per_day": 10,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "symbol": "AAPL",
            "side": "BUY",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 102.0,
            "risk_amount": 1.0,
            "rr": 2.0,
            "approx_lot": 1.0,
            "opened_at": "2026-05-20T00:00:00Z",
        }
        row = pd.Series({"symbol": "AAPL", "open": 100.0, "high": 100.8, "low": 100.0, "close": 101.1})

        closed = trader.check_exit(state, row, "2026-05-20T00:15:00Z")

        self.assertIsNone(closed["open_position"])
        self.assertEqual(closed["trades"][-1]["close_reason"], "MAX_PROFIT_USD")
        self.assertGreaterEqual(closed["trades"][-1]["pnl"], 1.0)

    def test_paper_trader_mark_to_market_updates_unrealized_pnl(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "side": "BUY",
            "entry": 100.0,
            "stop_loss": 99.0,
            "take_profit": 102.0,
            "risk_amount": 5.0,
            "rr": 2.0,
            "approx_lot": 1.0,
            "opened_at": "2026-05-20T00:00:00Z",
        }

        marked = trader.mark_to_market(state, 100.5, "2026-05-20T00:01:00Z")

        self.assertEqual(marked["unrealized_pnl"], 2.5)
        self.assertEqual(marked["equity"], 1002.5)
        self.assertEqual(marked["current_price"], 100.5)

    def test_paper_trader_closes_open_trade_when_bad_news_pause_hits(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_loss_usd": 1.0,
            "max_trades_per_day": 10,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "side": "BUY",
            "entry": 100.0,
            "stop_loss": 90.0,
            "take_profit": 120.0,
            "risk_amount": 10.0,
            "rr": 2.0,
            "approx_lot": 1.0,
            "opened_at": "2026-05-20T00:00:00Z",
        }
        trader.save_state(state)
        row = pd.Series({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5})
        signal = {"signal": "WAIT", "market_pause": True}

        trader.step(signal, row, "2026-05-20T00:15:00Z")
        after = trader.load_state()

        self.assertIsNone(after["open_position"])
        self.assertEqual(after["trades"][-1]["close_reason"], "BAD_NEWS_PAUSE")

    def test_auto_risk_reduces_after_losses_and_increases_after_wins(self):
        cfg = {
            "risk_percent": 0.5,
            "auto_risk_min_percent": 0.1,
            "auto_risk_max_percent": 1.0,
        }
        losses = [{"pnl": -1}, {"pnl": -2}, {"pnl": -1}]
        wins = [{"pnl": 1}, {"pnl": 2}]

        self.assertEqual(compute_auto_risk_percent(losses, cfg), 0.25)
        self.assertEqual(compute_auto_risk_percent(wins, cfg), 0.625)

    def test_rapid_risk_mode_sizes_one_dollar_target_from_balance(self):
        cfg = {
            "risk_mode": "rapid_1usd",
            "account_balance": 500,
            "rapid_target_usd": 1.0,
        }

        out = apply_risk_mode(cfg)

        self.assertEqual(out["risk_percent"], 0.2)
        self.assertEqual(out["max_loss_usd"], 1.0)
        self.assertEqual(out["max_profit_usd"], 1.0)
        self.assertEqual(out["auto_risk_mode"], False)
        self.assertEqual(out["auto_refresh_seconds"], 5)

    def test_safe_and_aggressive_risk_modes_are_separate_profiles(self):
        safe = apply_risk_mode({"risk_mode": "safe_balanced", "account_balance": 1000})
        aggr = apply_risk_mode({"risk_mode": "aggressive", "account_balance": 1000})

        self.assertLess(safe["risk_percent"], aggr["risk_percent"])
        self.assertEqual(safe["strict_signal_mode"], True)
        self.assertEqual(aggr["force_trade_mode"], True)

    def test_paper_trader_auto_risk_adjusts_trade_plan_before_open(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_trades_per_day": 10,
            "auto_risk_mode": True,
            "risk_percent": 0.5,
            "auto_risk_min_percent": 0.1,
            "auto_risk_max_percent": 1.0,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["trades"] = [{"pnl": -1}, {"pnl": -2}, {"pnl": -3}]
        signal = {
            "signal": "BUY",
            "trade_plan": {
                "side": "BUY",
                "entry": 100.0,
                "stop_loss": 99.0,
                "take_profit": 102.0,
                "risk_amount": 5.0,
                "rr": 2.0,
                "approx_lot": 1.0,
            }
        }

        opened = trader.open_position(state, signal, "2026-05-20T00:15:00Z")

        self.assertEqual(opened["open_position"]["risk_amount"], 2.5)
        self.assertEqual(opened["open_position"]["risk_percent"], 0.25)

    def test_paper_trader_stops_opening_after_loss_streak(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_trades_per_day": 10,
            "max_consecutive_losses": 3,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["trades"] = [{"pnl": -1}, {"pnl": -2}, {"pnl": -3}]
        signal = {
            "signal": "SELL",
            "trade_plan": {
                "side": "SELL",
                "entry": 100.0,
                "stop_loss": 101.0,
                "take_profit": 98.0,
                "risk_amount": 5.0,
                "rr": 2.0,
                "approx_lot": 1.0,
            }
        }

        opened = trader.open_position(state, signal, "2026-05-20T00:15:00Z")

        self.assertIsNone(opened["open_position"])
        self.assertEqual(opened["status"], "loss streak pause")

    def test_paper_trader_stores_symbol_and_ignores_wrong_symbol_exit(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_trades_per_day": 10,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        signal = {
            "symbol": "GBPUSD=X",
            "signal": "BUY",
            "trade_plan": {
                "side": "BUY",
                "entry": 1.3445,
                "stop_loss": 1.3435,
                "take_profit": 1.3465,
                "risk_amount": 2.5,
                "rr": 2.0,
                "approx_lot": 0.025,
            }
        }

        opened = trader.open_position(state, signal, "2026-05-20T00:15:00Z")
        wrong_row = pd.Series({
            "symbol": "AUDUSD=X",
            "open": 0.716,
            "high": 0.717,
            "low": 0.715,
            "close": 0.716,
        })
        checked = trader.check_exit(opened, wrong_row, "2026-05-20T00:16:00Z")

        self.assertEqual(checked["open_position"]["symbol"], "GBPUSD=X")
        self.assertEqual(checked["trades"], [])

    def test_paper_trader_manual_close_ignores_wrong_symbol(self):
        cfg = {
            "account_balance": 1000,
            "paper_state_path": "data/test_paper_state.json",
            "max_trades_per_day": 10,
        }
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "symbol": "AUDUSD=X",
            "side": "BUY",
            "entry": 0.715,
            "stop_loss": 0.714,
            "take_profit": 0.716,
            "risk_amount": 1.0,
            "rr": 1.0,
            "approx_lot": 0.01,
            "opened_at": "2026-05-20T00:15:00Z",
        }
        trader.save_state(state)
        wrong_row = pd.Series({"symbol": "EURUSD=X", "close": 1.162})

        closed = trader.close_position_market(wrong_row, "2026-05-20T00:16:00Z")

        self.assertEqual(closed["open_position"]["symbol"], "AUDUSD=X")
        self.assertEqual(closed["trades"], [])
        self.assertIn("skipped wrong symbol", closed["status"])

    def test_mark_to_market_ignores_wrong_symbol_price(self):
        cfg = {"account_balance": 1000, "paper_state_path": "data/test_paper_state.json"}
        trader = PaperTrader(cfg)
        state = trader.default_state()
        state["open_position"] = {
            "symbol": "AUDUSD=X",
            "side": "BUY",
            "entry": 0.715,
            "stop_loss": 0.714,
            "take_profit": 0.716,
            "risk_amount": 1.0,
            "rr": 1.0,
            "approx_lot": 0.01,
            "opened_at": "2026-05-20T00:15:00Z",
        }

        marked = trader.mark_to_market(state, 1.162, "2026-05-20T00:16:00Z", symbol="EURUSD=X")

        self.assertEqual(marked["unrealized_pnl"], 0.0)
        self.assertEqual(marked["equity"], 1000.0)
        self.assertIn("skipped wrong symbol", marked["status"])

    def test_signal_pauses_trading_on_bad_news(self):
        class Model:
            def predict_proba(self, _x):
                return np.array([[0.1, 0.9]])

        latest = pd.Series({
            "ret_1": 0.01,
            "ret_3": 0.01,
            "ret_6": 0.01,
            "ema_20_slope": 0.01,
            "ema_50_slope": 0.01,
            "ema_spread_50_200": 0.01,
            "rsi_14": 55,
            "atr_pct": 0.01,
            "range_pct": 0.01,
            "body_pct": 0.01,
            "bullish_engulfing": 1,
            "bearish_engulfing": 0,
            "above_ema_200": 1,
            "ema_50_above_200": 1,
            "close": 110.0,
            "ema_50": 105.0,
            "ema_200": 100.0,
            "atr_14": 1.0,
            "news_sentiment": -0.4,
        })
        bundle = {"model": Model(), "features": feature_columns(pd.DataFrame([latest]))}
        cfg = {
            "symbol": "AAPL",
            "min_model_probability": 0.58,
            "pause_on_bad_news": True,
            "bad_news_threshold": -0.25,
            "account_balance": 1000,
            "risk_percent": 0.5,
            "reward_risk": 2.0,
            "atr_sl_multiplier": 1.5,
        }

        signal = make_signal(latest, bundle, cfg)

        self.assertEqual(signal["signal"], "WAIT")
        self.assertTrue(signal["market_pause"])

    def test_force_trade_mode_converts_wait_to_suggested_side(self):
        class Model:
            def predict_proba(self, _x):
                return np.array([[0.45, 0.55]])

        latest = pd.Series({
            "ret_1": 0.01,
            "ret_3": 0.01,
            "ret_6": 0.01,
            "ema_20_slope": 0.01,
            "ema_50_slope": 0.01,
            "ema_spread_50_200": 0.01,
            "rsi_14": 55,
            "atr_pct": 0.01,
            "range_pct": 0.01,
            "body_pct": 0.01,
            "bullish_engulfing": 0,
            "bearish_engulfing": 0,
            "above_ema_200": 1,
            "ema_50_above_200": 1,
            "close": 110.0,
            "ema_50": 105.0,
            "ema_200": 100.0,
            "atr_14": 1.0,
            "news_sentiment": 0.0,
        })
        bundle = {"model": Model(), "features": feature_columns(pd.DataFrame([latest]))}
        cfg = {
            "symbol": "AAPL",
            "min_model_probability": 0.70,
            "force_trade_mode": True,
            "force_min_probability": 0.52,
            "pause_on_bad_news": True,
            "bad_news_threshold": -0.25,
            "account_balance": 1000,
            "risk_percent": 0.5,
            "reward_risk": 2.0,
            "atr_sl_multiplier": 1.5,
        }

        signal = make_signal(latest, bundle, cfg)

        self.assertEqual(signal["signal"], "BUY")
        self.assertEqual(signal["force_trade"], True)
        self.assertIn("trade_plan", signal)

    def test_force_trade_mode_does_not_sell_against_uptrend(self):
        class Model:
            def predict_proba(self, _x):
                return np.array([[0.58, 0.42]])

        latest = pd.Series({
            "ret_1": 0.01,
            "ret_3": 0.01,
            "ret_6": 0.01,
            "ema_20_slope": 0.01,
            "ema_50_slope": 0.01,
            "ema_spread_50_200": 0.01,
            "rsi_14": 73,
            "atr_pct": 0.01,
            "range_pct": 0.01,
            "body_pct": 0.01,
            "bullish_engulfing": 0,
            "bearish_engulfing": 0,
            "above_ema_200": 1,
            "ema_50_above_200": 1,
            "close": 110.0,
            "ema_50": 105.0,
            "ema_200": 100.0,
            "atr_14": 1.0,
            "news_sentiment": 0.0,
        })
        bundle = {"model": Model(), "features": feature_columns(pd.DataFrame([latest]))}
        cfg = {
            "symbol": "AAPL",
            "min_model_probability": 0.58,
            "force_trade_mode": True,
            "force_min_probability": 0.52,
            "force_respect_trend": True,
            "pause_on_bad_news": True,
            "bad_news_threshold": -0.25,
            "account_balance": 1000,
            "risk_percent": 0.5,
            "reward_risk": 2.0,
            "atr_sl_multiplier": 1.5,
        }

        signal = make_signal(latest, bundle, cfg)

        self.assertEqual(signal["suggested_side"], "SELL")
        self.assertEqual(signal["signal"], "WAIT")
        self.assertFalse(signal["force_trade"])

    def test_strict_signal_mode_blocks_weak_force_trade(self):
        class Model:
            def predict_proba(self, _x):
                return np.array([[0.45, 0.55]])

        latest = pd.Series({
            "ret_1": 0.01,
            "ret_3": 0.01,
            "ret_6": 0.01,
            "ema_20_slope": 0.01,
            "ema_50_slope": 0.01,
            "ema_spread_50_200": 0.01,
            "rsi_14": 55,
            "atr_pct": 0.01,
            "range_pct": 0.01,
            "body_pct": 0.01,
            "bullish_engulfing": 0,
            "bearish_engulfing": 0,
            "above_ema_200": 1,
            "ema_50_above_200": 1,
            "close": 110.0,
            "ema_50": 105.0,
            "ema_200": 100.0,
            "atr_14": 1.0,
            "news_sentiment": 0.0,
        })
        bundle = {"model": Model(), "features": feature_columns(pd.DataFrame([latest]))}
        cfg = {
            "symbol": "AAPL",
            "min_model_probability": 0.70,
            "force_trade_mode": True,
            "force_min_probability": 0.52,
            "strict_signal_mode": True,
            "pause_on_bad_news": True,
            "bad_news_threshold": -0.25,
            "account_balance": 1000,
            "risk_percent": 0.5,
            "reward_risk": 2.0,
            "atr_sl_multiplier": 1.5,
        }

        signal = make_signal(latest, bundle, cfg)

        self.assertEqual(signal["signal"], "WAIT")
        self.assertFalse(signal["force_trade"])


if __name__ == "__main__":
    unittest.main()

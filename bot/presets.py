from __future__ import annotations


PRESETS = {
    "market_packs": [
        {"id": "forex_major", "name": "Forex Major", "symbols": "EURUSD=X,GBPUSD=X,JPY=X,AUDUSD=X"},
        {"id": "us_stocks", "name": "US Stocks", "symbols": "AAPL,MSFT,NVDA,TSLA,SPY,QQQ"},
        {"id": "gold_crypto", "name": "Gold + Crypto", "symbols": "GC=F,BTC-USD,ETH-USD"},
        {"id": "mixed_safe", "name": "Mixed Starter", "symbols": "EURUSD=X,AAPL,MSFT,GC=F"},
    ],
    "timeframes": [
        {"id": "minute_live", "name": "1m Live", "period": "7d", "interval": "1m", "horizon_candles": 2, "auto_refresh_seconds": 15},
        {"id": "scalp", "name": "Scalp เร็ว", "period": "60d", "interval": "15m", "horizon_candles": 2, "auto_refresh_seconds": 30},
        {"id": "intraday", "name": "Intraday สมดุล", "period": "1y", "interval": "1h", "horizon_candles": 3, "auto_refresh_seconds": 60},
        {"id": "swing", "name": "Swing ช้า", "period": "2y", "interval": "1d", "horizon_candles": 2, "auto_refresh_seconds": 300},
    ],
    "risk_modes": [
        {"id": "safe_balanced", "name": "น้อย / ถือพอดี", "risk_mode": "safe_balanced"},
        {"id": "rapid_1usd", "name": "ไว $1 / ปิดเร็ว", "risk_mode": "rapid_1usd", "rapid_target_usd": 1.0},
        {"id": "aggressive", "name": "แรง / เสี่ยงมาก", "risk_mode": "aggressive"},
        {"id": "strict95", "name": "เข้ายากมาก", "risk_mode": "strict95"},
    ],
}

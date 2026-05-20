from __future__ import annotations

from urllib.parse import quote_plus

import feedparser
import pandas as pd
from textblob import TextBlob


FOREX_NAMES = {
    "EUR": "Euro",
    "USD": "US dollar",
    "GBP": "British pound",
    "JPY": "Japanese yen",
    "AUD": "Australian dollar",
    "NZD": "New Zealand dollar",
    "CAD": "Canadian dollar",
    "CHF": "Swiss franc",
}

FUTURE_QUERIES = {
    "GC=F": "gold futures XAU USD inflation Federal Reserve dollar",
    "SI=F": "silver futures metals dollar inflation",
    "CL=F": "crude oil futures OPEC demand inventory",
}

CRYPTO_QUERIES = {
    "BTC-USD": "bitcoin BTC crypto ETF regulation market",
    "ETH-USD": "ethereum ETH crypto ETF regulation market",
}


def score_text(text: str) -> float:
    if not text:
        return 0.0
    try:
        return float(TextBlob(str(text)).sentiment.polarity)
    except Exception:
        return 0.0


def build_news_query(symbol: str) -> str:
    clean = str(symbol).strip().upper()
    if clean in FUTURE_QUERIES:
        return FUTURE_QUERIES[clean]
    if clean in CRYPTO_QUERIES:
        return CRYPTO_QUERIES[clean]
    if clean.endswith("=X"):
        pair = clean[:-2]
        if len(pair) >= 6:
            base = pair[:3]
            quote = pair[3:6]
            base_name = FOREX_NAMES.get(base, base)
            quote_name = FOREX_NAMES.get(quote, quote)
            return f"{base} {quote} forex {base_name} {quote_name} central bank interest rate inflation"
        if pair == "JPY":
            return "USD JPY forex Japanese yen Bank of Japan Federal Reserve interest rate"
        return f"{pair} forex central bank interest rate inflation"
    ticker = clean.split(".")[0]
    return f"{ticker} stock earnings analyst price target market news"


def fetch_live_news(query: str, max_items: int = 12) -> list[str]:
    q = quote_plus(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)
    return [entry.get("title", "") for entry in feed.entries[:max_items] if entry.get("title", "")]


def fetch_live_news_sentiment(query: str, max_items: int = 12) -> float:
    try:
        titles = fetch_live_news(query, max_items)
        if not titles:
            return 0.0
        scores = [score_text(t) for t in titles]
        return float(sum(scores) / len(scores))
    except Exception:
        return 0.0


def fetch_live_news_brief(symbol: str, max_items: int = 6) -> dict:
    query = build_news_query(symbol)
    try:
        headlines = fetch_live_news(query, max_items)
    except Exception:
        headlines = []
    scores = [score_text(title) for title in headlines]
    sentiment = float(sum(scores) / len(scores)) if scores else 0.0
    if sentiment <= -0.15:
        bias = "negative"
    elif sentiment >= 0.15:
        bias = "positive"
    else:
        bias = "neutral"
    return {
        "symbol": symbol,
        "query": query,
        "sentiment": round(sentiment, 4),
        "bias": bias,
        "headlines": headlines,
    }


def add_live_news_score(df: pd.DataFrame, query: str, max_items: int) -> pd.DataFrame:
    out = df.copy()
    out["news_sentiment"] = fetch_live_news_sentiment(query, max_items)
    return out

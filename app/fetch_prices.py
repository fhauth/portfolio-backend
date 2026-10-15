"""
Kursabruf über yfinance.

Wichtig: yfinance macht ganz normale HTTPS-Anfragen an Yahoo-Finance-Endpunkte,
so wie ein Server das darf (im Gegensatz zum Browser, der an CORS scheitert -
siehe unsere Diskussion dazu). Das läuft hier server-seitig, deshalb funktioniert
es, wo es im Tool selbst (Browser) nicht ging.

Diese Funktion wird von zwei Stellen aufgerufen:
1. scripts/daily_fetch.py - der tägliche Cron-Job (schreibt in die DB)
2. app/main.py - ein manueller "Jetzt aktualisieren"-Endpunkt (optional, live)
"""

import time
import yfinance as yf
from datetime import date, datetime
import logging

logger = logging.getLogger("fetch_prices")


def fetch_current_price(ticker: str):
    """
    Holt den letzten verfügbaren Schlusskurs für einen Ticker.
    Gibt (price, currency) zurück, oder (None, None) bei Fehler.
    """
    try:
        t = yf.Ticker(ticker)
        # fast_info ist schneller als .info und reicht für unseren Zweck
        price = t.fast_info.get("lastPrice")
        currency = t.fast_info.get("currency")
        if price is None:
            # Fallback: letzten Tag aus der Historie nehmen
            hist = t.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return price, currency
    except Exception as e:
        logger.warning(f"Fehler beim Abruf von {ticker}: {e}")
        return None, None


def fetch_all(positions):
    """
    positions: Liste von Position-Objekten (aus der DB) mit .ticker und .name
    Gibt eine Liste von dicts zurück: [{position_id, name, ticker, price, currency, error}, ...]
    """
    results = []
    for pos in positions:
        price, currency = fetch_current_price(pos.ticker)
        time.sleep(1.0)  # Pause, damit Yahoo nicht mit 429 (Too Many Requests) blockt
        results.append({
            "position_id": pos.id,
            "name": pos.name,
            "ticker": pos.ticker,
            "price": price,
            "currency": currency,
            "error": price is None,
        })
    return results

"""
Fundamentaldaten- und Analysten-Abruf über yfinance.

Analog zu Bloomberg ANR (Analyst Recommendations) und FA (Financial
Analysis) - hier mit frei verfügbaren Daten statt Bloomberg-Feed.

yfinance liefert diese Felder über Ticker.info (bzw. Ticker.get_info()):
  - beta                        -> direkt übernommen
  - dividendYield                -> teils schon in %, teils als Dezimalzahl
                                     je nach yfinance-Version - wir normalisieren
  - trailingEps                  -> EPS der letzten 12 Monate
  - targetMeanPrice / targetHighPrice / targetLowPrice
  - recommendationMean           -> 1.0 (Strong Buy) bis 5.0 (Sell)
  - recommendationKey            -> "strong_buy" | "buy" | "hold" | "sell" | "strong_sell"
  - numberOfAnalystOpinions

Nicht jedes Feld ist für jeden Titel verfügbar (v.a. bei ETFs, ADRs/GDRs
und kleineren/ausländischen Werten oft lückenhaft) - fehlende Felder
bleiben None und werden im Frontend als "n/v" angezeigt statt eines
erfundenen Werts.
"""

import yfinance as yf
import logging
import math

logger = logging.getLogger("fetch_fundamentals")


def _normalize_dividend_yield(raw):
    """yfinance gibt dividendYield je nach Version mal als 0.023 (=2.3%),
    mal schon als 2.3 zurück. Heuristik: Werte >1 sind vermutlich schon
    in Prozent, Werte <1 sind vermutlich als Dezimalanteil gemeint."""
    if raw is None:
        return None
    return raw if raw > 1 else raw * 100


def _dividend_yield_percent(info):
    """Dividendenrendite in Prozent. trailingAnnualDividendYield ist bei Yahoo
    immer ein Dezimalanteil (0.023 = 2,3 %). Das Feld dividendYield ist in
    neueren yfinance-Versionen bereits in Prozent - nur als Fallback genutzt."""
    dec = info.get("trailingAnnualDividendYield")
    if dec is not None:
        return dec * 100
    raw = info.get("dividendYield")
    return raw  # neuere yfinance-Versionen liefern hier schon Prozent


def fetch_fundamentals_for_ticker(ticker: str):
    """Gibt ein dict mit allen Kennzahlen zurück, fehlende Felder als None."""
    try:
        t = yf.Ticker(ticker)
        info = t.get_info()
    except Exception as e:
        logger.warning(f"Fundamentaldaten für {ticker} nicht abrufbar: {e}")
        return None

    return {
        "beta": info.get("beta"),
        "dividend_yield": _dividend_yield_percent(info),
        "eps_ttm": info.get("trailingEps"),
        "analyst_rating_mean": info.get("recommendationMean"),
        "analyst_rating_key": info.get("recommendationKey"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "price_target_mean": info.get("targetMeanPrice"),
        "price_target_high": info.get("targetHighPrice"),
        "price_target_low": info.get("targetLowPrice"),
        "currency": info.get("currency"),
    }


def compute_annualized_volatility(closes):
    """
    Annualisierte Volatilität aus einer Liste täglicher Schlusskurse
    (chronologisch sortiert), berechnet als Standardabweichung der
    täglichen log-Renditen * sqrt(252). Braucht mindestens ~20
    Datenpunkte für ein einigermaßen aussagekräftiges Ergebnis.

    Wird selbst berechnet statt aus yfinance übernommen, weil yfinance
    kein direktes "Volatilität"-Feld liefert - das ist bei Bloomberg
    (HVT-Funktion) im Prinzip derselbe Ansatz.
    """
    if len(closes) < 10:
        return None
    returns = []
    for i in range(1, len(closes)):
        if closes[i-1] and closes[i] and closes[i-1] > 0:
            returns.append(math.log(closes[i] / closes[i-1]))
    if len(returns) < 10:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    daily_std = math.sqrt(variance)
    annualized = daily_std * math.sqrt(252) * 100  # in %
    return round(annualized, 2)


def backfill_history(ticker: str, period: str = "1y"):
    """
    Holt ein Jahr historischer Tagesschlusskurse für einen Ticker.
    Wird einmalig beim Anlegen einer neuen Position aufgerufen, damit
    Volatilität und "vor 5 Tagen/vor 1 Monat" sofort funktionieren,
    statt erst nach Wochen täglicher Cron-Läufe Daten zu haben.

    Gibt eine Liste von (date, close_price) zurück, chronologisch sortiert.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        if hist.empty:
            return []
        return [(idx.date(), float(row["Close"])) for idx, row in hist.iterrows()]
    except Exception as e:
        logger.warning(f"Backfill für {ticker} fehlgeschlagen: {e}")
        return []

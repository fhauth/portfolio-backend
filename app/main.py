"""
FastAPI-Backend für das Portfolio-Benchmark-Tool.

Endpunkte:
  GET  /api/health              - Lebenszeichen, für Render's Health-Check
  GET  /api/state               - kompletten Tool-Zustand laden (ersetzt window.storage.get)
  POST /api/state               - kompletten Tool-Zustand speichern (ersetzt window.storage.set)
  GET  /api/watchlist           - Positionen inkl. aktuellem Kurs, Kurs vor 5 Handelstagen, vor 1 Monat
  POST /api/watchlist/refresh   - manueller Sofort-Abruf (zusätzlich zum täglichen Cron-Job)
  GET  /api/fundamentals        - Beta, Volatilität, Dividendenrendite, EPS, Analystenkonsens (nur Aktien), Kursziel je Position
  POST /api/fundamentals/refresh - manueller Sofort-Abruf der Fundamentaldaten
  GET  /api/benchmark-performance - Kalenderjahres-Renditen je Benchmark-Baustein, aus eigener Kurshistorie berechnet

CORS: Wir setzen bewusst erlaubte Ursprünge (CORS_ORIGINS), damit NUR unser
eigenes Frontend diese API ansprechen darf - nicht "jede Webseite", wie es
bei Yahoo Finance selbst der Fall wäre.
"""

import os
import json
from datetime import date, timedelta
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .database import init_db, get_db, Position, PriceHistory, AppState, Fundamentals
from .seed_positions import seed
from .fetch_prices import fetch_all
from .fetch_fundamentals import fetch_fundamentals_for_ticker, compute_annualized_volatility

app = FastAPI(title="Portfolio Benchmark API")

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    from .database import SessionLocal
    db = SessionLocal()
    new_positions = seed(db)
    if new_positions:
        print(f"Seed: {len(new_positions)} Positionen angelegt: {[p.name for p in new_positions]}")
        print("Hinweis: Kurshistorie/Fundamentaldaten für neue Positionen werden erst beim nächsten Cron-Lauf befüllt.")
    db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------- Tool-Zustand (Gewichtungen, Index-Mix, Perioden, ...) ----------

@app.get("/api/state")
def get_state(db: Session = Depends(get_db)):
    row = db.query(AppState).filter(AppState.key == "tool_state").first()
    if not row:
        return {"exists": False, "value": None}
    return {"exists": True, "value": json.loads(row.value_json), "updated_at": row.updated_at.isoformat()}


@app.post("/api/state")
def save_state(payload: dict, db: Session = Depends(get_db)):
    value_json = json.dumps(payload)
    row = db.query(AppState).filter(AppState.key == "tool_state").first()
    if row:
        row.value_json = value_json
    else:
        row = AppState(key="tool_state", value_json=value_json)
        db.add(row)
    db.commit()
    return {"saved": True}


# ---------- Watchlist mit echten Kursen ----------

def _closest_price_before(db: Session, position_id: int, target_date: date):
    """Findet den Kurs-Datenpunkt am oder vor einem bestimmten Datum (falls der Markt
    an genau diesem Tag geschlossen war, z.B. Wochenende/Feiertag)."""
    row = (
        db.query(PriceHistory)
        .filter(PriceHistory.position_id == position_id, PriceHistory.date <= target_date)
        .order_by(desc(PriceHistory.date))
        .first()
    )
    return row.close_price if row else None


@app.get("/api/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.active == 1, Position.asset_class != "BENCHMARK").all()
    today = date.today()
    five_trading_days_ago = today - timedelta(days=7)   # grobe Näherung, s.u.
    one_month_ago = today - timedelta(days=30)

    out = []
    for p in positions:
        latest = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == p.id)
            .order_by(desc(PriceHistory.date))
            .first()
        )
        price_now = latest.close_price if latest else None
        price_5d = _closest_price_before(db, p.id, five_trading_days_ago)
        price_1m = _closest_price_before(db, p.id, one_month_ago)

        out.append({
            "id": p.id,
            "name": p.name,
            "ticker": p.ticker,
            "priceNow": price_now,
            "price5d": price_5d,
            "price1m": price_1m,
            "currency": latest.currency if latest else None,
            "lastUpdated": latest.date.isoformat() if latest else None,
        })
    return out


@app.post("/api/watchlist/refresh")
def refresh_watchlist(db: Session = Depends(get_db)):
    """Manueller Sofort-Abruf, zusätzlich zum täglichen Cron-Job.
    Nützlich zum Testen oder wenn du zwischendurch einen aktuellen Stand willst."""
    positions = db.query(Position).filter(Position.active == 1, Position.asset_class != "BENCHMARK").all()
    results = fetch_all(positions)
    today = date.today()
    saved = 0
    for r in results:
        if r["error"]:
            continue
        existing = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == r["position_id"], PriceHistory.date == today)
            .first()
        )
        if existing:
            existing.close_price = r["price"]
            existing.currency = r["currency"]
        else:
            db.add(PriceHistory(
                position_id=r["position_id"],
                date=today,
                close_price=r["price"],
                currency=r["currency"],
            ))
        saved += 1
    db.commit()
    errors = [r["name"] for r in results if r["error"]]
    return {"updated": saved, "failed": errors}


# ---------- Kennzahlen-Übersicht (Beta, Vola, Div.-Rendite, EPS, Analystenkonsens) ----------

RATING_LABELS_DE = {
    "strong_buy": "Kaufen (stark)",
    "buy": "Kaufen",
    "hold": "Halten",
    "sell": "Verkaufen",
    "strong_sell": "Verkaufen (stark)",
    "none": None,
}


@app.get("/api/fundamentals")
def get_fundamentals(db: Session = Depends(get_db)):
    """
    Liefert je Position die Kennzahlen für das Dashboard (Abschnitt
    'Kennzahlen-Übersicht' im Frontend). Die portfolio-gewichtete
    Aggregation (Beta/Vola/Div.-Rendite gewichtet nach Portfolioanteil)
    berechnet das Frontend selbst, da die Gewichte dort im Tool-Zustand
    liegen, nicht in dieser Datenbank.
    """
    positions = db.query(Position).filter(Position.active == 1, Position.asset_class.in_(["STOCK", "FUND"])).all()
    out = []
    for p in positions:
        f = db.query(Fundamentals).filter(Fundamentals.position_id == p.id).first()
        latest_price = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == p.id)
            .order_by(desc(PriceHistory.date))
            .first()
        )
        price_now = latest_price.close_price if latest_price else None

        upside = None
        if f and f.price_target_mean and price_now:
            upside = round((f.price_target_mean / price_now - 1) * 100, 2)

        out.append({
            "id": p.id,
            "name": p.name,
            "ticker": p.ticker,
            "assetClass": p.asset_class,
            "beta": f.beta if f else None,
            "volatility1y": f.volatility_1y if f else None,
            "dividendYield": f.dividend_yield if f else None,
            "epsTtm": f.eps_ttm if f else None,
            "analystRatingMean": f.analyst_rating_mean if f else None,
            "analystRatingKey": f.analyst_rating_key if f else None,
            "analystRatingLabel": RATING_LABELS_DE.get(f.analyst_rating_key) if f else None,
            "numAnalysts": f.num_analysts if f else None,
            "priceTargetMean": f.price_target_mean if f else None,
            "priceTargetHigh": f.price_target_high if f else None,
            "priceTargetLow": f.price_target_low if f else None,
            "priceNow": price_now,
            "upsidePct": upside,
            "currency": f.currency if f else None,
            "updatedAt": f.updated_at.isoformat() if f and f.updated_at else None,
        })
    return out


@app.post("/api/fundamentals/refresh")
def refresh_fundamentals(db: Session = Depends(get_db)):
    """Manueller Sofort-Abruf der Fundamentaldaten (dauert länger als
    /watchlist/refresh, da yfinance.get_info() pro Titel mehr Daten zieht)."""
    positions = db.query(Position).filter(Position.active == 1, Position.asset_class.in_(["STOCK", "FUND"])).all()
    ok, failed = 0, []
    for pos in positions:
        data = fetch_fundamentals_for_ticker(pos.ticker)
        history_rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == pos.id)
            .order_by(PriceHistory.date)
            .all()
        )
        closes = [r.close_price for r in history_rows]
        volatility = compute_annualized_volatility(closes)

        if data is None:
            failed.append(pos.name)
            data = {}

        row = db.query(Fundamentals).filter(Fundamentals.position_id == pos.id).first()
        if not row:
            row = Fundamentals(position_id=pos.id)
            db.add(row)

        row.beta = data.get("beta")
        row.volatility_1y = volatility
        row.dividend_yield = data.get("dividend_yield")
        row.eps_ttm = data.get("eps_ttm")
        row.currency = data.get("currency")

        # Analysten-Konsens/Kursziel NUR für Einzelaktien - bei Fonds/ETFs
        # nicht aussagekräftig (siehe Chat-Notiz vom 09.09.2026).
        if pos.asset_class == "STOCK":
            row.analyst_rating_mean = data.get("analyst_rating_mean")
            row.analyst_rating_key = data.get("analyst_rating_key")
            row.num_analysts = data.get("num_analysts")
            row.price_target_mean = data.get("price_target_mean")
            row.price_target_high = data.get("price_target_high")
            row.price_target_low = data.get("price_target_low")
        else:
            row.analyst_rating_mean = None
            row.analyst_rating_key = None
            row.num_analysts = None
            row.price_target_mean = None
            row.price_target_high = None
            row.price_target_low = None
        ok += 1
    db.commit()
    return {"updated": ok, "failed": failed}


# ---------- Automatisierte Benchmark-Perioden-Renditen ----------

@app.get("/api/benchmark-performance")
def get_benchmark_performance(db: Session = Depends(get_db)):
    """
    Berechnet Kalenderjahres-Renditen (und laufendes Jahr = YTD) für jeden
    als Benchmark-Baustein markierten Proxy-ETF, direkt aus der eigenen
    Kurshistorie. Ersetzt die bisher manuell recherchierte ETF_PERFORMANCE-
    Tabelle im Frontend - dort wird dieser Endpunkt periodisch abgefragt,
    sodass die Perioden-Renditen sich künftig von selbst aktualisieren.

    Rückgabeformat passend zum Frontend:
      { "MSCI World": {"2023": 19.67, "2024": 26.62, ...}, "S&P 500": {...}, ... }

    Hinweis: Kalenderjahre, für die keine Kurshistorie vorliegt (z.B. weil
    ein Benchmark-Baustein erst kürzlich hinzugefügt wurde und der 5-Jahres-
    Backfill noch nicht gelaufen ist), fehlen im Ergebnis für diesen Baustein -
    das Frontend zeigt dann für die betroffene Zelle weiterhin "—" an.
    """
    positions = db.query(Position).filter(Position.benchmark_label.isnot(None)).all()
    today = date.today()
    current_year = today.year

    out = {}
    for pos in positions:
        rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == pos.id)
            .order_by(PriceHistory.date)
            .all()
        )
        if not rows:
            continue

        by_year = {}
        for r in rows:
            by_year.setdefault(r.date.year, []).append(r)

        years_present = sorted(by_year.keys())
        result_for_position = {}

        for year in years_present:
            year_rows = by_year[year]
            end_price = year_rows[-1].close_price  # letzter Handelstag des Jahres (oder heute, laufendes Jahr)

            # Startkurs: letzter Handelstag des Vorjahres, falls vorhanden -
            # sonst erster verfügbarer Kurs DIESES Jahres (Näherung für das
            # allererste Jahr, für das wir überhaupt Daten haben).
            prev_year_rows = by_year.get(year - 1)
            if prev_year_rows:
                start_price = prev_year_rows[-1].close_price
            else:
                start_price = year_rows[0].close_price
                if len(year_rows) < 2:
                    continue  # nur ein Datenpunkt, keine Rendite berechenbar

            if start_price and start_price > 0:
                ret = round((end_price / start_price - 1) * 100, 2)
                label = str(year) if year != current_year else f"{year} (YTD, Stand {today.strftime('%d.%m.')})"
                result_for_position[label] = ret

        out[pos.benchmark_label] = result_for_position

    return out

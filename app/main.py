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
  POST /api/watchlist/add       - neuen Titel (Yahoo-Ticker) zur Watchlist hinzufügen (für die Handelssimulation)
  POST /api/watchlist/remove    - Titel wieder aus der Watchlist nehmen (deaktivieren)
  GET  /api/fx                  - Wechselkurse (Fremdwährung je 1 EUR) zur Umrechnung in Euro
  GET  /api/watchlist           - (erweitert um Sektor und Sektor-Rendite je Titel)
  GET  /api/news/titles         - aktuelle Meldungen zu den Einzelaktien (Yahoo Finance + Google News)
  GET  /api/news/macro          - Wirtschafts-Schlagzeilen (Tagesschau, Handelsblatt, FAZ, EZB, Google News)
  GET  /api/history             - Kursverläufe aller aktiven Positionen für den Performance-Vergleich

CORS: Wir setzen bewusst erlaubte Ursprünge (CORS_ORIGINS), damit NUR unser
eigenes Frontend diese API ansprechen darf - nicht "jede Webseite", wie es
bei Yahoo Finance selbst der Fall wäre.
"""

import os
import re
import json
from typing import Optional
from datetime import date, timedelta
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import desc

from .database import init_db, get_db, Position, PriceHistory, AppState, Fundamentals
from . import news as newsmod
from .seed_positions import seed, STOCK_SECTORS, SECTOR_ETFS, YAHOO_SECTOR_MAP
from .fetch_prices import fetch_all, fetch_current_price
from .fetch_fundamentals import fetch_fundamentals_for_ticker, compute_annualized_volatility, backfill_history

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


def _load_sector_map(db):
    """Sektoren für selbst hinzugefügte Titel: {Positionsname: Sektor}."""
    row = db.query(AppState).filter(AppState.key == "sector_map").first()
    try:
        return json.loads(row.value_json) if row else {}
    except Exception:
        return {}


def _save_sector(db, name, sector):
    smap = _load_sector_map(db)
    smap[name] = sector
    row = db.query(AppState).filter(AppState.key == "sector_map").first()
    if row:
        row.value_json = json.dumps(smap, ensure_ascii=False)
    else:
        db.add(AppState(key="sector_map", value_json=json.dumps(smap, ensure_ascii=False)))
    db.commit()


def _pct(now, then):
    if now is None or then is None or then == 0:
        return None
    return round((now / then - 1) * 100, 2)


@app.get("/api/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    positions = db.query(Position).filter(Position.active == 1, Position.asset_class != "BENCHMARK").all()
    today = date.today()
    five_trading_days_ago = today - timedelta(days=7)   # grobe Näherung, s.u.
    one_month_ago = today - timedelta(days=30)

    out = []
    smap = _load_sector_map(db)
    etf_perf_cache = {}

    def sector_perf(sector):
        """Rendite des Sektor-ETFs über dieselben Zeitfenster wie die Einzeltitel.
        Bevorzugt MSCI World (EUR); liefert dieser keine Kurse, Rückfall auf den US-SPDR-ETF."""
        if sector in etf_perf_cache:
            return etf_perf_cache[sector]
        res = (None, None, None)
        for i, etf_name in enumerate(SECTOR_ETFS.get(sector, [])):
            etf = db.query(Position).filter(Position.name == etf_name).first()
            if not etf:
                continue
            last = (db.query(PriceHistory).filter(PriceHistory.position_id == etf.id)
                    .order_by(desc(PriceHistory.date)).first())
            now_px = last.close_price if last else None
            r5 = _pct(now_px, _closest_price_before(db, etf.id, five_trading_days_ago))
            r1 = _pct(now_px, _closest_price_before(db, etf.id, one_month_ago))
            if r5 is not None or r1 is not None:
                res = (r5, r1, "MSCI World" if i == 0 else "US (S&P 500)")
                break
        etf_perf_cache[sector] = res
        return res

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
        sector = STOCK_SECTORS.get(p.name) or smap.get(p.name) if p.asset_class == "STOCK" else None
        sec5, sec1m, sec_src = sector_perf(sector) if sector else (None, None, None)

        out.append({
            "id": p.id,
            "name": p.name,
            "ticker": p.ticker,
            "priceNow": price_now,
            "price5d": price_5d,
            "price1m": price_1m,
            "currency": latest.currency if latest else None,
            "lastUpdated": latest.date.isoformat() if latest else None,
            "sector": sector,
            "sectorRet5d": sec5,
            "sectorRet1m": sec1m,
            "sectorSource": sec_src,
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


# ---------- Handelssimulation: Watchlist erweitern, Wechselkurse ----------

class AddPositionBody(BaseModel):
    ticker: str
    name: Optional[str] = None


class RemovePositionBody(BaseModel):
    id: int


def _fx_code(currency):
    """Yahoo meldet London-Kurse in Pence ('GBp'); Wechselkurs läuft trotzdem über GBP."""
    return (currency or "").upper()


def _ensure_fx_position(db, currency):
    """Legt (falls nötig) eine Wechselkurs-Position EUR/<Währung> an, damit der nächste
    Abruf den Kurs mitliefert. Gibt True zurück, wenn neu angelegt."""
    code = _fx_code(currency)
    if not code or code == "EUR" or len(code) != 3:
        return False
    ticker = f"EUR{code}=X"
    if db.query(Position).filter(Position.ticker == ticker).first():
        return False
    db.add(Position(name=f"FX EUR/{code}", ticker=ticker, asset_class="BENCHMARK", active=1))
    db.commit()
    return True


@app.post("/api/watchlist/add")
def add_to_watchlist(body: AddPositionBody, db: Session = Depends(get_db)):
    """Neuen Titel zur Watchlist hinzufügen. Der Titel wird beim täglichen Abruf automatisch
    mit Kurs, Historie und Kennzahlen versorgt. Zusätzlich versuchen wir hier sofort Kurs und
    Kennzahlen zu laden - klappt das (z.B. weil Yahoo gerade blockt) nicht, kommt alles beim
    nächsten Lauf."""
    ticker = body.ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.\-=^]{1,20}", ticker):
        raise HTTPException(status_code=422, detail="Ungültiger Ticker (erlaubt: Buchstaben, Ziffern, . - = ^).")

    existing = db.query(Position).filter(Position.ticker == ticker).first()
    if existing:
        was_inactive = not existing.active
        existing.active = 1
        db.commit()
        return {"id": existing.id, "name": existing.name, "ticker": existing.ticker,
                "assetClass": existing.asset_class, "verified": True, "alreadyExisted": True,
                "reactivated": was_inactive,
                "message": "Titel ist bereits in der Watchlist."}

    price, currency = fetch_current_price(ticker)
    name = (body.name or "").strip()
    asset_class = "STOCK"
    yahoo_sector = None
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).get_info()
        if not name:
            name = info.get("shortName") or info.get("longName") or ""
        if info.get("quoteType") in ("ETF", "MUTUALFUND"):
            asset_class = "FUND"
        yahoo_sector = YAHOO_SECTOR_MAP.get(info.get("sector") or "")
        if not currency:
            currency = info.get("currency")
    except Exception:
        pass
    name = name or ticker
    if db.query(Position).filter(Position.name == name).first():
        name = f"{name} ({ticker})"

    pos = Position(name=name, ticker=ticker, asset_class=asset_class, active=1)
    db.add(pos)
    db.commit()
    db.refresh(pos)
    if asset_class == "STOCK" and yahoo_sector:
        _save_sector(db, pos.name, yahoo_sector)

    verified = price is not None
    if verified:
        db.add(PriceHistory(position_id=pos.id, date=date.today(), close_price=price, currency=currency))
        db.commit()
        try:
            from .database import PriceHistory as PH
            for d, close in backfill_history(ticker, period="1y"):
                if not db.query(PH).filter(PH.position_id == pos.id, PH.date == d).first():
                    db.add(PH(position_id=pos.id, date=d, close_price=close, currency=None))
            db.commit()
        except Exception:
            db.rollback()
        try:
            data = fetch_fundamentals_for_ticker(ticker) or {}
            closes = [r.close_price for r in db.query(PriceHistory).filter(PriceHistory.position_id == pos.id).order_by(PriceHistory.date).all()]
            row = Fundamentals(position_id=pos.id)
            row.beta = data.get("beta")
            row.volatility_1y = compute_annualized_volatility(closes)
            row.dividend_yield = data.get("dividend_yield")
            row.eps_ttm = data.get("eps_ttm")
            row.currency = data.get("currency") or currency
            if asset_class == "STOCK":
                for k in ("analyst_rating_mean", "analyst_rating_key", "num_analysts",
                          "price_target_mean", "price_target_high", "price_target_low"):
                    setattr(row, k, data.get(k))
            db.add(row)
            db.commit()
        except Exception:
            db.rollback()
    _ensure_fx_position(db, currency)

    return {"id": pos.id, "name": pos.name, "ticker": pos.ticker, "assetClass": pos.asset_class,
            "verified": verified, "alreadyExisted": False,
            "message": ("Titel hinzugefügt, Kurs und Kennzahlen sind geladen." if verified else
                        "Titel hinzugefügt, aber Yahoo hat keinen Kurs geliefert (Ticker prüfen). "
                        "Kurs und Kennzahlen kommen beim nächsten täglichen Abruf, falls der Ticker stimmt.")}


@app.post("/api/watchlist/remove")
def remove_from_watchlist(body: RemovePositionBody, db: Session = Depends(get_db)):
    pos = db.query(Position).filter(Position.id == body.id).first()
    if not pos or pos.asset_class == "BENCHMARK":
        raise HTTPException(status_code=404, detail="Titel nicht gefunden.")
    pos.active = 0
    db.commit()
    return {"id": pos.id, "name": pos.name, "removed": True}


@app.get("/api/fx")
def get_fx(db: Session = Depends(get_db)):
    """Wechselkurse als {"USD": 1.17, "KRW": 1612.0, ...} = Fremdwährung je 1 EUR (letzter Abruf)."""
    out = {}
    fx_positions = db.query(Position).filter(Position.active == 1, Position.ticker.like("EUR%=X")).all()
    for p in fx_positions:
        latest = (db.query(PriceHistory).filter(PriceHistory.position_id == p.id)
                  .order_by(desc(PriceHistory.date)).first())
        if latest and len(p.ticker) == 8:
            out[p.ticker[3:6]] = latest.close_price
    out["EUR"] = 1.0
    return out


# ---------- Kursverläufe für den Performance-Vergleich im Tool ----------

@app.get("/api/history")
def get_history(days: int = 800, db: Session = Depends(get_db)):
    """Tägliche Schlusskurse aller aktiven Positionen (inkl. Benchmark-Proxys und
    Wechselkurse) der letzten `days` Tage. Das Frontend berechnet daraus die
    Wertentwicklung von Portfolio und Benchmark für frei wählbare Zeiträume."""
    days = max(30, min(days, 2000))
    since = date.today() - timedelta(days=days)
    out = []
    for p in db.query(Position).filter(Position.active == 1).all():
        rows = (db.query(PriceHistory)
                .filter(PriceHistory.position_id == p.id, PriceHistory.date >= since)
                .order_by(PriceHistory.date).all())
        if not rows:
            continue
        cur_row = (db.query(PriceHistory)
                   .filter(PriceHistory.position_id == p.id, PriceHistory.currency.isnot(None))
                   .order_by(desc(PriceHistory.date)).first())
        out.append({
            "id": p.id,
            "name": p.name,
            "ticker": p.ticker,
            "assetClass": p.asset_class,
            "benchmarkLabel": p.benchmark_label,
            "currency": cur_row.currency if cur_row else None,
            "series": [[r.date.isoformat(), r.close_price] for r in rows],
        })
    return out


# ---------- Nachrichten ----------

@app.get("/api/news/titles")
def get_news_titles(refresh: int = 0, db: Session = Depends(get_db)):
    """Meldungen zu allen aktiven Einzelaktien. Ergebnis wird ca. 20 Minuten zwischengespeichert;
    refresh=1 erzwingt einen neuen Abruf."""
    positions = [(p.id, p.name, p.ticker) for p in
                 db.query(Position).filter(Position.active == 1, Position.asset_class == "STOCK").all()]
    return newsmod.fetch_titles(positions, force=bool(refresh))


@app.get("/api/news/macro")
def get_news_macro(refresh: int = 0):
    return newsmod.fetch_macro(force=bool(refresh))

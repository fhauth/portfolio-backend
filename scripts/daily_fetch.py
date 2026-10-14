"""
Täglicher Kursabruf - das ist das Skript, das Render als 'Cron Job' ausführt
(siehe render.yaml, dort steht der Zeitplan).

Macht vier Dinge, in dieser Reihenfolge:
  1. Neue Positionen anlegen (falls seed_positions.py erweitert wurde) und
     für sie Kurshistorie nachladen (Backfill) - 5 Jahre für Benchmark-
     Bausteine (damit Kalenderjahres-Renditen ab 2023 berechenbar sind),
     1 Jahr für normale Depot-Positionen (reicht für Volatilität + 5-Tage-/
     1-Monats-Vergleich).
  2. Aktuellen Kurs für alle aktiven Positionen abrufen (inkl. Benchmark-Proxys).
  3. Fundamentaldaten (Beta, Dividendenrendite, EPS) für STOCK und FUND
     abrufen - Analysten-Konsens/Kursziel NUR für STOCK (bei Fonds/ETFs
     nicht aussagekräftig, siehe Chat-Notiz vom 09.09.2026).
  4. Falls ein Benchmark-Baustein noch keine ausreichend tiefe Historie hat
     (z.B. weil er nachträglich als Benchmark markiert wurde), zusätzlichen
     5-Jahres-Backfill nachholen.

Empfohlener Zeitplan (in render.yaml): 22:15 Uhr MEZ / 22:15 CET.
"""

import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import init_db, SessionLocal, Position, PriceHistory, Fundamentals
from app.seed_positions import seed
from app.fetch_prices import fetch_all
from app.fetch_fundamentals import fetch_fundamentals_for_ticker, compute_annualized_volatility, backfill_history


def save_history(db, position_id, history):
    added = 0
    for d, close in history:
        existing = db.query(PriceHistory).filter(
            PriceHistory.position_id == position_id, PriceHistory.date == d
        ).first()
        if not existing:
            db.add(PriceHistory(position_id=position_id, date=d, close_price=close, currency=None))
            added += 1
    db.commit()
    return added


def backfill_new_positions(db, new_positions):
    for pos in new_positions:
        period = "5y" if pos.benchmark_label else "1y"
        print(f"Backfill ({period}) für neue Position: {pos.name} ({pos.ticker}) ...")
        history = backfill_history(pos.ticker, period=period)
        added = save_history(db, pos.id, history)
        print(f"  -> {added} historische Kurse geladen.")


def ensure_deep_history_for_benchmarks(db):
    """Falls ein Benchmark-Baustein (z.B. nachträglich markiert) noch keine
    ~4+ Jahre Historie hat, zusätzlichen 5-Jahres-Backfill nachholen."""
    benchmark_positions = db.query(Position).filter(Position.benchmark_label.isnot(None)).all()
    cutoff = date.today() - timedelta(days=4 * 365)
    for pos in benchmark_positions:
        earliest = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == pos.id)
            .order_by(PriceHistory.date)
            .first()
        )
        if earliest is None or earliest.date > cutoff:
            print(f"Vertiefe Historie für Benchmark-Baustein {pos.name} ({pos.ticker}) auf 5 Jahre ...")
            history = backfill_history(pos.ticker, period="5y")
            added = save_history(db, pos.id, history)
            print(f"  -> {added} zusätzliche historische Kurse geladen.")


def fetch_and_save_prices(db, positions):
    print(f"Rufe aktuelle Kurse für {len(positions)} Positionen ab ...")
    results = fetch_all(positions)
    today = date.today()
    saved, failed = 0, []

    for r in results:
        if r["error"]:
            failed.append(r["name"])
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
        print(f"  ✓ {r['name']} ({r['ticker']}): {r['price']} {r['currency']}")

    db.commit()
    print(f"Kurse: {saved} aktualisiert, {len(failed)} fehlgeschlagen.")
    if failed:
        print("Fehlgeschlagen:", ", ".join(failed))


def fetch_and_save_fundamentals(db, positions):
    """Nur für STOCK und FUND - reine Benchmark-Proxys (asset_class=BENCHMARK)
    sind kein Depot-Bestandteil und tauchen nicht in der Kennzahlen-Übersicht auf."""
    targets = [p for p in positions if p.asset_class in ("STOCK", "FUND")]
    print(f"\nRufe Fundamentaldaten für {len(targets)} Positionen ab ...")
    ok, failed = 0, []
    for pos in targets:
        data = fetch_fundamentals_for_ticker(pos.ticker) or {}

        history_rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.position_id == pos.id)
            .order_by(PriceHistory.date)
            .all()
        )
        closes = [r.close_price for r in history_rows]
        volatility = compute_annualized_volatility(closes)

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
        print(f"  ✓ {pos.name}: Beta={row.beta}, Vola={row.volatility_1y}%, "
              f"Div.-Rendite={row.dividend_yield}%, EPS={row.eps_ttm}"
              + (f", Rating={row.analyst_rating_key} ({row.num_analysts} Analysten), Kursziel Ø={row.price_target_mean}"
                 if pos.asset_class == "STOCK" else " (Analysten-Daten: n/a bei Fonds)"))

    db.commit()
    print(f"Fundamentaldaten: {ok} aktualisiert.")


def main():
    init_db()
    db = SessionLocal()

    new_positions = seed(db)
    if new_positions:
        backfill_new_positions(db, new_positions)

    ensure_deep_history_for_benchmarks(db)

    positions = db.query(Position).filter(Position.active == 1).all()
    fetch_and_save_prices(db, positions)
    fetch_and_save_fundamentals(db, positions)

    db.close()
    print("\nFertig.")


if __name__ == "__main__":
    main()

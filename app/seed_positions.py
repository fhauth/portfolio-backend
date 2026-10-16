"""
Startbelegung der 'positions'-Tabelle.

Yahoo-Finance-Ticker brauchen ein Börsen-Suffix, sonst wird die falsche
(meist eine US-)Notierung getroffen. Beispiel: "SIE" ohne Suffix ist NICHT
Siemens. Deshalb hier explizit die Xetra/Paris/Mailand/Amsterdam-Kürzel.

asset_class:
  "STOCK"     - Einzelaktie im Depot
  "FUND"      - Fonds/ETF im Depot
  "BENCHMARK" - reiner Vergleichsindex-Proxy, KEIN Depot-Bestandteil
                (erscheint deshalb nicht in Watchlist/Kennzahlen-Übersicht,
                nur in der automatisierten Perioden-Renditen-Berechnung)

benchmark_label: gesetzt, wenn diese Position (zusätzlich oder ausschließlich)
als Baustein für die automatische Perioden-Renditen-Berechnung dient. Der
Name muss exakt den Index-Namen entsprechen, die im Frontend-Tool als
"index"-Werte der Benchmark-Bausteine verwendet werden (siehe
CLASS_INDEX_SUGGESTIONS in der HTML-Datei).
"""

POSITIONS = [
    {"name": "ASML",                    "ticker": "ASML.AS", "asset_class": "STOCK"},
    {"name": "Baker Hughes",            "ticker": "BKR",     "asset_class": "STOCK"},
    {"name": "Boeing",                  "ticker": "BA",      "asset_class": "STOCK"},
    {"name": "Daimler Truck Holding",   "ticker": "DTG.DE",  "asset_class": "STOCK"},
    {"name": "Ferrari",                 "ticker": "RACE.MI", "asset_class": "STOCK"},
    {"name": "General Dynamics",        "ticker": "GD",      "asset_class": "STOCK"},
    {"name": "Goldman Sachs",           "ticker": "GS",      "asset_class": "STOCK"},
    {"name": "Hermes",                  "ticker": "RMS.PA",  "asset_class": "STOCK"},
    {"name": "JPMorgan Chase",          "ticker": "JPM",     "asset_class": "STOCK"},
    {"name": "Philip Morris",           "ticker": "PM",      "asset_class": "STOCK"},
    {"name": "Rheinmetall",             "ticker": "RHM.DE",  "asset_class": "STOCK"},
    {"name": "Rollins",                 "ticker": "ROL",     "asset_class": "STOCK"},
    {"name": "SK Hynix (GDR)",          "ticker": "000660.KS","asset_class": "STOCK"},  # Korea-Listing als bester frei verfügbarer Proxy für die GDR
    {"name": "Siemens",                 "ticker": "SIE.DE",  "asset_class": "STOCK"},
    {"name": "Siemens Energy",          "ticker": "ENR.DE",  "asset_class": "STOCK"},
    {"name": "SpaceX",                  "ticker": "SPCX",    "asset_class": "STOCK"},   # seit 12.06.2026 an der Nasdaq
    {"name": "T-Mobile US",             "ticker": "TMUS",    "asset_class": "STOCK"},
    {"name": "Waste Management",        "ticker": "WM",      "asset_class": "STOCK"},

    # Fonds/ETFs im Depot (ergänzt am 09.09.2026). MSCI World und Core S&P 500
    # dienen DOPPELT als Depot-Position UND als Benchmark-Baustein (identischer
    # Fonds), deshalb benchmark_label gesetzt.
    {"name": "MSCI World USD (Acc)",                              "ticker": "EUNL.DE", "asset_class": "FUND", "benchmark_label": "MSCI World"},
    {"name": "Core S&P 500 USD (Acc)",                            "ticker": "SXR8.DE", "asset_class": "FUND", "benchmark_label": "S&P 500"},
    {"name": "MSCI Emerging Markets Ex China USD (Acc)",          "ticker": "EXCH.AS", "asset_class": "FUND"},
    {"name": "MSCI World Information Technology USD (Acc)",       "ticker": "XDWT.DE", "asset_class": "FUND"},
    {"name": "Core Stoxx Europe 600 EUR (Acc)",                   "ticker": "EXIE.DE", "asset_class": "FUND"},
    {"name": "Energy Transition Metals And Rare Earths Miners USD (Acc)", "ticker": "RARE.DE", "asset_class": "FUND"},

    # Reine Benchmark-Proxy-ETFs (ergänzt am 09.09.2026) - kein Depot-Bestandteil,
    # dienen ausschließlich der automatisierten Perioden-Renditen-Berechnung für
    # den Blended-Benchmark-Vergleich (ersetzen die bisher manuell recherchierten
    # ETF_PERFORMANCE-Werte im Frontend).
    {"name": "iShares Core MSCI EM IMI (Benchmark-Proxy)",              "ticker": "IS3N.DE", "asset_class": "BENCHMARK", "benchmark_label": "MSCI Emerging Markets"},
    {"name": "iShares Core Global Aggregate Bond EUR Hedged (Benchmark-Proxy)", "ticker": "EUNA.DE", "asset_class": "BENCHMARK", "benchmark_label": "Bloomberg Global Aggregate"},
    {"name": "Xtrackers EUR Overnight Rate Swap (Benchmark-Proxy)",     "ticker": "XEON.DE", "asset_class": "BENCHMARK", "benchmark_label": "€STR"},
]


# Aus der Überwachung genommene Positionen (werden in der DB deaktiviert und
# nicht mehr als Benchmark-Baustein genutzt). Rohstoffe sind aktuell nicht relevant.
RETIRED = [
    "Invesco Bloomberg Commodity (Benchmark-Proxy)",
    "iShares Diversified Commodity Swap (Benchmark-Proxy)",
]


def seed(db):
    from .database import Position
    for name in RETIRED:
        old = db.query(Position).filter(Position.name == name).first()
        if old is not None and (old.active or old.benchmark_label):
            old.active = 0
            old.benchmark_label = None
    db.commit()
    existing_by_name = {p.name: p for p in db.query(Position).all()}
    new_positions = []
    for p in POSITIONS:
        if p["name"] in existing_by_name:
            # Bereits vorhanden - ggf. benchmark_label nachtragen (z.B. wenn
            # ein bestehender Depot-Fonds nachträglich auch als Benchmark-
            # Baustein markiert wird, wie MSCI World / Core S&P 500 hier).
            existing = existing_by_name[p["name"]]
            new_label = p.get("benchmark_label")
            if new_label and existing.benchmark_label != new_label:
                existing.benchmark_label = new_label
            continue
        pos = Position(
            name=p["name"],
            ticker=p["ticker"],
            asset_class=p["asset_class"],
            active=1,
            benchmark_label=p.get("benchmark_label"),
        )
        db.add(pos)
        new_positions.append(pos)
    db.commit()
    for pos in new_positions:
        db.refresh(pos)  # IDs nach dem Commit verfügbar machen
    return new_positions

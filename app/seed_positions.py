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

    # Wechselkurse (Fremdwährung je 1 EUR) für die Handelssimulation, damit Kurse
    # von US-/Korea-Titeln in Euro umgerechnet werden können. Kein Depot-Bestandteil.
    # Weitere Währungen legt das Backend automatisch an, wenn ein Titel in einer
    # anderen Währung zur Watchlist hinzugefügt wird.
    {"name": "FX EUR/USD", "ticker": "EURUSD=X", "asset_class": "BENCHMARK"},
    {"name": "FX EUR/KRW", "ticker": "EURKRW=X", "asset_class": "BENCHMARK"},

    # Sektor-Subindizes (Xtrackers MSCI World je GICS-Sektor, Xetra) für den Vergleich
    # "Einzeltitel vs. eigener Sektor" in der Portfolio-Überwachung. Kein Depot-Bestandteil.
    # Immobilien werden bewusst nicht verglichen (keine Immobilienaktien im Depot).
    {"name": "Sektor Industrie (MSCI World)",              "ticker": "XDWI.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Informationstechnologie (MSCI World)", "ticker": "XDWT.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Finanzwesen (MSCI World)",            "ticker": "XDWF.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Gesundheitswesen (MSCI World)",       "ticker": "XDWH.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Zykl. Konsumgüter (MSCI World)",      "ticker": "XDWC.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Basiskonsumgüter (MSCI World)",       "ticker": "XDWS.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Energie (MSCI World)",                "ticker": "XDW0.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Werkstoffe (MSCI World)",             "ticker": "XDWM.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Versorger (MSCI World)",              "ticker": "XDWU.DE", "asset_class": "BENCHMARK"},
    {"name": "Sektor Kommunikationsdienste (MSCI World)",  "ticker": "XWTS.DE", "asset_class": "BENCHMARK"},

    # Rückfall-Sektorvergleich: US Select Sector SPDR ETFs (USD, S&P 500). Wird nur genutzt,
    # wenn der MSCI-World-Sektor-ETF oben keine Kurse liefert.
    {"name": "Sektor Industrie (US, SPDR XLI)",              "ticker": "XLI",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Informationstechnologie (US, SPDR XLK)", "ticker": "XLK",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Finanzwesen (US, SPDR XLF)",            "ticker": "XLF",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Gesundheitswesen (US, SPDR XLV)",       "ticker": "XLV",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Zykl. Konsumgüter (US, SPDR XLY)",      "ticker": "XLY",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Basiskonsumgüter (US, SPDR XLP)",       "ticker": "XLP",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Energie (US, SPDR XLE)",                "ticker": "XLE",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Werkstoffe (US, SPDR XLB)",             "ticker": "XLB",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Versorger (US, SPDR XLU)",              "ticker": "XLU",  "asset_class": "BENCHMARK"},
    {"name": "Sektor Kommunikationsdienste (US, SPDR XLC)",  "ticker": "XLC",  "asset_class": "BENCHMARK"},
]

# GICS-Sektor (Bezeichnungen wie im Frontend, SECTORS) -> [bevorzugter Sektor-ETF, Rückfall-ETF]
SECTOR_ETFS = {
    "Industrie":               ["Sektor Industrie (MSCI World)",               "Sektor Industrie (US, SPDR XLI)"],
    "Informationstechnologie": ["Sektor Informationstechnologie (MSCI World)", "Sektor Informationstechnologie (US, SPDR XLK)"],
    "Finanzwesen":             ["Sektor Finanzwesen (MSCI World)",             "Sektor Finanzwesen (US, SPDR XLF)"],
    "Gesundheitswesen":        ["Sektor Gesundheitswesen (MSCI World)",        "Sektor Gesundheitswesen (US, SPDR XLV)"],
    "Zykl. Konsumgüter":       ["Sektor Zykl. Konsumgüter (MSCI World)",       "Sektor Zykl. Konsumgüter (US, SPDR XLY)"],
    "Basiskonsumgüter":        ["Sektor Basiskonsumgüter (MSCI World)",        "Sektor Basiskonsumgüter (US, SPDR XLP)"],
    "Energie":                 ["Sektor Energie (MSCI World)",                 "Sektor Energie (US, SPDR XLE)"],
    "Werkstoffe":              ["Sektor Werkstoffe (MSCI World)",              "Sektor Werkstoffe (US, SPDR XLB)"],
    "Versorger":               ["Sektor Versorger (MSCI World)",               "Sektor Versorger (US, SPDR XLU)"],
    "Kommunikationsdienste":   ["Sektor Kommunikationsdienste (MSCI World)",   "Sektor Kommunikationsdienste (US, SPDR XLC)"],
}

# Sektor je Einzelaktie im Depot (GICS). Neue Titel über die Watchlist-Funktion
# bekommen ihren Sektor automatisch von Yahoo (siehe app/main.py).
STOCK_SECTORS = {
    "ASML": "Informationstechnologie",
    "Baker Hughes": "Energie",
    "Boeing": "Industrie",
    "Daimler Truck Holding": "Industrie",
    "Ferrari": "Zykl. Konsumgüter",
    "General Dynamics": "Industrie",
    "Goldman Sachs": "Finanzwesen",
    "Hermes": "Zykl. Konsumgüter",
    "JPMorgan Chase": "Finanzwesen",
    "Philip Morris": "Basiskonsumgüter",
    "Rheinmetall": "Industrie",
    "Rollins": "Industrie",
    "SK Hynix (GDR)": "Informationstechnologie",
    "Siemens": "Industrie",
    "Siemens Energy": "Industrie",
    "SpaceX": "Industrie",
    "T-Mobile US": "Kommunikationsdienste",
    "Waste Management": "Industrie",
}

# Yahoo-Finance-Sektorbezeichnung -> GICS-Sektor wie im Frontend
YAHOO_SECTOR_MAP = {
    "Industrials": "Industrie",
    "Technology": "Informationstechnologie",
    "Financial Services": "Finanzwesen",
    "Healthcare": "Gesundheitswesen",
    "Consumer Cyclical": "Zykl. Konsumgüter",
    "Consumer Defensive": "Basiskonsumgüter",
    "Energy": "Energie",
    "Basic Materials": "Werkstoffe",
    "Utilities": "Versorger",
    "Communication Services": "Kommunikationsdienste",
}


# Aus der Überwachung genommene Positionen (werden in der DB deaktiviert und
# nicht mehr als Benchmark-Baustein genutzt). Rohstoffe und Geldmarkt sind aktuell nicht relevant.
RETIRED = [
    "Invesco Bloomberg Commodity (Benchmark-Proxy)",
    "iShares Diversified Commodity Swap (Benchmark-Proxy)",
    "Xtrackers EUR Overnight Rate Swap (Benchmark-Proxy)",
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

"""
Datenbank-Layer.

Warum Turso statt lokaler SQLite-Datei: Render löscht bei Free Web Services
alle lokalen Dateien bei jedem Redeploy (keine persistente Festplatte im
Gratis-Tarif, offiziell so dokumentiert). Turso ist eine SQLite-kompatible
Datenbank, die übers Netzwerk erreichbar ist - bleibt also unabhängig davon
erhalten, was mit dem Render-Dienst selbst passiert, und ist ebenfalls
kostenlos (Free Tier: 5 GB Speicher, kein Zeitlimit).

Lokal zum Testen (ohne Turso-Account) fällt der Code automatisch auf eine
lokale SQLite-Datei zurück, wenn TURSO_DATABASE_URL nicht gesetzt ist.
"""

import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")  # z.B. "libsql://mein-projekt-orgname.turso.io"
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

if TURSO_DATABASE_URL:
    # sqlalchemy-libsql übersetzt "sqlite+libsql://" auf die Turso-HTTP-API.
    # Das "libsql://"-Präfix aus dem Turso-Dashboard wird dafür durch
    # "sqlite+libsql://" ersetzt, der Auth-Token als Query-Parameter angehängt.
    _host = TURSO_DATABASE_URL.replace("libsql://", "")
    DATABASE_URL = f"sqlite+libsql://{_host}?authToken={TURSO_AUTH_TOKEN}&secure=true"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Lokaler Fallback fürs Entwickeln/Testen ohne Turso-Account
    DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.db"))
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Position(Base):
    """Eine überwachte Position (Aktie, Fonds im Depot, oder Benchmark-Proxy-ETF)."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)       # Anzeigename, z.B. "Rheinmetall"
    ticker = Column(String, nullable=False)                   # Yahoo-Finance-Ticker, z.B. "RHM.DE"
    asset_class = Column(String, nullable=False)              # "STOCK", "FUND" oder "BENCHMARK"
    active = Column(Integer, default=1)                       # 0 = pausiert/nicht mehr im Depot
    benchmark_label = Column(String, nullable=True)           # z.B. "MSCI World" - wenn gesetzt, wird diese
                                                                # Position auch als Benchmark-Baustein im
                                                                # Perioden-Renditen-Abschnitt des Frontends genutzt


class PriceHistory(Base):
    """Ein einzelner Kurs-Datenpunkt zu einem Datum."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True)
    position_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)          # Handelstag, auf den sich der Kurs bezieht
    close_price = Column(Float, nullable=False)
    currency = Column(String, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class Fundamentals(Base):
    """
    Kennzahlen-Snapshot je Position (Beta, Dividendenrendite, EPS,
    Analysten-Konsens, Kursziel). Wird täglich überschrieben (nur der
    letzte Stand wird gehalten, keine Historie nötig - anders als bei
    Kursen, wo die Historie für 5-Tage-/1-Monats-Vergleiche gebraucht wird).
    """
    __tablename__ = "fundamentals"

    position_id = Column(Integer, primary_key=True)
    beta = Column(Float, nullable=True)
    volatility_1y = Column(Float, nullable=True)         # annualisiert, aus eigener price_history berechnet, in %
    dividend_yield = Column(Float, nullable=True)        # in %
    eps_ttm = Column(Float, nullable=True)                # trailing twelve months, in Handelswährung
    analyst_rating_mean = Column(Float, nullable=True)    # 1.0 (Strong Buy) bis 5.0 (Sell), yfinance-Konvention
    analyst_rating_key = Column(String, nullable=True)    # z.B. "buy", "hold", "strong_buy"
    num_analysts = Column(Integer, nullable=True)
    price_target_mean = Column(Float, nullable=True)
    price_target_high = Column(Float, nullable=True)
    price_target_low = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppState(Base):
    """
    Einfacher Key-Value-Speicher für den gesamten Tool-Zustand
    (Gewichtungen, Index-Mix, Perioden usw.) - ersetzt das bisherige
    window.storage aus der Claude-Oberfläche.
    """
    __tablename__ = "app_state"

    key = Column(String, primary_key=True)
    value_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

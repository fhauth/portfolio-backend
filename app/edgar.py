"""
SEC-EDGAR-Anbindung: EPS (TTM) und Dividende je Aktie (TTM) direkt aus den
Berichten (10-K / 10-Q) US-börsennotierter Unternehmen.

Quelle: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
        https://www.sec.gov/files/company_tickers.json   (Ticker -> CIK)

Die SEC verlangt, dass sich Abrufer im User-Agent mit Kontaktdaten
identifizieren. Der Kontakt kommt aus der Umgebungsvariable SEC_CONTACT
(in GitHub: Repository-Secret "SEC_CONTACT"). Ohne diese Variable wird EDGAR
übersprungen und es bleibt bei den Yahoo-Werten.

TTM-Berechnung (Flussgrößen wie EPS und Dividende):
  - Liegt der letzte Bericht am Geschäftsjahresende (10-K):  TTM = Jahreswert.
  - Sonst:  TTM = letztes Geschäftsjahr + laufendes Jahr bis heute (YTD)
                  - dasselbe YTD-Zeitfenster des Vorjahres.
Fehlt für diese Rechnung ein Baustein, wird der Wert NICHT geschätzt, sondern
nicht geliefert (dann gilt Yahoo bzw. n/v).
"""

import os
import re
import json
import time
import logging
import urllib.request
from datetime import date, datetime

logger = logging.getLogger("edgar")

TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic"]
DPS_TAGS = ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"]
FORMS = ("10-K", "10-K/A", "10-KT", "10-Q", "10-Q/A")

US_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")

_ticker_map = None


def _user_agent():
    contact = os.environ.get("SEC_CONTACT", "").strip()
    if not contact:
        return None
    return f"PortfolioBenchmarkTool {contact}"


def _get_json(url, timeout=30):
    ua = _user_agent()
    if not ua:
        raise RuntimeError("SEC_CONTACT nicht gesetzt")
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def is_us_candidate(ticker):
    """Yahoo-Ticker ohne Börsenkürzel (SIE.DE, ASML.AS ...) = vermutlich US-Listing."""
    return bool(ticker) and bool(US_TICKER_RE.match(ticker.upper())) and "=" not in ticker


def load_ticker_map():
    global _ticker_map
    if _ticker_map is None:
        raw = _get_json(TICKER_URL)
        _ticker_map = {}
        for v in raw.values():
            _ticker_map[str(v["ticker"]).upper()] = int(v["cik_str"])
    return _ticker_map


def cik_for(ticker):
    m = load_ticker_map()
    t = ticker.upper()
    return m.get(t) or m.get(t.replace(".", "-"))


# ---------- reine Rechenlogik (ohne Netz, testbar) ----------

def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _entries(facts, tags, unit):
    """Liefert (tag, bereinigte Einträge) für das erste Tag mit brauchbaren Daten.
    Je Zeitraum (start,end) wird der zuletzt eingereichte Eintrag verwendet."""
    usgaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in tags:
        node = usgaap.get(tag)
        if not node:
            continue
        rows = (node.get("units") or {}).get(unit) or []
        best = {}
        for r in rows:
            if r.get("form") not in FORMS or not r.get("start") or not r.get("end"):
                continue
            try:
                s, e = _d(r["start"]), _d(r["end"])
                filed = _d(r["filed"]) if r.get("filed") else date.min
                val = float(r["val"])
            except Exception:
                continue
            key = (s, e)
            if key not in best or filed >= best[key]["filed"]:
                best[key] = {"start": s, "end": e, "days": (e - s).days, "val": val, "filed": filed, "form": r["form"]}
        if best:
            return tag, list(best.values())
    return None, []


def ttm_from_entries(entries, max_age_days=500):
    """TTM aus Berichtszeiträumen. Rückgabe dict(value, period_end, basis, filed, form) oder None."""
    if not entries:
        return None
    annual = [x for x in entries if 350 <= x["days"] <= 380]
    partial = [x for x in entries if 60 <= x["days"] <= 290]
    latest_end = max(x["end"] for x in entries)
    if (date.today() - latest_end).days > max_age_days:
        return None

    # Fall A: der jüngste Zeitraum ist ein volles Geschäftsjahr
    a_at_end = [x for x in annual if x["end"] == latest_end]
    if a_at_end:
        a = max(a_at_end, key=lambda x: x["filed"])
        return {"value": a["val"], "period_end": a["end"], "basis": "Geschäftsjahr", "filed": a["filed"], "form": a["form"]}

    # Fall B: unterjährig -> Jahr + YTD - Vorjahres-YTD
    cur = [x for x in partial if x["end"] == latest_end]
    if not cur:
        return None
    ytd = max(cur, key=lambda x: x["days"])   # längster Zeitraum bis zu diesem Stichtag (3/6/9 Monate)
    prior = [x for x in partial
             if abs((ytd["end"] - x["end"]).days - 365) <= 12 and abs(x["days"] - ytd["days"]) <= 12]
    # letztes volles Geschäftsjahr endet unmittelbar vor Beginn des laufenden YTD
    fy = [x for x in annual if abs((ytd["start"] - x["end"]).days) <= 12]
    if not prior or not fy:
        return None
    p = max(prior, key=lambda x: x["filed"])
    f = max(fy, key=lambda x: x["filed"])
    return {"value": f["val"] + ytd["val"] - p["val"], "period_end": ytd["end"], "basis": "TTM", "filed": ytd["filed"], "form": ytd["form"]}


def last_fiscal_year(entries):
    """Rückfall: Wert des letzten abgeschlossenen Geschäftsjahres (nur wenn nicht zu alt)."""
    annual = [x for x in entries if 350 <= x["days"] <= 380]
    if not annual:
        return None
    a = max(annual, key=lambda x: x["end"])
    if (date.today() - a["end"]).days > 500:
        return None
    return {"value": a["val"], "period_end": a["end"], "basis": "Geschäftsjahr", "filed": a["filed"], "form": a["form"]}


def metrics_from_facts(facts):
    """Berechnet EPS (TTM) und DPS (TTM bzw. letztes Geschäftsjahr) aus companyfacts-JSON."""
    out = {}
    _, eps_e = _entries(facts, EPS_TAGS, "USD/shares")
    eps = ttm_from_entries(eps_e)
    if eps:
        out["eps"] = eps
    _, dps_e = _entries(facts, DPS_TAGS, "USD/shares")
    dps = ttm_from_entries(dps_e) or last_fiscal_year(dps_e)
    if dps and dps["value"] >= 0:
        out["dps"] = dps
    return out


def fetch_us_metrics(ticker):
    """Holt die Kennzahlen für einen Ticker. None, wenn nicht verfügbar (dann gilt Yahoo)."""
    if not _user_agent() or not is_us_candidate(ticker):
        return None
    try:
        cik = cik_for(ticker)
        if not cik:
            return None
        facts = _get_json(FACTS_URL.format(cik=cik))
        time.sleep(0.2)   # SEC-Limit: max. 10 Anfragen/Sekunde
    except Exception as e:
        logger.warning(f"EDGAR für {ticker} nicht abrufbar: {e}")
        return None
    res = metrics_from_facts(facts)
    return res or None

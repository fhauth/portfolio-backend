"""
Nachrichtenabruf für das Tool (kostenlos, ohne API-Schlüssel).

Quellen:
  - Meldungen je Titel:  Yahoo Finance (über yfinance, englisch) und Google News RSS
                         (Suche nach dem Firmennamen, deutsch)
  - Wirtschaft/Makro:    RSS-Feeds von Tagesschau, Handelsblatt, FAZ, EZB und Google News
                         (Rubrik Wirtschaft). Es werden nur Schlagzeilen mit Link übernommen,
                         keine Volltexte.

Jede Quelle ist einzeln abgesichert: fällt ein Feed aus, laufen die anderen weiter, und die
Antwort nennt, welche Feeds nicht geantwortet haben. Ergebnisse werden kurz im Speicher
gehalten (CACHE_SECONDS), damit nicht bei jedem Seitenaufruf alle Quellen abgefragt werden.
"""

import re
import time
import logging
import html as htmllib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

import requests

logger = logging.getLogger("news")

CACHE_SECONDS = 20 * 60
MAX_AGE_DAYS_TITLES = 14
MAX_ITEMS_PER_TITLE = 6
MAX_MACRO_ITEMS = 40
HTTP_TIMEOUT = 8
MAX_BYTES = 2_000_000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioBenchmarkTool/1.0)"}

# (Anzeigename, URL, Sprache)
MACRO_FEEDS = [
    ("Tagesschau Wirtschaft", "https://www.tagesschau.de/wirtschaft/index~rss2.xml", "de"),
    ("Handelsblatt Finanzen", "https://www.handelsblatt.com/contentexport/feed/finanzen", "de"),
    ("Handelsblatt Unternehmen", "https://www.handelsblatt.com/contentexport/feed/unternehmen", "de"),
    ("FAZ Finanzen", "https://www.faz.net/rss/aktuell/finanzen/", "de"),
    ("FAZ Wirtschaft", "https://www.faz.net/rss/aktuell/wirtschaft/", "de"),
    ("EZB Pressemitteilungen", "https://www.ecb.europa.eu/rss/press.xml", "en"),
    ("Google News Wirtschaft", "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=de&gl=DE&ceid=DE:de", "de"),
]

_cache = {}


def _cached(key):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    return None


def _store(key, value):
    _cache[key] = (time.time(), value)
    return value


def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(el, name):
    for c in el:
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def _parse_date(text):
    """RFC-822 (RSS) oder ISO-8601 (Atom/Yahoo) -> aware UTC datetime, sonst None."""
    if not text:
        return None
    try:
        d = parsedate_to_datetime(text)
    except Exception:
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _clean(text):
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _safe_url(url):
    return url if isinstance(url, str) and url.lower().startswith(("http://", "https://")) else None


def parse_feed(xml_bytes, default_source=""):
    """RSS 2.0 und Atom -> Liste {title, url, source, published(datetime|None)}."""
    root = ET.fromstring(xml_bytes)
    items = []
    for el in root.iter():
        name = _local(el.tag)
        if name not in ("item", "entry"):
            continue
        title = _clean(_child_text(el, "title"))
        url = _child_text(el, "link")
        if not url:  # Atom: <link href="...">
            for c in el:
                if _local(c.tag) == "link" and c.get("href"):
                    url = c.get("href")
                    break
        published = _parse_date(_child_text(el, "pubDate") or _child_text(el, "published") or _child_text(el, "updated"))
        source = _clean(_child_text(el, "source")) or default_source
        url = _safe_url(url)
        if title and url:
            items.append({"title": title, "url": url, "source": source, "published": published})
    return items


def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, stream=True)
    r.raise_for_status()
    data = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(data) > MAX_BYTES:
        raise ValueError("Feed zu groß")
    return data


def _iso(d):
    return d.isoformat() if d else None


def _norm(title):
    return re.sub(r"[^a-z0-9äöüß]+", " ", title.lower()).strip()


# ---------------- Wirtschaft / Makro ----------------

def fetch_macro(force=False):
    cached = None if force else _cached("macro")
    if cached:
        return cached
    feeds_status, items = [], []

    def one(name, url, lang):
        data = _get(url)
        parsed = parse_feed(data, default_source=name)
        return name, lang, parsed

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(one, n, u, l): n for n, u, l in MACRO_FEEDS}
        try:
            for f in as_completed(futures, timeout=30):
                n = futures[f]
                try:
                    name, lang, parsed = f.result()
                    feeds_status.append({"name": name, "ok": True, "count": len(parsed)})
                    for it in parsed:
                        # Google News hängt " - Quelle" an die Überschrift
                        title = it["title"]
                        src = it["source"]
                        if name.startswith("Google News") and " - " in title:
                            title, _, tail = title.rpartition(" - ")
                            src = tail or src
                        items.append({"title": title, "url": it["url"], "source": src or name,
                                      "feed": name, "lang": lang, "published": it["published"]})
                except Exception as e:
                    logger.warning("Feed %s fehlgeschlagen: %s", n, e)
                    feeds_status.append({"name": n, "ok": False, "count": 0})
        except Exception:
            pass
    done = {s["name"] for s in feeds_status}
    for n, _, _ in MACRO_FEEDS:
        if n not in done:
            feeds_status.append({"name": n, "ok": False, "count": 0})

    seen, out = set(), []
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    for it in sorted(items, key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        key = _norm(it["title"])
        if key in seen or (it["published"] and it["published"] < cutoff):
            continue
        seen.add(key)
        out.append({**it, "published": _iso(it["published"])})
        if len(out) >= MAX_MACRO_ITEMS:
            break
    feeds_status.sort(key=lambda s: s["name"])
    return _store("macro", {"fetchedAt": datetime.now(timezone.utc).isoformat(), "items": out, "feeds": feeds_status})


# ---------------- Meldungen je Titel ----------------

def _search_name(name):
    """'SK Hynix (GDR)' -> 'SK Hynix' ; 'Siemens' bleibt 'Siemens'."""
    return re.sub(r"\s*\(.*?\)\s*", " ", name).strip()


def _yahoo_news(ticker):
    import yfinance as yf
    out = []
    for n in (yf.Ticker(ticker).news or []):
        c = n.get("content") or n
        title = _clean(c.get("title") or "")
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or n.get("link"))
        pub = _parse_date(c.get("pubDate") or c.get("displayTime"))
        if pub is None and n.get("providerPublishTime"):
            pub = datetime.fromtimestamp(n["providerPublishTime"], tz=timezone.utc)
        source = (c.get("provider") or {}).get("displayName") or n.get("publisher") or "Yahoo Finance"
        url = _safe_url(url)
        if title and url:
            out.append({"title": title, "url": url, "source": source, "published": pub, "lang": "en"})
    return out


def _google_news(name):
    q = quote_plus(f"{_search_name(name)} Aktie")
    url = f"https://news.google.com/rss/search?q={q}&hl=de&gl=DE&ceid=DE:de"
    out = []
    for it in parse_feed(_get(url), default_source="Google News"):
        title, src = it["title"], it["source"]
        if " - " in title:
            title, _, tail = title.rpartition(" - ")
            src = tail or src
        out.append({"title": title, "url": it["url"], "source": src, "published": it["published"], "lang": "de"})
    return out


def _fetch_one_title(pos_id, name, ticker, longer_names):
    """Yahoo + Google für einen Titel. Gibt (items, yahoo_ok, google_ok) zurück."""
    items, y_ok, g_ok = [], True, True
    try:
        items += _yahoo_news(ticker)
    except Exception as e:
        y_ok = False
        logger.warning("Yahoo-News %s: %s", ticker, e)
    try:
        key = _search_name(name).lower()
        for it in _google_news(name):
            low = it["title"].lower()
            if key.split()[0] not in low:          # Treffer ohne Firmennamen verwerfen
                continue
            if any(l in low for l in longer_names):  # z.B. "Siemens Energy" bei "Siemens"
                continue
            items.append(it)
    except Exception as e:
        g_ok = False
        logger.warning("Google-News %s: %s", name, e)
    return pos_id, name, items, y_ok, g_ok


def fetch_titles(positions, force=False):
    """positions: Liste (id, name, ticker) der Einzelaktien."""
    cached = None if force else _cached("titles")
    if cached:
        return cached
    names = [p[1] for p in positions]
    results, y_fail, g_fail = [], 0, 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for pid, name, ticker in positions:
            longer = [n.lower() for n in names if n != name and n.lower().startswith(name.lower() + " ")]
            futures.append(pool.submit(_fetch_one_title, pid, name, ticker, longer))
        try:
            for f in as_completed(futures, timeout=45):
                try:
                    pid, name, items, y_ok, g_ok = f.result()
                except Exception:
                    continue
                y_fail += 0 if y_ok else 1
                g_fail += 0 if g_ok else 1
                results.append((pid, name, items))
        except Exception:
            pass

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS_TITLES)
    out = []
    for pid, name, items in results:
        seen, kept = set(), []
        for it in sorted(items, key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
            key = _norm(it["title"])
            if key in seen or (it["published"] and it["published"] < cutoff) or not it["published"]:
                continue
            seen.add(key)
            kept.append(it)
            if len(kept) >= MAX_ITEMS_PER_TITLE:
                break
        for it in kept:
            out.append({"positionId": pid, "name": name, "title": it["title"], "url": it["url"],
                        "source": it["source"], "lang": it["lang"], "published": _iso(it["published"])})
    out.sort(key=lambda x: x["published"], reverse=True)
    return _store("titles", {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "items": out,
        "sources": {"yahooFailed": y_fail, "googleFailed": g_fail, "titles": len(positions)},
    })

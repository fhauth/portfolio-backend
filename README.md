# Portfolio-Benchmark Backend

Server-seitiges Backend für das Portfolio-Benchmark-Tool: ruft täglich zu
Handelsschluss automatisch Kurse ab (löst das CORS-Problem, das im Browser
nicht lösbar war) und speichert Tool-Zustand + Kurshistorie dauerhaft.

## Architektur

- **FastAPI** (`app/main.py`) – REST-API für Frontend
- **SQLAlchemy** + **Turso** (`app/database.py`) – Datenbank, extern gehostet
  (kostenlos, bleibt bei Redeploys erhalten – anders als eine lokale
  SQLite-Datei im Render-Gratis-Tarif)
- **yfinance** (`app/fetch_prices.py`) – Kursabruf, funktioniert server-seitig
  ohne CORS-Problem
- **Cron-Skript** (`scripts/daily_fetch.py`) – läuft laut `render.yaml`
  werktags um 21:15 UTC (22:15 MEZ / 23:15 MESZ), kurz nach US-Börsenschluss

## Einmalige Einrichtung

### 1. Turso-Datenbank anlegen (kostenlos, ca. 5 Minuten)

```bash
# Turso-CLI installieren (siehe https://docs.turso.tech/cli/installation)
curl -sSfL https://get.tur.so/install.sh | bash

turso auth signup          # Account anlegen (GitHub-Login)
turso db create portfolio-benchmark
turso db show portfolio-benchmark --url        # -> TURSO_DATABASE_URL
turso db tokens create portfolio-benchmark     # -> TURSO_AUTH_TOKEN
```

Beide Werte notieren, die brauchst du gleich in Render.

### 2. Code zu GitHub pushen

```bash
cd portfolio-backend
git init
git add .
git commit -m "Initial commit"
# Repo auf GitHub anlegen, dann:
git remote add origin https://github.com/DEIN-USERNAME/portfolio-backend.git
git push -u origin main
```

### 3. Bei Render deployen

1. Auf [render.com](https://render.com) mit GitHub anmelden
2. "New" → "Blueprint" → dein `portfolio-backend`-Repo auswählen
3. Render erkennt automatisch `render.yaml` und legt **beide** Dienste an
   (Web Service + Cron Job)
4. Bei **beiden** Diensten unter "Environment" die zwei Variablen eintragen:
   - `TURSO_DATABASE_URL` (aus Schritt 1)
   - `TURSO_AUTH_TOKEN` (aus Schritt 1)
5. Deploy abwarten (paar Minuten), dann die URL des Web Service kopieren
   (sieht aus wie `https://portfolio-backend-xyz.onrender.com`)

### 4. Frontend verbinden

In der HTML-Datei (`portfolio-benchmark-v19.html`) ganz oben im `<script>`-Bereich
die Zeile

```js
const API_BASE = window.PORTFOLIO_API_BASE || 'http://localhost:8000';
```

— entweder direkt die Render-URL eintragen:

```js
const API_BASE = window.PORTFOLIO_API_BASE || 'https://portfolio-backend-xyz.onrender.com';
```

— oder (empfohlen, damit man es nicht bei jedem Update der HTML-Datei vergisst)
vor dem Haupt-Skript im `<head>` ergänzen:

```html
<script>window.PORTFOLIO_API_BASE = 'https://portfolio-backend-xyz.onrender.com';</script>
```

### 5. CORS einschränken (Sicherheit)

Nach dem ersten erfolgreichen Test in Render bei der `CORS_ORIGINS`-Umgebungsvariable
des Web Service `*` durch die tatsächliche URL ersetzen, von der aus du das
Frontend öffnest (z.B. `https://claude.ai` oder deine eigene Hosting-URL),
damit nicht jede beliebige Webseite deine API ansprechen kann.

## Lokal testen (ohne Turso, ohne Render)

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
# -> http://localhost:8000/api/health sollte {"status":"ok"} zurückgeben
```

Ohne gesetzte `TURSO_DATABASE_URL` nutzt die App automatisch eine lokale
SQLite-Datei unter `data/portfolio.db` - praktisch zum Entwickeln, aber
das ist dann wieder die "geht bei Redeploy verloren"-Variante, nur lokal.

Manuellen Kursabruf testen:

```bash
python scripts/daily_fetch.py
```

## Neue Position hinzufügen

In `app/seed_positions.py` einen Eintrag zur `POSITIONS`-Liste hinzufügen
(Name + Yahoo-Finance-Ticker + Anlageklasse) und neu deployen - wird beim
nächsten Start automatisch angelegt, bestehende Daten bleiben erhalten.

## Bekannte Einschränkungen

- **SK Hynix (GDR)**: Yahoo Finance hat keinen sauberen Ticker für die
  Global Depositary Receipt selbst, es wird ersatzweise die Korea-Notierung
  (`000660.KS`, in KRW) verwendet - Kursniveau weicht vom tatsächlichen
  GDR-Preis ab, prozentuale Veränderungen sind aber eine brauchbare Näherung.
- **Render Free Tier**: Der Web Service "schläft" nach 15 Minuten Inaktivität
  ein und braucht beim nächsten Aufruf ein paar Sekunden zum Aufwachen - für
  ein persönliches Analyse-Tool unkritisch. Der Cron Job ist davon nicht
  betroffen und läuft unabhängig zur geplanten Zeit.
- **Fonds/ETFs** sind noch nicht in der Watchlist enthalten (siehe Chat-Notiz
  "die machen wir später") - können nach demselben Muster in
  `seed_positions.py` ergänzt werden.

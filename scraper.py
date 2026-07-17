#!/usr/bin/env python3
"""
KNBSB Hoofdklasse (Lucky Day) – Standen scraper
================================================
Haalt de standen op van:
    https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/standings
en schrijft ze weg als standen.json.

De oorspronkelijke versie gebruikte platte urllib-requests, maar die worden
inmiddels hard geblokkeerd door deze site (HTTP 403 al bij de eerste request
vanaf GitHub Actions-runners) — hetzelfde patroon dat we eerder zagen bij
stats.baseball.cz en ffbs.wbsc.org. Dit script bevat daarom dezelfde hardening:
  1. Eerst een snelle poging met `requests` + volledige browser-headers.
  2. Bij 403/429/503: Playwright-fallback met stealth-init-script (verbergt
     de meest voorkomende headless-Chromium-fingerprints) en een paar
     herhaalpogingen.
  3. Optionele proxy-ondersteuning via de PROXY_URL env-var/secret, voor het
     geval ook dit een IP-reputatie-blokkade blijkt (in plaats van alleen
     bot-detectie) — zonder die secret verandert er niets aan het gedrag.

De parse-logica (fase-headers + tabel) is ongewijzigd t.o.v. de oorspronkelijke
versie.
"""
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
import requests
# ---------------------------------------------------------------------------
# Proxy (optioneel)
# ---------------------------------------------------------------------------
PROXY_URL = os.environ.get("PROXY_URL", "").strip() or None
REQUEST_PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None
# ---------------------------------------------------------------------------
# Configuratie
# ---------------------------------------------------------------------------
URL = "https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/standings"
TIMEOUT = 30
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['nl-NL', 'nl', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = { runtime: {} };
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
    window.navigator.permissions.query = (params) => (
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : origQuery(params)
    );
}
"""
# ---------------------------------------------------------------------------
# Strategie 1: requests met browser-headers
# ---------------------------------------------------------------------------
def haal_via_requests() -> str:
    resp = requests.get(URL, headers=BROWSER_HEADERS, timeout=TIMEOUT, proxies=REQUEST_PROXIES)
    resp.raise_for_status()
    return resp.text
# ---------------------------------------------------------------------------
# Strategie 2: Playwright-fallback
# ---------------------------------------------------------------------------
def _playwright_proxy_config():
    if not PROXY_URL:
        return None
    parsed = urllib.parse.urlsplit(PROXY_URL)
    server = f"{parsed.scheme}://{parsed.hostname}" + (f":{parsed.port}" if parsed.port else "")
    config = {"server": server}
    if parsed.username:
        config["username"] = urllib.parse.unquote(parsed.username)
    if parsed.password:
        config["password"] = urllib.parse.unquote(parsed.password)
    return config
def haal_via_playwright() -> str:
    """
    Laadt de standen-pagina in headless Chromium en geeft de volledige HTML
    terug. Probeert het tot 2 keer met een verse browser-context, met
    stealth-maatregelen tegen headless-detectie.
    """
    from playwright.sync_api import sync_playwright
    max_pogingen = 2
    laatste_fout = None
    for poging in range(1, max_pogingen + 1):
        try:
            with sync_playwright() as p:
                proxy_config = _playwright_proxy_config()
                if proxy_config:
                    print(f"  → gebruik proxy: {proxy_config['server']}", flush=True)
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                    proxy=proxy_config,
                )
                context = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="nl-NL",
                    viewport={"width": 1366, "height": 900},
                    extra_http_headers={"Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"},
                )
                context.add_init_script(STEALTH_INIT_SCRIPT)
                page = context.new_page()
                print(f"  Playwright (poging {poging}/{max_pogingen}): standen-pagina laden…", flush=True)
                resp = page.goto(URL, wait_until="domcontentloaded", timeout=60_000)
                status = resp.status if resp else None
                print(f"  → paginastatus: {status}", flush=True)
                if status and status >= 400:
                    fragment = page.content()[:300].replace("\n", " ")
                    print(f"  ⚠ Pagina gaf status {status}. Fragment: {fragment}", file=sys.stderr)
                page.wait_for_timeout(6_000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:  # noqa: BLE001
            laatste_fout = e
            print(f"  ✗ Playwright-poging {poging}/{max_pogingen} mislukt: {e}", file=sys.stderr)
            if poging < max_pogingen:
                print("  → nieuwe poging over 10s met verse browser-context…", flush=True)
                import time
                time.sleep(10)
    raise laatste_fout
def fetch_html() -> str:
    try:
        print("→ Ophalen (requests) …", flush=True)
        return haal_via_requests()
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        print(f"  ✗ HTTP {code} — val terug op Playwright", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ Fout bij requests: {e} — val terug op Playwright", file=sys.stderr)
    print("→ Fallback naar Playwright (browsercontext)…", flush=True)
    return haal_via_playwright()
# ---------------------------------------------------------------------------
# Parsing (ongewijzigd t.o.v. de oorspronkelijke versie)
# ---------------------------------------------------------------------------
def clean(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[A-Z]{2,4}\s+', '', text)
    return text.strip()
def parse_standings(html):
    result = {}
    parts = re.split(r'<h3[^>]*>(.*?)</h3>', html, flags=re.DOTALL)
    i = 1
    while i < len(parts):
        fase_naam = re.sub(r'<[^>]+>', '', parts[i]).strip()
        rest = parts[i + 1] if i + 1 < len(parts) else ''
        table_match = re.search(r'<table[^>]*>(.*?)</table>', rest, re.DOTALL)
        if not table_match:
            i += 2
            continue
        table_html = table_match.group(1)
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
        fase_rijen = []
        for row in rows:
            tds_raw = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            tds = [re.sub(r'<[^>]+>', '', td).strip() for td in tds_raw]
            tds = [re.sub(r'\s+', ' ', td).strip() for td in tds]
            if len(tds) < 5:
                continue
            positie = tds[0] if tds[0] else '-'
            team = ''
            team_idx = -1
            for j in range(1, len(tds)):
                if re.search(r'[A-Za-z]', tds[j]):
                    team = clean(tds[j])
                    team_idx = j
                    break
            if not team or team_idx == -1:
                continue
            cijfers = [c for c in tds[team_idx + 1:] if c != '']
            if len(cijfers) < 3:
                continue
            rij = {
                "positie": positie,
                "team":    team,
                "w":       cijfers[0] if len(cijfers) > 0 else '-',
                "l":       cijfers[1] if len(cijfers) > 1 else '-',
                "t":       cijfers[2] if len(cijfers) > 2 else '-',
                "pct":     cijfers[3] if len(cijfers) > 3 else '-',
                "gb":      cijfers[4] if len(cijfers) > 4 else '-',
            }
            fase_rijen.append(rij)
        if fase_rijen:
            result[fase_naam] = fase_rijen
        i += 2
    return result
def main():
    print(f"Ophalen van {URL}...")
    html = fetch_html()
    print(f"Ontvangen: {len(html)} bytes")
    standen = parse_standings(html)
    print(f"Gevonden fases: {list(standen.keys())}")
    output = {
        "bijgewerkt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bron":       URL,
        "standen":    standen,
    }
    with open("standen.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print("✅ standen.json opgeslagen")
if __name__ == "__main__":
    main()

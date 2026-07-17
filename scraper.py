#!/usr/bin/env python3
"""
KNBSB Hoofdklasse (Lucky Day) – Standen scraper
================================================
Haalt de standen op van:
    https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/standings
en schrijft ze weg als standen.json.

BELANGRIJKE WIJZIGING t.o.v. de vorige versie
----------------------------------------------
De site draait op Inertia.js (dit blijkt uit de uitslagen-scraper: die site
zet alle data in een `data-page="{...JSON...}"`-attribuut op de root-<div>,
in plaats van losse <table>-markup in de HTML). Nu de 403-blokkade is
opgelost (via `requests` + browser-headers, met Playwright-stealth als
fallback), kwam de ruwe HTML wel binnen — maar de oude regex-parser
(<h3>/<table>/<tr>/<td>) vond niks meer, omdat de standen ook via die
Inertia data-page JSON worden aangeleverd i.p.v. als kant-en-klare tabellen.

Deze versie probeert daarom EERST de Inertia-JSON te lezen (zelfde aanpak
als de uitslagen-scraper), en valt pas terug op de oude tabel-regex als er
geen data-page gevonden wordt (voor het geval deze pagina toch anders is
opgebouwd dan de uitslagen-pagina).

Omdat de exacte prop-namen voor de standen (bv. "standings", "table",
"groups", "phases", ...) niet vooraf bekend zijn, print het script bij de
eerste run de beschikbare props-keys + structuur naar de Actions-log. Komt
er (nog) niks bruikbaars uit? Stuur die logregels door, dan stem ik de
key-namen exact af.
"""
import json
import re
import sys
import urllib.parse
import os
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
# Team-logo's (zelfde lijst als de uitslagen-scraper, voor consistentie)
# ---------------------------------------------------------------------------
TEAM_LOGOS = {
    "Curaçao Neptunus":                              "https://worldbaseballnews.org/wp-content/uploads/2025/11/neptunus.png",
    "HCAW":                                          "https://worldbaseballnews.org/wp-content/uploads/2025/11/hcaw.png",
    "Amsterdam Pirates":                             "https://worldbaseballnews.org/wp-content/uploads/2025/11/amsterdam-pirates.png",
    "Kinheim":                                       "https://worldbaseballnews.org/wp-content/uploads/2025/11/kinheim.png",
    "Oosterhout Twins":                              "https://worldbaseballnews.org/wp-content/uploads/2025/11/twins-1.png",
    "Worldwide Pharma Logistics Hoofddorp Pioniers": "https://worldbaseballnews.org/wp-content/uploads/2025/11/pioniers.png",
    "UVV":                                           "https://worldbaseballnews.org/wp-content/uploads/2025/11/uvv.png",
}


def logo(team_naam: str) -> str:
    if team_naam in TEAM_LOGOS:
        return TEAM_LOGOS[team_naam]
    for naam, url in TEAM_LOGOS.items():
        if naam.lower() in team_naam.lower() or team_naam.lower() in naam.lower():
            return url
    return ""


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
    terug (na JS-uitvoering). Probeert het tot 2 keer met een verse
    browser-context, met stealth-maatregelen tegen headless-detectie.
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
# Inertia-parsing (nieuw — zelfde aanpak als de uitslagen-scraper)
# ---------------------------------------------------------------------------
def extract_inertia_data(html):
    match = re.search(r'<div[^>]+id=["\']app["\'][^>]+data-page=["\']([^"\']+)["\']', html)
    if not match:
        match = re.search(r'data-page="([^"]+)"', html)
    if not match:
        match = re.search(r"data-page='([^']+)'", html)
    if not match:
        return None
    raw = match.group(1)
    raw = raw.replace('&quot;', '"').replace('&#039;', "'").replace('&amp;', '&')
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _get_pos(rij, *sleutels, default='-'):
    for s in sleutels:
        if s in rij and rij[s] not in (None, ''):
            return rij[s]
    return default


def parse_standen_uit_inertia(data):
    """
    Zoekt de standen in de Inertia-props. De exacte structuur is niet vooraf
    bekend (elke pagina/component kan andere prop-namen gebruiken), dus dit
    probeert een aantal voor de hand liggende sleutels en print de gevonden
    props-keys naar de log zodat we dit kunnen verfijnen als het niet meteen
    goed staat.
    """
    props = data.get('props', {})
    print(f"  Props keys (standen-pagina): {list(props.keys())}", flush=True)

    kandidaten = ['standings', 'standing', 'table', 'tables', 'groups', 'phases', 'divisions', 'ranking', 'rankings']
    bron = None
    gekozen_key = None
    for key in kandidaten:
        if key in props and props[key]:
            bron = props[key]
            gekozen_key = key
            break
    if bron is None:
        print("  ❌ Geen bekende standen-sleutel gevonden in props.", flush=True)
        return {}

    print(f"  → gebruik props['{gekozen_key}']", flush=True)

    result = {}
    # Structuur kan zijn: { "Regular Season": [ {...rij...}, ... ], ... }
    # of: [ { "name": "...", "teams": [ {...}, ... ] }, ... ]
    if isinstance(bron, dict):
        fasen = bron.items()
    elif isinstance(bron, list):
        fasen = []
        for fase in bron:
            if isinstance(fase, dict):
                naam = fase.get('name') or fase.get('title') or fase.get('phase') or 'Standen'
                rijen = fase.get('teams') or fase.get('rows') or fase.get('standings') or fase.get('data') or []
                fasen.append((naam, rijen))
            elif isinstance(fase, list):
                fasen.append(('Standen', fase))
        fasen = tuple(fasen)
    else:
        fasen = ()

    for fase_naam, rijen in fasen:
        if not isinstance(rijen, list):
            continue
        fase_rijen = []
        for i, rij in enumerate(rijen, start=1):
            if not isinstance(rij, dict):
                continue
            team = rij.get('team')
            if isinstance(team, dict):
                team_naam = team.get('name') or team.get('short_name') or ''
            else:
                team_naam = rij.get('team_name') or rij.get('name') or str(team or '')
            fase_rijen.append({
                "positie": str(_get_pos(rij, 'position', 'rank', 'pos', default=str(i))),
                "team":    team_naam,
                "logo":    logo(team_naam),
                "w":       str(_get_pos(rij, 'wins', 'w', 'won')),
                "l":       str(_get_pos(rij, 'losses', 'l', 'lost')),
                "t":       str(_get_pos(rij, 'ties', 't', 'draws')),
                "pct":     str(_get_pos(rij, 'pct', 'win_pct', 'percentage')),
                "gb":      str(_get_pos(rij, 'gb', 'games_behind')),
            })
        if fase_rijen:
            result[fase_naam] = fase_rijen
    return result


# ---------------------------------------------------------------------------
# Fallback: oude tabel-regex-parsing (voor het geval de pagina toch
# server-rendered HTML-tabellen bevat i.p.v. Inertia-props)
# ---------------------------------------------------------------------------
def clean(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[A-Z]{2,4}\s+', '', text)
    return text.strip()


def parse_standen_uit_tabellen(html):
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
            fase_rijen.append({
                "positie": positie,
                "team":    team,
                "logo":    logo(team),
                "w":       cijfers[0] if len(cijfers) > 0 else '-',
                "l":       cijfers[1] if len(cijfers) > 1 else '-',
                "t":       cijfers[2] if len(cijfers) > 2 else '-',
                "pct":     cijfers[3] if len(cijfers) > 3 else '-',
                "gb":      cijfers[4] if len(cijfers) > 4 else '-',
            })
        if fase_rijen:
            result[fase_naam] = fase_rijen
        i += 2
    return result


def parse_standings(html):
    data = extract_inertia_data(html)
    if data is not None:
        standen = parse_standen_uit_inertia(data)
        if standen:
            return standen
        print("  ⚠ Inertia-data gevonden maar geen standen eruit gehaald — probeer tabel-regex als fallback.", flush=True)
    else:
        print("  ⚠ Geen Inertia data-page gevonden — probeer tabel-regex.", flush=True)
    return parse_standen_uit_tabellen(html)


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

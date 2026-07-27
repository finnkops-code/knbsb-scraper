#!/usr/bin/env python3
"""
Honkbal Hoofdklasse – Standen scraper
======================================
Haalt de standen op van:
    https://honkbalhoofdklasse.com/stand
en schrijft ze weg als standen.json.

NIEUWE BRON (i.p.v. stats.knbsbstats.nl)
-----------------------------------------
honkbalhoofdklasse.com draait op Next.js. De standen-pagina is
server-rendered: een gewone GET met browser-headers levert de volledige,
al-gerenderde HTML op (getest en bevestigd — geen 403/WAF-blokkade zoals bij
de oude bron). Er zijn daarom twee parse-strategieën, in volgorde geprobeerd:

  1. __NEXT_DATA__-JSON: Next.js zet de hydration-props standaard in
     <script id="__NEXT_DATA__" type="application/json">{...}</script>.
     Als de standen-array daarin te vinden is, is dat de betrouwbaarste bron
     (geen tekst-parsing nodig). De exacte prop-namen zijn niet vooraf
     bekend, dus dit wordt recursief gezocht op basis van herkenbare
     sleutels (wins/losses/w/l/pct/team). Bij twijfel print het script de
     kandidaten naar de Actions-log.
  2. HTML-fallback: elke rij op de standen-pagina is een <a href="/rosters/
     <slug>">...</a> die de hele rij omvat (positie, team, GB/Leader, W, L,
     PCT, streak). De team-slug in de URL (bv. "neptunus", "pirates") is een
     betrouwbaarder team-ID dan de zichtbare tekst (die de teamnaam dubbel
     bevat i.v.m. responsive layout), dus de slug wordt als primaire
     team-sleutel gebruikt.

Playwright blijft als laatste redmiddel staan voor het geval de site ooit
alsnog client-side rendering of een bot-blokkade introduceert.
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
URL = "https://honkbalhoofdklasse.com/stand"
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
# Team-mapping: URL-slug (/rosters/<slug>) -> canonieke teamnaam + logo
# ---------------------------------------------------------------------------
SLUG_TEAM_NAMES = {
    "neptunus": "Curaçao Neptunus",
    "pirates":  "Amsterdam Pirates",
    "kinheim":  "Kinheim",
    "hcaw":     "HCAW",
    "twins":    "Oosterhout Twins",
    "pioniers": "Hoofddorp Pioniers",
    "uvv":      "UVV",
}
TEAM_LOGOS = {
    "Curaçao Neptunus":  "https://worldbaseballnews.org/wp-content/uploads/2025/11/neptunus.png",
    "HCAW":              "https://worldbaseballnews.org/wp-content/uploads/2025/11/hcaw.png",
    "Amsterdam Pirates":  "https://worldbaseballnews.org/wp-content/uploads/2025/11/amsterdam-pirates.png",
    "Kinheim":            "https://worldbaseballnews.org/wp-content/uploads/2025/11/kinheim.png",
    "Oosterhout Twins":   "https://worldbaseballnews.org/wp-content/uploads/2025/11/twins-1.png",
    "Hoofddorp Pioniers": "https://worldbaseballnews.org/wp-content/uploads/2025/11/pioniers.png",
    "UVV":                "https://worldbaseballnews.org/wp-content/uploads/2025/11/uvv.png",
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
# Strategie 2: Playwright-fallback (redmiddel als de site ooit CSR/WAF krijgt)
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
                    browser.close()
                    raise RuntimeError(f"Pagina gaf status {status} (mogelijk IP/WAF-blokkade)")
                page.wait_for_timeout(4_000)
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
# Strategie A: __NEXT_DATA__-JSON uitlezen (primair)
# ---------------------------------------------------------------------------
def extract_next_data(html):
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _looks_like_standings_rows(items):
    if not items or not all(isinstance(it, dict) for it in items):
        return False
    keys = set()
    for it in items:
        keys |= {k.lower() for k in it.keys()}
    heeft_wl = any(k in keys for k in ("wins", "win", "w")) and any(
        k in keys for k in ("losses", "loss", "l")
    )
    heeft_team = any("team" in k or "slug" in k or "club" in k for k in keys)
    return heeft_wl and heeft_team


def find_standings_lists(obj, depth=0, max_depth=10, gevonden=None):
    if gevonden is None:
        gevonden = []
    if depth > max_depth:
        return gevonden
    if isinstance(obj, list):
        if _looks_like_standings_rows(obj):
            gevonden.append(obj)
        for item in obj:
            find_standings_lists(item, depth + 1, max_depth, gevonden)
    elif isinstance(obj, dict):
        for v in obj.values():
            find_standings_lists(v, depth + 1, max_depth, gevonden)
    return gevonden


def _get(rij, *sleutels, default="-"):
    laag = {k.lower(): v for k, v in rij.items()}
    for s in sleutels:
        if s in laag and laag[s] not in (None, ""):
            return laag[s]
    return default


def _slug_uit(rij):
    for veld in ("slug", "teamSlug", "team_slug"):
        for k, v in rij.items():
            if k.lower() == veld.lower() and isinstance(v, str):
                return v.strip("/").split("/")[-1]
    team = rij.get("team")
    if isinstance(team, dict):
        for veld in ("slug", "id"):
            if isinstance(team.get(veld), str):
                return team[veld].strip("/").split("/")[-1]
    return None


def parse_standen_uit_next_data(data):
    kandidaten = find_standings_lists(data)
    if not kandidaten:
        print("  ❌ Geen standen-achtige lijst gevonden in __NEXT_DATA__.", flush=True)
        return {}
    kandidaten.sort(key=len, reverse=True)
    for i, kandidaat in enumerate(kandidaten[:5]):
        voorbeeld_keys = list(kandidaat[0].keys()) if kandidaat else []
        print(f"  Kandidaat {i}: {len(kandidaat)} rijen, keys: {voorbeeld_keys}", flush=True)
    rijen_bron = kandidaten[0]
    print(f"  → gebruik kandidaat met {len(rijen_bron)} rijen", flush=True)

    fase_rijen = []
    for i, rij in enumerate(rijen_bron, start=1):
        slug = _slug_uit(rij)
        if slug and slug in SLUG_TEAM_NAMES:
            team_naam = SLUG_TEAM_NAMES[slug]
        else:
            team = rij.get("team")
            if isinstance(team, dict):
                team_naam = team.get("name") or team.get("naam") or ""
            else:
                team_naam = str(_get(rij, "team", "teamname", "name", default=""))
        gb_raw = str(_get(rij, "gb", "games_behind", "gamesbehind", default="0"))
        fase_rijen.append({
            "positie": str(_get(rij, "position", "rank", "pos", default=str(i))),
            "team":    team_naam,
            "logo":    logo(team_naam),
            "w":       str(_get(rij, "wins", "win", "w")),
            "l":       str(_get(rij, "losses", "loss", "l")),
            "t":       str(_get(rij, "ties", "draws", "t", default="-")),
            "pct":     str(_get(rij, "pct", "win_pct", "percentage", "winpercentage")),
            "gb":      gb_raw,
            "streak":  str(_get(rij, "streak", "last5", "last_five", default="-")),
        })
    return {"Standen": fase_rijen} if fase_rijen else {}


# ---------------------------------------------------------------------------
# Strategie B: HTML-fallback via de /rosters/<slug>-links per rij
# ---------------------------------------------------------------------------
ROW_RE = re.compile(r'<a\s[^>]*href="(/rosters/[^"?#]+)"[^>]*>(.*?)</a>', re.DOTALL)
GB_OF_LEADER_RE = re.compile(r'(Leader|[+-]?\d+(?:\.\d+)?\s*GB)', re.IGNORECASE)
ROW_TAIL_RE = re.compile(r'(\d+)\s+(\d+)\s+(\d*\.\d+)\s*([WLT]{1,10})?\s*$')


def _tekst_zonder_tags(html_fragment: str) -> str:
    tekst = re.sub(r'<[^>]+>', ' ', html_fragment)
    tekst = tekst.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&#039;', "'").replace('&quot;', '"')
    return re.sub(r'\s+', ' ', tekst).strip()


def parse_standen_uit_tabellen(html):
    fase_rijen = []
    for match in ROW_RE.finditer(html):
        href, inner_html = match.group(1), match.group(2)
        slug = href.strip("/").split("/")[-1]
        tekst = _tekst_zonder_tags(inner_html)
        if not tekst:
            continue

        pos_match = re.match(r'^(\d+)\s*(.*)$', tekst)
        if not pos_match:
            continue
        positie, rest = pos_match.group(1), pos_match.group(2)

        gb_match = GB_OF_LEADER_RE.search(rest)
        if not gb_match:
            continue
        naam_blob = rest[:gb_match.start()].strip()
        staart = rest[gb_match.end():].strip()

        staart_match = ROW_TAIL_RE.search(staart)
        if not staart_match:
            continue
        w, l, pct, streak = staart_match.groups()

        team_naam = SLUG_TEAM_NAMES.get(slug)
        if not team_naam:
            # Teamnaam staat dubbel in de tekst (responsive layout) —
            # probeer de herhaling eruit te halen, anders de ruwe blob.
            genormaliseerd = ' '.join(naam_blob.split())
            n = len(genormaliseerd)
            if n % 2 == 0 and genormaliseerd[:n // 2] == genormaliseerd[n // 2:]:
                team_naam = genormaliseerd[:n // 2]
            elif n % 2 == 1 and ' ' in genormaliseerd and genormaliseerd[:n // 2] == genormaliseerd[n // 2 + 1:]:
                team_naam = genormaliseerd[:n // 2]
            else:
                team_naam = genormaliseerd or slug.title()

        gb_marker = gb_match.group(1)
        gb_waarde = "0" if gb_marker.lower() == "leader" else re.sub(r'[^0-9.]', '', gb_marker)

        fase_rijen.append({
            "positie": positie,
            "team":    team_naam,
            "logo":    logo(team_naam),
            "w":       w,
            "l":       l,
            "t":       "-",
            "pct":     pct,
            "gb":      gb_waarde,
            "streak":  streak or "-",
        })
    return {"Standen": fase_rijen} if fase_rijen else {}


def parse_standings(html):
    data = extract_next_data(html)
    if data is not None:
        standen = parse_standen_uit_next_data(data)
        if standen:
            return standen
        print("  ⚠ __NEXT_DATA__ gevonden maar geen bruikbare standen — probeer HTML-fallback.", flush=True)
    else:
        print("  ⚠ Geen __NEXT_DATA__ gevonden — probeer HTML-fallback.", flush=True)
    return parse_standen_uit_tabellen(html)


def print_diagnose(html):
    """
    Print wat context zodat een mislukte run in de Actions-log te
    analyseren is, zonder dat we de volledige (grote) pagina hoeven te
    dumpen. Helpt om de parser gericht bij te stellen i.p.v. te gokken.
    """
    print(f"  [diagnose] lengte HTML: {len(html)} bytes", flush=True)
    print(f"  [diagnose] bevat '__NEXT_DATA__': {'__NEXT_DATA__' in html}", flush=True)
    print(f"  [diagnose] bevat '__next_f.push' (RSC-streaming): {'__next_f.push' in html}", flush=True)
    print(f"  [diagnose] aantal keer '/rosters/' in HTML: {html.count('/rosters/')}", flush=True)
    idx = html.find("Neptunus")
    if idx == -1:
        idx = html.find("neptunus")
    if idx != -1:
        fragment = html[max(0, idx - 400):idx + 400]
        print("  [diagnose] fragment rond 'Neptunus':", flush=True)
        print(fragment, flush=True)
    else:
        print("  [diagnose] 'Neptunus' komt niet voor in de HTML — data is vermoedelijk (nog) niet gerenderd.", flush=True)


def main():
    print(f"Ophalen van {URL}...")
    html = fetch_html()
    print(f"Ontvangen: {len(html)} bytes")
    standen = parse_standings(html)

    if not standen or not any(standen.values()):
        # De pagina kan (deels) client-side gerenderd zijn, waardoor een
        # kale requests.get() een lege/onvolledige DOM oplevert. Val in dat
        # geval terug op Playwright, dat JavaScript wél uitvoert.
        print("  ⚠ Geen standen in de requests-HTML — probeer Playwright (met JS-rendering)…", flush=True)
        try:
            html = haal_via_playwright()
            print(f"  Ontvangen via Playwright: {len(html)} bytes", flush=True)
            standen = parse_standings(html)
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ Playwright-fallback mislukte: {e}", file=sys.stderr)

    print(f"Gevonden fases: {list(standen.keys())}")
    for fase, rijen in standen.items():
        print(f"  {fase}: {len(rijen)} teams")
    if not standen or not any(standen.values()):
        print_diagnose(html)
        print("❌ Geen standen gevonden — bestaande standen.json wordt NIET overschreven.", file=sys.stderr)
        sys.exit(1)
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

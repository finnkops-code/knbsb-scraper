import json
import re
import urllib.request
from datetime import datetime, timezone

RESULTS_URL = "https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/schedule-and-results"

# ── Logo URLs ─────────────────────────────────────────────────────────────────
# Vervang de lege strings door de media URL's uit je WordPress bibliotheek

TEAM_LOGOS = {
    "Curaçao Neptunus":                              "",
    "HCAW":                                          "",
    "Amsterdam Pirates":                             "",
    "Kinheim":                                       "",
    "Oosterhout Twins":                              "",
    "Worldwide Pharma Logistics Hoofddorp Pioniers": "",
    "UVV":                                           "",
}

def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "nl-NL,nl;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")

def clean(text):
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^[A-Z]{2,4}\s+', '', text)
    return text.strip()

def strip_tags(html):
    return re.sub(r'<[^>]+>', '', html).strip()

def logo(team_naam):
    if team_naam in TEAM_LOGOS:
        return TEAM_LOGOS[team_naam]
    for naam, url in TEAM_LOGOS.items():
        if naam.lower() in team_naam.lower() or team_naam.lower() in naam.lower():
            return url
    return ""

def parse_results(html):
    results = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)

    for row in rows:
        tds_raw = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        tds = [re.sub(r'\s+', ' ', strip_tags(td)).strip() for td in tds_raw]
        tds = [t for t in tds if t]

        if len(tds) < 4:
            continue

        score_idx = -1
        for j, td in enumerate(tds):
            if re.match(r'^\d+\s*[-–]\s*\d+$', td):
                score_idx = j
                break

        if score_idx == -1 or score_idx < 2:
            continue

        datum_raw = tds[0]
        thuis = clean(tds[score_idx - 1])
        uit   = clean(tds[score_idx + 1]) if score_idx + 1 < len(tds) else ''

        if not thuis or not uit:
            continue

        score_parts = re.split(r'\s*[-–]\s*', tds[score_idx])
        score_thuis = score_parts[0].strip() if len(score_parts) > 0 else '-'
        score_uit   = score_parts[1].strip() if len(score_parts) > 1 else '-'

        winnaar = None
        if score_thuis.isdigit() and score_uit.isdigit():
            if int(score_thuis) > int(score_uit):
                winnaar = 'thuis'
            elif int(score_uit) > int(score_thuis):
                winnaar = 'uit'
            else:
                winnaar = 'gelijk'

        results.append({
            "datum":       datum_raw,
            "thuis":       thuis,
            "thuis_logo":  logo(thuis),
            "score_thuis": score_thuis,
            "score_uit":   score_uit,
            "uit":         uit,
            "uit_logo":    logo(uit),
            "winnaar":     winnaar,
        })

    results.reverse()
    return results[:20]

def main():
    print(f"Uitslagen ophalen van {RESULTS_URL}...")
    html = fetch_html(RESULTS_URL)
    print(f"Ontvangen: {len(html)} bytes")

    uitslagen = parse_results(html)
    print(f"Wedstrijden gevonden: {len(uitslagen)}")

    for u in uitslagen[:5]:
        print(f"  {u['datum']} | {u['thuis']} {u['score_thuis']}-{u['score_uit']} {u['uit']}")

    with open("uitslagen.json", "w", encoding="utf-8") as f:
        json.dump({
            "bijgewerkt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bron":       RESULTS_URL,
            "uitslagen":  uitslagen,
        }, f, ensure_ascii=False, indent=2)

    print("✅ uitslagen.json opgeslagen")

if __name__ == "__main__":
    main()

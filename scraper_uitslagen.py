import json
import re
import urllib.request
from datetime import datetime, timezone

RESULTS_URL = "https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/schedule-and-results"

TEAM_LOGOS = {
    "Curaçao Neptunus":                              "https://worldbaseballnews.org/wp-content/uploads/2025/11/neptunus.png",
    "HCAW":                                          "https://worldbaseballnews.org/wp-content/uploads/2025/11/hcaw.png",
    "Amsterdam Pirates":                             "https://worldbaseballnews.org/wp-content/uploads/2025/11/amsterdam-pirates.png",
    "Kinheim":                                       "https://worldbaseballnews.org/wp-content/uploads/2025/11/kinheim.png",
    "Oosterhout Twins":                              "https://worldbaseballnews.org/wp-content/uploads/2025/11/twins-1.png",
    "Worldwide Pharma Logistics Hoofddorp Pioniers": "https://worldbaseballnews.org/wp-content/uploads/2025/11/pioniers.png",
    "UVV":                                           "https://worldbaseballnews.org/wp-content/uploads/2025/11/uvv.png",
}

def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "nl-NL,nl;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "X-Inertia": "true",
        "X-Requested-With": "XMLHttpRequest",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")

def logo(team_naam):
    if team_naam in TEAM_LOGOS:
        return TEAM_LOGOS[team_naam]
    for naam, url in TEAM_LOGOS.items():
        if naam.lower() in team_naam.lower() or team_naam.lower() in naam.lower():
            return url
    return ""

def parse_results(data):
    results = []

    # Inertia geeft JSON terug met props
    rounds = data.get('props', {}).get('rounds', [])
    if not rounds:
        # Probeer andere structuur
        rounds = data.get('rounds', [])
    if not rounds:
        games = data.get('props', {}).get('games', [])
        rounds = [{'games': games}] if games else []

    for ronde in rounds:
        games = ronde.get('games', [])
        for game in games:
            # Sla geplande wedstrijden over
            score_thuis = game.get('score_home') or game.get('run_home') or game.get('home_score')
            score_uit   = game.get('score_away') or game.get('run_away') or game.get('away_score')

            if score_thuis is None or score_uit is None:
                continue

            thuis = game.get('home_team', {}).get('name', '') or game.get('team_home', '')
            uit   = game.get('away_team', {}).get('name', '') or game.get('team_away', '')

            results.append({
                "datum":       game.get('date', '') or game.get('game_date', ''),
                "thuis":       thuis,
                "thuis_logo":  logo(thuis),
                "score_thuis": str(score_thuis),
                "score_uit":   str(score_uit),
                "uit":         uit,
                "uit_logo":    logo(uit),
                "winnaar":     'thuis' if int(score_thuis) > int(score_uit) else 'uit' if int(score_uit) > int(score_thuis) else 'gelijk',
            })

    results.reverse()
    return results[:20]

def main():
    print(f"Uitslagen ophalen van {RESULTS_URL}...")
    raw = fetch_html(RESULTS_URL)
    print(f"Ontvangen: {len(raw)} bytes")

    # Probeer Inertia JSON te parsen
    data = json.loads(raw)
    print(f"Inertia data geladen, keys: {list(data.keys())}")

    uitslagen = parse_results(data)
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

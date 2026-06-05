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

def extract_inertia_data(html):
    # Inertia stopt alle data in data-page attribuut van de app div
    match = re.search(r'<div[^>]+id=["\']app["\'][^>]+data-page=["\']([^"\']+)["\']', html)
    if not match:
        # Probeer alternatief patroon
        match = re.search(r'data-page="([^"]+)"', html)
    if not match:
        match = re.search(r"data-page='([^']+)'", html)
    if not match:
        print("❌ Geen Inertia data gevonden in HTML")
        print("HTML snippet:", html[:500])
        return None
    raw = match.group(1)
    # HTML entities decoderen
    raw = raw.replace('&quot;', '"').replace('&#039;', "'").replace('&amp;', '&')
    return json.loads(raw)

def parse_results(data):
    results = []

    props = data.get('props', {})
    print(f"Props keys: {list(props.keys())}")

    # Zoek naar rounds of games in props
    rounds = props.get('rounds', props.get('schedule', props.get('games', [])))

    if isinstance(rounds, dict):
        rounds = list(rounds.values())

    if not rounds:
        print("❌ Geen rounds/games gevonden in props")
        return results

    for ronde in rounds:
        if isinstance(ronde, dict):
            games = ronde.get('games', [ronde] if ronde.get('home_team') else [])
        else:
            games = []

        for game in games:
            score_thuis = game.get('score_home') or game.get('run_home') or game.get('home_score') or game.get('home_runs')
            score_uit   = game.get('score_away') or game.get('run_away') or game.get('away_score') or game.get('away_runs')

            if score_thuis is None or score_uit is None:
                continue

            thuis = ''
            uit   = ''
            home  = game.get('home_team', {})
            away  = game.get('away_team', {})
            if isinstance(home, dict):
                thuis = home.get('name', home.get('short_name', ''))
            else:
                thuis = str(home)
            if isinstance(away, dict):
                uit = away.get('name', away.get('short_name', ''))
            else:
                uit = str(away)

            try:
                winnaar = 'thuis' if int(score_thuis) > int(score_uit) else 'uit' if int(score_uit) > int(score_thuis) else 'gelijk'
            except:
                winnaar = None

            results.append({
                "datum":       game.get('date', game.get('game_date', game.get('scheduled', ''))),
                "thuis":       thuis,
                "thuis_logo":  logo(thuis),
                "score_thuis": str(score_thuis),
                "score_uit":   str(score_uit),
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

    data = extract_inertia_data(html)
    if not data:
        print("❌ Kon geen data extraheren")
        return

    print(f"Data keys: {list(data.keys())}")
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

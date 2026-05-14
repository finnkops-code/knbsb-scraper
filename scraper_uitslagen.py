from playwright.sync_api import sync_playwright
import json, re
from datetime import datetime

URL = "https://stats.knbsbstats.nl/en/events/2026-lucky-day-hoofdklasse/schedule-and-results"

def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=30000)

        # Wacht tot wedstrijden geladen zijn
        page.wait_for_selector(".game, .match, [class*='game'], [class*='result']", timeout=15000)

        wedstrijden = []

        # Blokken per speeldag
        dagen = page.query_selector_all("[class*='round'], [class*='day'], [class*='group']")

        for dag in dagen:
            games = dag.query_selector_all("[class*='game'], [class*='match']")
            for game in games:
                try:
                    # Teamnamen
                    teams = game.query_selector_all("[class*='team-name'], [class*='teamname']")
                    thuis = teams[0].inner_text().strip() if len(teams) > 0 else ""
                    uit   = teams[1].inner_text().strip() if len(teams) > 1 else ""

                    # Score
                    scores = game.query_selector_all("[class*='score'], [class*='run']")
                    score_thuis = scores[0].inner_text().strip() if len(scores) > 0 else "-"
                    score_uit   = scores[1].inner_text().strip() if len(scores) > 1 else "-"

                    # Innings
                    innings_el = game.query_selector("[class*='inning'], [class*='period']")
                    innings = innings_el.inner_text().strip() if innings_el else ""

                    # Status (gespeeld / gepland)
                    status_el = game.query_selector("[class*='status']")
                    status = status_el.inner_text().strip() if status_el else "unknown"

                    wedstrijden.append({
                        "thuis": thuis,
                        "uit": uit,
                        "score_thuis": score_thuis,
                        "score_uit": score_uit,
                        "innings": innings,
                        "status": status,
                        "bijgewerkt": datetime.utcnow().isoformat()
                    })
                except Exception as e:
                    print(f"Fout bij wedstrijd: {e}")

        browser.close()
        return wedstrijden

data = scrape()
with open("resultaten.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"{len(data)} wedstrijden opgeslagen.")

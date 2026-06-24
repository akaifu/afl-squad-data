#!/usr/bin/env python3
"""
Convert a Wheelo Ratings AFL Team Lists CSV export into ages.json.

Why this exists: Wheelo Ratings (wheeloratings.com/afl_team_lists.html) is
a JS-rendered dashboard - a plain scraper can't read its table directly.
But it has a "Download as CSV" button that works fine when a real person
clicks it in a browser. This script takes that downloaded CSV and converts
it into the same ages.json format the AFL list tool already expects from
the AFL Tables scraper - so you can swap between them, or just re-run this
whenever you grab a fresh CSV.

Unlike the AFL Tables version, this source includes EVERY listed player,
including ones who haven't debuted yet in the current season - which is
the whole reason to use it. Age is "as at 31 December" of the given year,
per Wheelo Ratings' own page note.

Usage:
    python3 convert_wheelo_csv.py afl-team-lists.csv

Produces ages.json in the current directory.
"""
import csv
import json
import sys
import time

# Wheelo Ratings' team names -> our internal club ids (must match the ids
# used in squads.json / contracts.json for the merge in the tool to work).
CLUB_NAME_MAP = {
    "Adelaide": "adelaide",
    "Brisbane": "brisbane",
    "Carlton": "carlton",
    "Collingwood": "collingwood",
    "Essendon": "essendon",
    "Fremantle": "fremantle",
    "Geelong": "geelong",
    "Gold Coast": "goldcoast",
    "Greater Western Sydney": "gws",
    "Hawthorn": "hawthorn",
    "Melbourne": "melbourne",
    "North Melbourne": "northmelbourne",
    "Port Adelaide": "portadelaide",
    "Richmond": "richmond",
    "St Kilda": "stkilda",
    "Sydney": "sydney",
    "West Coast": "westcoast",
    "Western Bulldogs": "westernbulldogs",
}


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 convert_wheelo_csv.py <csv_file>", file=sys.stderr)
        sys.exit(1)

    csv_path = sys.argv[1]
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print("ERROR: CSV appears empty", file=sys.stderr)
        sys.exit(1)

    required_cols = {"Player", "Team", "Age"}
    missing_cols = required_cols - set(rows[0].keys())
    if missing_cols:
        print(f"ERROR: CSV is missing expected columns: {missing_cols}",
              file=sys.stderr)
        print(f"Found columns: {list(rows[0].keys())}", file=sys.stderr)
        sys.exit(1)

    clubs = {}
    unmapped_teams = set()
    skipped_no_age = 0

    for r in rows:
        team = r["Team"].strip()
        club_id = CLUB_NAME_MAP.get(team)
        if not club_id:
            unmapped_teams.add(team)
            continue
        clubs.setdefault(club_id, [])
        age_raw = r["Age"].strip() if r["Age"] else ""
        if not age_raw:
            skipped_no_age += 1
            age = None
        else:
            try:
                age = int(float(age_raw))
            except ValueError:
                age = None
        clubs[club_id].append({
            "name": r["Player"].strip(),
            "age": age,
        })

    if unmapped_teams:
        print(f"WARNING: these team names in the CSV didn't match any "
              f"known club - check CLUB_NAME_MAP if these are real clubs: "
              f"{unmapped_teams}", file=sys.stderr)

    all_ages = [p["age"] for c in clubs.values() for p in c if p["age"] is not None]
    league_avg = round(sum(all_ages) / len(all_ages), 2) if all_ages else None

    output = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "wheeloratings.com/afl_team_lists.html (manually exported CSV)",
        "note": (
            "Unlike an AFL-Tables-derived version, this includes ALL listed "
            "players, including those who have not yet debuted this season - "
            "age is calculated as at 31 December of the season per the "
            "source page's own note."
        ),
        "leagueAverageAge": league_avg,
        "clubs": clubs,
    }

    with open("ages.json", "w") as f:
        json.dump(output, f, indent=2)

    total = sum(len(v) for v in clubs.values())
    print(f"Done. Wrote ages.json - {len(clubs)} clubs, {total} players, "
          f"league average age {league_avg}.", file=sys.stderr)
    if skipped_no_age:
        print(f"NOTE: {skipped_no_age} rows had no age value.", file=sys.stderr)


if __name__ == "__main__":
    main()

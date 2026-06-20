#!/usr/bin/env python3
"""
AFL Squad Scraper
------------------
Fetches the live AFL squad list (player name, guernsey number, position,
profile URL) for all 18 clubs directly from each club's official website,
and writes the result to squads.json.

This is designed to run on a schedule via GitHub Actions, so the JSON file
in the repo is always a fresh snapshot of who is actually on each club's list.

NOTE: This script deliberately does NOT scrape contracts or salaries -
that data isn't published on club sites. It only solves "who is currently
on the list", which is the part that needs to stay live. Contract/salary
data should still be maintained separately (see contracts.json).
"""
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; AFLListTool/1.0; +https://github.com/)"

# Each club's official squad page. These were verified by hand against the
# live site structure. If a club redesigns their site, only this URL needs
# updating - the parser itself looks for a generic pattern.
CLUBS = [
    {"id": "adelaide",         "name": "Adelaide",         "short": "ADEL", "color": "#1560BD", "url": "https://www.afc.com.au/teams/afl"},
    {"id": "brisbane",         "name": "Brisbane Lions",   "short": "BRIS", "color": "#A30046", "url": "https://www.lions.com.au/teams/afl"},
    {"id": "carlton",          "name": "Carlton",          "short": "CARL", "color": "#0E3B6E", "url": "https://www.carltonfc.com.au/teams/afl"},
    {"id": "collingwood",      "name": "Collingwood",      "short": "COLL", "color": "#999999", "url": "https://www.collingwoodfc.com.au/teams/afl"},
    {"id": "essendon",         "name": "Essendon",         "short": "ESS",  "color": "#CC0000", "url": "https://www.essendonfc.com.au/teams/afl"},
    {"id": "fremantle",        "name": "Fremantle",        "short": "FRE",  "color": "#6B2D8B", "url": "https://www.fremantlefc.com.au/teams/afl"},
    {"id": "geelong",          "name": "Geelong",          "short": "GEE",  "color": "#1C3C6E", "url": "https://www.geelongcats.com.au/teams/afl"},
    {"id": "goldcoast",        "name": "Gold Coast",       "short": "GCS",  "color": "#E8252B", "url": "https://www.goldcoastfc.com.au/teams/afl"},
    {"id": "gws",              "name": "GWS Giants",       "short": "GWS",  "color": "#F47920", "url": "https://www.gwsgiants.com.au/teams/afl"},
    {"id": "hawthorn",         "name": "Hawthorn",         "short": "HAW",  "color": "#623000", "url": "https://www.hawthornfc.com.au/teams/afl"},
    {"id": "melbourne",        "name": "Melbourne",        "short": "MEL",  "color": "#CC2031", "url": "https://www.melbournefc.com.au/teams/afl"},
    {"id": "northmelbourne",   "name": "North Melbourne",  "short": "NM",   "color": "#003087", "url": "https://www.nmfc.com.au/teams/afl"},
    {"id": "portadelaide",     "name": "Port Adelaide",    "short": "PORT", "color": "#008AAB", "url": "https://www.portadelaidefc.com.au/teams/afl"},
    {"id": "richmond",         "name": "Richmond",         "short": "RICH", "color": "#D4A800", "url": "https://www.richmondfc.com.au/football/afl/squad"},
    {"id": "stkilda",          "name": "St Kilda",         "short": "STK",  "color": "#ED0F05", "url": "https://www.saints.com.au/teams/afl"},
    {"id": "sydney",           "name": "Sydney",           "short": "SYD",  "color": "#E2001A", "url": "https://www.sydneyswans.com.au/teams/afl"},
    {"id": "westcoast",        "name": "West Coast",       "short": "WCE",  "color": "#003087", "url": "https://www.westcoasteagles.com.au/teams/afl"},
    {"id": "westernbulldogs",  "name": "W. Bulldogs",      "short": "WB",   "color": "#014896", "url": "https://www.westernbulldogs.com.au/teams/afl"},
]

# Matches lines like:
#   01 *Nick Vlastuin Defender*  ->  /players/443/nick-vlastuin
# The AFL club site template renders each player as a link to /players/{id}/{slug}
# with the visible text "{num} {Name} {Position}". We parse that text pattern
# directly out of the rendered markdown/text rather than raw HTML tags, since
# club sites occasionally tweak markup but the text content stays consistent.
PLAYER_LINE_RE = re.compile(
    r'(?<![\d])(\d{1,2})\s+\*?'
    r'([A-Z][A-Za-z\'\.\-]+(?:\s+[A-Z][A-Za-z\'\.\-]+)+?)\s*\*?\s+'
    r'(Key Forward|Key Defender|Defender|Forward|Midfielder|Ruck)\*?'
    r'(?:\s*\(https?://[^\s)]+/players/(\d+)/[^\s)]+\))?'
)

POSITION_MAP = {
    "Defender": "DEF",
    "Forward": "FWD",
    "Key Forward": "FWD",
    "Key Defender": "DEF",
    "Midfielder": "MID",
    "Ruck": "RUC",
}


def fetch_url(url, retries=3, timeout=20):
    """Fetch a URL's raw text content with basic retry handling."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts: {last_err}")


class TextExtractor(HTMLParser):
    """Strips HTML tags but keeps href targets inline next to link text,
    so we can regex over the result like 'Name Position (url)'."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self.current_href = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and "/players/" in href:
                self.current_href = href

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href:
            self.parts.append(f"({self.current_href})")
            self.current_href = None

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)

    def get_text(self):
        return " ".join(self.parts)


def parse_squad_html(html, club_id):
    """Extract player entries from a club squad page's HTML."""
    extractor = TextExtractor()
    extractor.feed(html)
    text = extractor.get_text()

    players = []
    seen_ids = set()
    for m in PLAYER_LINE_RE.finditer(text):
        num, name, position_raw, pid = m.groups()
        name = re.sub(r'\s+', ' ', name).strip()
        if pid and pid in seen_ids:
            continue
        if pid:
            seen_ids.add(pid)
        players.append({
            "num": int(num),
            "name": name,
            "pos": POSITION_MAP.get(position_raw, "MID"),
            "playerId": pid,
            "profileUrl": f"https://www.afl.com.au/players/{pid}" if pid else None,
        })
    return players


def scrape_club(club):
    print(f"  Fetching {club['name']} ({club['url']}) ...", file=sys.stderr)
    html = fetch_url(club["url"])
    players = parse_squad_html(html, club["id"])
    print(f"    -> found {len(players)} players", file=sys.stderr)
    return players


def main():
    result = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "clubs": {},
    }
    failures = []

    for club in CLUBS:
        try:
            players = scrape_club(club)
            if len(players) < 30:
                # Sanity check - AFL clubs carry ~38-45 listed players.
                # Fewer than 30 strongly suggests the page structure didn't
                # match (e.g. site redesign) rather than a real short list.
                print(f"    WARNING: only {len(players)} players found for "
                      f"{club['name']} - URL or parser may need updating",
                      file=sys.stderr)
                failures.append(club["id"])
            result["clubs"][club["id"]] = {
                "name": club["name"],
                "short": club["short"],
                "color": club["color"],
                "sourceUrl": club["url"],
                "players": players,
            }
        except Exception as e:
            print(f"    ERROR scraping {club['name']}: {e}", file=sys.stderr)
            failures.append(club["id"])
            result["clubs"][club["id"]] = {
                "name": club["name"],
                "short": club["short"],
                "color": club["color"],
                "sourceUrl": club["url"],
                "players": [],
                "error": str(e),
            }
        time.sleep(1)  # be polite between requests

    with open("squads.json", "w") as f:
        json.dump(result, f, indent=2)

    total_players = sum(len(c["players"]) for c in result["clubs"].values())
    print(f"\nDone. Wrote squads.json - {len(result['clubs'])} clubs, "
          f"{total_players} total players.", file=sys.stderr)
    if failures:
        print(f"Clubs needing attention: {', '.join(failures)}", file=sys.stderr)
        print("Check squads.json's 'error' field for those clubs, and verify "
              "the 'url' in CLUBS still points at a live squad page.",
              file=sys.stderr)
        # Exit non-zero so GitHub Actions flags the run, but the JSON file
        # still gets written and committed with whatever data we did get -
        # partial data beats no data.
        sys.exit(1)


if __name__ == "__main__":
    main()

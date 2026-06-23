#!/usr/bin/env python3
"""
AFL Player Age Scraper
------------------------
Player date-of-birth isn't published on club sites or footywire's
out-of-contract page, but AFL Tables has it on every player's individual
stats page (e.g. afltables.com/afl/stats/players/J/Jordan_Dawson.html ->
"Born: 9-Apr-1997"), confirmed against real AFL Tables pages.

This runs in two steps:
  1. Fetch each club's 2026 "game by game" page
     (afltables.com/afl/stats/teams/{team}/2026_gbg.html), which lists
     every player who has played for that club this season, each linking
     to their individual stats page.
  2. Visit each linked player page and pull their "Born:" date.

This is a MUCH bigger scrape than the squad/contract ones (potentially
600-700+ individual page fetches across the league), so it caches results
in ages_cache.json across runs - a player's birthdate never changes, so
once we have it we never need to re-fetch that specific player again.
Only new names (not yet in the cache) get fetched on each run.

NOTE: AFL Tables only lists players who have actually played a senior
game in 2026. Cat B players, new draftees yet to debut, and some rookies
won't appear here and so won't have an age - that's an inherent limitation
of this data source, not a bug.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import date
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; AFLListTool/1.0; +https://github.com/)"
BASE = "https://afltables.com"
CACHE_FILE = "ages_cache.json"

# AFL Tables' own team-folder slugs, paired with our internal club ids.
# Some of these are confirmed against live pages (adelaide, padelaide,
# bullldogs, gws, kangaroos, lions, wcoast pattern); others are
# best-guesses following AFL Tables' naming conventions. verify_slugs()
# below checks every one of these against the real site on each run and
# logs a clear warning for any that don't resolve, rather than failing
# silently or assuming a guess is correct.
TEAM_SLUGS = {
    "adelaide": "adelaide",
    "brisbane": "brisbanel",
    "carlton": "carlton",
    "collingwood": "collingwood",
    "essendon": "essendon",
    "fremantle": "fremantle",
    "geelong": "geelong",
    "goldcoast": "goldcoast",
    "gws": "gws",
    "hawthorn": "hawthorn",
    "melbourne": "melbourne",
    "northmelbourne": "kangaroos",
    "portadelaide": "padelaide",
    "richmond": "richmond",
    "stkilda": "stkilda",
    "sydney": "swans",
    "westcoast": "westcoast",
    "westernbulldogs": "bullldogs",
}

# If a slug above turns out wrong, try these alternates in order before
# giving up on that club for this run. Keeps one wrong guess from blocking
# the whole scrape, and surfaces in the log exactly which slug worked so
# you (or I) can update TEAM_SLUGS permanently afterwards.
SLUG_FALLBACKS = {
    "brisbane": ["brisbanel", "lions", "brisbane"],
    "goldcoast": ["goldcoast", "gcoast", "suns"],
    "westcoast": ["westcoast", "wcoast", "eagles"],
    "gws": ["gws", "gwsydney", "gwsyd"],
    "westernbulldogs": ["bullldogs", "bulldogs", "footscray"],
}


def find_working_slug(club_id, default_slug):
    """Try the default slug first, then fallbacks, returning the first
    that actually resolves to a real 2026 game-by-game page."""
    candidates = SLUG_FALLBACKS.get(club_id, [default_slug])
    if default_slug not in candidates:
        candidates = [default_slug] + candidates
    for slug in candidates:
        url = f"{BASE}/afl/stats/teams/{slug}/2026_gbg.html"
        try:
            html = fetch_url(url, retries=1, timeout=10)
            if "Game by Game" in html or "/players/" in html:
                if slug != default_slug:
                    print(f"    NOTE: {club_id} slug '{default_slug}' didn't "
                          f"work, but '{slug}' did - update TEAM_SLUGS",
                          file=sys.stderr)
                return slug
        except Exception:
            continue
    print(f"    WARNING: no working AFL Tables slug found for {club_id} "
          f"(tried {candidates})", file=sys.stderr)
    return None

MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

BORN_RE = re.compile(r'Born\s*:\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})')


def fetch_url(url, retries=3, timeout=20):
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


class RosterLinkExtractor(HTMLParser):
    """Pulls (player_name, player_page_url) pairs from a game-by-game page -
    every player link points at /afl/stats/players/{Initial}/{Name}.html."""
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.players = []
        self._current_href = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and "/players/" in href and href.endswith(".html"):
                self._current_href = href
                self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current_href:
            name = "".join(self._current_text).strip()
            if name:
                full_url = urllib.parse.urljoin(self.base_url, self._current_href)
                self.players.append((name, full_url))
            self._current_href = None


def calc_age(birth_year, birth_month, birth_day):
    today = date.today()
    age = today.year - birth_year - (
        (today.month, today.day) < (birth_month, birth_day)
    )
    return age


def strip_tags(html):
    """Quick tag-stripping for a single regex search - good enough here
    since we're not parsing structure, just hunting for one date pattern
    in body text. Collapses all tags to a single space so 'Born:</b> 9-Apr'
    style markup still reads as 'Born: 9-Apr' once stripped."""
    return re.sub(r'<[^>]+>', ' ', html)


def fetch_birthdate(player_url):
    html = fetch_url(player_url)
    text = strip_tags(html)
    m = BORN_RE.search(text)
    if not m:
        # Log enough context to actually diagnose this from the Actions log,
        # rather than silently returning None for every player with no clue
        # why. Print a short snippet of the STRIPPED text (not raw HTML) so
        # we can actually read what's around where "Born" should be.
        born_idx = text.find('Born')
        if born_idx >= 0:
            snippet = re.sub(r'\s+', ' ', text[born_idx:born_idx+100])
        else:
            snippet = '(no "Born" text found anywhere on the page - ' + \
                       re.sub(r'\s+', ' ', text)[:150] + ')'
        print(f"    DEBUG: no Born: match for {player_url} - near 'Born': {snippet}",
              file=sys.stderr)
        return None
    day, mon_str, year = m.groups()
    month = MONTHS.get(mon_str)
    if not month:
        print(f"    DEBUG: matched Born: but couldn't parse month '{mon_str}' for {player_url}",
              file=sys.stderr)
        return None
    return {"year": int(year), "month": month, "day": int(day)}


def get_roster_links(club_id, team_slug):
    url = f"{BASE}/afl/stats/teams/{team_slug}/2026_gbg.html"
    print(f"  Fetching roster links for {club_id} ({url}) ...", file=sys.stderr)
    html = fetch_url(url)
    parser = RosterLinkExtractor(url)
    parser.feed(html)
    # de-dupe by url since a player can appear once per round
    seen = {}
    for name, link in parser.players:
        seen[link] = name
    print(f"    -> {len(seen)} unique players found", file=sys.stderr)
    return [(name, link) for link, name in seen.items()]


def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def main():
    cache = load_cache()  # keyed by player_url -> {name, year, month, day}
    result_clubs = {}
    new_fetches = 0
    failures = []

    for club_id, default_slug in TEAM_SLUGS.items():
        team_slug = find_working_slug(club_id, default_slug)
        if not team_slug:
            failures.append(club_id)
            result_clubs[club_id] = []
            continue
        try:
            roster = get_roster_links(club_id, team_slug)
        except Exception as e:
            print(f"    ERROR fetching roster for {club_id}: {e}", file=sys.stderr)
            failures.append(club_id)
            result_clubs[club_id] = []
            continue

        club_players = []
        first_failure_logged = False
        for name, link in roster:
            if link in cache:
                dob = cache[link]
            else:
                try:
                    dob = fetch_birthdate(link)
                    new_fetches += 1
                    time.sleep(0.5)  # be polite - this is a lot of requests
                except Exception as e:
                    if not first_failure_logged:
                        # Full detail on the FIRST failure per club only, so
                        # the log stays readable but we still get a real
                        # diagnosis instead of 35 identical warning lines.
                        print(f"    ERROR fetching DOB for {name} ({link}): "
                              f"{type(e).__name__}: {e}", file=sys.stderr)
                        first_failure_logged = True
                    else:
                        print(f"    WARNING: could not fetch DOB for {name}",
                              file=sys.stderr)
                    dob = None
                if dob:
                    cache[link] = dob

            if dob:
                age = calc_age(dob["year"], dob["month"], dob["day"])
                club_players.append({
                    "name": name,
                    "birthYear": dob["year"],
                    "birthMonth": dob["month"],
                    "birthDay": dob["day"],
                    "age": age,
                })
            else:
                club_players.append({"name": name, "age": None})

        result_clubs[club_id] = club_players
        time.sleep(1)

    # Persist cache for next run - this is the bulk of why this scraper
    # stays fast after the first run.
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

    league_avg = None
    all_ages = [p["age"] for c in result_clubs.values() for p in c if p["age"] is not None]
    if all_ages:
        league_avg = round(sum(all_ages) / len(all_ages), 2)

    output = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Age is calculated from AFL Tables birthdate data. Only players "
            "who have played a senior game in 2026 will appear - new "
            "draftees yet to debut and some Cat B players will be missing "
            "here even though they're on the live squad list."
        ),
        "leagueAverageAge": league_avg,
        "clubs": result_clubs,
    }

    with open("ages.json", "w") as f:
        json.dump(output, f, indent=2)

    total = sum(len(v) for v in result_clubs.values())
    print(f"\nDone. Wrote ages.json - {len(result_clubs)} clubs, {total} players, "
          f"{new_fetches} new DOB lookups this run (rest from cache).",
          file=sys.stderr)
    if failures:
        print(f"Clubs needing attention: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

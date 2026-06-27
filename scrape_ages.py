#!/usr/bin/env python3
"""
AFL Player Age Scraper
------------------------
Player date-of-birth isn't published on club sites or footywire's
out-of-contract page, but AFL Tables has it for every player who's ever
played a senior game, on each club's "All Time Player List" page
(afltables.com/afl/stats/alltime/{team}.html) - one static HTML table per
club, with name, DOB, height, weight and games played for every player in
club history, including the current 2026 list.

This is a much better source than an earlier version of this script used
(each club's year-by-year "game by game" page) - that page turned out to
require JavaScript to render its rows, which meant the old scraper was
silently missing most established players (anyone whose name didn't
happen to appear in some other static fragment of the page), not just
genuinely undebuted ones. The All Time Player List page has no such
problem - confirmed real, static, server-rendered HTML with every name
and DOB directly in the table - and it's ALSO faster, since it's one
request per club instead of one request per player.

Cat B players and brand new draftees who haven't played a senior game yet
still won't appear here - that's a genuine, inherent limitation of any
stats-based source, not a bug. See scrape_draftguru.py for how that gap
gets filled.
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
from scrape_draftguru import get_draftguru_dob_gapfill, normName

USER_AGENT = "Mozilla/5.0 (compatible; AFLListTool/1.0; +https://github.com/)"
BASE = "https://afltables.com"

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
        url = f"{BASE}/afl/stats/alltime/{slug}.html"
        try:
            html = fetch_url(url, retries=1, timeout=10)
            if "All Time Player List" in html or "/players/" in html:
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


class AllTimeListExtractor(HTMLParser):
    """Pulls (player_name, dob_year, dob_month, dob_day) from the All Time
    Player List page's table. Each player row looks like:
      <a href=".../players/J/Josh_Kelly.html">Kelly, Josh</a> ... 1995-02-12 ...
    This page is plain server-rendered HTML (confirmed - no JS warning,
    unlike the year-by-year game-by-game pages), and crucially lists EVERY
    player who's ever played for the club, with DOB right there in the
    row - no need to visit individual player pages at all."""
    def __init__(self):
        super().__init__()
        self.rows = []  # (name, year, month, day)
        self._in_player_link = False
        self._current_text = []
        self._pending_name = None
        self._cells_since_name = []
        self._in_cell = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and "/players/" in href:
                self._in_player_link = True
                self._current_text = []
        elif tag == "td":
            self._in_cell = True
            self._current_text = []

    def handle_data(self, data):
        if self._in_player_link or self._in_cell:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_player_link:
            name = "".join(self._current_text).strip()
            self._pending_name = name if name else None
            self._in_player_link = False
        elif tag == "td":
            cell_text = "".join(self._current_text).strip()
            self._in_cell = False
            if self._pending_name is not None:
                self._cells_since_name.append(cell_text)
                # DOB is the very next cell after the one containing the
                # player link (Cap | # | Player | DOB | ...) - so once
                # we've seen 1 cell past the name, check if it's a date.
                m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', cell_text)
                if m:
                    y, mo, d = m.groups()
                    self.rows.append((self._pending_name, int(y), int(mo), int(d)))
                    self._pending_name = None
                    self._cells_since_name = []
                elif len(self._cells_since_name) > 2:
                    # Gone too far without finding a date - this row's
                    # format didn't match what we expected, abandon it
                    # rather than mis-attribute a DOB to the wrong player.
                    self._pending_name = None
                    self._cells_since_name = []


def reorder_afltables_name(name):
    """AFL Tables renders names as 'Lastname, Firstname' on roster pages.
    Every other part of this pipeline (squads.json from club sites,
    Draft Guru) uses 'Firstname Lastname' - store that consistent form in
    our output so downstream matching (in the browser tool, and within
    this script) doesn't silently fail on a name-order mismatch."""
    name = name.strip()
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[1] + ' ' + parts[0]
    return name


def calc_age(birth_year, birth_month, birth_day):
    today = date.today()
    age = today.year - birth_year - (
        (today.month, today.day) < (birth_month, birth_day)
    )
    return age


def get_alltime_list(club_id, team_slug):
    """Fetch the All Time Player List page for a club - one request gets
    every player who's ever played for them, each with name + DOB right
    in the table. Much more reliable than the old approach (per-player
    page fetches off a JS-rendered roster page that was silently missing
    most current players)."""
    url = f"{BASE}/afl/stats/alltime/{team_slug}.html"
    print(f"  Fetching all-time player list for {club_id} ({url}) ...", file=sys.stderr)
    html = fetch_url(url)
    parser = AllTimeListExtractor()
    parser.feed(html)
    # de-dupe by name (a player can't appear twice in this list, but be safe)
    seen = {}
    for name, y, mo, d in parser.rows:
        seen[name] = (y, mo, d)
    print(f"    -> {len(seen)} players found with DOB", file=sys.stderr)
    return [(name, y, mo, d) for name, (y, mo, d) in seen.items()]


def load_current_squads():
    """Read squads.json (built separately by scrape_squads.py) to get the
    full current list per club - including undebuted players that AFL
    Tables' game-by-game page simply doesn't know about. This is what lets
    us identify exactly who needs a Draft Guru gap-fill, rather than
    guessing or crawling everything."""
    if not os.path.exists("squads.json"):
        print("    WARNING: squads.json not found - run scrape_squads.py first "
              "for the gap-fill step to know who's actually on each list. "
              "Continuing with AFL Tables data only.", file=sys.stderr)
        return {}
    try:
        with open("squads.json") as f:
            data = json.load(f)
        return {
            club_id: [p["name"] for p in club.get("players", [])]
            for club_id, club in data.get("clubs", {}).items()
        }
    except Exception as e:
        print(f"    WARNING: could not read squads.json: {e}", file=sys.stderr)
        return {}


def main():
    result_clubs = {}
    failures = []

    for club_id, default_slug in TEAM_SLUGS.items():
        team_slug = find_working_slug(club_id, default_slug)
        if not team_slug:
            failures.append(club_id)
            result_clubs[club_id] = []
            continue
        try:
            alltime_list = get_alltime_list(club_id, team_slug)
        except Exception as e:
            print(f"    ERROR fetching all-time list for {club_id}: {e}", file=sys.stderr)
            failures.append(club_id)
            result_clubs[club_id] = []
            continue

        club_players = []
        for name, year, month, day in alltime_list:
            display_name = reorder_afltables_name(name)
            age = calc_age(year, month, day)
            club_players.append({
                "name": display_name,
                "birthYear": year,
                "birthMonth": month,
                "birthDay": day,
                "age": age,
            })

        result_clubs[club_id] = club_players
        time.sleep(1)

    # ─── GAP-FILL UNDEBUTED PLAYERS VIA DRAFT GURU ───────────────────────────
    # AFL Tables only knows players who've played a senior game. Cross-check
    # against the actual current squad lists (squads.json, built separately
    # by scrape_squads.py) to find anyone on a real 2026 list who has no
    # age yet, then look ONLY those names up via Draft Guru's draft-order
    # pages - not a full crawl, just the specific gap.
    current_squads = load_current_squads()
    have_age_by_club = {
        club_id: {normName(p["name"]) for p in players if p.get("age") is not None}
        for club_id, players in result_clubs.items()
    }
    missing_names = set()
    name_to_clubs = {}  # normalized name -> list of (club_id, original_name)
    for club_id, names in current_squads.items():
        have = have_age_by_club.get(club_id, set())
        for name in names:
            key = normName(name)
            if key not in have:
                missing_names.add(key)
                name_to_clubs.setdefault(key, []).append((club_id, name))

    if missing_names:
        print(f"\n{len(missing_names)} players on current lists have no AFL "
              f"Tables age - checking Draft Guru for those specifically ...",
              file=sys.stderr)
        try:
            gapfill = get_draftguru_dob_gapfill(missing_names)
        except Exception as e:
            print(f"    WARNING: Draft Guru gap-fill step failed entirely: {e}",
                  file=sys.stderr)
            gapfill = {}

        filled = 0
        for key, dob in gapfill.items():
            age = calc_age(dob["year"], dob["month"], dob["day"])
            for club_id, original_name in name_to_clubs.get(key, []):
                result_clubs.setdefault(club_id, []).append({
                    "name": original_name,
                    "birthYear": dob["year"],
                    "birthMonth": dob["month"],
                    "birthDay": dob["day"],
                    "age": age,
                    "source": "draftguru_gapfill",
                })
                filled += 1

        still_missing_keys = missing_names - set(gapfill.keys())
        still_missing_names = sorted(
            name_to_clubs[key][0][1] for key in still_missing_keys if key in name_to_clubs
        )
        print(f"Gap-filled {filled} player record(s) from Draft Guru "
              f"({len(still_missing_keys)} still not found anywhere).",
              file=sys.stderr)
        if still_missing_names:
            print("Still unresolved (genuinely no age found in any source - "
                  "likely very recent/obscure Cat B signings, internationals, "
                  "or pre-2024 drafted players who somehow have no AFL Tables "
                  "record): " + ", ".join(still_missing_names), file=sys.stderr)
    else:
        still_missing_names = []
        print("\nNo gap-fill needed - squads.json not found, or every "
              "current player already has an AFL Tables age.", file=sys.stderr)

    league_avg = None
    all_ages = [p["age"] for c in result_clubs.values() for p in c if p["age"] is not None]
    if all_ages:
        league_avg = round(sum(all_ages) / len(all_ages), 2)

    output = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Age is primarily calculated from AFL Tables birthdate data "
            "(players who've played at least one senior game). Players on "
            "the current squad list who AFL Tables has no record for "
            "(typically new draftees who haven't debuted yet) are "
            "gap-filled from Draft Guru's draft-order records where "
            "possible - these are marked source:'draftguru_gapfill'. A "
            "player with no age at all means neither source has them, "
            "which can happen for very recent or obscure signings."
        ),
        "leagueAverageAge": league_avg,
        "unresolvedPlayers": still_missing_names,
        "clubs": result_clubs,
    }

    with open("ages.json", "w") as f:
        json.dump(output, f, indent=2)

    total = sum(len(v) for v in result_clubs.values())
    print(f"\nDone. Wrote ages.json - {len(result_clubs)} clubs, {total} players "
          f"(one request per club via the All Time Player List page).",
          file=sys.stderr)
    if failures:
        print(f"Clubs needing attention: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

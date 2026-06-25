#!/usr/bin/env python3
"""
Draft Guru DOB scraper - gap-filler for undebuted players
-------------------------------------------------------------
AFL Tables only has a date of birth for players who've played at least one
senior game (it's stats data, indexed by games played). That leaves a real
gap: brand new draftees, and some Cat B/rookie signings, who are genuinely
on a 2026 list but haven't played yet.

Draft Guru's draft-order pages (one per year, per draft type) are static,
server-rendered HTML listing every player taken in that draft - including
ones with 0 career games - each linking to an individual profile page with
a clean "Born: DD Mon YYYY" line. This covers the gap AFL Tables can't.

This module is intentionally narrow in scope: it only looks at RECENT
drafts (configurable via DRAFT_YEARS_TO_CHECK below), since anyone from
years ago either has debuted by now (so AFL Tables already has them) or
isn't on a 2026 list anymore. There's no need to crawl decades of history -
that would be slow and mostly irrelevant.

Returns a dict of {normalized_name: {year, month, day}} that the caller
(scrape_ages.py) merges in ONLY for players AFL Tables didn't already find -
AFL Tables remains the primary source since draft-order "Age" columns can
occasionally be off by using "as at draft day" math rather than calendar
age, whereas the individual Draft Guru player page DOB itself is the same
underlying fact either source would report.
"""
import re
import sys
import time
import urllib.request
import urllib.parse
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; AFLListTool/1.0; +https://github.com/)"
BASE = "https://www.draftguru.com.au"

# Only check draft types/years that could plausibly include a player who
# hasn't debuted yet as of mid-2026. Update the year list as seasons pass -
# e.g. once we're well into 2027, drop 2024 and add 2026's drafts here.
DRAFT_PAGES_TO_CHECK = [
    "/years/2024/national_draft",
    "/years/2024/rookie_draft",
    "/years/2024/preseason_draft",
    "/years/2025/national_draft",
    "/years/2025/rookie_draft",
    "/years/2025/preseason_draft",
    "/years/2025/midseason_draft",
]

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Matches "Born: 01 Sep 2007" style text from individual player pages.
BORN_RE = re.compile(r'Born:\s*(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})', re.IGNORECASE)

# Matches player profile links in draft-order tables, e.g.
# /players/dylan_patterson/1
PLAYER_LINK_RE = re.compile(r'href="(/players/[^"]+)"')


def normName(name):
    return re.sub(r'\s+', ' ', re.sub(r"['\u2019.\-]", '', name.lower())).strip()


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


class DraftPageLinkExtractor(HTMLParser):
    """Pulls (player_name, profile_url) pairs out of a draft-order page."""
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.players = []
        self._in_player_link = False
        self._current_href = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith("/players/"):
                self._in_player_link = True
                self._current_href = href
                self._current_text = []

    def handle_data(self, data):
        if self._in_player_link:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_player_link:
            name = "".join(self._current_text).strip()
            if name and not name.lower().startswith("father-son") \
                    and not name.lower().startswith("academy"):
                full_url = urllib.parse.urljoin(self.base_url, self._current_href)
                self.players.append((name, full_url))
            self._in_player_link = False


def strip_tags(html):
    return re.sub(r'<[^>]+>', ' ', html)


def get_draft_page_players(path):
    url = BASE + path
    try:
        html = fetch_url(url)
    except Exception as e:
        print(f"    WARNING: could not fetch draft page {url}: {e}", file=sys.stderr)
        return []
    parser = DraftPageLinkExtractor(url)
    parser.feed(html)
    # de-dupe by url
    seen = {}
    for name, link in parser.players:
        seen[link] = name
    return [(name, link) for link, name in seen.items()]


def fetch_dob_from_profile(profile_url):
    html = fetch_url(profile_url)
    text = strip_tags(html)
    m = BORN_RE.search(text)
    if not m:
        return None
    day, mon_str, year = m.groups()
    month = MONTHS.get(mon_str.lower())
    if not month:
        return None
    return {"year": int(year), "month": month, "day": int(day)}


def get_draftguru_dob_gapfill(names_still_missing):
    """
    names_still_missing: a set of normalized player names that AFL Tables
    had no age for. We only bother fetching Draft Guru profiles for names
    actually in this set, to keep the scrape small and targeted rather
    than fetching every recent draftee's profile regardless of need.

    Returns: dict of {normalized_name: {year, month, day}}
    """
    if not names_still_missing:
        return {}

    result = {}
    seen_profile_urls = set()

    for path in DRAFT_PAGES_TO_CHECK:
        print(f"  Checking Draft Guru {path} for gap-fill candidates ...",
              file=sys.stderr)
        players = get_draft_page_players(path)
        time.sleep(1)
        for name, profile_url in players:
            key = normName(name)
            if key not in names_still_missing:
                continue  # not someone we need - skip the profile fetch entirely
            if profile_url in seen_profile_urls:
                continue
            seen_profile_urls.add(profile_url)
            try:
                dob = fetch_dob_from_profile(profile_url)
                time.sleep(0.5)
            except Exception as e:
                print(f"    WARNING: could not fetch DOB for {name} from "
                      f"{profile_url}: {e}", file=sys.stderr)
                continue
            if dob:
                result[key] = dob
                print(f"    Gap-filled {name}: {dob['year']}-{dob['month']:02d}-{dob['day']:02d}",
                      file=sys.stderr)

    return result


if __name__ == "__main__":
    # Standalone smoke test - check a couple of known-uncapped 2025 draftees
    test_names = {normName("Dylan Patterson"), normName("Oskar Taylor")}
    found = get_draftguru_dob_gapfill(test_names)
    print(found)

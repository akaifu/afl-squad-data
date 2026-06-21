#!/usr/bin/env python3
"""
AFL Contract Status Scraper
----------------------------
Footywire publishes a page per year listing which players are out of
contract that year, with their AFL Players' Association free-agency status
(Non-Free Agent / Restricted Free Agent / Unrestricted Free Agent).

This does NOT give a precise "contract ends in year X" for every player -
that figure isn't published anywhere publicly for players who aren't
expiring soon. What it DOES give, reliably, is: for any player who shows up
in one of these yearly lists, we know for certain they're off-contract at
the end of that specific year, and what their free-agency status is.

This scraper pulls every year footywire has data for (currently 2026-2034)
and writes out a per-player record of the earliest known expiry year and
FA status. Players not found in any list are left with expiryYear: null -
that's not a bug, it just means their contract genuinely runs past
whatever range footywire publishes, and the tool should say so honestly
rather than guessing a date.
"""
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "Mozilla/5.0 (compatible; AFLListTool/1.0; +https://github.com/)"
BASE_URL = "https://www.footywire.com/afl/footy/out_of_contract_players"

# Footywire's dropdown on this page currently spans these years - update if
# they extend the range further in future.
YEARS = list(range(2026, 2035))

# Maps footywire's club section headers to our internal club ids, matching
# the ids used in squads.json from the squad scraper, so the two datasets
# join cleanly on the front end.
CLUB_NAME_TO_ID = {
    "adelaide": "adelaide",
    "brisbane": "brisbane",
    "carlton": "carlton",
    "collingwood": "collingwood",
    "essendon": "essendon",
    "fremantle": "fremantle",
    "geelong": "geelong",
    "gold coast": "goldcoast",
    "gws": "gws",
    "greater western sydney": "gws",
    "hawthorn": "hawthorn",
    "melbourne": "melbourne",
    "north melbourne": "northmelbourne",
    "kangaroos": "northmelbourne",
    "port adelaide": "portadelaide",
    "richmond": "richmond",
    "st kilda": "stkilda",
    "sydney": "sydney",
    "west coast": "westcoast",
    "western bulldogs": "westernbulldogs",
}

FA_MAP = {
    "non-free agent": "",
    "restricted free agent": "RFA",
    "unrestricted free agent": "UFA",
    "unknown": "",
}


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


class SectionedTableExtractor(HTMLParser):
    """
    Walks the page picking up two things in document order:
      - club section headers, e.g. "Adelaide Players Out of Contract in 2026"
      - table rows of (player name, years service, FA status)
    so we can attribute each row to whichever club header most recently
    preceded it. Footywire's markup nests these in tables/headers rather
    than one flat structure, so order-of-appearance is the reliable signal,
    not depth or tag type.
    """
    def __init__(self):
        super().__init__()
        self.current_club = None
        self.rows = []  # (club_id, player_name, fa_status)
        self._in_row = False
        self._row_cells = []
        self._current_cell = []
        self._text_buffer = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_row = True
            self._row_cells = []
        if tag == "td" and self._in_row:
            self._current_cell = []

    def handle_endtag(self, tag):
        if tag == "td" and self._in_row:
            self._row_cells.append("".join(self._current_cell).strip())
        if tag == "tr" and self._in_row:
            self._process_row(self._row_cells)
            self._in_row = False

    def handle_data(self, data):
        if self._in_row:
            self._current_cell.append(data)
            # Header rows like "Adelaide Players Out of Contract in 2026"
            # are themselves inside a <tr><td>, so check cell text too -
            # not just the non-row text buffer.
            self._check_for_club_header(data)
        else:
            self._text_buffer.append(data)
            combined = "".join(self._text_buffer)
            self._check_for_club_header(combined)
            if len(combined) > 500:
                self._text_buffer = [combined[-200:]]

    def _check_for_club_header(self, text):
        m = re.search(r'([A-Za-z .]+?)\s+Players Out of Contract in \d{4}', text)
        if m:
            club_name = m.group(1).strip().lower()
            club_id = CLUB_NAME_TO_ID.get(club_name)
            if club_id:
                self.current_club = club_id

    def _process_row(self, cells):
        # Expected row shape once cleaned: [Name, YearsService, FAStatus]
        # Header rows ("Name", "Years Service", "Status") get skipped since
        # they won't match the FA_MAP lookup.
        if len(cells) < 3:
            return
        name, _years_service, status = cells[0], cells[1], cells[2]
        status_key = status.strip().lower()
        if status_key not in FA_MAP:
            return
        if not name or name.lower() == "name":
            return
        if self.current_club:
            self.rows.append((self.current_club, name.strip(), FA_MAP[status_key]))


def normName(name):
    return re.sub(r'\s+', ' ', re.sub(r"['\u2019.\-]", '', name.lower())).strip()


def scrape_year(year):
    url = f"{BASE_URL}?year={year}"
    print(f"  Fetching out-of-contract list for {year} ...", file=sys.stderr)
    html = fetch_url(url)
    parser = SectionedTableExtractor()
    parser.feed(html)
    print(f"    -> found {len(parser.rows)} player rows across "
          f"{len({r[0] for r in parser.rows})} clubs", file=sys.stderr)
    return parser.rows


def main():
    # contracts[clubId][normalizedName] = {name, expiryYear, fa}
    # Keep the EARLIEST expiry year seen for a player (a player can't be
    # simultaneously off-contract in two different years - if they show up
    # in more than one year's list across different scrapes over time it
    # means their situation changed between scrapes, so earliest-known is
    # the most conservative, useful answer for "when do I need to decide").
    contracts = {}

    for year in YEARS:
        try:
            rows = scrape_year(year)
        except Exception as e:
            print(f"    ERROR fetching {year}: {e}", file=sys.stderr)
            continue
        for club_id, name, fa in rows:
            contracts.setdefault(club_id, {})
            key = normName(name)
            existing = contracts[club_id].get(key)
            if existing is None or year < existing["expiryYear"]:
                contracts[club_id][key] = {
                    "name": name,
                    "expiryYear": year,
                    "fa": fa,
                }
        time.sleep(1)

    result = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sourceUrl": BASE_URL,
        "yearsScraped": YEARS,
        "note": (
            "expiryYear is only populated for players who appeared in one "
            "of footywire's out-of-contract lists for the scraped year "
            "range. A player with no entry here is NOT necessarily signed "
            "long-term - it may just mean their contract runs past the "
            "scraped range, or footywire hasn't listed them. Treat missing "
            "data as 'unknown', not 'long contract'."
        ),
        "clubs": {
            club_id: list(players.values())
            for club_id, players in contracts.items()
        },
    }

    with open("contracts.json", "w") as f:
        json.dump(result, f, indent=2)

    total = sum(len(v) for v in result["clubs"].values())
    print(f"\nDone. Wrote contracts.json - {len(result['clubs'])} clubs, "
          f"{total} player contract records.", file=sys.stderr)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Zero Hanger draft-order scraper -> draft_order.json
Zero Hanger has no public API: the order is a server-rendered HTML table that
their editors update by hand during the trade period. So we poll the page.
Only overwrites draft_order.json if the parsed result passes sanity checks.
"""
import json, re, sys, time, urllib.request
from html.parser import HTMLParser

URL = "https://www.zerohanger.com/afl/afl-draft-order-2026/"
UA = "Mozilla/5.0 (compatible; AFLListTool/1.0; personal project)"
SLUG = {
    "adelaide-crows": "adelaide", "brisbane-lions": "brisbane", "carlton-blues": "carlton",
    "collingwood-magpies": "collingwood", "essendon-bombers": "essendon",
    "fremantle-dockers": "fremantle", "geelong-cats": "geelong", "gold-coast-suns": "goldcoast",
    "gws-giants": "gws", "hawthorn-hawks": "hawthorn", "melbourne-demons": "melbourne",
    "north-melbourne-kangaroos": "northmelbourne", "port-adelaide-power": "portadelaide",
    "richmond-tigers": "richmond", "st-kilda-saints": "stkilda", "sydney-swans": "sydney",
    "west-coast-eagles": "westcoast", "western-bulldogs": "westernbulldogs",
    "tasmania-devils": "tasmania",
}

class OrderParser(HTMLParser):
    def __init__(s):
        super().__init__()
        s.round = None; s.rows = []
        s.in_h2 = False; s.h2 = []
        s.in_tr = False; s.cells = []; s.cell = None; s.flags = []
    def handle_starttag(s, tag, a):
        a = dict(a)
        if tag == "h2": s.in_h2, s.h2 = True, []
        elif tag == "tr": s.in_tr, s.cells, s.flags = True, [], []
        elif tag == "td" and s.in_tr: s.cell = []
        elif tag == "img" and s.in_tr:
            m = re.search(r"team-flags/([a-z0-9-]+)\.", a.get("src") or a.get("data-src") or "")
            if m and (not s.flags or s.flags[-1] != m.group(1)):  # lazy-load dupes
                s.flags.append(m.group(1))
    def handle_endtag(s, tag):
        if tag == "h2":
            s.in_h2 = False
            m = re.search(r"Round\s+(\d+)(\s*-\s*\d+)?", "".join(s.h2))
            s.round = (int(m.group(1)), bool(m.group(2))) if m else None  # None after "Club Picks"
        elif tag == "td" and s.cell is not None:
            s.cells.append("".join(s.cell).strip()); s.cell = None
        elif tag == "tr" and s.in_tr:
            s.in_tr = False; s.finish_row()
    def handle_data(s, d):
        if s.in_h2: s.h2.append(d)
        if s.cell is not None: s.cell.append(d)
    def finish_row(s):
        if not s.round or not s.cells or not s.cells[0].isdigit() or not s.flags: return
        club = SLUG.get(s.flags[0])
        if not club: return
        frm = SLUG.get(s.flags[1]) if len(s.flags) > 1 else None
        pts = s.cells[-1].replace(",", "")
        s.rows.append({
            "pick": int(s.cells[0]), "round": s.round[0],
            "roundLabel": f"{s.round[0]}+" if s.round[1] else str(s.round[0]),
            "club": club, "from": frm, "points": int(pts) if pts.isdigit() else None,
        })

def parse(html):
    p = OrderParser(); p.feed(html); return p.rows

def validate(rows):
    nums = [r["pick"] for r in rows]
    if len(rows) < 40 or nums != list(range(1, len(rows) + 1)):
        return f"picks not sequential/complete ({len(rows)} rows)"
    r1 = sum(1 for r in rows if r["round"] == 1)
    if not 16 <= r1 <= 24: return f"implausible round 1 size ({r1})"
    return None

def main():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    rows = parse(html)
    err = validate(rows)
    if err:
        print("ERROR:", err, "- keeping previous draft_order.json", file=sys.stderr); sys.exit(1)
    with open("draft_order.json", "w") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "source": URL, "picks": rows}, f, indent=1)
    print(f"Wrote draft_order.json - {len(rows)} picks", file=sys.stderr)

if __name__ == "__main__":
    main()

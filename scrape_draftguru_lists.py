#!/usr/bin/env python3
"""
Draft Guru club lists -> lists2027.json
Membership comes from each club's "List Build Picture" page (/lists/2027/<club>/build): player links grouped
under draft-year headings. Full names are rebuilt from the profile slug (first name) + link text (surname).
List category (senior / rookie / cat B) comes from the main club list page ONLY if the per-category counts
match Draft Guru's own index-page totals for that club; otherwise it is left null and the tool keeps its own.
Validate before trusting: each club's player count must equal senior + rookies + cat B from the index page.
"""
import json, re, sys, time, urllib.request, urllib.parse
from html.parser import HTMLParser

SEASON = 2027
BASE = "https://www.draftguru.com.au"
UA = "Mozilla/5.0 (compatible; AFLListTool/1.0; personal project)"
CLUBS = {  # draftguru slug -> our club id
    "adelaide": "adelaide", "brisbane": "brisbane", "carlton": "carlton", "collingwood": "collingwood",
    "essendon": "essendon", "fremantle": "fremantle", "geelong": "geelong", "gold-coast": "goldcoast",
    "greater-western-sydney": "gws", "hawthorn": "hawthorn", "melbourne": "melbourne",
    "north-melbourne": "northmelbourne", "port-adelaide": "portadelaide", "richmond": "richmond",
    "st-kilda": "stkilda", "sydney": "sydney", "west-coast": "westcoast", "western-bulldogs": "westernbulldogs",
}

def fetch(url, retries=3):
    err = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        except Exception as e:
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {err}")

class Rows(HTMLParser):
    """Collects each <tr>: its text and any /players/ links as (slug, link text)."""
    def __init__(s):
        super().__init__(); s.rows = []; s.cur = None; s.href = None; s.txt = []
    def handle_starttag(s, tag, a):
        a = dict(a)
        if tag == "tr": s.cur = {"text": [], "links": [], "club": None}
        if tag == "a":
            h = a.get("href") or ""
            m = re.search(r"/lists/%d/([a-z-]+)/?$" % SEASON, h)
            if m and s.cur is not None: s.cur["club"] = m.group(1)
            if "/players/" in h: s.href, s.txt = h, []
    def handle_data(s, d):
        if s.cur is not None: s.cur["text"].append(d)
        if s.href: s.txt.append(d)
    def handle_endtag(s, tag):
        if tag == "a" and s.href:
            if s.cur is not None: s.cur["links"].append((s.href, "".join(s.txt).strip()))
            s.href = None
        if tag == "tr" and s.cur is not None:
            s.cur["text"] = " ".join("".join(s.cur["text"]).split()); s.rows.append(s.cur); s.cur = None

class Build(HTMLParser):
    """Player links in document order, tagged with the most recent bare 4-digit heading (draft year)."""
    def __init__(s):
        super().__init__(); s.year = None; s.href = None; s.txt = []; s.players = []
    def handle_starttag(s, tag, a):
        h = dict(a).get("href") or ""
        if tag == "a" and "/players/" in h: s.href, s.txt = h, []
    def handle_data(s, d):
        if s.href: s.txt.append(d)
        elif re.fullmatch(r"\s*(19|20)\d\d\s*", d): s.year = int(d)
    def handle_endtag(s, tag):
        if tag == "a" and s.href:
            s.players.append((s.href, "".join(s.txt).strip(), s.year)); s.href = None

def full_name(href, surname):
    slug = urllib.parse.unquote(href.rstrip("/").split("/")[-2])
    first = slug.split("_")[0].replace("-", " ").title().replace(" ", "-") if "_" in slug else ""
    return f"{first} {surname}".strip()

def index_counts():
    p = Rows(); p.feed(fetch(f"{BASE}/lists/{SEASON}"))
    out = {}
    for r in p.rows:
        if not r["club"] or r["club"] not in CLUBS: continue
        t = r["text"]
        s = re.search(r"(\d+)\s+players", t); k = re.search(r"players\s+(\d+)\s*\(\+(\d+)\s*cat B\)", t, re.I)
        if s and k: out[r["club"]] = {"senior": int(s.group(1)), "rookie": int(k.group(1)), "catB": int(k.group(2))}
    return out

def categories(slug, expected):
    """player-link -> 'senior'|'rookie'|'catb', only if per-category totals match the index page."""
    p = Rows(); p.feed(fetch(f"{BASE}/lists/{SEASON}/{slug}"))
    got = {}
    for r in p.rows:
        for href, _ in r["links"][:1]:
            t = r["text"].lower()
            got[href] = "catb" if re.search(r"cat\.?\s*b", t) else ("rookie" if "rookie" in t else "senior")
    c = {k: sum(1 for v in got.values() if v == k) for k in ("senior", "rookie", "catb")}
    ok = expected and got and (c["senior"], c["rookie"], c["catb"]) == (expected["senior"], expected["rookie"], expected["catB"])
    return got if ok else None

def main():
    exp = index_counts(); out = {}; bad = []
    print(f"index page: {len(exp)} clubs with counts", file=sys.stderr)
    for slug, cid in CLUBS.items():
        try:
            b = Build(); b.feed(fetch(f"{BASE}/lists/{SEASON}/{slug}/build"))
            seen = {}; [seen.setdefault(h, (n, y)) for h, n, y in b.players if n]
            cats = categories(slug, exp.get(slug)); time.sleep(1)
            players = [{"name": full_name(h, n), "draftYear": y, "list": (cats or {}).get(h)} for h, (n, y) in seen.items()]
            e = exp.get(slug); total = sum(e.values()) if e else None
            if total is not None and len(players) != total:
                bad.append(f"{cid}: {len(players)} players vs expected {total}")
            out[cid] = {"expected": e, "categoriesVerified": cats is not None, "players": players}
            print(f"  {cid}: {len(players)} players (expected {total}), categories {'verified' if cats else 'NOT verified'}", file=sys.stderr)
        except Exception as ex:
            bad.append(f"{cid}: {ex}")
    if len(out) < 18: print("ERROR: missing clubs - keeping previous lists2027.json:", bad, file=sys.stderr); sys.exit(1)
    json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "season": SEASON,
               "source": f"{BASE}/lists/{SEASON}", "clubs": out}, open("lists2027.json", "w"), indent=1)
    if bad: print("WARNING mismatches:", *bad, sep="\n  ", file=sys.stderr); sys.exit(1)

if __name__ == "__main__":
    main()

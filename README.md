# AFL Live Squad Scraper

Keeps a `squads.json` file in this repo updated automatically every day with
the current player list (name, guernsey number, position) for all 18 AFL
clubs, scraped from each club's own official website.

Your AFL list management tool fetches this JSON file directly from GitHub
(via the raw file URL) so the squad list stays current without you ever
touching it.

## ⚠️ Read this before relying on it

**I could not personally test this scraper against the live club websites.**
The sandbox I built it in only has network access to a small allowlist of
developer domains (PyPI, npm, GitHub, etc.) — it cannot reach
`richmondfc.com.au`, `afc.com.au`, and so on. I verified:

- The **parsing logic** works correctly against realistic sample HTML built
  from what I confirmed (via a web-fetch tool, not direct network access) is
  actually on Richmond's live squad page.
- The **URL for Richmond** (`richmondfc.com.au/football/afl/squad`) is
  confirmed correct and live as of when I checked.
- The **URLs for the other 17 clubs** are my best guess based on each
  club's known domain and Richmond's URL pattern (`/teams/afl` or
  `/football/afl/squad`). **I have not individually confirmed each one.**
  Some are likely wrong.

**What this means practically:** the first time this runs (do it manually,
see below, don't wait for the schedule), check the output. Some clubs will
probably come back with 0 players or an error. That's expected — it just
means that club's URL in `scrape_squads.py` needs a quick fix. Open the
failing club's site in your browser, find their squad/player-list page, and
update the `url` field in the `CLUBS` list near the top of the script.

This is a normal part of running any scraper against sites you don't
control — they change layouts and URLs over time without warning, so
treat the URL list as something you may need to touch again later too,
not a "set and forget."

## Setup (one-time, ~10 minutes)

1. **Create a free GitHub account** if you don't have one: github.com/join

2. **Create a new repository:**
   - Click "+" → "New repository" in the top right of github.com
   - Name it something like `afl-squad-data`
   - Set it to **Public** (required for the free raw-file URL access your
     tool will use — don't worry, it's just player names/numbers, nothing
     sensitive)
   - Click "Create repository"

3. **Upload these files** to the new repo (drag-and-drop works on the
   GitHub web UI, or use `git push` if you're comfortable with git):
   - `scrape_squads.py`
   - `.github/workflows/update-squads.yml` (keep this exact folder path)
   - This `README.md`

4. **Run it manually the first time:**
   - Go to your repo on GitHub → "Actions" tab
   - Click "Update AFL squads" in the left sidebar
   - Click "Run workflow" → "Run workflow" (green button)
   - Wait ~30-60 seconds, then click into the run to see the log output
   - Look for `WARNING` or `ERROR` lines — those tell you exactly which
     clubs need their URL fixed

5. **Fix any broken club URLs:**
   - Open `scrape_squads.py` in the GitHub web editor (click the file, then
     the pencil/edit icon)
   - Find the club's `url` field in the `CLUBS` list
   - Search "[club name] AFL squad" to find their real current squad page
   - Update the URL, commit the change
   - Re-run the workflow (step 4) to confirm it's fixed

6. **Get your raw JSON URL** once everything's green:
   - It will be:
     `https://raw.githubusercontent.com/YOUR_USERNAME/afl-squad-data/main/squads.json`
   - Paste this into the list management tool's settings (see tool README)

After that, it just runs itself daily. Check back occasionally (maybe
monthly) since club site redesigns will eventually break a URL or two.

## What this does NOT do

- **No contracts, salaries, or list status (rookie/Cat B/senior).** That
  data isn't published anywhere on club websites — it stays manually
  maintained in the tool itself.
- **No live polling.** It updates once a day (or whenever you manually
  trigger it) — not the instant a club announces a signing.
- **No guarantee of always working.** It's scraping public web pages, not
  using an official data API (the real one - Champion Data - is paid and
  licensed). Club site redesigns can and will eventually break this.

## Files

- `scrape_squads.py` — the scraper itself. Run locally with `python3
  scrape_squads.py` to test, or let GitHub Actions run it on schedule.
- `.github/workflows/update-squads.yml` — tells GitHub to run the scraper
  daily and commit the result automatically.
- `squads.json` — the output (created after first run). This is what your
  tool fetches.

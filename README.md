# Website Screenshot Tracker

Takes screenshots of a website on a schedule you set.

**New here? Open `SETUP-GUIDE.txt` — it walks through everything click by
click, no IT knowledge required.**

## The one file you edit: `config.ini`

| Setting | What it does | Example |
|---|---|---|
| `url` | The website to screenshot | `https://www.coolbetchile.com/en/casino/slots/lobby` |
| `site_name` | Short name used in screenshot filenames | `coolbet` |
| `run_daily_at` | Once a day at a fixed time (24h) | `09:00` |
| `run_every_minutes` | Or: repeat every X minutes | `60` (hourly) |
| `output_folder` | Where screenshots are saved | `output` or `D:\Screenshots\Coolbet` |
| `require_country` | VPN safety check — skip snapshot if IP isn't from this country | `CL` (empty = off) |

Set **either** `run_daily_at` **or** `run_every_minutes`, leave the other empty.
Restart the tracker (close window, double-click `run_tracker.bat`) after editing.

## How it runs

`run_tracker.bat` starts `tracker.py`, which keeps a small window open and
takes screenshots on the configured schedule. A shortcut in the Windows
Startup folder (see guide, Step 5) makes it launch on every boot.

One-off screenshot from a command line: `python tracker.py --once`

## Multiple websites

Copy the whole folder once per website, edit each copy's `config.ini`,
start each copy's `run_tracker.bat`. Python is installed only once.

## Output

`<site_name>_YYYY-MM-DD_HH-MM.png` — one full-page screenshot per run,
named with the site name, date, and time.

## GitHub Actions (alternative hosting, for reference)

`.github/workflows/daily.yml` runs `tracker.py --once` daily on GitHub's
servers (US-based — a Chilean proxy would be needed for geo-restricted
sites).

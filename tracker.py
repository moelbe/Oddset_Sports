"""
Website Screenshot Tracker
--------------------------
All settings (URL, schedule, output folder, ...) are read from
config.ini in the same folder — edit that file, not this one.

Normal use (takes screenshots on schedule):   run_tracker.bat
                                        or:   python tracker.py

One immediate screenshot:                      python tracker.py --once

FIRST-TIME LOGIN for sites with a security check ("I am a human"):
                                               python tracker.py --login
  This opens a VISIBLE browser at the site. You solve the check by
  hand, then press Enter in the black window. The session is saved,
  so later automatic screenshots reuse it and usually don't see the
  check again.

Each snapshot produces (in the configured output folder):
  <site_name>_YYYY-MM-DD_HH-MM.png      full-page screenshot
"""

import configparser
import datetime
import json
import pathlib
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE_DIR = pathlib.Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.ini"
# Saved browser session (cookies etc.) lives here, so a security check
# solved once during --login is remembered for later runs.
PROFILE_DIR = BASE_DIR / "browser-profile"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        sys.exit(f"ERROR: config.ini not found next to tracker.py ({CONFIG_PATH})")
    cp = configparser.ConfigParser()
    cp.read(CONFIG_PATH, encoding="utf-8")
    s = cp["settings"]

    cfg = {
        "url": s.get("url", "").strip(),
        "site_name": (s.get("site_name", "site").strip() or "site"),
        "run_daily_at": s.get("run_daily_at", "").strip(),
        "run_every_minutes": s.get("run_every_minutes", "").strip(),
        "output_folder": s.get("output_folder", "output").strip() or "output",
        "require_country": s.get("require_country", "").strip(),
        "show_browser": s.get("show_browser", "no").strip().lower()
        in ("yes", "true", "1", "ja"),
        "use_saved_session": s.get("use_saved_session", "yes").strip().lower()
        in ("yes", "true", "1", "ja"),
        "image_format": (
            "jpeg"
            if s.get("image_format", "jpeg").strip().lower() in ("jpeg", "jpg")
            else "png"
        ),
        "jpeg_quality": int(s.get("jpeg_quality", "80") or 80),
        "max_height": int(s.get("max_height", "8000") or 8000),
        "capture_height": int(s.get("capture_height", "0") or 0),
    }

    if not cfg["url"].startswith("http"):
        sys.exit("ERROR in config.ini: 'url' must start with https://")

    out = pathlib.Path(cfg["output_folder"])
    if not out.is_absolute():
        out = BASE_DIR / out
    cfg["output_dir"] = out

    if cfg["run_every_minutes"]:
        try:
            cfg["interval"] = int(cfg["run_every_minutes"])
            if cfg["interval"] < 1:
                raise ValueError
        except ValueError:
            sys.exit("ERROR in config.ini: 'run_every_minutes' must be a whole number like 60")
    else:
        cfg["interval"] = None

    if cfg["run_daily_at"]:
        try:
            datetime.datetime.strptime(cfg["run_daily_at"], "%H:%M")
        except ValueError:
            sys.exit("ERROR in config.ini: 'run_daily_at' must look like 09:00 (24h format)")

    if not cfg["run_daily_at"] and not cfg["interval"]:
        sys.exit(
            "ERROR in config.ini: set either 'run_daily_at' (e.g. 09:00) "
            "or 'run_every_minutes' (e.g. 60)."
        )
    return cfg


def check_country(expected: str) -> bool:
    """True if the current public IP is in the expected country."""
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=15) as r:
            info = json.load(r)
        country = info.get("country", "?")
        print(f"  Public IP: {info.get('ip', '?')} ({country})")
        return country == expected
    except Exception as e:
        print(f"  WARNING: could not verify IP country ({e}); continuing anyway.")
        return True


def open_context(p, headless: bool, use_profile: bool = True):
    """Open a browser. With use_profile=True the session (cookies etc.) is
    kept between runs — needed after a one-time --login. With False every
    run starts completely fresh, which avoids restored scroll positions
    and half-saved cookie banners."""
    if use_profile:
        PROFILE_DIR.mkdir(exist_ok=True)
        return p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1920, "height": 1080},
        )
    browser = p.chromium.launch(headless=headless)
    return browser.new_context(viewport={"width": 1920, "height": 1080})


def dismiss_banners(page) -> None:
    """Close cookie/consent dialogs. Prefers rejecting optional cookies."""
    labels = [
        "Rechazar todas",
        "Reject all",
        "Alle ablehnen",
        "Confirmar mis preferencias",
        "Aceptar todas",
        "Accept all",
        "Aceptar",
        "Accept",
        "Akzeptieren",
        "OK",
        "Got it",
    ]
    for label in labels:
        try:
            btn = page.get_by_role("button", name=label, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2_000)
                page.wait_for_timeout(1_500)
                return
        except Exception:
            pass


def load_all_content(page):
    """Find the element that really scrolls, scroll it fully so lazy rows
    load, and return the total content height. Works for sites that scroll
    inside an inner container (not the window)."""
    js = """
    async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      // Find the element that actually scrolls (largest scrollable area).
      function findScroller() {
        let best = document.scrollingElement || document.documentElement;
        let bestH = best ? best.scrollHeight : 0;
        for (const el of document.querySelectorAll('*')) {
          const oy = getComputedStyle(el).overflowY;
          if ((oy === 'auto' || oy === 'scroll') &&
              el.scrollHeight > el.clientHeight + 200 &&
              el.scrollHeight > bestH) {
            best = el; bestH = el.scrollHeight;
          }
        }
        return best;
      }
      const sc = findScroller();
      let last = -1;
      // Repeatedly jump to the bottom until the height stops growing,
      // giving lazy-loaded rows time to appear each time.
      for (let i = 0; i < 50; i++) {
        sc.scrollTop = sc.scrollHeight;
        window.scrollTo(0, document.documentElement.scrollHeight);
        await sleep(700);
        const h = sc.scrollHeight;
        if (h === last) break;
        last = h;
      }
      sc.scrollTop = 0;
      window.scrollTo(0, 0);
      return Math.max(
        sc.scrollHeight,
        document.documentElement.scrollHeight,
        document.body ? document.body.scrollHeight : 0
      );
    }
    """
    try:
        return int(page.evaluate(js))
    except Exception:
        return 0


def scroll_to_top(page) -> None:
    """Force the window and every scrollable box back to the very top."""
    try:
        page.evaluate(
            """() => {
              window.scrollTo(0, 0);
              if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
              for (const el of document.querySelectorAll('*')) {
                if (el.scrollTop) el.scrollTop = 0;
              }
            }"""
        )
    except Exception:
        pass


def login(cfg: dict) -> int:
    """Open a visible browser so the user can pass a security check once."""
    print("Opening a visible browser so you can solve any security check.")
    print("When the site's normal page is fully visible, come back here")
    print("and press Enter to save the session.\n")
    with sync_playwright() as p:
        context = open_context(p, headless=False, use_profile=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=90_000)
        input("Press Enter here once the site is showing normally... ")
        context.close()
    print("Session saved. You can now run normal screenshots.")
    return 0


def take_snapshot(cfg: dict) -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    print(f"[{stamp}] Snapshot starting — {cfg['url']}")

    if cfg["require_country"] and not check_country(cfg["require_country"]):
        print(
            f"  SKIPPED: connection is not from {cfg['require_country']} — "
            "VPN appears to be disconnected. Will try again at the next "
            "scheduled time."
        )
        return

    cfg["output_dir"].mkdir(parents=True, exist_ok=True)
    shot = cfg["output_dir"] / f"{cfg['site_name']}_{stamp}.{cfg['image_format']}"

    with sync_playwright() as p:
        context = open_context(
            p, headless=not cfg["show_browser"], use_profile=cfg["use_saved_session"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        # Casino/live pages never reach "network idle" (jackpot tickers etc.),
        # so wait only for the basic document, then give it time to render.
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8_000)

        # Close cookie/consent dialogs BEFORE measuring and scrolling,
        # and once more afterwards in case one appears late.
        dismiss_banners(page)
        page.wait_for_timeout(3_000)

        if cfg["capture_height"] > 0:
            # TOP-ONLY MODE: capture just the top part of the page. No
            # full-page scroll needed, so the file stays small and fast.
            page.set_viewport_size(
                {"width": 1920, "height": cfg["capture_height"]}
            )
            page.wait_for_timeout(2_000)
            scroll_to_top(page)
            page.wait_for_timeout(1_000)
            if cfg["image_format"] == "jpeg":
                page.screenshot(
                    path=str(shot), full_page=False, type="jpeg",
                    quality=cfg["jpeg_quality"],
                )
            else:
                page.screenshot(path=str(shot), full_page=False, type="png")
            context.close()
            size_mb = shot.stat().st_size / 1_000_000 if shot.exists() else 0
            print(f"  Screenshot saved: {shot.name} ({size_mb:.1f} MB)")
            print("  Done.")
            return

        # Load every row (handles sites that scroll inside an inner box),
        # then grow the window to the full content height so the
        # screenshot captures the whole page, not just the first screen.
        total_h = load_all_content(page)
        page.wait_for_timeout(2_000)
        dismiss_banners(page)
        if total_h > 1080:
            page.set_viewport_size(
                {"width": 1920, "height": min(total_h + 200, cfg["max_height"])}
            )
            page.wait_for_timeout(3_000)

        # Resizing re-flows the page and can restore an old scroll
        # position — force everything back to the very top before shooting.
        scroll_to_top(page)
        page.wait_for_timeout(2_000)

        # JPEG is far smaller than PNG for photo-heavy casino pages, which
        # keeps the file well under GitHub's 100 MB limit. PNG stays an
        # option via config for pin-sharp text.
        if cfg["image_format"] == "jpeg":
            page.screenshot(
                path=str(shot), full_page=True, type="jpeg",
                quality=cfg["jpeg_quality"],
            )
        else:
            page.screenshot(path=str(shot), full_page=True, type="png")
        context.close()

    size_mb = shot.stat().st_size / 1_000_000 if shot.exists() else 0
    print(f"  Screenshot saved: {shot.name} ({size_mb:.1f} MB)")
    print("  Done.")


def seconds_until_daily(hhmm: str) -> float:
    now = datetime.datetime.now()
    target = now.replace(
        hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0
    )
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def main() -> int:
    cfg = load_config()

    if "--login" in sys.argv:
        return login(cfg)

    print("Tracker started.")
    print(f"  Website:  {cfg['url']}")
    print(f"  Saves to: {cfg['output_dir']}")
    if cfg["run_daily_at"]:
        print(f"  Schedule: daily at {cfg['run_daily_at']}")
    else:
        print(f"  Schedule: every {cfg['interval']} minutes")
    print("  (Keep this window open. Close it to stop the tracker.)\n")

    if "--once" in sys.argv:
        take_snapshot(cfg)
        return 0

    if cfg["run_daily_at"]:
        while True:
            wait = seconds_until_daily(cfg["run_daily_at"])
            hrs = wait / 3600
            print(f"Next snapshot at {cfg['run_daily_at']} (in {hrs:.1f} h). Waiting...")
            time.sleep(wait)
            try:
                take_snapshot(cfg)
            except Exception as e:
                print(f"  ERROR during snapshot: {e} — will retry tomorrow.")
    else:
        while True:
            try:
                take_snapshot(cfg)
            except Exception as e:
                print(f"  ERROR during snapshot: {e} — will retry at next interval.")
            print(f"Next snapshot in {cfg['interval']} minutes. Waiting...")
            time.sleep(cfg["interval"] * 60)


if __name__ == "__main__":
    sys.exit(main())

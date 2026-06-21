"""Save your ESPN auth cookies (one-time setup).

ESPN auth is just two cookies. Paste them from a browser where you're already logged into
ESPN; they authenticate both the read and write APIs -- no automated browser login needed.

Run this in your own terminal (your cookie values stay on this machine):

    python setup_cookies.py

How to find the cookies (in your normal browser, logged into ESPN):
  1. Go to https://fantasy.espn.com and make sure you're logged in.
  2. Open DevTools (F12) -> Application -> Storage -> Cookies -> https://fantasy.espn.com
     (or use the Network tab: click a fantasy.espn.com request -> Request Headers -> Cookie).
  3. Copy the VALUE of `espn_s2` and the VALUE of `SWID` (SWID looks like {AAAA-BBBB-...}).

Use the dedicated co-manager account for full read+write; your personal account also works.
"""
from __future__ import annotations

import config


def main() -> int:
    config.AUTH_DIR.mkdir(exist_ok=True)
    print("Paste your ESPN cookie values (they stay on this machine).\n")
    espn_s2 = input("espn_s2: ").strip()
    swid = input("SWID (with braces, e.g. {ABC-123}): ").strip()

    if not espn_s2 or not swid:
        print("\nBoth values are required. Nothing saved.")
        return 1
    if not (swid.startswith("{") and swid.endswith("}")):
        swid = "{" + swid.strip("{}") + "}"

    config.save_cookies(espn_s2, swid)
    print(f"\nSaved -> {config.COOKIES_FILE}")
    print("Next: python cli.py status")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

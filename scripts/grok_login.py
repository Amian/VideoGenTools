#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from camoufox.sync_api import Camoufox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Grok Imagine in the persistent Camoufox profile so you can sign in once for later automation."
    )
    parser.add_argument("--profile", help="Persistent Camoufox profile directory.")
    parser.add_argument("--url", default="https://grok.com/imagine", help="Grok Imagine URL.")
    parser.add_argument("--headless", action="store_true", help="Run headless.")
    return parser.parse_args()


def default_profile_path() -> Path:
    return Path.home() / ".camoufox" / "GrokImagineProfile"


def reveal_imagine_input(page) -> None:
    page.evaluate(
        """
        () => {
          const overlay = document.querySelector('#onetrust-consent-sdk');
          if (overlay) overlay.remove();

          const toggle =
            document.querySelector('button[aria-label*="Toggle Sidebar"]') ||
            document.querySelector('button[title*="Toggle Sidebar"]');
          if (toggle) {
            toggle.click();
          }

          const scrollables = Array.from(document.querySelectorAll('body, main, [role="main"], div')).filter((element) => {
            const style = window.getComputedStyle(element);
            return (
              (style.overflowY === 'auto' || style.overflowY === 'scroll') &&
              element.scrollHeight > element.clientHeight + 200 &&
              element.clientHeight > 300
            );
          });

          for (const element of scrollables) {
            element.scrollTop = element.scrollHeight;
          }

          window.scrollTo(0, document.body.scrollHeight);
          window.scrollTo(0, document.documentElement.scrollHeight);

          const composer =
            document.querySelector('form.w-full') ||
            document.querySelector('div[contenteditable="true"]') ||
            document.querySelector('textarea');

          if (composer && composer.scrollIntoView) {
            composer.scrollIntoView({ block: 'center', inline: 'nearest' });
          }
        }
        """
    )


def main() -> None:
    args = parse_args()
    profile_path = Path(args.profile).expanduser().resolve() if args.profile else default_profile_path()
    profile_path.mkdir(parents=True, exist_ok=True)

    with Camoufox(
        headless=args.headless,
        persistent_context=True,
        user_data_dir=str(profile_path),
    ) as browser:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.set_viewport_size({"width": 1600, "height": 1200})
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        reveal_imagine_input(page)
        page.wait_for_timeout(1000)
        print(f"Profile used: {profile_path}")
        print("Sign into Grok in the opened browser window, then press Enter here to close it.")
        input()


if __name__ == "__main__":
    main()

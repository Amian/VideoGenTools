#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def default_profile_path() -> Path:
    home = Path.home()
    if os.name == "posix" and sys_platform() == "darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome" / "ImageGenProfile"
    if os.name == "nt":
        return home / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "ImageGenProfile"
    return home / ".config" / "google-chrome" / "ImageGenProfile"


def sys_platform() -> str:
    import sys

    return sys.platform


def chrome_executable_path() -> Path | None:
    if sys_platform() == "darwin":
        candidate = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return candidate if candidate.exists() else None
    return None


def cleanup_profile_locks(profile_path: Path) -> None:
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        lock_path = profile_path / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
            except OSError:
                pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a Playwright Chromium window using the same Chrome ImageGenProfile as the free-image skill."
    )
    parser.add_argument("--url", default="https://grok.com/imagine", help="URL to open.")
    parser.add_argument("--profile", help="Override profile path.")
    parser.add_argument("--headless", action="store_true", help="Run headless.")
    parser.add_argument("--width", type=int, default=1600, help="Viewport width.")
    parser.add_argument("--height", type=int, default=1200, help="Viewport height.")
    parser.add_argument(
        "--grok-zoom",
        type=float,
        default=0.8,
        help="Page zoom to apply on Grok pages so the composer stays visible.",
    )
    return parser.parse_args()


def reveal_grok_input(page, *, grok_zoom: float) -> None:
    page.evaluate(
        """
        ({ grokZoom }) => {
          document.documentElement.style.zoom = String(grokZoom);
          document.body.style.zoom = String(grokZoom);

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

          document.documentElement.scrollTop = document.documentElement.scrollHeight;
          document.body.scrollTop = document.body.scrollHeight;
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
        """,
        {"grokZoom": grok_zoom},
    )


def main() -> None:
    args = parse_args()
    profile_path = Path(args.profile).expanduser().resolve() if args.profile else default_profile_path()
    profile_path.mkdir(parents=True, exist_ok=True)
    cleanup_profile_locks(profile_path)

    executable_path = chrome_executable_path()

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=args.headless,
            executable_path=str(executable_path) if executable_path else None,
            no_viewport=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                f"--window-size={args.width},{args.height}",
                "--start-maximized",
                "--force-device-scale-factor=1",
                "--high-dpi-support=1",
            ],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_viewport_size({"width": args.width, "height": args.height})
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if "grok.com/imagine" in args.url:
            for _ in range(3):
                reveal_grok_input(page, grok_zoom=args.grok_zoom)
                page.wait_for_timeout(1000)
        print(f"Profile used: {profile_path}")
        print(f"URL: {args.url}")
        print("Press Enter to close...")
        input()
        context.close()


if __name__ == "__main__":
    main()

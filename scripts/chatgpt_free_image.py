#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime
from pathlib import Path

from camoufox.sync_api import Camoufox


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open ChatGPT with Camoufox, submit one image prompt, and download the generated image."
    )
    parser.add_argument("--prompt", required=True, help="Image prompt to submit to ChatGPT.")
    parser.add_argument("--output", required=True, help="Output file path or output directory.")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Optional reference image path. Repeat --image to attach multiple images.",
    )
    parser.add_argument("--profile", help="Persistent Camoufox profile directory.")
    parser.add_argument("--url", default="https://chatgpt.com/", help="ChatGPT URL.")
    parser.add_argument("--timeout-ms", type=int, default=180000, help="Image generation timeout in milliseconds.")
    parser.add_argument("--headless", action="store_true", help="Run headless.")
    parser.add_argument("--debug-dir", help="Optional directory for screenshots and DOM diagnostics.")
    return parser.parse_args()


def default_profile_path() -> Path:
    return Path.home() / ".camoufox" / "ImageGenProfile"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_output_path(output_arg: str) -> Path:
    output = Path(output_arg).expanduser().resolve()
    if output.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
        ensure_dir(output.parent)
        return output

    ensure_dir(output)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output / f"generated-{stamp}.png"


def sanitize_label(label: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in label.lower())
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "step"


def make_debug_dir(debug_dir: str | None) -> Path | None:
    if not debug_dir:
        return None
    path = Path(debug_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_debug_artifacts(page, debug_dir: Path | None, label: str) -> None:
    if debug_dir is None:
        return

    slug = sanitize_label(label)
    screenshot_path = debug_dir / f"{slug}.png"
    json_path = debug_dir / f"{slug}.json"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as error:
        screenshot_path.write_text(f"Screenshot failed: {error}\n", encoding="utf-8")

    try:
        diagnostics = page.evaluate(
            """
            () => {
              const toSummary = (element) => {
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return {
                  tag: element.tagName.toLowerCase(),
                  id: element.id || null,
                  className: element.className || null,
                  role: element.getAttribute('role'),
                  type: element.getAttribute('type'),
                  placeholder: element.getAttribute('placeholder'),
                  ariaLabel: element.getAttribute('aria-label'),
                  title: element.getAttribute('title'),
                  text: (element.innerText || element.textContent || '').trim().slice(0, 300),
                  value: 'value' in element ? (element.value || '').slice(0, 300) : null,
                  visible:
                    rect.width > 0 &&
                    rect.height > 0 &&
                    style.visibility !== 'hidden' &&
                    style.display !== 'none',
                  rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                  },
                  disabled: Boolean(element.disabled),
                };
              };

              return {
                url: location.href,
                title: document.title,
                readyState: document.readyState,
                textareas: Array.from(document.querySelectorAll('textarea')).map(toSummary).slice(0, 20),
                contenteditables: Array.from(document.querySelectorAll('[contenteditable=\"true\"], [role=\"textbox\"]')).map(toSummary).slice(0, 20),
                fileInputs: Array.from(document.querySelectorAll('input[type=\"file\"]')).map(toSummary).slice(0, 20),
                buttons: Array.from(document.querySelectorAll('button')).map(toSummary).slice(0, 60),
                images: Array.from(document.querySelectorAll('img')).map(toSummary).slice(0, 30),
                visibleTextSample: Array.from(document.querySelectorAll('h1, h2, h3, p, span, div'))
                  .map((element) => (element.innerText || '').trim())
                  .filter(Boolean)
                  .slice(0, 60),
              };
            }
            """
        )
        json_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    except Exception as error:
        json_path.write_text(json.dumps({"error": str(error)}, indent=2), encoding="utf-8")


def find_composer(page, timeout_ms: int = 30000):
    selectors = [
        'textarea[placeholder*="Message"]',
        'textarea[data-testid="composer-text-input"]',
        "#prompt-textarea",
        'div[contenteditable="true"][data-testid="composer-text-input"]',
        'div[contenteditable="true"][role="textbox"]',
    ]

    elapsed = 0
    while elapsed < timeout_ms:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                return locator, selector
        page.wait_for_timeout(1000)
        elapsed += 1000

    raise RuntimeError("Could not find the ChatGPT prompt composer after waiting 30 seconds.")


def enter_prompt(page, prompt: str) -> None:
    composer, selector = find_composer(page)
    composer.click()
    if selector.startswith("textarea") or selector == "#prompt-textarea":
        composer.fill(prompt)
    else:
        composer.fill("")
        composer.type(prompt, delay=10)


def prompt_send_state(page) -> dict:
    return page.evaluate(
        """
        () => {
          const composer =
            document.querySelector('textarea[placeholder*="Message"]') ||
            document.querySelector('textarea[data-testid="composer-text-input"]') ||
            document.querySelector('#prompt-textarea') ||
            document.querySelector('div[contenteditable="true"][data-testid="composer-text-input"]') ||
            document.querySelector('div[contenteditable="true"][role="textbox"]');

          const sendButton =
            document.querySelector('button[data-testid="send-button"]') ||
            document.querySelector('button[aria-label="Send message"]') ||
            document.querySelector('button[aria-label="Send prompt"]');

          const progress = document.querySelector('[role="progressbar"], .animate-spin');

          let composerText = "";
          if (composer) {
            if ("value" in composer) {
              composerText = composer.value || "";
            } else {
              composerText = composer.innerText || "";
            }
          }

          return {
            composerText,
            sendDisabled: Boolean(sendButton && sendButton.disabled),
            hasProgress: Boolean(progress && progress.offsetParent !== null),
          };
        }
        """
    )


def resolve_image_paths(image_args: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for image_arg in image_args:
        image_path = Path(image_arg).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Input image not found: {image_path}")
        resolved.append(image_path)
    return resolved


def upload_images(page, image_paths: list[Path]) -> None:
    if not image_paths:
        return

    string_paths = [str(image_path) for image_path in image_paths]

    file_inputs = page.locator('input[type="file"]')
    if file_inputs.count():
        try:
            file_inputs.last.set_input_files(string_paths)
            page.wait_for_timeout(2000)
            return
        except Exception:
            pass

    attach_button_selectors = [
        'button[aria-label*="Attach"]',
        'button[aria-label*="attach"]',
        'button[aria-label*="Upload"]',
        'button[aria-label*="upload"]',
        'button[data-testid*="upload"]',
        'button:has(svg)',
    ]

    for selector in attach_button_selectors:
        button = page.locator(selector).first
        try:
            if not button.count() or not button.is_visible():
                continue
            with page.expect_file_chooser(timeout=5000) as chooser_info:
                button.click()
            chooser = chooser_info.value
            chooser.set_files(string_paths)
            page.wait_for_timeout(2000)
            return
        except Exception:
            continue

    raise RuntimeError("Could not find a ChatGPT file upload control for the provided images.")


def get_latest_image_state(page) -> dict:
    return page.evaluate(
        """
        () => {
          const images = Array.from(document.querySelectorAll('img[alt="Generated image"], img[alt*="Generated"]'));
          const image = images.length ? images[images.length - 1] : null;
          const progress = document.querySelector('[role="progressbar"], .animate-spin');
          return {
            src: image ? image.src : null,
            width: image ? image.naturalWidth : 0,
            height: image ? image.naturalHeight : 0,
            hasProgress: Boolean(progress && progress.offsetParent !== null),
          };
        }
        """
    )


def wait_for_new_image(page, previous_src: str | None, timeout_ms: int) -> dict:
    elapsed = 0
    stable_src = None
    stable_count = 0

    while elapsed < timeout_ms:
        state = get_latest_image_state(page)
        has_new_image = bool(state["src"]) and state["src"] != previous_src
        is_large_enough = state["width"] >= 512 and state["height"] >= 512

        if state["src"] and state["src"] == stable_src:
            stable_count += 1
        else:
            stable_src = state["src"]
            stable_count = 0

        if has_new_image and is_large_enough and stable_count >= 2 and not state["hasProgress"]:
            return state

        page.wait_for_timeout(1500)
        elapsed += 1500

    raise RuntimeError("Timed out waiting for the generated image to finish.")


def click_send(page) -> None:
    send_state = prompt_send_state(page)
    if send_state["composerText"].strip():
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)

        post_enter_state = prompt_send_state(page)
        if (
            not post_enter_state["composerText"].strip()
            or post_enter_state["sendDisabled"]
            or post_enter_state["hasProgress"]
        ):
            return

    selectors = [
        'button[data-testid="send-button"]:not([disabled])',
        'button[aria-label="Send message"]:not([disabled])',
        'button[aria-label="Send prompt"]:not([disabled])',
        'button:has(svg[mask*="send"]):not([disabled])',
    ]

    page.keyboard.press("Escape")
    page.wait_for_timeout(200)

    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() and locator.is_visible():
            try:
                locator.click(force=True)
                return
            except Exception:
                try:
                    page.evaluate(
                        """
                        (sel) => {
                          const button = document.querySelector(sel);
                          if (button) {
                            button.click();
                          }
                        }
                        """,
                        selector,
                    )
                    return
                except Exception:
                    continue

    page.keyboard.press("Enter")


def download_generated_image(page, output_path: Path) -> None:
    image_selector = 'img[alt="Generated image"], img[alt*="Generated"]'
    page.locator(image_selector).last.hover()
    page.wait_for_timeout(500)

    try:
        with page.expect_download(timeout=15000) as download_info:
            page.evaluate(
                """
                () => {
                  const buttons = Array.from(document.querySelectorAll('button[aria-label*="Download"], button[aria-label*="download"]'));
                  const button = buttons[buttons.length - 1];
                  if (!button) {
                    throw new Error("Download button not found.");
                  }
                  button.click();
                }
                """
            )
        download = download_info.value
        download.save_as(str(output_path))
        return
    except Exception:
        state = get_latest_image_state(page)
        if not state["src"]:
            raise

        data_url = page.evaluate(
            """
            async (src) => {
              const response = await fetch(src);
              const blob = await response.blob();
              return await new Promise((resolve) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve(reader.result);
                reader.readAsDataURL(blob);
              });
            }
            """,
            state["src"],
        )
        if isinstance(data_url, str) and data_url.startswith("data:image/"):
            payload = data_url.split(",", 1)[1]
            output_path.write_bytes(base64.b64decode(payload))
            return

        raise RuntimeError("Failed to download generated image.")


def generate_image(
    *,
    prompt: str,
    output: str,
    images: list[str] | None = None,
    profile: str | None = None,
    url: str = "https://chatgpt.com/",
    timeout_ms: int = 180000,
    headless: bool = False,
    debug_dir: str | None = None,
) -> Path:
    profile_path = Path(profile).expanduser().resolve() if profile else default_profile_path()
    output_path = resolve_output_path(output)
    image_paths = resolve_image_paths(images or [])
    debug_path = make_debug_dir(debug_dir)
    ensure_dir(profile_path)

    with Camoufox(
        headless=headless,
        persistent_context=True,
        user_data_dir=str(profile_path),
    ) as browser:
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        write_debug_artifacts(page, debug_path, "01-after-load")

        previous_image = get_latest_image_state(page)
        upload_images(page, image_paths)
        write_debug_artifacts(page, debug_path, "02-after-upload")
        enter_prompt(page, prompt)
        write_debug_artifacts(page, debug_path, "03-after-prompt")
        click_send(page)
        write_debug_artifacts(page, debug_path, "04-after-send")
        wait_for_new_image(page, previous_image.get("src"), timeout_ms)
        write_debug_artifacts(page, debug_path, "05-image-ready")
        download_generated_image(page, output_path)
        write_debug_artifacts(page, debug_path, "06-after-download")

    return output_path


def main() -> None:
    args = parse_args()
    output_path = generate_image(
        prompt=args.prompt,
        output=args.output,
        images=args.image,
        profile=args.profile,
        url=args.url,
        timeout_ms=args.timeout_ms,
        headless=args.headless,
        debug_dir=args.debug_dir,
    )
    profile_path = Path(args.profile).expanduser().resolve() if args.profile else default_profile_path()
    print(f"Saved image: {output_path}")
    print(f"Profile used: {profile_path}")


if __name__ == "__main__":
    main()

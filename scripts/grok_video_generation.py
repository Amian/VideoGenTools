#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime
from pathlib import Path

from open_free_image_playwright import (
    chrome_executable_path,
    cleanup_profile_locks,
    default_profile_path as default_playwright_profile_path,
    reveal_grok_input,
)
from playwright.sync_api import sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open Grok Imagine with Playwright, submit one prompt with optional reference images, and download the generated video."
    )
    parser.add_argument("--prompt", required=True, help="Video prompt to submit to Grok Imagine.")
    parser.add_argument("--output", required=True, help="Output file path or output directory.")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Optional reference image path. Repeat --image to attach multiple images.",
    )
    parser.add_argument("--profile", help="Persistent Playwright/Chrome profile directory.")
    parser.add_argument("--url", default="https://grok.com/imagine", help="Grok Imagine URL.")
    parser.add_argument(
        "--saved-url",
        default="https://grok.com/imagine/saved",
        help="Grok Imagine Saved URL used to retrieve finished videos.",
    )
    parser.add_argument("--timeout-ms", type=int, default=420000, help="Video generation timeout in milliseconds.")
    parser.add_argument("--headless", action="store_true", help="Run headless.")
    parser.add_argument("--debug-dir", help="Optional directory for screenshots and DOM diagnostics.")
    return parser.parse_args()


def default_profile_path() -> Path:
    return default_playwright_profile_path()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def resolve_output_path(output_arg: str) -> Path:
    output = Path(output_arg).expanduser().resolve()
    if output.suffix.lower() in {".mp4", ".mov", ".webm"}:
        ensure_dir(output.parent)
        return output

    ensure_dir(output)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output / f"generated-video-{stamp}.mp4"


def resolve_image_paths(image_args: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for image_arg in image_args:
        image_path = Path(image_arg).expanduser().resolve()
        if not image_path.is_file():
            raise FileNotFoundError(f"Input image not found: {image_path}")
        resolved.append(image_path)
    return resolved


def make_debug_dir(debug_dir: str | None) -> Path | None:
    if not debug_dir:
        return None
    path = Path(debug_dir).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_label(label: str) -> str:
    safe = "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in label.lower())
    while "--" in safe:
        safe = safe.replace("--", "-")
    return safe.strip("-") or "step"


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
                  name: element.getAttribute('name'),
                  role: element.getAttribute('role'),
                  type: element.getAttribute('type'),
                  placeholder: element.getAttribute('placeholder'),
                  ariaLabel: element.getAttribute('aria-label'),
                  title: element.getAttribute('title'),
                  text: (element.innerText || element.textContent || '').trim().slice(0, 200),
                  value: 'value' in element ? (element.value || '').slice(0, 200) : null,
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

              const unique = (items) => {
                const seen = new Set();
                return items.filter((item) => {
                  const key = JSON.stringify(item);
                  if (seen.has(key)) return false;
                  seen.add(key);
                  return true;
                });
              };

              return {
                url: location.href,
                title: document.title,
                readyState: document.readyState,
                textareas: unique(Array.from(document.querySelectorAll('textarea')).map(toSummary)).slice(0, 20),
                contenteditables: unique(
                  Array.from(document.querySelectorAll('[contenteditable="true"], [contenteditable=""], [role="textbox"]')).map(
                    toSummary
                  )
                ).slice(0, 20),
                fileInputs: unique(Array.from(document.querySelectorAll('input[type="file"]')).map(toSummary)).slice(0, 20),
                buttons: unique(Array.from(document.querySelectorAll('button')).map(toSummary)).slice(0, 60),
                links: unique(Array.from(document.querySelectorAll('a')).map(toSummary)).slice(0, 30),
                visibleTextSample: Array.from(document.querySelectorAll('h1, h2, h3, p, span, div'))
                  .map((element) => (element.innerText || '').trim())
                  .filter(Boolean)
                  .slice(0, 50),
              };
            }
            """
        )
        json_path.write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    except Exception as error:
        json_path.write_text(json.dumps({"error": str(error)}, indent=2), encoding="utf-8")


def dismiss_known_overlays(page) -> None:
    selectors = [
        "#onetrust-reject-all-handler",
        "#onetrust-accept-btn-handler",
        "#onetrust-close-btn-container button",
        'button[aria-label*="cookie" i]',
        'button[aria-label*="consent" i]',
        'button:has-text("Reject All")',
        'button:has-text("Accept All")',
        'button:has-text("Close")',
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                locator.click(force=True)
                page.wait_for_timeout(500)
                break
        except Exception:
            continue

    try:
        page.evaluate(
            """
            () => {
              const overlay = document.querySelector('#onetrust-consent-sdk');
              if (overlay) {
                overlay.style.display = 'none';
                overlay.remove();
              }
            }
            """
        )
    except Exception:
        pass


def is_signed_out(page) -> bool:
    return bool(
        page.evaluate(
            """
            () => {
              const elements = Array.from(document.querySelectorAll('a, button'));
              const hasSignIn = elements.some((element) => {
                const text = (element.innerText || element.textContent || '').trim();
                const rect = element.getBoundingClientRect();
                return text === 'Sign in' && rect.width > 0 && rect.height > 0;
              });
              const hasSignUp = elements.some((element) => {
                const text = (element.innerText || element.textContent || '').trim();
                const rect = element.getBoundingClientRect();
                return text === 'Sign up' && rect.width > 0 && rect.height > 0;
              });
              return hasSignIn && hasSignUp;
            }
            """
        )
    )


def ensure_video_mode(page) -> None:
    result = page.evaluate(
        """
        () => {
          const buttons = Array.from(document.querySelectorAll('button'));
          const candidates = buttons
            .filter((button) => {
              const text = (button.innerText || button.textContent || '').trim();
              const rect = button.getBoundingClientRect();
              return text === 'Video' && rect.width > 0 && rect.height > 0 && rect.y > window.innerHeight / 2;
            })
            .sort((left, right) => right.getBoundingClientRect().y - left.getBoundingClientRect().y);

          const target = candidates[0];
          if (!target) {
            return { found: false };
          }

          target.click();
          return {
            found: true,
            className: target.className || '',
            ariaPressed: target.getAttribute('aria-pressed'),
            ariaSelected: target.getAttribute('aria-selected'),
          };
        }
        """
    )

    if not result.get("found"):
        raise RuntimeError("Could not find the Grok Imagine Video mode toggle.")

    page.wait_for_timeout(800)


def find_composer(page, timeout_ms: int = 30000):
    selectors = [
        'textarea[placeholder*="Describe"]',
        'textarea[placeholder*="Prompt"]',
        'textarea[placeholder*="Message"]',
        'textarea[data-testid="composer-text-input"]',
        "#prompt-textarea",
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

    generic_candidates = page.locator('textarea, div[contenteditable="true"], [role="textbox"]')
    if generic_candidates.count():
        for index in range(generic_candidates.count()):
            locator = generic_candidates.nth(index)
            try:
                if locator.is_visible():
                    return locator, "generic"
            except Exception:
                continue

    raise RuntimeError("Could not find the Grok Imagine prompt composer after waiting 30 seconds.")


def enter_prompt(page, prompt: str) -> None:
    composer, selector = find_composer(page)
    dismiss_known_overlays(page)
    try:
        composer.focus()
    except Exception:
        composer.evaluate("(element) => element.focus()")
    if selector.startswith("textarea") or selector == "#prompt-textarea":
        composer.fill(prompt)
    else:
        composer.evaluate(
            """
            (element, text) => {
              element.focus();
              element.textContent = '';
              element.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'deleteContentBackward' }));
              element.textContent = text;
              element.dispatchEvent(new InputEvent('input', { bubbles: true, data: text, inputType: 'insertText' }));
            }
            """,
            prompt,
        )


def resolve_video_src(video) -> str | None:
    if not video:
        return None
    if video.get("currentSrc"):
        return video["currentSrc"]
    if video.get("src"):
        return video["src"]
    if video.get("sourceSrc"):
        return video["sourceSrc"]
    return None


def download_url_to_path(page, url: str, output_path: Path) -> None:
    response = page.context.request.get(
        url,
        headers={
            "referer": page.url,
            "origin": "https://grok.com",
        },
    )
    if not response.ok:
        raise RuntimeError(f"Failed to fetch video URL: {response.status}")
    output_path.write_bytes(response.body())


def generation_state(page) -> dict:
    return page.evaluate(
        """
        () => {
          const composer =
            document.querySelector('textarea[placeholder*="Describe"]') ||
            document.querySelector('textarea[placeholder*="Prompt"]') ||
            document.querySelector('textarea[placeholder*="Message"]') ||
            document.querySelector('textarea[data-testid="composer-text-input"]') ||
            document.querySelector('#prompt-textarea') ||
            document.querySelector('div[contenteditable="true"][role="textbox"]');

          const sendButton =
            document.querySelector('button[data-testid="send-button"]') ||
            document.querySelector('button[aria-label*="Submit"]') ||
            document.querySelector('button[aria-label*="Generate"]') ||
            document.querySelector('button[aria-label*="Send"]') ||
            document.querySelector('button[type="submit"]');

          const progress = document.querySelector('[role="progressbar"], .animate-spin');
          const videos = Array.from(document.querySelectorAll('video'));
          const video = videos.length ? videos[videos.length - 1] : null;
          const source = video ? video.querySelector('source') : null;
          const signInLink = Array.from(document.querySelectorAll('a, button')).find((element) => {
            const text = (element.innerText || element.textContent || '').trim();
            const rect = element.getBoundingClientRect();
            return text === 'Sign in' && rect.width > 0 && rect.height > 0;
          });
          const signUpLink = Array.from(document.querySelectorAll('a, button')).find((element) => {
            const text = (element.innerText || element.textContent || '').trim();
            const rect = element.getBoundingClientRect();
            return text === 'Sign up' && rect.width > 0 && rect.height > 0;
          });

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
            isSignedOut: Boolean(signInLink && signUpLink),
            isSubscribePrompt:
              location.href.includes('#subscribe') ||
              /Try Free For 3 Days|Claim free offer/i.test(document.body.innerText || ''),
            hasServerFailedToast: /Server failed to respond/i.test(document.body.innerText || ''),
            video: video
              ? {
                  src: video.src || null,
                  currentSrc: video.currentSrc || null,
                  sourceSrc: source ? source.src || null : null,
                  readyState: video.readyState,
                  duration: Number.isFinite(video.duration) ? video.duration : 0,
                  videoWidth: video.videoWidth || 0,
                  videoHeight: video.videoHeight || 0,
                }
              : null,
          };
        }
        """
    )


def collect_saved_items(page) -> list[dict]:
    return page.evaluate(
        """
        () => {
          const anchors = Array.from(document.querySelectorAll('a[href*="/imagine/"]'))
            .filter((anchor) => {
              const href = anchor.href || '';
              const rect = anchor.getBoundingClientRect();
              if (!href || href.endsWith('/imagine') || href.endsWith('/imagine/saved')) return false;
              if (rect.width < 120 || rect.height < 120) return false;
              return Boolean(anchor.querySelector('img, video'));
            })
            .map((anchor, index) => {
              const rect = anchor.getBoundingClientRect();
              const image = anchor.querySelector('img');
              const video = anchor.querySelector('video');
              return {
                key: anchor.href,
                href: anchor.href,
                text: (anchor.innerText || anchor.textContent || '').trim().slice(0, 200),
                imageSrc: image ? image.currentSrc || image.src || null : null,
                videoSrc: video ? video.currentSrc || video.src || null : null,
                rect: {
                  x: Math.round(rect.x),
                  y: Math.round(rect.y),
                  width: Math.round(rect.width),
                  height: Math.round(rect.height),
                },
                index,
              };
            });

          anchors.sort((left, right) => {
            if (left.rect.y !== right.rect.y) return left.rect.y - right.rect.y;
            if (left.rect.x !== right.rect.x) return left.rect.x - right.rect.x;
            return left.index - right.index;
          });

          return anchors;
        }
        """
    )


def open_saved_page(page, saved_url: str, debug_dir: Path | None = None, label: str | None = None) -> None:
    page.goto(saved_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    dismiss_known_overlays(page)
    if label:
        write_debug_artifacts(page, debug_dir, label)


def wait_for_saved_item(page, saved_url: str, previous_keys: set[str], timeout_ms: int, debug_dir: Path | None = None) -> dict:
    elapsed = 0

    while elapsed < timeout_ms:
        open_saved_page(page, saved_url)

        items = collect_saved_items(page)
        for item in items:
            if item["key"] not in previous_keys:
                if debug_dir is not None:
                    write_debug_artifacts(page, debug_dir, "06-saved-item-found")
                return item

        page.wait_for_timeout(5000)
        elapsed += 5000

    raise RuntimeError("Timed out waiting for a new saved Grok video.")


def open_saved_item(page, item: dict) -> None:
    href = item.get("href")
    if href:
        page.goto(href, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        dismiss_known_overlays(page)
        return

    raise RuntimeError("Saved Grok item is missing a detail URL.")


def upload_images(page, image_paths: list[Path]) -> None:
    if not image_paths:
        return

    string_paths = [str(image_path) for image_path in image_paths]

    attach_button_selectors = [
        'button[aria-label*="Attach"]',
        'button[aria-label*="attach"]',
        'button[aria-label*="Upload"]',
        'button[aria-label*="upload"]',
        'button[data-testid*="upload"]',
    ]

    for _ in range(30):
        file_inputs = page.locator('input[type="file"]')
        try:
            if file_inputs.count():
                file_inputs.last.set_input_files(string_paths)
                page.wait_for_timeout(2000)
                return
        except Exception:
            pass

        for selector in attach_button_selectors:
            button = page.locator(selector).first
            try:
                if not button.count() or not button.is_visible():
                    continue
                with page.expect_file_chooser(timeout=5000) as chooser_info:
                    button.click()
                chooser_info.value.set_files(string_paths)
                page.wait_for_timeout(2000)
                return
            except Exception:
                continue

        page.wait_for_timeout(1000)

    raise RuntimeError("Could not find a Grok Imagine file upload control for the provided images.")


def click_generate(page) -> None:
    dismiss_known_overlays(page)

    clicked = page.evaluate(
        """
        () => {
          const form = document.querySelector('form.w-full');
          if (form) {
            const submitButton =
              form.querySelector('button[aria-label*="Submit"]') ||
              form.querySelector('button[type="submit"]');

            if (submitButton && !submitButton.disabled) {
              submitButton.click();
              return true;
            }

            if (typeof form.requestSubmit === 'function') {
              form.requestSubmit();
              return true;
            }
          }

          const composer =
            document.querySelector('textarea[placeholder*="Describe"]') ||
            document.querySelector('textarea[placeholder*="Prompt"]') ||
            document.querySelector('textarea[placeholder*="Message"]') ||
            document.querySelector('textarea[data-testid="composer-text-input"]') ||
            document.querySelector('#prompt-textarea') ||
            document.querySelector('div[contenteditable="true"][role="textbox"]') ||
            document.querySelector('div[contenteditable="true"]');

          const composerRect = composer ? composer.getBoundingClientRect() : null;
          let container = composer;
          while (container && container.parentElement) {
            const rect = container.getBoundingClientRect();
            if (rect.width >= 500 && rect.height >= 90 && rect.top >= window.innerHeight / 2 - 100) {
              break;
            }
            container = container.parentElement;
          }

          if (container) {
            const rect = container.getBoundingClientRect();
            const x = rect.right - 28;
            const y = rect.bottom - 28;
            const target = document.elementFromPoint(x, y);
            if (target) {
              target.dispatchEvent(new MouseEvent('mousemove', { bubbles: true, clientX: x, clientY: y }));
              target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: x, clientY: y }));
              target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: x, clientY: y }));
              target.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: x, clientY: y }));
              return true;
            }
          }

          const candidates = Array.from(
            document.querySelectorAll('button, [role="button"], div[tabindex], span[tabindex]')
          ).filter((element) => {
            const rect = element.getBoundingClientRect();
            if (!rect.width || !rect.height) return false;
            if (!composerRect) return false;
            const text = (element.innerText || element.textContent || '').trim();
            const ariaLabel = element.getAttribute('aria-label') || '';
            const nearComposer =
              rect.right >= composerRect.right - 120 &&
              rect.top >= composerRect.top - 40 &&
              rect.bottom <= composerRect.bottom + 140;
            const likelySubmit =
              text === '' ||
              /send|generate|create/i.test(text) ||
              /send|generate|create/i.test(ariaLabel);
            return nearComposer && likelySubmit;
          }).sort((left, right) => right.getBoundingClientRect().right - left.getBoundingClientRect().right);

          const target = candidates[0];
          if (!target) {
            return false;
          }

          target.click();
          return true;
        }
        """
    )
    if clicked:
        page.wait_for_timeout(1000)
        return

    selectors = [
        'button[aria-label*="Submit"]:not([disabled])',
        'button[aria-label*="Generate"]:not([disabled])',
        'button[data-testid="send-button"]:not([disabled])',
        'button[aria-label*="Send"]:not([disabled])',
        'button[type="submit"]:not([disabled])',
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
                          if (button) button.click();
                        }
                        """,
                        selector,
                    )
                    return
                except Exception:
                    continue

    page.keyboard.press("Enter")


def wait_for_generation_start(page, timeout_ms: int = 15000) -> None:
    elapsed = 0

    while elapsed < timeout_ms:
        state = generation_state(page)
        if state["isSubscribePrompt"]:
            raise RuntimeError("Grok redirected to the subscription/upgrade prompt instead of starting generation.")
        if state["hasServerFailedToast"]:
            raise RuntimeError("Grok returned 'Server failed to respond' while submitting the generation.")
        if state["hasProgress"]:
            return
        if "/imagine/post/" in page.url:
            return

        page.wait_for_timeout(1000)
        elapsed += 1000


def wait_for_new_video(page, previous_src: str | None, timeout_ms: int) -> dict:
    elapsed = 0
    stable_src = None
    stable_count = 0

    while elapsed < timeout_ms:
        state = generation_state(page)
        video = state.get("video")
        video_src = resolve_video_src(video)
        has_new_video = bool(video_src) and video_src != previous_src
        has_dimensions = bool(video and video["videoWidth"] > 0 and video["videoHeight"] > 0)
        is_ready = bool(video and video["readyState"] >= 3)

        if video_src and video_src == stable_src:
            stable_count += 1
        else:
            stable_src = video_src
            stable_count = 0

        if has_new_video and has_dimensions and is_ready and stable_count >= 2 and not state["hasProgress"]:
            return state

        page.wait_for_timeout(2000)
        elapsed += 2000

    raise RuntimeError("Timed out waiting for the generated video to finish.")


def has_download_button(page) -> bool:
    selectors = [
        'button[aria-label*="Download"]',
        'button[aria-label*="download"]',
        'a[download]',
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                return True
        except Exception:
            continue
    return False


def post_video_ready_state(page) -> dict:
    return page.evaluate(
        """
        () => {
          const visibleText = Array.from(document.querySelectorAll('button, span, div, p'))
            .map((element) => (element.innerText || element.textContent || '').trim())
            .filter(Boolean)
            .slice(0, 200);
          const video = document.querySelector('video');
          const videoSrc = video ? (video.currentSrc || video.src || null) : null;
          return {
            hasDownloadButton: Boolean(
              document.querySelector('button[aria-label*="Download"], button[aria-label*="download"], a[download]')
            ),
            hasGeneratingText: visibleText.some((text) => /generating/i.test(text)),
            hasCancelVideo: visibleText.some((text) => /cancel video/i.test(text)),
            videoSrc,
          };
        }
        """
    )


def wait_for_post_download(page, timeout_ms: int) -> None:
    elapsed = 0
    while elapsed < timeout_ms:
        state = post_video_ready_state(page)
        if state["hasDownloadButton"] and not state["hasGeneratingText"] and not state["hasCancelVideo"] and state["videoSrc"]:
            return
        page.wait_for_timeout(2000)
        elapsed += 2000

    raise RuntimeError("Timed out waiting for the finished Grok post page video.")


def download_post_video_via_cdp(page, output_path: Path, timeout_ms: int = 45000) -> None:
    post_url = page.url
    capture_page = page.context.new_page()
    capture_page.set_viewport_size({"width": 1600, "height": 1200})
    cdp = page.context.new_cdp_session(capture_page)
    cdp.send("Network.enable")

    matches: list[dict] = []

    def on_response(params: dict) -> None:
        response = params.get("response", {})
        url = response.get("url", "")
        mime_type = response.get("mimeType", "")
        status = int(response.get("status", 0) or 0)
        if ".mp4" not in url:
            return
        if params.get("type") != "Media":
            return
        if not mime_type.startswith("video/"):
            return
        if status not in {200, 206}:
            return
        matches.append(
            {
                "request_id": params["requestId"],
                "url": url,
                "status": status,
            }
        )

    cdp.on("Network.responseReceived", on_response)

    capture_page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
    capture_page.wait_for_timeout(3000)

    elapsed = 0
    last_error: Exception | None = None
    while elapsed < timeout_ms:
        for match in reversed(matches):
            try:
                body = cdp.send("Network.getResponseBody", {"requestId": match["request_id"]})
                payload = body.get("body", "")
                if not payload:
                    continue
                if body.get("base64Encoded"):
                    video_bytes = base64.b64decode(payload)
                else:
                    video_bytes = payload.encode("utf-8")
                if len(video_bytes) < 1024:
                    continue
                output_path.write_bytes(video_bytes)
                capture_page.close()
                return
            except Exception as exc:
                last_error = exc

        capture_page.wait_for_timeout(1000)
        elapsed += 1000

    capture_page.close()
    if last_error is not None:
        raise RuntimeError(f"Failed to capture Grok post video bytes via CDP: {last_error}") from last_error
    raise RuntimeError("Timed out waiting for Grok post video bytes via CDP.")


def download_generated_video(page, output_path: Path) -> None:
    video_selector = "video"
    page.locator(video_selector).last.hover()
    page.wait_for_timeout(500)

    try:
        download_button = page.locator('button[aria-label*="Download"], button[aria-label*="download"]').last
        if not download_button.count():
            raise RuntimeError("Download button not found.")
        with page.expect_download(timeout=20000) as download_info:
            download_button.click(force=True)
        download_info.value.save_as(str(output_path))
        return
    except Exception:
        state = generation_state(page)
        video_src = resolve_video_src(state.get("video"))
        if not video_src:
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
            video_src,
        )
        if isinstance(data_url, str) and data_url.startswith("data:video/"):
            payload = data_url.split(",", 1)[1]
            output_path.write_bytes(base64.b64decode(payload))
            return

        raise RuntimeError("Failed to download generated video.")


def download_saved_video(page, output_path: Path) -> None:
    try:
        page.locator("video").first.hover(timeout=5000)
    except Exception:
        pass

    try:
        button = page.locator('button[aria-label*="Download"], button[aria-label*="download"], a[download]').last
        if not button.count():
            raise RuntimeError("Download button not found.")
        with page.expect_download(timeout=20000) as download_info:
            button.click(force=True)
        download_info.value.save_as(str(output_path))
        return
    except Exception:
        pass

    try:
        video_src = page.evaluate(
            """
            () => {
              const video = document.querySelector('video');
              if (!video) return null;
              return video.currentSrc || video.src || null;
            }
            """
        )
        if not video_src:
            raise RuntimeError("Saved Grok video source not found.")
        download_url_to_path(page, video_src, output_path)
        if output_path.exists() and output_path.stat().st_size > 0:
            return
    except Exception:
        pass

    raise RuntimeError("Failed to download saved Grok video.")


def generate_video(
    *,
    prompt: str,
    output: str,
    images: list[str] | None = None,
    profile: str | None = None,
    url: str = "https://grok.com/imagine",
    saved_url: str = "https://grok.com/imagine/saved",
    timeout_ms: int = 420000,
    headless: bool = False,
    debug_dir: str | None = None,
) -> Path:
    profile_path = Path(profile).expanduser().resolve() if profile else default_profile_path()
    output_path = resolve_output_path(output)
    image_paths = resolve_image_paths(images or [])
    debug_path = make_debug_dir(debug_dir)
    ensure_dir(profile_path)
    cleanup_profile_locks(profile_path)
    executable_path = chrome_executable_path()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=headless,
            executable_path=str(executable_path) if executable_path else None,
            no_viewport=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--window-size=1600,1200",
                "--start-maximized",
                "--force-device-scale-factor=1",
                "--high-dpi-support=1",
            ],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        saved_page = browser.new_page()
        page.set_viewport_size({"width": 1600, "height": 1200})
        saved_page.set_viewport_size({"width": 1600, "height": 1200})
        try:
            open_saved_page(saved_page, saved_url, debug_path, "00-saved-baseline")
            baseline_items = collect_saved_items(saved_page)
            baseline_keys = {item["key"] for item in baseline_items}

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            dismiss_known_overlays(page)
            for _ in range(3):
                reveal_grok_input(page, grok_zoom=0.8)
                page.wait_for_timeout(800)
            write_debug_artifacts(page, debug_path, "01-after-load")

            upload_images(page, image_paths)
            write_debug_artifacts(page, debug_path, "02-after-upload")
            ensure_video_mode(page)
            for _ in range(2):
                reveal_grok_input(page, grok_zoom=0.8)
                page.wait_for_timeout(500)
            write_debug_artifacts(page, debug_path, "03-after-video-mode")
            enter_prompt(page, prompt)
            write_debug_artifacts(page, debug_path, "04-after-prompt")
            click_generate(page)
            write_debug_artifacts(page, debug_path, "05-after-generate")
            wait_for_generation_start(page)
            if "/imagine/post/" in page.url:
                wait_for_post_download(page, min(timeout_ms, 120000))
                write_debug_artifacts(page, debug_path, "06-post-download-ready")
                download_post_video_via_cdp(page, output_path, timeout_ms=min(timeout_ms, 45000))
                write_debug_artifacts(page, debug_path, "07-after-download")
                return output_path
            saved_item = wait_for_saved_item(saved_page, saved_url, baseline_keys, timeout_ms, debug_path)
            open_saved_item(saved_page, saved_item)
            write_debug_artifacts(saved_page, debug_path, "07-saved-item-open")
            download_saved_video(saved_page, output_path)
            write_debug_artifacts(saved_page, debug_path, "08-after-download")
        except Exception:
            write_debug_artifacts(page, debug_path, "99-error")
            raise
        finally:
            browser.close()

    return output_path


def main() -> None:
    args = parse_args()
    output_path = generate_video(
        prompt=args.prompt,
        output=args.output,
        images=args.image,
        profile=args.profile,
        url=args.url,
        saved_url=args.saved_url,
        timeout_ms=args.timeout_ms,
        headless=args.headless,
        debug_dir=args.debug_dir,
    )
    profile_path = Path(args.profile).expanduser().resolve() if args.profile else default_profile_path()
    print(f"Saved video: {output_path}")
    print(f"Profile used: {profile_path}")


if __name__ == "__main__":
    main()

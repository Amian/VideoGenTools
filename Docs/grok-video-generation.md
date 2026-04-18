# Standalone Grok Imagine Video Script

This project includes a standalone Playwright-based script that opens Grok Imagine, submits a prompt with optional reference images, then retrieves the finished video from Grok Saved.

## Install

```bash
cd /Users/anum/Development/VideoRecreator
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
```

## Run

```bash
python3 scripts/grok_video_generation.py \
  --prompt "Create a cinematic slow pan across this scene with subtle ambient motion" \
  --image ./refs/frame.png \
  --output ./output-videos
```

You can attach multiple reference images:

```bash
python3 scripts/grok_video_generation.py \
  --prompt "Use these references to generate a short realistic video with soft camera motion" \
  --image ./refs/frame-1.png \
  --image ./refs/frame-2.png \
  --output ./output-videos/clip-001.mp4
```

The script submits on `https://grok.com/imagine` and then polls `https://grok.com/imagine/saved` for the next new item before downloading it.

## One-Time Login

```bash
python3 scripts/open_free_image_playwright.py --url "https://grok.com/imagine"
```

Sign into Grok once in the opened browser window. Later runs reuse the same persistent Chrome profile.

## Clip Batch Workflow

To generate one video per clip in a run:

```bash
python3 scripts/generate_clip_videos_with_grok.py --run-id run_011
```

This batch script is intentionally sequential:

- it submits clip `1`, waits for the next new Saved item, downloads it, and records it as clip `1`
- then it moves to clip `2`
- and so on

That is the mapping rule. It does not rely on completion order across multiple concurrent jobs.

## Notes

- The single-video script opens `https://grok.com/imagine` and retrieves finished videos from `https://grok.com/imagine/saved`.
- It uses a persistent Playwright/Chrome profile so your Grok login can be reused.
- Default profile path is `~/Library/Application Support/Google/Chrome/ImageGenProfile` on macOS.
- First run should be non-headless so you can sign in if needed.
- The clip batch script stores outputs in `data/runs/<run_id>/animations/clip_XXXX.mp4`.
- Mapping is tracked in `data/runs/<run_id>/manifests/clips.json`.
- Per-attempt logs are written to `data/runs/<run_id>/logs/clip-video-generation.jsonl`.

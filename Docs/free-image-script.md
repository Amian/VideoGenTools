# Standalone ChatGPT Image Script

This project includes a standalone Camoufox-based script that opens ChatGPT, submits an image prompt, waits for image generation to finish, and downloads the result.

## Install

```bash
cd /Users/anum/Development/VideoRecreator
python3 -m pip install -r requirements.txt
python3 -m camoufox fetch
```

## Run

```bash
python3 scripts/chatgpt_free_image.py \
  --prompt "a cinematic portrait of an antique dealer in warm window light" \
  --output ./output-images
```

You can also write to a specific file:

```bash
python3 scripts/chatgpt_free_image.py \
  --prompt "a studio product photo of a porcelain teapot on linen" \
  --output ./output-images/teapot.png
```

You can attach one or more reference images:

```bash
python3 scripts/chatgpt_free_image.py \
  --prompt "turn these references into a clean product hero image" \
  --image ./refs/angle-1.jpg \
  --image ./refs/angle-2.jpg \
  --image ./refs/detail.jpg \
  --output ./output-images/hero.png
```

## Notes

- The script uses a persistent Camoufox profile so your ChatGPT login can be reused.
- Default profile path is `~/.camoufox/ImageGenProfile`.
- First run should be non-headless so you can sign in if needed.
- The script is intentionally simple: one prompt in, one downloaded image out.
- If the composer is slow to load, the script waits at least 30 seconds before failing.
- `--image` is optional and repeatable, so one prompt can include multiple uploaded reference images.

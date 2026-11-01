"""Generate images with Together AI FLUX.1 [schnell] Free.

Env vars:
  TOGETHER_API_KEY  (required)  - from api.together.ai
  NUM_IMAGES        (optional)  - default 50
  MODEL             (optional)  - default black-forest-labs/FLUX.1-schnell-Free
  WIDTH / HEIGHT    (optional)  - default 1024
  STEPS             (optional)  - default 4 (schnell max is 4)
  SLEEP_SECONDS     (optional)  - default 6.5 (free endpoint limit ~10 img/min)
"""
import base64
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API_URL = "https://api.together.ai/v1/images/generations"

API_KEY = os.environ.get("TOGETHER_API_KEY", "").strip()
NUM_IMAGES = int(os.environ.get("NUM_IMAGES") or 50)
MODEL = os.environ.get("MODEL") or "black-forest-labs/FLUX.1-schnell-Free"
WIDTH = int(os.environ.get("WIDTH") or 1024)
HEIGHT = int(os.environ.get("HEIGHT") or 1024)
STEPS = int(os.environ.get("STEPS") or 4)
SLEEP_SECONDS = float(os.environ.get("SLEEP_SECONDS") or 6.5)
MAX_RETRIES = 5

DEFAULT_PROMPTS = [
    "a misty mountain village at sunrise, cinematic lighting, highly detailed",
    "a red vintage car parked on a rainy neon-lit street, photorealistic",
    "a bowl of fresh fruit on a wooden table, soft natural light, 35mm photo",
    "a futuristic city skyline at dusk, flying vehicles, concept art",
    "a cozy reading nook with a window and plants, warm light, interior photo",
    "a lone lighthouse on a rocky coast during a storm, dramatic sky",
    "a street food stall at night in an Indian market, vibrant colors, photorealistic",
    "a astronaut walking on a colorful alien planet, wide shot, sci-fi illustration",
    "a tiger resting in tall grass, golden hour, wildlife photography",
    "a minimalist flat illustration of a mountain lake, pastel colors",
]


def load_prompts():
    path = Path("prompts.txt")
    if path.exists():
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
        if lines:
            return lines
    return DEFAULT_PROMPTS


def generate_one(prompt, seed):
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "width": WIDTH,
        "height": HEIGHT,
        "steps": STEPS,
        "n": 1,
        "seed": seed,
        "response_format": "b64_json",
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        except requests.RequestException as exc:
            wait = 5 * attempt
            print(f"  network error ({exc}); retry {attempt}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            item = resp.json()["data"][0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            if item.get("url"):
                return requests.get(item["url"], timeout=120).content
            raise RuntimeError(f"No image in response: {str(item)[:200]}")

        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else 10 * attempt
            print(f"  HTTP {resp.status_code}; retry {attempt}/{MAX_RETRIES} in {wait:.0f}s")
            time.sleep(wait)
            continue

        # 400/401/403/404 etc. - not worth retrying
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")

    raise RuntimeError("Gave up after retries")


def main():
    if not API_KEY:
        sys.exit("TOGETHER_API_KEY is not set. Add it as a GitHub Actions secret.")

    prompts = load_prompts()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path("output") / day
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Model: {MODEL} | {WIDTH}x{HEIGHT} | steps={STEPS} | target={NUM_IMAGES} images")

    log = []
    ok = 0
    for i in range(1, NUM_IMAGES + 1):
        prompt = prompts[(i - 1) % len(prompts)]
        seed = random.randint(1, 2**31 - 1)
        print(f"[{i}/{NUM_IMAGES}] {prompt[:70]}")
        started = time.time()
        try:
            data = generate_one(prompt, seed)
            file_path = out_dir / f"img_{i:03d}.png"
            file_path.write_bytes(data)
            ok += 1
            log.append({"index": i, "file": file_path.name, "prompt": prompt, "seed": seed, "status": "ok"})
            print(f"  saved {file_path} ({len(data)//1024} KB)")
        except Exception as exc:  # keep going; record failure
            log.append({"index": i, "prompt": prompt, "seed": seed, "status": "failed", "error": str(exc)})
            print(f"  FAILED: {exc}")
            # Stop early if the key/model is clearly wrong (first call fails with 401/403/404)
            if ok == 0 and i >= 3 and all(e["status"] == "failed" for e in log):
                print("First 3 requests all failed - stopping early.")
                break

        # stay under the free-tier rate limit
        elapsed = time.time() - started
        if i < NUM_IMAGES and elapsed < SLEEP_SECONDS:
            time.sleep(SLEEP_SECONDS - elapsed)

    (out_dir / "log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = f"### Image generation\n\n- Model: `{MODEL}`\n- Size: {WIDTH}x{HEIGHT}\n- Success: **{ok}/{NUM_IMAGES}**\n"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(summary)
    print(summary)

    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

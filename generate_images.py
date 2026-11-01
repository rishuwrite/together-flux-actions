"""Generate images from free providers with automatic fallback.

Order (default): Cloudflare Workers AI (FLUX.1 schnell) -> Pollinations -> Together (optional, paid).
When a provider runs out of its daily quota (or is not configured), the script moves to the next one.

Env vars
  NUM_IMAGES                 default 50
  PROVIDERS                  default "cloudflare,pollinations,together"
  STEPS                      default 4 (FLUX schnell: 1-8)
  CLOUDFLARE_ACCOUNT_ID      } for cloudflare
  CLOUDFLARE_API_TOKEN       }
  POLLINATIONS_API_KEY       optional (anonymous works but is slow: ~1 image / 15 s)
  TOGETHER_API_KEY           optional (paid account needed)
"""
import base64
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests

NUM_IMAGES = int(os.environ.get("NUM_IMAGES") or 50)
PROVIDERS = [p.strip().lower() for p in (os.environ.get("PROVIDERS") or "cloudflare,pollinations,together").split(",") if p.strip()]
STEPS = max(1, min(int(os.environ.get("STEPS") or 4), 8))
MAX_RETRIES = 4
MAX_CONSECUTIVE_FAILS = 3

QUOTA_MARKERS = ("daily free allocation", "4006", "insufficient credit", "out of credits", "quota")

DEFAULT_PROMPTS = [
    "a misty mountain village at sunrise, cinematic lighting, highly detailed",
    "a red vintage car parked on a rainy neon-lit street, photorealistic",
    "a bowl of fresh fruit on a wooden table, soft natural light, 35mm photo",
]


class QuotaExhausted(Exception):
    """Provider's free allowance is used up for today."""


class ProviderDisabled(Exception):
    """Provider is not configured or credentials are wrong."""


def load_prompts():
    path = Path("prompts.txt")
    if path.exists():
        lines = [l.strip() for l in path.read_text(encoding="utf-8").splitlines()]
        lines = [l for l in lines if l and not l.startswith("#")]
        if lines:
            return lines
    return DEFAULT_PROMPTS


def sniff_ext(data: bytes):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def http(method, url, **kw):
    """requests with retry. Raises QuotaExhausted / ProviderDisabled / RuntimeError."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, timeout=120, **kw)
        except requests.RequestException as exc:
            wait = 5 * attempt
            print(f"    network error ({exc}); retry {attempt}/{MAX_RETRIES} in {wait}s")
            time.sleep(wait)
            continue

        if resp.status_code == 200:
            return resp

        body = resp.text[:400]
        low = body.lower()
        if resp.status_code == 402 or any(m in low for m in QUOTA_MARKERS):
            raise QuotaExhausted(f"HTTP {resp.status_code}: {body}")
        if resp.status_code in (401, 403):
            raise ProviderDisabled(f"HTTP {resp.status_code}: {body}")
        if resp.status_code in (429, 500, 502, 503, 504):
            ra = resp.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else 10 * attempt
            print(f"    HTTP {resp.status_code}; retry {attempt}/{MAX_RETRIES} in {wait:.0f}s")
            time.sleep(wait)
            continue
        raise RuntimeError(f"HTTP {resp.status_code}: {body}")
    raise RuntimeError("gave up after retries")


# ---------------------------------------------------------------- providers
def gen_cloudflare(prompt, seed):
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not acct or not token:
        raise ProviderDisabled("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set")
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    resp = http(
        "POST", url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"prompt": prompt, "steps": STEPS, "seed": seed},
    )
    if resp.headers.get("content-type", "").startswith("image/"):
        return resp.content
    data = resp.json()
    if not data.get("success", True) or "result" not in data:
        raise RuntimeError(f"unexpected response: {str(data)[:300]}")
    return base64.b64decode(data["result"]["image"])


def gen_pollinations(prompt, seed):
    key = os.environ.get("POLLINATIONS_API_KEY", "").strip()
    q = urllib.parse.quote(prompt)
    params = {"width": 1024, "height": 1024, "model": "flux", "seed": seed, "nologo": "true"}
    if key:
        url = f"https://gen.pollinations.ai/image/{q}"
        params["key"] = key
    else:
        url = f"https://image.pollinations.ai/prompt/{q}"
    return http("GET", url, params=params).content


def gen_together(prompt, seed):
    key = os.environ.get("TOGETHER_API_KEY", "").strip()
    if not key:
        raise ProviderDisabled("TOGETHER_API_KEY not set")
    model = os.environ.get("TOGETHER_MODEL") or "black-forest-labs/FLUX.1-schnell"
    resp = http(
        "POST", "https://api.together.ai/v1/images/generations",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "prompt": prompt, "width": 1024, "height": 1024,
              "steps": min(STEPS, 4), "n": 1, "seed": seed, "response_format": "b64_json"},
    )
    item = resp.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    return requests.get(item["url"], timeout=120).content


GENERATORS = {"cloudflare": gen_cloudflare, "pollinations": gen_pollinations, "together": gen_together}
MIN_INTERVAL = {
    "cloudflare": 0.3,
    "pollinations": 3 if os.environ.get("POLLINATIONS_API_KEY") else 16,  # anonymous ~1 req / 15 s
    "together": 6.5,
}


# --------------------------------------------------------------------- main
def main():
    unknown = [p for p in PROVIDERS if p not in GENERATORS]
    if unknown:
        sys.exit(f"Unknown provider(s): {unknown}. Choose from {list(GENERATORS)}")

    prompts = load_prompts()
    out_dir = Path("output") / datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)

    active = list(PROVIDERS)
    fails = {p: 0 for p in PROVIDERS}
    last_call = {p: 0.0 for p in PROVIDERS}
    per_provider = {p: 0 for p in PROVIDERS}
    log, ok = [], 0
    print(f"Target: {NUM_IMAGES} images | providers: {active}")

    for i in range(1, NUM_IMAGES + 1):
        if not active:
            print("No providers left - stopping.")
            break
        prompt = prompts[(i - 1) % len(prompts)]
        seed = random.randint(1, 2**31 - 1)
        done = False

        for provider in list(active):
            wait = MIN_INTERVAL[provider] - (time.time() - last_call[provider])
            if wait > 0:
                time.sleep(wait)
            print(f"[{i}/{NUM_IMAGES}] {provider}: {prompt[:60]}")
            try:
                data = GENERATORS[provider](prompt, seed)
                last_call[provider] = time.time()
                ext = sniff_ext(data)
                if not ext:
                    raise RuntimeError(f"response is not an image ({len(data)} bytes)")
                path = out_dir / f"img_{i:03d}.{ext}"
                path.write_bytes(data)
                fails[provider] = 0
                per_provider[provider] += 1
                ok += 1
                log.append({"index": i, "file": path.name, "provider": provider, "prompt": prompt, "seed": seed})
                print(f"    saved {path} ({len(data)//1024} KB)")
                done = True
                break
            except QuotaExhausted as exc:
                last_call[provider] = time.time()
                print(f"    {provider} quota used up -> switching. ({str(exc)[:120]})")
                active.remove(provider)
            except ProviderDisabled as exc:
                print(f"    {provider} disabled -> switching. ({str(exc)[:120]})")
                active.remove(provider)
            except Exception as exc:
                last_call[provider] = time.time()
                fails[provider] += 1
                print(f"    {provider} failed ({fails[provider]}/{MAX_CONSECUTIVE_FAILS}): {str(exc)[:200]}")
                if fails[provider] >= MAX_CONSECUTIVE_FAILS:
                    print(f"    disabling {provider} for this run")
                    active.remove(provider)
        if not done:
            log.append({"index": i, "prompt": prompt, "status": "failed"})

    (out_dir / "log.json").write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"### Image generation", "", f"- Success: **{ok}/{NUM_IMAGES}**"]
    lines += [f"- {p}: {n}" for p, n in per_provider.items()]
    summary = "\n".join(lines) + "\n"
    print(summary)
    sp = os.environ.get("GITHUB_STEP_SUMMARY")
    if sp:
        with open(sp, "a", encoding="utf-8") as f:
            f.write(summary)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

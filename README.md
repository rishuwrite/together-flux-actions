# together-flux-actions

Generates images with **Together AI – FLUX.1 [schnell] Free** from a GitHub Action
and uploads them as a downloadable artifact.

## Setup

1. **Get a Together AI key**: sign up at <https://api.together.ai>, then Settings → API Keys → create a key. No credit card needed for the free endpoint.
2. **Add the secret in GitHub**: repo → Settings → Secrets and variables → Actions → *New repository secret*
   - Name: `TOGETHER_API_KEY`
   - Secret: your key
3. **Run it**: repo → Actions → *Generate images (Together FLUX schnell)* → *Run workflow* (default 50 images).
4. **Download**: open the finished run → *Artifacts* → `images-<run number>` (kept 7 days).

## Files

| File | Purpose |
|---|---|
| `generate_images.py` | Calls Together API, saves PNGs + `log.json` |
| `prompts.txt` | Your prompts, one per line (optional) |
| `.github/workflows/generate-images.yml` | The Action |

## Settings (env vars in the workflow)

`NUM_IMAGES` (50), `WIDTH`/`HEIGHT` (1024), `STEPS` (4), `SLEEP_SECONDS` (6.5), `MODEL`.

## Notes

- The free endpoint is limited to roughly 10 images/min, so 50 images take ~6 minutes.
- If every request fails with 401/403 check the secret; 404 means the free model is no longer offered - set `MODEL` to a paid one such as `black-forest-labs/FLUX.1-schnell`.
- Never commit your API key; only use Actions secrets.

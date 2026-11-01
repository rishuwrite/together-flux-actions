# free-image-actions

Generates images from a GitHub Action using **Cloudflare Workers AI (FLUX.1 schnell)** first,
then falls back to **Pollinations**, and optionally **Together AI** (paid).

## Secrets (repo -> Settings -> Secrets and variables -> Actions -> New repository secret)

| Secret | Required | Where to get it |
|---|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | yes | dash.cloudflare.com -> AI -> Workers AI -> "Use REST API" |
| `CLOUDFLARE_API_TOKEN`  | yes | same page -> "Create a Workers AI API Token" |
| `POLLINATIONS_API_KEY`  | no  | enter.pollinations.ai (faster than anonymous) |
| `TOGETHER_API_KEY`      | no  | api.together.ai (needs prepaid credits) |

## Run
Actions tab -> "Generate images (free providers)" -> Run workflow -> set count -> download artifact `images-<n>` (kept 7 days).

## Free limits
Cloudflare free plan: 10,000 Neurons/day (resets 00:00 UTC) = about 170 images at 1024x1024 / 4 steps.
When it runs out, the script switches to Pollinations automatically (anonymous: 1 image every 45 s).

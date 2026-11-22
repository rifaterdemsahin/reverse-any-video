# reverse-any-video

Paste a video link. Get the structure and timing of the video as numbers, a storyboard, a script to write, a
teleprompter version, an edit list and a HyperFrames project with placeholders. You fill in your own words and
render your own video in the same structure.

- **Live app:** https://reverse-any-video.fly.dev/
- **Admin area** (sign in with the owner's Azure account): https://reverse-any-video.fly.dev/admin
- **Agents:** read [`AGENTS.md`](AGENTS.md). The output rules are in [`schemas/output-contract.json`](schemas/output-contract.json).

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn server:app --reload            # http://localhost:8000
python -m unittest discover -s tests -v
python -m unittest discover -s evals -p "eval_*.py" -v
```

You need ffmpeg on the path. The DeepInfra key is optional. It adds the storyboard and the shot-level clip names.

## What the customer gets

One zip per job, `reverse-any-video-<job_id>.zip`.

| File | For | Needs |
|---|---|---|
| `video.json` | title, channel, date, a link to the thumbnail (not copied) | link or upload |
| `metrics.json` | length, pace, cut rate, shot length, hook timing, as numbers | link or upload |
| `script.md` | the script to write, one block per scene, with a word target | link or upload |
| `prompter.md` | the same script set out for a teleprompter | link or upload |
| `storyboard.png` | one card per scene: time, length, words | link or upload |
| `hyperframes_template.json` | the scene plan with `{{placeholders}}` and a timeline | link or upload |
| `hyperframes_prompt.md` | the style, the pacing and a prompt per scene | link or upload |
| `hyperframes_project.zip` | a HyperFrames project: scenes, storyboard reference, animated subtitles | link or upload |
| `README.md`, `AGENTS.md` | how to use the files, and instructions for an AI agent | link or upload |
| `edit_decision_list.edl` | one event per shot, for any editor | upload |
| `storyboard.md` | one panel per shot: on screen, camera, speech yes or no | upload and the AI key |

A link is read for captions and timing only. It is never downloaded. Uploads are analysed in full.

**Never included:** the source video, its frames, its transcript, or any sentence from the source. Those are kept
in Azure for the operator only.

## Pages

| Page | Who | What |
|---|---|---|
| `/` | customer | landing page |
| `/start` | customer | paste a link, see the price |
| `/pricing` | customer | cost breakdown and credit packs |
| `/account` | customer | sign in by email link, balance, buy credit |
| `/admin` | owner | analyzer |
| `/admin/outputs` | owner | every job, its files, who requested it |
| `/admin/sanity` | owner | live checks with fix hints |
| `/admin/guide`, `/admin/setup`, `/admin/settings` | owner | guides and every setting |

## Configuration

Settings are environment variables or Azure Key Vault secrets. The full list, with defaults, is on the
`/admin/settings` page. The ones you need first:

- `ACCESS_TOKEN` (secret): the password for the analyzer and the jobs API.
- `DEEPINFRA_API_KEY` (secret): the storyboard and the shot-level clip names.
- `AZURE_KEYVAULT_URL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`: how the app reads Key Vault.
- `SESSION_SECRET` (secret): signs the customer and admin sessions.
- `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`: payments, in test mode until `STRIPE_ALLOW_LIVE=1`.

Key Vault secret names are in [`docs/azure-setup.md`](docs/azure-setup.md).

## Deploy

```bash
fly auth login
fly deploy --ha=false
curl -s https://reverse-any-video.fly.dev/healthz
```

Every `.py` file at the top level is copied into the image, and so is `docs/`. A new module needs no Dockerfile
change. `.github/workflows/fly-deploy.yml` runs the tests on push to `main`.

## Command line

```bash
python reverse_video.py "https://www.youtube.com/watch?v=KnqTiAXUH7M"
python reverse_video.py my_clip.mp4 --transcript my_clip.srt
```

Add `--local-report` to also write `analysis.json`, `transcript_script.md`, `SKILL.md` and `report.html`. Those
files contain transcript text, so the server never writes them.

## Tests and evals

- `tests/`: unit and API tests. The API tests need `httpx2` on recent Starlette versions.
- `evals/`: checks the rules in `AGENTS.md` against real outputs. No transcript wording in any output, numbers
  only in `metrics.json`, the template is a valid plan, pricing invariants, and every page and menu link.

## Project notes

- Pricing and its sources: [`pricing.py`](pricing.py). Rates are third-party listings. Check them before you quote.
- Cleanup and open decisions: [`admin/cleanup-review.md`](admin/cleanup-review.md) (internal, not for the public repo).
- Status and next steps: [`todo.md`](todo.md).

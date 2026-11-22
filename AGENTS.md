# AGENTS.md: instructions for an AI agent working on this repo

Read this first. It tells you what the project is, the rules that must not break, and how to run, test and deploy it.

## What this project is

A paid analysis service. A customer gives a video link (or uploads a video). The app measures how the video is built
and returns a package they can use to make their own video in HyperFrames:

- `storyboard.md`: one panel per shot. Speech is shown as yes or no. Never the words.
- `edit_decision_list.edl`: CMX 3600 EDL, one event per shot. Needs an uploaded video.
- `metrics.json`: length, pace, cut rate, shot length, hook timing, as numbers.
- `hyperframes_prompt.md`: style, pacing and a prompt per scene.
- `hyperframes_template.json`: scene plan with placeholders such as `{{headline_2}}`.

Not delivered, ever: the source video, its frames, its transcript, or any sentence from the source.

## Rules that must hold

1. **No source text in outputs.** Descriptions, storyboard panels and prompts are written in our own words. Speech is
   reported as "yes" or "no". Do not add a field that carries transcript text.
2. **No YouTube downloads.** `server.py` always passes `download=False` for URLs. Links are read for captions and timing
   only. Uploaded videos are analysed in full.
3. **Internal files stay internal.** The source video and `frames.zip` go to Azure under `internal/<job_id>/`
   (`storage.save_internal`). They are never in `OUTPUT_FILES` and never in the bundle.
4. **Secrets never in the repo, the page or chat.** Settings come from environment variables or Azure Key Vault
   (`vault.py`). The public pages (`docs/`) must not contain any secret value. The analyzer keeps the access token
   in the browser's `localStorage` only.
5. **Prices show cents, never $0.00.** `pricing._cent_up` rounds each amount up with a $0.01 floor. The customer pays
   the sum of the lines they see.
6. **Do not commit or deploy without the owner's go-ahead.** Ask first.
7. **Do not bypass a permission denial.** If a command is blocked, stop, say what was blocked and why, and let the
   owner decide.

## Output contract (machine-readable)

`schemas/output-contract.json` is the source of truth for what a job delivers. Read it before changing any output.
- `files[]`: each deliverable, its format, the inputs that produce it (`link`, `upload`, AI key), and what it holds.
- `$defs.metrics` and `$defs.template`: JSON Schemas. `metrics.json` and `hyperframes_template.json` must match them.
- `availability`: a link gives metrics, prompt and template. An upload gives all five.
- `never_delivered`: the source video, frames, transcript and any source words. Evals in `evals/` enforce this.

If you add or rename an output, update `schemas/output-contract.json`, the `OUTPUT_FILES` set in `server.py`, the
README table, and the page text in `docs/app.html`, then run the evals.

## Where things are

| Path | What it is |
|---|---|
| `server.py` | FastAPI app: jobs, bundle, projects, quote, pages, routes |
| `reverse_video.py` | the analyser: transcript, script metrics, ffmpeg shots, `run()` |
| `reverse_llm.py` | storyboard (vision model) and EDL, frames for analysis |
| `deepinfra.py` | stdlib client for DeepInfra chat calls |
| `template.py` | HyperFrames template and prompts from measured structure |
| `pricing.py` | cost calculator and price (margin, fixed fees, cent rounding) |
| `storage.py` | Azure Blob: projects and internal files |
| `vault.py` | reads secrets from Azure Key Vault, env vars first |
| `gmail.py` | sends mail through the Gmail API (not yet wired to jobs) |
| `create_video.py` | older plan-and-render pipeline (Claude plan, HyperFrames build) |
| `docs/` | every page: `app.html` (analyzer, built into `index.html`), `landing.html`, `start.html`, `pricing.html`, `setup.html`, `settings.html`, `menu.js` (shared menu) |
| `docs/build.py` | wraps `app.html` into `index.html`. Run it after editing `app.html` |
| `admin/` | internal documents, for the owner only |
| `todo.md` | what is done and what is missing |
| `tests/` | unit tests; `test_server.py` and `test_projects.py` need `httpx2` for the API tests |

## Run it locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn server:app --reload          # http://localhost:8000
```

ffmpeg must be on the path (`brew install ffmpeg`, `apt install ffmpeg`, or `winget install Gyan.FFmpeg`).

## Test

```bash
python -m unittest discover -s tests -v
```

Known environment issue: `fastapi.testclient` needs the `httpx2` package on recent Starlette. If the API tests are
skipped or error, run `pip install httpx2`. The pure-logic tests (`test_pricing`, `test_reverse_llm`,
`test_reverse_video`, `test_projects.StoreUnit`) do not need it.

## Settings

Every setting, its default and its purpose is on the `/settings` page of the running app, and in the README.
The ones an agent most often needs:

- `ACCESS_TOKEN` (secret): the analyzer and API password. Set with `fly secrets set`.
- `DEEPINFRA_API_KEY` (secret): turns on the storyboard. Without it, the other outputs still work.
- `AZURE_KEYVAULT_URL`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`: how the app reads Key Vault.
- `PRICE_MARGIN` (default 0.10), `FX_GBP_USD`, `STRIPE_FEE_PERCENT`, `STRIPE_FEE_FIXED`: pricing.

## Deploy (Fly.io)

```bash
fly deploy --ha=false                # app: reverse-any-video; the image copies every module listed in the Dockerfile
curl -s https://reverse-any-video.fly.dev/healthz
```

Any new `.py` module the server imports must be added to the `COPY` line in `Dockerfile`, or the app crashes on
start. This has happened before. Check `fly logs --app reverse-any-video` if the machine stops.

## Known gaps (see `todo.md`)

- Stripe checkout, the order flow and email on completion are not built.
- Order records live on the Fly machine's disk and are lost on restart.
- A link job produces no shots, so no EDL and no storyboard. Those need an upload.
- The HyperFrames render needs a render backend (`RENDER_BACKEND`, `SPRITES_TOKEN`) to produce a video.

## Working style

- Make changes in small steps and run the pure-logic tests after each one.
- Keep docs in step with code: when a setting or an output changes, update `README.md`, `docs/settings.html` and
  `docs/landing.html` if the customer sees it.
- Put internal notes in `admin/`, not in `docs/`, which is public.

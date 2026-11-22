# reverse-any-video

Reverse-engineer any video's **script** and **editing style** into numbers, turn the numbers into a
reusable `SKILL.md` blueprint, then have Claude write a **new** video in that style and render it with
[HyperFrames](https://hyperframes.heygen.com) on a [Fly.io Sprite](https://sprites.dev).

```
video ──► reverse_video.py ──► analysis.json + SKILL.md ──► Claude plan ──► HyperFrames project ──► MP4
           (measure)              (blueprint)              (your touches)     (HTML + GSAP)      (local or Sprite)
```

Starting base: [How to reverse engineer any editing style (Turned it into a skill)](https://www.youtube.com/watch?v=KnqTiAXUH7M)
by Taha El Harti. This repo is an independent, open implementation of the `/reverse-any-video` idea from that
video. See [`examples/KnqTiAXUH7M`](examples/KnqTiAXUH7M) for what has been captured from it so far.

## Links

- **Live app:** https://reverse-any-video.fly.dev/
- **First test video:** https://www.youtube.com/watch?v=KnqTiAXUH7M
- **First test output:** [`examples/KnqTiAXUH7M`](examples/KnqTiAXUH7M): `script.md`, `SKILL.md`, `analysis.json`, `report.html`

## What it measures

| From the transcript | From the video file (ffmpeg) |
|---|---|
| Words per minute, overall and per 30 s | Shot cuts (scene detection) |
| Hook: first ~15 s, classified (question, promise, number, story, contrarian) | Average, median, min and max shot length |
| Sections, split on pauses and transition words | Cuts per minute and per 30 s window |
| Open loops ("in a second", "stick around") | Silences: how tightly pauses were trimmed |
| Calls to action ("subscribe", "link in the description") | Keyframe contact sheet, one frame per shot |
| Questions, "you" vs "I", fillers, top vocabulary | |

## Ways to use it

### 1. In the browser

Open [`docs/index.html`](docs/index.html) (or enable GitHub Pages on `/docs`). Paste a transcript, optionally
load the video file, and it draws the timeline and writes the blueprint. Nothing leaves your machine.

### 2. Command line

```bash
pip install -r requirements.txt        # yt-dlp, deno, transcript API (plus the server's packages)
python reverse_video.py "https://www.youtube.com/watch?v=KnqTiAXUH7M" --download
```

Writes `out/<id>/analysis.json`, `script.md`, `SKILL.md` and `report.html`.

| Flag | Use |
|---|---|
| `--transcript FILE` | Your own transcript: VTT, SRT, YouTube json3, JSON, or text copied from YouTube's **Show transcript** panel |
| `--video FILE` | Analyse a local video file alongside a URL |
| `--download` | Download the video at ≤480p with yt-dlp for cut analysis |
| `--cookies cookies.txt` | Pass browser cookies to yt-dlp when YouTube asks you to sign in |
| `--scene-threshold 0.3` | ffmpeg scene score that counts as a cut; lower it for subtle cuts |

A local file works too: `python reverse_video.py my_edit.mp4 --transcript my_edit.srt`.

### 3. As a Claude Code skill

Open this repo in Claude Code and run `/reverse-any-video <url>`. The skill
([`.claude/skills/reverse-any-video/SKILL.md`](.claude/skills/reverse-any-video/SKILL.md)) runs the measurements,
reads the script, and writes a style blueprint you can save as your own `/<name>-style` skill. To use it in
every project, copy that folder to `~/.claude/skills/`.

### 4. As a web app on Fly.io

`server.py` serves the page plus a job API that fetches the URL, downloads the video and runs ffmpeg on the
server. The page shows a **Fetch and analyze URL** panel when it is served this way.

```bash
fly auth login
fly launch --copy-config --no-deploy --name reverse-any-video   # pick another name if taken
fly deploy --ha=false
```

Jobs live in memory, so keep one machine (`--ha=false`, or `fly scale count 1`).

YouTube often answers cloud IPs with "Sign in to confirm you're not a bot". Give the server a cookies.txt
exported from a browser that is signed in to YouTube (use a spare account):

```bash
fly secrets set YT_COOKIES="$(cat cookies.txt)"
```

To write scripts with Claude and render videos from the web page:

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...      # from platform.claude.com
fly secrets set SPRITES_TOKEN=...                 # from sprites.dev/account
```

Optional: `fly secrets set ACCESS_TOKEN=...` so only people with the token can start jobs (the page asks for it).

| Variable | Default | Meaning |
|---|---|---|
| `WORKERS` | 2 | analyses that run at once |
| `MAX_UPLOAD_MB` | 300 | largest video upload |
| `MAX_DURATION` | 1800 | longest video the server will download, in seconds |
| `JOB_TTL` | 3600 | seconds to keep finished jobs |
| `ALLOWED_URL_HOSTS` | YouTube hosts | comma-separated, or `*` for any site yt-dlp supports |
| `YT_COOKIES` | none | secret: cookies.txt contents |
| `ACCESS_TOKEN` | none | secret: required in `X-Access-Token` to start jobs |
| `ANTHROPIC_API_KEY` | none | secret: Claude writes the script (`CLAUDE_MODEL`, default `claude-opus-5-5`) |
| `SPRITES_TOKEN` | none | secret: render on a Fly.io Sprite |
| `RENDER_BACKEND` | auto | `sprite` when `SPRITES_TOKEN` is set, else `none`; or force `local` |
| `SPRITE_NAME` | rav-render | the Sprite that renders |

**Deploy on every push:** `.github/workflows/fly-deploy.yml` runs the tests, then `flyctl deploy` on `main`.
Create a token with `fly tokens create deploy` and add it as the repository secret `FLY_API_TOKEN`. Until
the secret exists, the deploy step is skipped.

**Run the server locally:** `pip install -r requirements.txt && uvicorn server:app --reload`, then open
http://localhost:8000. The API is documented at `/api/docs`.

### 5. Create a new video in the style

`create_video.py` (and the **Create** section of the web page) takes the measurements, a brief and your
touches, and produces a new video:

1. **Plan:** Claude (`claude-opus-5-5`, structured JSON output) writes an original script: hook within the
   measured hook time, the same section order, narration sized to the measured words per minute.
2. **Build:** the plan becomes a HyperFrames project: `index.html` with a GSAP timeline, a punch-in on every
   beat of the measured average shot length, burned-in captions, `script.md`, `captions.srt`.
3. **Render:** `npx hyperframes render` makes the MP4, locally or on a Fly.io Sprite.

```bash
python create_video.py --analysis out/KnqTiAXUH7M/analysis.json \
  --brief "Why small teams should automate their weekly report" \
  --brand Acme --accent "#ff5a1f" --font "Space Grotesk" --aspect portrait --logo logo.png \
  --tone "direct, no hype" --cta "Grab the template below" --render local
python create_video.py --plan out/new-video/project/plan.json --render sprite   # re-render after editing
```

Your touches: `--brand --background --text --accent --font --aspect (landscape|portrait|square) --duration
--logo --tone --cta --instructions --css FILE --no-captions`. The project is plain HTML, so open it with
`npx hyperframes preview` to scrub the timeline and change anything by hand.

| Render backend | Needs | Use when |
|---|---|---|
| `local` | Node.js 22+, FFmpeg, Chrome | your own machine |
| `sprite` | `SPRITES_TOKEN` from [sprites.dev/account](https://sprites.dev/account) | the Fly.io app: renders run on a Sprite named `SPRITE_NAME` (default `rav-render`), which installs Node, FFmpeg, HyperFrames and Chrome on first use and keeps them |
| `none` | nothing | you only want the project zip |

### API

```bash
curl -F url="https://www.youtube.com/watch?v=KnqTiAXUH7M" -F download=true https://<app>.fly.dev/api/jobs
curl https://<app>.fly.dev/api/jobs/<id>                       # status, log, results
curl https://<app>.fly.dev/api/jobs/<id>/files/SKILL.md        # also report.html, script.md, analysis.json
curl -F video=@clip.mp4 -F transcript_file=@clip.srt https://<app>.fly.dev/api/jobs
curl -F brief="..." -F metrics=@metrics.json -F touches='{"brand":"Acme"}' https://<app>.fly.dev/api/plans
curl -F plan=@plan.json -F touches='{"brand":"Acme"}' -F logo=@logo.png https://<app>.fly.dev/api/renders
```

### LLM production package (DeepInfra)

Give the app a video link and, when `DEEPINFRA_API_KEY` is set, it also writes:

| File | What it is | Made by |
|---|---|---|
| `script_clean.md` | the transcript as a clean script with sections and `[mm:ss]` times | text model |
| `storyboard.md` | one panel per shot (spread evenly, up to 40): on-screen description, camera, text on screen, dialogue, purpose | vision model |
| `edit_decision_list.edl` | CMX 3600 EDL, one event per shot on one track, ready for a non-linear editor | the shot cuts, plus clip names from the storyboard |
| `frames.zip` | one JPEG per shot, named by its timecode | ffmpeg |

Without a key, the app writes the measured outputs only, as before. A model failure is reported in
`analysis.json` under `llm.errors`, and the other files are still written.

```bash
fly secrets set --stage --app reverse-any-video DEEPINFRA_API_KEY=<your-key>   # then: fly deploy --ha=false
```

Model names are set with `DEEPINFRA_VISION_MODEL` and `DEEPINFRA_TEXT_MODEL`. The defaults are
`Qwen/Qwen2.5-VL-32B-Instruct` and `meta-llama/Llama-3.3-70B-Instruct`. Models are retired often, so check the
live list at deepinfra.com if a call fails with a 404.

### Cost and price

`/pricing` (and `GET /api/quote?duration_s=306`) shows what one analysis costs: DeepInfra tokens, Fly.io compute
and Azure storage, plus a 10% margin on that cost and an estimated card fee. Every rate has its source, and
each can be overridden with an environment variable of the same name (for example `PRICE_MARGIN=0.10`,
`DEEPINFRA_...` prices in `pricing.py`). Rates are third-party listings and must be checked before you quote a customer.

### Projects and Azure storage

A project is a folder for one video's analyses. Every project lives in one Azure Blob container
(`reverse-any-video`), each in its own folder:

```
reverse-any-video/
  projects/<slug>/project.json            the project record
  projects/<slug>/jobs/<job_id>/*.md, *.json, report.html, SKILL.md
```

```bash
curl -H "X-Access-Token: $TOKEN" -F name="Hook study" https://<app>.fly.dev/api/projects        # create
curl -H "X-Access-Token: $TOKEN" https://<app>.fly.dev/api/projects                            # list
curl -H "X-Access-Token: $TOKEN" -F url="https://www.youtube.com/watch?v=KnqTiAXUH7M" \
     -F download=true -F project=hook-study https://<app>.fly.dev/api/jobs                      # analyse into the project
```

The connection string is kept in Azure Key Vault. The server reads it with the service principal set in
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET`, from the vault in `AZURE_KEYVAULT_URL`
(secret name `reverse-any-video-storage-connection-string`). Without these the project endpoints return 503
and jobs run as before, saving nothing.

The resources, their current status and the commands to finish the setup are in
[`docs/azure-setup.md`](docs/azure-setup.md).

To run this on your own Fly.io and Azure account, follow the step-by-step guide:
https://claude.ai/artifact/EJqZnm3wE3EAVvwidFTuFA (private until you share it).

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The video tests build a synthetic clip with cuts at 2, 3.5, 6 and 8 s and a silent second at 4 s, then check
that all four cuts and the silence are found. The Claude and Sprite steps are tested against fakes; a real
HyperFrames render runs with `RAV_RENDER_TEST=1` (needs Node 22+, FFmpeg, Chrome).

## Rebuilding the page

`docs/app.html` is the page body; `python docs/build.py` wraps it into the standalone `docs/index.html`.

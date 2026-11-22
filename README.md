# reverse-any-video

Reverse-engineer any video's **script** and **editing style** into numbers, then turn the numbers into a
reusable `SKILL.md` blueprint for Claude.

Starting base: [How to reverse engineer any editing style (Turned it into a skill)](https://www.youtube.com/watch?v=KnqTiAXUH7M)
by Taha El Harti. This repo is an independent, open implementation of the `/reverse-any-video` idea from that
video. See [`examples/KnqTiAXUH7M`](examples/KnqTiAXUH7M) for what has been captured from it so far.

## What it measures

| From the transcript | From the video file (ffmpeg) |
|---|---|
| Words per minute, overall and per 30 s | Shot cuts (scene detection) |
| Hook: first ~15 s, classified (question, promise, number, story, contrarian) | Average, median, min and max shot length |
| Sections, split on pauses and transition words | Cuts per minute and per 30 s window |
| Open loops ("in a second", "stick around") | Silences: how tightly pauses were trimmed |
| Calls to action ("subscribe", "link in the description") | Keyframe contact sheet, one frame per shot |
| Questions, "you" vs "I", fillers, top vocabulary | |

## Four ways to use it

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

**Deploy on every push:** `.github/workflows/fly-deploy.yml` runs the tests, then `flyctl deploy` on `main`.
Create a token with `fly tokens create deploy` and add it as the repository secret `FLY_API_TOKEN`. Until
the secret exists, the deploy step is skipped.

**Run the server locally:** `pip install -r requirements.txt && uvicorn server:app --reload`, then open
http://localhost:8000. The API is documented at `/api/docs`.

### API

```bash
curl -F url="https://www.youtube.com/watch?v=KnqTiAXUH7M" -F download=true https://<app>.fly.dev/api/jobs
curl https://<app>.fly.dev/api/jobs/<id>                       # status, log, results
curl https://<app>.fly.dev/api/jobs/<id>/files/SKILL.md        # also report.html, script.md, analysis.json
curl -F video=@clip.mp4 -F transcript_file=@clip.srt https://<app>.fly.dev/api/jobs
```

## Tests

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The video tests build a synthetic clip with cuts at 2, 3.5, 6 and 8 s and a silent second at 4 s, then check
that all four cuts and the silence are found.

## Rebuilding the page

`docs/app.html` is the page body; `python docs/build.py` wraps it into the standalone `docs/index.html`.

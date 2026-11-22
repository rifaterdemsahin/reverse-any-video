---
name: reverse-any-video
description: Reverse-engineer any video's script and editing style into a reusable blueprint. Use when the user gives a YouTube URL or video file and wants its script, hook, structure, pacing, cut rhythm or "style" extracted, copied, or turned into a skill.
---

# /reverse-any-video

Turn one video into numbers, then turn the numbers into a style you can reuse.
Measure first, describe second: every claim in the blueprint must trace back to
`analysis.json`.

## 1. Measure

Run from the repository root:

```bash
python reverse_video.py "<url or file>" --download --out out
```

- No `yt-dlp`? `pip install -r requirements.txt`. No `ffmpeg`? The script still analyses the transcript.
- YouTube says "Sign in to confirm you're not a bot": ask the user for a `cookies.txt` (`--cookies`), or ask
  them to paste the transcript from YouTube's **Show transcript** panel into a file and pass `--transcript`.
- The user has the video file: pass it as the source, or `--video FILE` alongside the URL.
- Never invent a transcript, shot count or timestamp. If a piece is missing, say which piece and why.

Outputs in `out/<id>/`: `analysis.json`, `script.md`, `SKILL.md` (draft blueprint), `report.html`.

## 2. Read the script

Read `script.md` end to end before writing anything. Note, with timestamps:

- **Hook**: what is promised in the first ~15 s, and how (question, number, story, contrarian claim).
- **Structure**: the sections `analysis.json → script.sections` found. Check them against the text and merge or
  split where the heuristic got it wrong.
- **Retention devices**: open loops ("in a second", "stick around"), pattern breaks, questions.
- **CTAs**: where and how the viewer is asked to act.
- **Voice**: "you" vs "I" ratio, sentence length, recurring words (`script.keywords`).

## 3. Read the edit

From `analysis.json → video`: average and median shot length, cuts per minute, where cutting speeds up
(`cuts_30s`), total silence (how tightly pauses were trimmed). Look at the contact sheet in `report.html` to
name the visual patterns: talking head vs B-roll vs screen recording, text overlays, zooms.

## 4. Write the blueprint

Edit the generated `out/<id>/SKILL.md` into a skill someone could follow to make a new video in this style:
timings as ranges taken from the measurements, a section template with target lengths, a hook formula with the
original as the worked example, and an editing checklist. Keep the numbers; cut generic advice.

Offer to save it as `.claude/skills/<name>-style/SKILL.md` so the style can be reused with `/<name>-style`.

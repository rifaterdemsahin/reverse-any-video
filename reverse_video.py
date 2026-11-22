#!/usr/bin/env python3
"""reverse-any-video: reverse-engineer a video's script and editing style.

Give it a YouTube URL or a local video file. It measures what can be measured
(transcript, speaking rate, hook, structure, CTAs, shot cuts, pacing, silences)
and writes:

  out/<id>/analysis.json   every number the report uses
  out/<id>/script.md       the transcript with timestamps and section breaks
  out/<id>/SKILL.md        a style blueprint you can hand to Claude as a skill
  out/<id>/report.html     a self-contained visual report

Only the standard library is required. Optional:
  yt-dlp                  metadata, captions and (with --download) the video file
  youtube-transcript-api  captions when yt-dlp is missing or blocked
  ffmpeg / ffprobe        shot-cut, silence and keyframe analysis of a video file
  DEEPINFRA_API_KEY       adds the LLM outputs: script_clean.md, storyboard.md,
                          edit_decision_list.edl and frames.zip (see reverse_llm.py)
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import deepinfra
import reverse_llm

# --------------------------------------------------------------------------- #
# Transcript parsing                                                          #
# --------------------------------------------------------------------------- #

TS = r"(?:(\d+):)?(\d{1,2}):(\d{2})(?:[.,](\d{1,3}))?"


def _ts_to_s(h, m, s, ms=None) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + (int((ms or "0").ljust(3, "0")) / 1000)


def parse_ts(text: str) -> float:
    m = re.fullmatch(TS, text.strip())
    if not m:
        raise ValueError(f"not a timestamp: {text!r}")
    return _ts_to_s(*m.groups())


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)          # VTT inline tags
    text = re.sub(r"\[(music|applause|laughter)\]", "", text, flags=re.I)
    text = html.unescape(text).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _finish(segs: list[dict]) -> list[dict]:
    """Drop empties and rolling auto-caption repeats; fill missing end times."""
    out: list[dict] = []
    for s in sorted(segs, key=lambda x: x["start"]):
        t = _clean(s["text"])
        if not t:
            continue
        if out and (t == out[-1]["text"] or out[-1]["text"].endswith(t)):
            out[-1]["end"] = max(out[-1]["end"], s.get("end") or s["start"])
            continue
        if out and t.startswith(out[-1]["text"]) and s["start"] - out[-1]["start"] < 4:
            out[-1]["text"] = t                    # growing auto-caption line
            out[-1]["end"] = max(out[-1]["end"], s.get("end") or s["start"])
            continue
        out.append({"start": round(s["start"], 3), "end": s.get("end"), "text": t})
    for i, s in enumerate(out):
        if s["end"] is None or s["end"] <= s["start"]:
            nxt = out[i + 1]["start"] if i + 1 < len(out) else None
            words = len(s["text"].split())
            s["end"] = round(nxt if nxt else s["start"] + max(1.0, words / 2.5), 3)
    return out


def parse_transcript(raw: str) -> tuple[list[dict], str]:
    """Parse any common transcript format. Returns (segments, format_name)."""
    raw = raw.lstrip("﻿")
    stripped = raw.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(stripped)
        if isinstance(data, dict) and "events" in data:                     # yt json3
            segs = []
            for ev in data["events"]:
                text = "".join(seg.get("utf8", "") for seg in ev.get("segs", []))
                if text.strip():
                    st = ev.get("tStartMs", 0) / 1000
                    segs.append({"start": st, "end": st + ev.get("dDurationMs", 0) / 1000, "text": text})
            return _finish(segs), "youtube-json3"
        if isinstance(data, list):                                          # transcript-api
            segs = [{"start": float(d["start"]),
                     "end": float(d["start"]) + float(d.get("duration", d.get("dur", 0)) or 0) or None,
                     "text": d["text"]} for d in data]
            return _finish(segs), "json-list"
    arrow = re.compile(rf"^\s*{TS}\s*-->\s*{TS}")
    if arrow.search(raw, re.M) or re.search(rf"{TS}\s*-->", raw):
        segs, cur = [], None
        for line in raw.splitlines():
            m = arrow.match(line)
            if m:
                g = m.groups()
                cur = {"start": _ts_to_s(*g[:4]), "end": _ts_to_s(*g[4:]), "text": ""}
                segs.append(cur)
            elif cur is not None and line.strip() and not line.strip().isdigit():
                cur["text"] += " " + line
            elif not line.strip():
                cur = None
        return _finish(segs), "vtt" if raw.lstrip().upper().startswith("WEBVTT") else "srt"
    # YouTube "Show transcript" copy: "0:00" line then text, or "0:00 text"
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    duration_label = re.compile(r"^\d+ (?:hours?|minutes?|seconds?)(?:,? \d+ (?:minutes?|seconds?))*$")
    segs, stamped = [], 0
    for line in lines:
        if duration_label.match(line):
            continue
        m = re.match(rf"^\[?({TS})\]?\s*(.*)$", line)
        if m and m.group(1):
            stamped += 1
            segs.append({"start": parse_ts(m.group(1)), "end": None, "text": m.group(6)})
        elif segs:
            segs[-1]["text"] += " " + line
    if stamped >= 2:
        return _finish(segs), "youtube-copy"
    # Plain text: estimate timing at 150 wpm and mark it as estimated.
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", stripped))
    t, segs = 0.0, []
    for s in sentences:
        if s:
            dur = max(1.0, len(s.split()) / 2.5)
            segs.append({"start": t, "end": t + dur, "text": s})
            t += dur
    return _finish(segs), "plain-text (timing estimated)"


# --------------------------------------------------------------------------- #
# Script analysis                                                             #
# --------------------------------------------------------------------------- #

STOP = set("""a about above after again all also am an and any are as at be because been before being
below between both but by can could did do does doing don't down during each few for from further get
got had has have having he her here hers him his how i i'm if in into is it it's its itself just let's
me more most my no nor not now of off on once only or other our out over own really right same she so
some such than that that's the their them then there these they this those through to too under until
up very was we were what when where which while who why will with would you you're your yours gonna
going want one thing things like okay yeah see know make way go actually basically""".split())

CTA = [r"\bsubscribe\b", r"\blike (?:this|the) video\b", r"\bhit (?:the )?like\b", r"\bcomment\b",
       r"\blink (?:is )?(?:in|below)\b", r"\bdescription\b", r"\bfollow\b", r"\bsign up\b",
       r"\bdownload\b", r"\bfree\b", r"\bnewsletter\b", r"\bcheck (?:it|this|them) out\b"]
OPEN_LOOP = [r"\bin a (?:second|minute|moment|bit)\b", r"\blater (?:on|in this video)\b",
             r"\bstick around\b", r"\bbut first\b", r"\b(?:till|until|to) the end\b",
             r"\bI'll show you\b", r"\bby the end\b", r"\bcoming up\b", r"\bwait (?:until|till)\b"]
TRANSITION = re.compile(r"^(?:so|now|next|first|second|third|finally|step \w+|number \w+|okay|alright|"
                        r"let's|here's|the (?:first|second|third|next|last)|part \w+|and that's)\b", re.I)
FILLER = [r"\bum+\b", r"\buh+\b", r"\byou know\b", r"\bbasically\b", r"\bliterally\b", r"\bkind of\b",
          r"\bsort of\b", r"\bI mean\b"]


def _hits(patterns, segs):
    found = []
    for s in segs:
        for p in patterns:
            if re.search(p, s["text"], re.I):
                found.append({"t": s["start"], "text": s["text"], "match": re.search(p, s["text"], re.I).group(0)})
                break
    return found


def classify_hook(text: str) -> list[str]:
    kinds = []
    if "?" in text:
        kinds.append("question")
    if re.search(r"\b(how to|here's how|I'll show|you'll learn|by the end|step by step)\b", text, re.I):
        kinds.append("promise")
    if re.search(r"\b\d[\d,.%]*\b|\b(million|thousand|hours?|days?|minutes?)\b", text, re.I):
        kinds.append("specific number")
    if re.search(r"\b(last (week|month|year)|when I|I was|I tried|I spent|story)\b", text, re.I):
        kinds.append("story")
    if re.search(r"\b(never|nobody|everyone|stop|wrong|secret|mistake|without)\b", text, re.I):
        kinds.append("contrarian / curiosity")
    return kinds or ["statement"]


def split_sections(segs: list[dict], min_len: float = 20.0) -> list[dict]:
    if not segs:
        return []
    starts = [0]
    for i in range(1, len(segs)):
        gap = segs[i]["start"] - segs[i - 1]["end"]
        since = segs[i]["start"] - segs[starts[-1]]["start"]
        if since >= min_len and (gap > 1.5 or TRANSITION.match(segs[i]["text"])):
            starts.append(i)
    # Fall back to 60 s windows when the script has no detectable breaks.
    if len(starts) == 1 and segs[-1]["end"] > 120:
        starts, nxt = [0], 60.0
        for i, s in enumerate(segs):
            if s["start"] >= nxt:
                starts.append(i)
                nxt = s["start"] + 60
    sections = []
    for n, a in enumerate(starts):
        b = starts[n + 1] if n + 1 < len(starts) else len(segs)
        chunk = segs[a:b]
        text = " ".join(s["text"] for s in chunk)
        dur = max(0.1, chunk[-1]["end"] - chunk[0]["start"])
        words = len(text.split())
        first = re.split(r"(?<=[.!?])\s", text)[0]
        sections.append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "words": words,
                         "wpm": round(words / dur * 60), "label": first[:90] + ("…" if len(first) > 90 else ""),
                         "text": text})
    return sections


def analyze_script(segs: list[dict], duration: float | None = None) -> dict:
    if not segs:
        return {}
    text = " ".join(s["text"] for s in segs)
    words = re.findall(r"[A-Za-z0-9']+", text)
    spoken = max(1.0, segs[-1]["end"] - segs[0]["start"])
    duration = duration or segs[-1]["end"]
    hook_segs = [s for s in segs if s["start"] < 15] or segs[:3]
    hook = " ".join(s["text"] for s in hook_segs)
    lw = [w.lower() for w in words]
    you = sum(w in ("you", "your", "you're", "yours", "you'll") for w in lw)
    me = sum(w in ("i", "me", "my", "i'm", "i've", "i'll", "mine") for w in lw)
    keywords = Counter(w for w in lw if len(w) > 2 and w not in STOP and not w.isdigit()).most_common(15)
    buckets = []
    for b in range(0, int(duration) + 1, 30):
        n = sum(len(s["text"].split()) for s in segs if b <= s["start"] < b + 30)
        buckets.append({"t": b, "words": n, "wpm": n * 2})
    fillers = Counter()
    for p in FILLER:
        fillers[p.strip("\\b").replace("+", "")] = len(re.findall(p, text, re.I))
    return {
        "segments": len(segs), "words": len(words), "duration_s": round(duration, 1),
        "wpm": round(len(words) / spoken * 60),
        "avg_sentence_words": round(len(words) / max(1, len(re.findall(r"[.!?]+", text)) or 1), 1),
        "questions": text.count("?"),
        "hook": {"text": hook, "seconds": round(hook_segs[-1]["end"], 1), "kinds": classify_hook(hook)},
        "sections": split_sections(segs),
        "ctas": _hits(CTA, segs), "open_loops": _hits(OPEN_LOOP, segs),
        "you_vs_i": {"you": you, "i": me, "ratio": round(you / me, 2) if me else None},
        "fillers": {k: v for k, v in fillers.items() if v},
        "keywords": keywords, "pace_30s": buckets,
    }


# --------------------------------------------------------------------------- #
# Video analysis (ffmpeg)                                                     #
# --------------------------------------------------------------------------- #

def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def probe(path: Path) -> dict:
    r = _run(["ffprobe", "-v", "error", "-show_entries",
              "format=duration:stream=codec_type,width,height,r_frame_rate", "-of", "json", str(path)])
    data = json.loads(r.stdout or "{}")
    info = {"duration_s": float(data.get("format", {}).get("duration", 0) or 0), "has_audio": False}
    for st in data.get("streams", []):
        if st.get("codec_type") == "video" and "width" in st:
            num, _, den = st.get("r_frame_rate", "0/1").partition("/")
            info.update(width=st["width"], height=st["height"],
                        fps=round(float(num) / float(den or 1), 2) if float(den or 1) else None)
        if st.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def detect_cuts(path: Path, threshold: float = 0.3) -> list[float]:
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-filter:v",
              f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"])
    return [round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def detect_silences(path: Path, noise_db: int = -35, min_s: float = 0.4) -> list[dict]:
    r = _run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
              f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return [{"start": round(a, 2), "end": round(b, 2)} for a, b in zip(starts, ends)]


def keyframes(path: Path, times: list[float], limit: int = 24) -> list[dict]:
    if len(times) > limit:
        step = len(times) / limit
        times = [times[int(i * step)] for i in range(limit)]
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(times):
            out = Path(td) / f"{i}.jpg"
            _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
                  "-frames:v", "1", "-vf", "scale=240:-2", "-q:v", "6", str(out)])
            if out.exists():
                frames.append({"t": round(t, 2), "jpg": base64.b64encode(out.read_bytes()).decode()})
    return frames


def analyze_video(path: Path, threshold: float = 0.3, with_frames: bool = True) -> dict:
    if not shutil.which("ffmpeg"):
        return {"error": "ffmpeg not installed"}
    info = probe(path)
    dur = info["duration_s"]
    cuts = [c for c in detect_cuts(path, threshold) if 0.2 < c < dur - 0.2]
    bounds = [0.0] + cuts + [dur]
    shots = [round(b - a, 3) for a, b in zip(bounds, bounds[1:]) if b - a > 0.04]
    per_30 = [{"t": b, "cuts": sum(b <= c < b + 30 for c in cuts)} for b in range(0, int(dur) + 1, 30)]
    result = {
        **info, "scene_threshold": threshold, "cuts": cuts, "shots": len(shots),
        "shot_avg_s": round(statistics.mean(shots), 2) if shots else None,
        "shot_median_s": round(statistics.median(shots), 2) if shots else None,
        "shot_min_s": round(min(shots), 2) if shots else None,
        "shot_max_s": round(max(shots), 2) if shots else None,
        "cuts_per_min": round(len(cuts) / dur * 60, 1) if dur else None,
        "cuts_30s": per_30,
        "first_cut_s": cuts[0] if cuts else None,
        "shot_bounds": [[round(a, 3), round(b, 3)] for a, b in zip(bounds, bounds[1:]) if b - a > 0.04],
    }
    if info.get("has_audio"):
        sil = detect_silences(path)
        result["silences"] = sil
        result["silence_total_s"] = round(sum(s["end"] - s["start"] for s in sil), 1)
    if with_frames:
        mids = [(a + b) / 2 for a, b in zip(bounds, bounds[1:])]
        result["frames"] = keyframes(path, mids)
    return result


# --------------------------------------------------------------------------- #
# Fetching from YouTube                                                       #
# --------------------------------------------------------------------------- #

def youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None


def oembed(url: str) -> dict:
    q = urllib.parse.urlencode({"url": url, "format": "json"})
    with urllib.request.urlopen(f"https://www.youtube.com/oembed?{q}", timeout=20) as r:
        d = json.load(r)
    return {"title": d.get("title"), "channel": d.get("author_name"), "channel_url": d.get("author_url"),
            "thumbnail": d.get("thumbnail_url"), "source": "oembed"}


def fetch_youtube(url: str, workdir: Path, cookies: str | None, download: bool, log,
                  max_duration: int | None = None) -> tuple[dict, str | None, Path | None]:
    """Return (metadata, raw_transcript_or_None, video_path_or_None)."""
    vid = youtube_id(url)
    meta: dict = {"id": vid, "url": url}
    transcript = None
    video_path = None
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        base = [ytdlp]
        if not shutil.which("deno") and shutil.which("node"):
            base += ["--js-runtimes", "node"]      # yt-dlp needs a JS runtime for YouTube
        if cookies:
            base += ["--cookies", cookies]
        cmd = [*base, "--skip-download", "--write-info-json", "--write-subs", "--write-auto-subs",
               "--sub-langs", "en.*,en", "--sub-format", "json3", "-o", str(workdir / "src.%(ext)s"), url]
        r = _run(cmd)
        info_file = workdir / "src.info.json"
        if info_file.exists():
            info = json.loads(info_file.read_text())
            meta.update(title=info.get("title"), channel=info.get("channel") or info.get("uploader"),
                        channel_url=info.get("channel_url"), upload_date=info.get("upload_date"),
                        duration_s=info.get("duration"), views=info.get("view_count"),
                        likes=info.get("like_count"), description=info.get("description"),
                        chapters=info.get("chapters"), tags=info.get("tags"),
                        thumbnail=info.get("thumbnail"), source="yt-dlp")
            subs = sorted(workdir.glob("src.*.json3"), key=lambda p: ("orig" in p.name, len(p.name)))
            if subs:
                transcript = subs[0].read_text()
                log(f"captions: {subs[0].name}")
        else:
            log("yt-dlp could not read the video: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        too_long = max_duration and (meta.get("duration_s") or 0) > max_duration
        if download and too_long:
            log(f"skipped download: video is longer than {max_duration} s")
        elif download:
            dcmd = [*base, "-f", "bv*[height<=480]+ba/b[height<=480]/b", "--merge-output-format", "mp4",
                    "-o", str(workdir / "video.%(ext)s"), url]
            _run(dcmd)
            found = list(workdir.glob("video.*"))
            video_path = found[0] if found else None
            log("downloaded video" if video_path else "video download failed")
    if transcript is None and vid:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            fetched = YouTubeTranscriptApi().fetch(vid, languages=["en", "en-US", "en-GB"])
            transcript = json.dumps([{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched])
            log("captions: youtube-transcript-api")
        except Exception as e:  # noqa: BLE001 - report and continue
            log(f"youtube-transcript-api failed: {type(e).__name__}")
    if not meta.get("title"):
        try:
            meta.update(oembed(url))
        except Exception as e:  # noqa: BLE001
            log(f"oEmbed failed: {e}")
    return meta, transcript, video_path


# --------------------------------------------------------------------------- #
# Outputs                                                                     #
# --------------------------------------------------------------------------- #

def fmt_t(s: float | None) -> str:
    if s is None:
        return "–"
    s = int(round(s))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def script_md(meta: dict, segs: list[dict], script: dict) -> str:
    out = [f"# Script — {meta.get('title') or meta.get('id')}", ""]
    if meta.get("url"):
        out += [f"Source: {meta['url']}", ""]
    if not segs:
        return "\n".join(out + ["_No transcript was available. Re-run with `--transcript FILE`._", ""])
    sec_starts = {s["start"]: s for s in script.get("sections", [])}
    for seg in segs:
        if seg["start"] in sec_starts:
            out += ["", f"## [{fmt_t(seg['start'])}] {sec_starts[seg['start']]['label']}", ""]
        out.append(f"`{fmt_t(seg['start'])}` {seg['text']}  ")
    return "\n".join(out) + "\n"


def blueprint_md(meta: dict, script: dict, video: dict) -> str:
    title = meta.get("title") or meta.get("id") or "this video"
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "video").lower()).strip("-")[:40] or "video"
    L = ["---", f"name: {slug}-style",
         f"description: Recreate the script structure and editing rhythm measured from \"{title}\". "
         "Use when writing or editing a video in this style.", "---", "",
         f"# Style blueprint: {title}", ""]
    if meta.get("channel"):
        L += [f"Measured from {meta['channel']}'s video ({meta.get('url', '')}). "
              "Every number below came from reverse_video.py; nothing is guessed.", ""]
    if video and not video.get("error"):
        L += ["## Editing rhythm", "",
              f"- Average shot: **{video['shot_avg_s']} s** (median {video['shot_median_s']} s, "
              f"range {video['shot_min_s']}–{video['shot_max_s']} s)",
              f"- **{video['cuts_per_min']} cuts per minute** across {video['shots']} shots",
              f"- First cut at {video['first_cut_s']} s" if video.get("first_cut_s") is not None else "- No cuts detected",
              ]
        if video.get("silence_total_s") is not None:
            L.append(f"- Total silence: {video['silence_total_s']} s of {round(video['duration_s'])} s "
                     "(low numbers mean pauses were cut out)")
        busiest = max(video["cuts_30s"], key=lambda b: b["cuts"], default=None)
        if busiest and busiest["cuts"]:
            L.append(f"- Fastest cutting: {fmt_t(busiest['t'])}–{fmt_t(busiest['t'] + 30)} "
                     f"({busiest['cuts']} cuts in 30 s)")
        L.append("")
    if script:
        h = script["hook"]
        L += ["## Script", "",
              f"- Speaking rate: **{script['wpm']} words per minute** ({script['words']} words)",
              f"- Hook (first {h['seconds']} s, {', '.join(h['kinds'])}):", f"  > {h['text']}",
              f"- Questions asked: {script['questions']}",
              f"- Viewer focus: \"you\" {script['you_vs_i']['you']}× vs \"I\" {script['you_vs_i']['i']}×", "",
              "### Structure", ""]
        for i, s in enumerate(script["sections"], 1):
            L.append(f"{i}. `{fmt_t(s['start'])}` {s['label']} ({s['words']} words, {s['wpm']} wpm)")
        L.append("")
        if script["open_loops"]:
            L += ["### Open loops (retention promises)", ""]
            L += [f"- `{fmt_t(x['t'])}` \"{x['match']}\" — {x['text']}" for x in script["open_loops"]] + [""]
        if script["ctas"]:
            L += ["### Calls to action", ""]
            L += [f"- `{fmt_t(x['t'])}` \"{x['match']}\" — {x['text']}" for x in script["ctas"]] + [""]
        if script["keywords"]:
            L += ["### Vocabulary", "", ", ".join(f"{w} ({n})" for w, n in script["keywords"]), ""]
    L += ["## Recreate it", "",
          "1. Write a hook that lands in the same time window and uses the same hook type.",
          "2. Follow the section order above; keep each section's share of the runtime.",
          "3. Speak at the measured words-per-minute; cut pauses down to the measured silence level.",
          "4. Cut at the measured average shot length; speed up where the original's fastest window sits.",
          "5. Place open loops and calls to action at the same relative timestamps.", ""]
    return "\n".join(L)


REPORT_CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--fg:#14181f;--muted:#5b6472;--line:#dde1e7;--accent:#e0242f;--accent2:#f5c518}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--panel:#171b21;--fg:#e8ebf0;--muted:#98a1ae;--line:#2a3039;--accent:#ff4b55}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px max(16px,env(safe-area-inset-left))}
h1{font-size:28px;line-height:1.2;margin:.2em 0;text-wrap:balance}h2{font-size:18px;margin:32px 0 12px}
.meta{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}.tile span{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.bars{display:flex;align-items:flex-end;gap:2px;height:90px;border-bottom:1px solid var(--line)}
.bars i{flex:1;background:var(--accent);min-height:1px;border-radius:2px 2px 0 0}
table{width:100%;border-collapse:collapse}td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
td.t{font-family:ui-monospace,monospace;color:var(--muted);white-space:nowrap}
blockquote{margin:0;padding:12px 16px;background:var(--panel);border-left:4px solid var(--accent2);border-radius:6px}
.frames{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}.frames figure{margin:0}
.frames img{width:100%;border-radius:6px;display:block}.frames figcaption{font:12px ui-monospace,monospace;color:var(--muted)}
.wrap{overflow-x:auto}.note{color:var(--muted);font-size:13px}
"""


def _bars(values: list[float]) -> str:
    top = max(values or [1]) or 1
    return '<div class="bars">' + "".join(f'<i style="height:{v / top * 100:.0f}%" title="{v}"></i>' for v in values) + "</div>"


def report_html(meta: dict, script: dict, video: dict, segs: list[dict]) -> str:
    e = html.escape
    title = meta.get("title") or meta.get("id") or "Video"
    tiles = []
    if script:
        tiles += [(script["wpm"], "words / min"), (script["words"], "words"), (len(script["sections"]), "sections"),
                  (script["questions"], "questions"), (len(script["ctas"]), "calls to action")]
    if video and not video.get("error"):
        tiles += [(video["shots"], "shots"), (f"{video['shot_avg_s']}s", "avg shot"),
                  (video["cuts_per_min"], "cuts / min")]
    body = [f"<main><p class='meta'>reverse-any-video report</p><h1>{e(title)}</h1>",
            f"<p class='meta'>{e(meta.get('channel') or '')} · <a href='{e(meta.get('url') or '#')}'>{e(meta.get('url') or '')}</a></p>"]
    if tiles:
        body.append('<div class="grid">' + "".join(f'<div class="tile"><b>{e(str(v))}</b><span>{e(k)}</span></div>' for v, k in tiles) + "</div>")
    if script:
        h = script["hook"]
        body += [f"<h2>Hook · first {h['seconds']} s · {e(', '.join(h['kinds']))}</h2>", f"<blockquote>{e(h['text'])}</blockquote>",
                 "<h2>Speaking pace (words per 30 s)</h2>", _bars([b["words"] for b in script["pace_30s"]])]
        rows = "".join(f"<tr><td class='t'>{fmt_t(s['start'])}</td><td>{e(s['label'])}</td><td>{s['words']}</td><td>{s['wpm']}</td></tr>" for s in script["sections"])
        body.append(f"<h2>Structure</h2><div class='wrap'><table><tr><th>Start</th><th>Opens with</th><th>Words</th><th>WPM</th></tr>{rows}</table></div>")
        marks = [("open loop", x) for x in script["open_loops"]] + [("CTA", x) for x in script["ctas"]]
        if marks:
            rows = "".join(f"<tr><td class='t'>{fmt_t(x['t'])}</td><td>{k}</td><td>{e(x['text'])}</td></tr>" for k, x in sorted(marks, key=lambda m: m[1]["t"]))
            body.append(f"<h2>Retention devices</h2><div class='wrap'><table>{rows}</table></div>")
    if video and not video.get("error"):
        body += ["<h2>Cuts per 30 s</h2>", _bars([b["cuts"] for b in video["cuts_30s"]])]
        if video.get("frames"):
            figs = "".join(f"<figure><img src='data:image/jpeg;base64,{f['jpg']}' alt='shot at {fmt_t(f['t'])}'><figcaption>{fmt_t(f['t'])}</figcaption></figure>" for f in video["frames"])
            body.append(f"<h2>Shot contact sheet</h2><div class='frames'>{figs}</div>")
    if segs:
        rows = "".join(f"<tr><td class='t'>{fmt_t(s['start'])}</td><td>{e(s['text'])}</td></tr>" for s in segs)
        body.append(f"<h2>Full script</h2><div class='wrap'><table>{rows}</table></div>")
    else:
        body.append("<h2>Script</h2><p class='note'>No transcript was available. Re-run with <code>--transcript FILE</code>.</p>")
    body.append("</main>")
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(title)} · reverse-any-video</title><style>{REPORT_CSS}</style></head><body>{''.join(body)}</body></html>"


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def run(source: str | None, out_root: Path | str = "out", transcript_text: str | None = None,
        video_file: Path | str | None = None, download: bool = False, cookies: str | None = None,
        scene_threshold: float = 0.3, frames: bool = True, max_duration: int | None = None,
        job_id: str | None = None, log=None, title: str | None = None) -> dict:
    """Analyse one video and write the four output files. Returns a summary dict.

    `source` is a URL, a local video path, or None to analyse `transcript_text` alone.
    Used by the CLI and by server.py.
    """
    log = log or (lambda m: print(f"· {m}", file=sys.stderr))
    is_url = bool(source) and re.match(r"https?://", source) is not None
    vid = youtube_id(source) if is_url else (Path(source).stem if source else None)
    out = Path(out_root) / (job_id or vid or "video")
    out.mkdir(parents=True, exist_ok=True)

    meta, raw, video_path = {"id": vid, "url": source if is_url else None, "title": None}, None, None
    if is_url:
        with tempfile.TemporaryDirectory() as td:
            meta, raw, dl = fetch_youtube(source, Path(td), cookies, download, log, max_duration)
            if dl:
                video_path = out / dl.name
                shutil.move(str(dl), video_path)
    elif source:
        video_path = Path(source)
        meta["title"] = video_path.stem
    if title and not meta.get("title"):
        meta["title"] = title
    if video_file:
        video_path = Path(video_file)
    if transcript_text:
        raw = transcript_text

    segs, fmt = parse_transcript(raw) if raw else ([], None)
    if fmt:
        log(f"transcript: {len(segs)} segments ({fmt})")
    video = analyze_video(video_path, scene_threshold, frames) if video_path else {}
    if video_path:
        log(f"video: {video.get('shots')} shots, {video.get('cuts_per_min')} cuts/min")
    script = analyze_script(segs, video.get("duration_s") or meta.get("duration_s")) if segs else {}

    llm = None
    key = deepinfra.api_key()
    if key and (segs or video_path):
        log("LLM steps: DeepInfra")
        llm = reverse_llm.build(out, meta.get("title") or vid or "video", source if is_url else None,
                                video_path, video, segs, key, log)

    analysis = {"meta": meta, "transcript_format": fmt, "script": script, "llm": llm,
                "video": {k: v for k, v in video.items() if k != "frames"}, "segments": segs}
    (out / "analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
    (out / "script.md").write_text(script_md(meta, segs, script))
    (out / "SKILL.md").write_text(blueprint_md(meta, script, video))
    (out / "report.html").write_text(report_html(meta, script, video, segs))
    return {"out_dir": str(out), "analysis": analysis, "frames": video.get("frames", []),
            "has_transcript": bool(segs), "has_video": bool(video_path)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="YouTube URL or path to a local video file")
    ap.add_argument("--transcript", help="transcript file (VTT, SRT, json3, JSON, or YouTube 'Show transcript' copy)")
    ap.add_argument("--video", help="local video file to analyse alongside a URL")
    ap.add_argument("--download", action="store_true", help="download the video (≤480p) with yt-dlp for cut analysis")
    ap.add_argument("--cookies", help="cookies.txt for yt-dlp, if YouTube asks you to sign in")
    ap.add_argument("--scene-threshold", type=float, default=0.3, help="ffmpeg scene score for a cut (default 0.3)")
    ap.add_argument("--max-duration", type=int, help="skip downloading videos longer than this many seconds")
    ap.add_argument("--no-frames", action="store_true", help="skip the keyframe contact sheet")
    ap.add_argument("--out", default="out", help="output directory (default: out)")
    a = ap.parse_args(argv)

    transcript = Path(a.transcript).read_text(encoding="utf-8", errors="replace") if a.transcript else None
    r = run(a.source, a.out, transcript, a.video, a.download, a.cookies, a.scene_threshold,
            not a.no_frames, a.max_duration)
    print(f"wrote {r['out_dir']}/analysis.json, script.md, SKILL.md, report.html")
    if not r["has_transcript"] and not r["has_video"]:
        print("No transcript or video was available, so only metadata was saved. "
              "Pass --transcript FILE and/or --video FILE.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

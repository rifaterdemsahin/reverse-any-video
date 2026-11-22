"""LLM steps that turn one analysed video into a production package (DeepInfra, see deepinfra.py).

Written into the job folder:
  storyboard.md            one panel per sampled shot: what is on screen, camera, purpose (vision model).
                           It says whether there is speech, never what is said
  edit_decision_list.edl   CMX 3600 EDL, one event per shot. Needs no model, names come from the storyboard

Nothing here reproduces source text. Frames are used for analysis only and are not delivered.

Every step is optional and reports its own error, so one failure does not stop the others.
Environment:
  STORYBOARD_SHOTS         how many shots get a vision-model panel (default 40, evenly spaced)
  STORYBOARD_BATCH         shots per vision request (default 8)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import deepinfra as di

STORYBOARD_SHOTS = int(os.environ.get("STORYBOARD_SHOTS", "40"))
STORYBOARD_BATCH = int(os.environ.get("STORYBOARD_BATCH", "8"))
FRAME_WIDTH = 640
TRANSCRIPT_CHARS = 60000

VISION_PROMPT = """You are a film editor reverse-engineering a video for a storyboard.
Each image is one shot: the frame from its middle. Its time range and the words spoken during it come before it.
Describe every shot in your own words. Never quote or transcribe speech. Return only a JSON array with one object per shot, in the same order:
[{"shot": <shot number>, "description": "what is on screen, one or two sentences",
  "camera": "framing and movement, e.g. close-up, static, slow push-in",
  "on_screen_text": "visible text, or empty string",
  "purpose": "what this shot does in the story, a few words",
  "clip_name": "a 3 to 5 word name for this clip"}]"""

SCRIPT_PROMPT = """Rewrite this timestamped transcript of a video as a clean script.
Keep the speaker's words. Remove caption noise such as repeated fragments and >> markers.
Start each section with a markdown heading (## Title) where the topic changes, and put the time
[mm:ss] at the start of each paragraph. Return plain markdown only, no preamble."""


# --------------------------------------------------------------------------- #
# Timecodes, shots and the EDL                                                #
# --------------------------------------------------------------------------- #

def timecode(seconds: float, fps: float) -> str:
    """Non-drop-frame timecode HH:MM:SS:FF. Frame rates such as 29.97 use their nominal rate."""
    base = max(1, round(fps or 25))
    frames = max(0, round(seconds * (fps or 25)))
    ff = frames % base
    total_s = frames // base
    return f"{total_s // 3600:02d}:{(total_s // 60) % 60:02d}:{total_s % 60:02d}:{ff:02d}"


def _ascii(text: str, limit: int = 80) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\x20-\x7e]", "", text or "")).strip()[:limit]


def edl(title: str, shots: list[dict], fps: float) -> str:
    """CMX 3600 EDL. Source and record in/out are the same shot times, laid end to end on one track."""
    lines = [f"TITLE: {_ascii(title, 60) or 'reverse-any-video'}", "FCM: NON-DROP FRAME", ""]
    record = 0.0
    for i, shot in enumerate(shots, 1):
        dur = shot["end"] - shot["start"]
        lines.append(f"{i:03d}  AX       V     C        "
                     f"{timecode(shot['start'], fps)} {timecode(shot['end'], fps)} "
                     f"{timecode(record, fps)} {timecode(record + dur, fps)}")
        lines.append(f"* FROM CLIP NAME:  {_ascii(shot.get('name', f'Shot {i:03d}'))}")
        lines.append("")
        record += dur
    return "\n".join(lines)


def shots_from_bounds(bounds: list[list[float]]) -> list[dict]:
    return [{"start": float(a), "end": float(b), "name": f"Shot {i:03d}"}
            for i, (a, b) in enumerate(bounds, 1) if float(b) > float(a)]


def sample_indices(total: int, k: int) -> list[int]:
    if total <= k:
        return list(range(total))
    return sorted({round(i * (total - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]


def words_in(segs: list[dict], start: float, end: float, limit: int = 300) -> str:
    text = " ".join(s["text"] for s in segs if start <= s.get("start", -1) < end)
    return text[:limit]


def _mmss(s: float) -> str:
    return f"{int(s) // 60:02d}:{s - int(s) // 60 * 60:04.1f}"


# --------------------------------------------------------------------------- #
# Frames                                                                      #
# --------------------------------------------------------------------------- #

def extract_frames(video: Path, shots: list[dict], out_dir: Path, fps: float) -> list[Path | None]:
    """One JPEG per shot, taken at the shot's middle. Returns one path per shot (None if ffmpeg failed)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path | None] = []
    for i, shot in enumerate(shots, 1):
        mid = (shot["start"] + shot["end"]) / 2
        dst = out_dir / f"shot_{i:03d}_{timecode(mid, fps).replace(':', '-')}.jpg"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{mid:.3f}", "-i", str(video),
                            "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2", "-q:v", "4", "-y", str(dst)],
                           capture_output=True)
        paths.append(dst if r.returncode == 0 and dst.exists() else None)
    return paths


# --------------------------------------------------------------------------- #
# Model steps                                                                 #
# --------------------------------------------------------------------------- #

def describe_storyboard(shots: list[dict], frames: list[bytes | None], segs: list[dict], key: str,
                        log=None, record=None) -> dict[int, dict]:
    """Ask the vision model about each sampled shot. Returns {shot_number: description}."""
    log = log or (lambda m: None)
    found: dict[int, dict] = {}
    pairs = [(i, s, f) for i, (s, f) in enumerate(zip(shots, frames), 1) if f]
    for b in range(0, len(pairs), STORYBOARD_BATCH):
        batch = pairs[b:b + STORYBOARD_BATCH]
        content: list[dict] = [{"type": "text", "text": VISION_PROMPT}]
        for n, shot, jpg in batch:
            spoken = words_in(segs, shot["start"], shot["end"]) or "(no words)"
            content.append({"type": "text", "text": f"Shot {n}, {_mmss(shot['start'])} to {_mmss(shot['end'])}. "
                                                    f"Words spoken: {spoken}"})
            content.append(di.image_part(jpg))
        log(f"storyboard: shots {batch[0][0]}-{batch[-1][0]} to {di.VISION_MODEL}")
        answer = di.parse_json(di.chat([{"role": "user", "content": content}], di.VISION_MODEL, key,
                                                      max_tokens=3000, record=record))
        for item in answer if isinstance(answer, list) else []:
            try:
                found[int(item["shot"])] = item
            except (KeyError, TypeError, ValueError):
                continue
    return found


def clean_script(segs: list[dict], title: str, key: str) -> str:
    lines = [f"[{_mmss(s['start'])[:5]}] {s['text']}" for s in segs]
    text = "\n".join(lines)[:TRANSCRIPT_CHARS]
    answer = di.chat([{"role": "system", "content": SCRIPT_PROMPT},
                      {"role": "user", "content": f"Title: {title}\n\nTranscript:\n{text}"}],
                     di.TEXT_MODEL, key, max_tokens=6000)
    return answer.strip() + "\n"


def storyboard_md(title: str, source: str | None, shots: list[dict], frame_names: list[str | None],
                  panels: dict[int, dict], fps: float, total: int, segs: list[dict]) -> str:
    out = [f"# Storyboard: {title}", ""]
    if source:
        out += [f"Source: {source}", ""]
    out += [f"{len(panels)} of {total} shots described by {di.VISION_MODEL}, spread evenly across the video. "
            f"Every shot's frame is in `frames.zip`. Timecodes are {fps:g} fps.", ""]
    for n, shot in enumerate(shots, 1):
        p = panels.get(n)
        if not p:
            continue
        out += [f"## Shot {n:03d} · {_mmss(shot['start'])} to {_mmss(shot['end'])} · "
                f"{_ascii(str(p.get('clip_name', ''))) or shot['name']}", ""]
        if frame_names[n - 1]:
            out.append(f"- Frame: `{frame_names[n - 1]}`")
        out += [f"- On screen: {p.get('description', '')}",
                f"- Camera: {p.get('camera', '')}",
                f"- Text on screen: {p.get('on_screen_text', '') or 'none'}",
                f"- Speech in shot: {'yes' if words_in(segs, shot['start'], shot['end']) else 'no'}",
                f"- Purpose: {p.get('purpose', '')}", ""]
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def build(out_dir: Path, title: str, source: str | None, video_path: Path | None, video_info: dict,
          segs: list[dict], key: str, log=None) -> dict:
    """Write the LLM outputs into out_dir. Returns a summary for analysis.json."""
    log = log or (lambda m: None)
    trace: list[dict] = []          # every prompt sent to a model and every reply, for the operator
    summary: dict = {"enabled": True, "vision_model": di.VISION_MODEL, "text_model": di.TEXT_MODEL,
                     "files": [], "errors": []}
    fps = video_info.get("fps") or 25

    def step(name, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one step failing must not stop the others
            summary["errors"].append(f"{name}: {type(e).__name__}: {e}")
            log(f"llm {name} failed: {e}")
            return None

    bounds = video_info.get("shot_bounds") or []
    if video_path and bounds:
        shots = shots_from_bounds(bounds)
        with tempfile.TemporaryDirectory() as td:
            paths = step("frames", lambda: extract_frames(video_path, shots, Path(td), fps)) or [None] * len(shots)
            names = [p.name if p else None for p in paths]
            if any(paths):
                with zipfile.ZipFile(out_dir / "frames.zip", "w", zipfile.ZIP_DEFLATED) as z:
                    for p in paths:
                        if p:
                            z.write(p, p.name)
                summary["files"].append("frames.zip")
                summary["frames"] = sum(1 for p in paths if p)

            panels: dict[int, dict] = {}
            picked = sample_indices(len(shots), STORYBOARD_SHOTS)
            sample = [shots[i] for i in picked]
            jpgs = [paths[i].read_bytes() if paths[i] else None for i in picked]
            got = step("storyboard", lambda: describe_storyboard(sample, jpgs, segs, key, log, trace.append))
            for n, item in (got or {}).items():
                if 1 <= n <= len(picked):
                    panels[picked[n - 1] + 1] = item
            if panels:
                for idx, item in panels.items():
                    if item.get("clip_name"):
                        shots[idx - 1]["name"] = _ascii(f"{idx:03d} {item['clip_name']}")
                (out_dir / "storyboard.md").write_text(
                    storyboard_md(title, source, shots, names, panels, fps, len(shots), segs))
                summary["files"].append("storyboard.md")
                summary["storyboard_panels"] = len(panels)

        (out_dir / "edit_decision_list.edl").write_text(edl(title, shots, fps))
        summary["files"].append("edit_decision_list.edl")
        summary["edl_events"] = len(shots)

    (out_dir / "llm_trace.json").write_text(json.dumps(trace, indent=2, ensure_ascii=False))
    summary["trace_entries"] = len(trace)
    summary["ok"] = not summary["errors"]
    return summary

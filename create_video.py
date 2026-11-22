#!/usr/bin/env python3
"""create_video: make a NEW video in a reverse-engineered style.

  1. plan     Claude writes an original script (scenes + narration) that follows the
              measured blueprint: hook length, section order, words per minute, CTAs.
  2. build    The plan + your touches (brand, colours, font, logo, custom CSS) become a
              HyperFrames project: index.html with a GSAP timeline, captions, script.
  3. render   `npx hyperframes render` turns it into an MP4, either on this machine or
              on a Fly.io Sprite (a remote sandbox), so the web app stays small.

Examples:
  python create_video.py --analysis out/KnqTiAXUH7M/analysis.json \\
      --brief "Why every small team should automate their weekly report" \\
      --brand "Acme" --accent "#ff5a1f" --render local
  python create_video.py --plan plan.json --render sprite      # re-render an edited plan

Environment:
  ANTHROPIC_API_KEY   for the plan step (or an `ant auth login` profile)
  CLAUDE_MODEL        default claude-opus-5-5
  SPRITES_TOKEN       for --render sprite;  SPRITE_NAME (default rav-render)
  HYPERFRAMES_VERSION default 0.9.80;  GSAP_PATH  local gsap.min.js instead of the CDN
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HYPERFRAMES_VERSION = os.environ.get("HYPERFRAMES_VERSION", "0.9.80")
GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

ASPECTS = {"landscape": (1920, 1080), "portrait": (1080, 1920), "square": (1080, 1080)}
FONTS = ["Inter", "Space Grotesk", "Archivo", "Poppins", "Montserrat", "DM Sans", "IBM Plex Sans",
         "Sora", "Bebas Neue", "Playfair Display"]
SCENE_KINDS = ["title", "point", "list", "stat", "quote", "cta"]

TOUCH_DEFAULTS = {
    "brand": "", "background": "#0f1115", "text": "#f5f6f8", "accent": "#f6c600",
    "font": "Inter", "aspect": "landscape", "duration_s": 60, "tone": "", "cta": "",
    "instructions": "", "custom_css": "", "captions": True,
}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_touches(t: dict | None) -> dict:
    """Merge with defaults and validate, so user input can never break the HTML."""
    out = dict(TOUCH_DEFAULTS)
    for k, v in (t or {}).items():
        if k in out and v not in (None, ""):
            out[k] = v
    for k in ("background", "text", "accent"):
        if not HEX.match(str(out[k])):
            out[k] = TOUCH_DEFAULTS[k]
    if out["font"] not in FONTS:
        out["font"] = TOUCH_DEFAULTS["font"]
    if out["aspect"] not in ASPECTS:
        out["aspect"] = "landscape"
    try:
        out["duration_s"] = max(10, min(600, int(out["duration_s"])))
    except (TypeError, ValueError):
        out["duration_s"] = TOUCH_DEFAULTS["duration_s"]
    out["captions"] = str(out["captions"]).lower() not in ("false", "0", "no", "off")
    out["custom_css"] = re.sub(r"</\s*style", "", str(out["custom_css"]), flags=re.I)[:20000]
    for k in ("brand", "tone", "cta", "instructions"):
        out[k] = str(out[k])[:2000]
    return out


# --------------------------------------------------------------------------- #
# Metrics: the numbers the plan and the timing follow                         #
# --------------------------------------------------------------------------- #

def metrics_from_analysis(analysis: dict) -> dict:
    """Condense reverse_video.py's analysis.json into what the plan step needs."""
    s, v = analysis.get("script") or {}, analysis.get("video") or {}
    total = sum(sec["end"] - sec["start"] for sec in s.get("sections", [])) or 1
    return {
        "title": (analysis.get("meta") or {}).get("title"),
        "wpm": s.get("wpm"), "hook_seconds": (s.get("hook") or {}).get("seconds"),
        "hook_kinds": (s.get("hook") or {}).get("kinds", []), "questions": s.get("questions"),
        "sections": [{"label": sec["label"], "share": round((sec["end"] - sec["start"]) / total, 2)}
                     for sec in s.get("sections", [])],
        "open_loops": [x["match"] for x in s.get("open_loops", [])],
        "ctas": [x["match"] for x in s.get("ctas", [])],
        "shot_avg_s": v.get("shot_avg_s"), "cuts_per_min": v.get("cuts_per_min"),
    }


# --------------------------------------------------------------------------- #
# 1. Plan (Claude)                                                            #
# --------------------------------------------------------------------------- #

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": SCENE_KINDS},
                "headline": {"type": "string"},
                "body": {"type": "string"},
                "items": {"type": "array", "items": {"type": "string"}},
                "stat": {"type": "string"},
                "narration": {"type": "string"},
            },
            "required": ["kind", "headline", "body", "items", "stat", "narration"],
            "additionalProperties": False,
        }},
    },
    "required": ["title", "logline", "scenes"],
    "additionalProperties": False,
}

SYSTEM = """You are a video scriptwriter and editor. You receive a style blueprint measured from an \
existing video and a brief for a NEW video. Write an original script on the brief's topic that \
follows the blueprint's structure and rhythm. Never reuse the source video's sentences.

Scene kinds and their fields (leave unused fields as "" or []):
- title: headline (max 8 words), body = short subtitle
- point: headline (max 8 words), body (max 20 words)
- list: headline, items (2-5, max 6 words each)
- stat: stat (a number or short figure the brief supports, never invented facts), headline = what it measures
- quote: body = the line, headline = who or where it comes from (only if the brief supplies it)
- cta: headline = the ask, body = how to act on it
Every scene has narration: what the voiceover says while it is on screen."""


def build_prompt(metrics: dict, blueprint: str, brief: str, touches: dict) -> str:
    wpm = metrics.get("wpm") or 150
    words = int(wpm * touches["duration_s"] / 60)
    lines = [
        "<blueprint>", blueprint.strip() or "(none)", "</blueprint>", "",
        "<measured>", json.dumps(metrics, indent=1), "</measured>", "",
        "<brief>", brief.strip(), "</brief>", "",
        "<constraints>",
        f"- Target runtime: {touches['duration_s']} s, so about {words} words of narration in total at {wpm} wpm.",
        f"- The first scene is the hook: it must land within {metrics.get('hook_seconds') or 15} s and use the "
        f"same hook type ({', '.join(metrics.get('hook_kinds') or ['statement'])}).",
        "- Follow the blueprint's section order and give each section a similar share of the runtime.",
        "- Use open loops and calls to action at similar relative points to the original.",
    ]
    if touches.get("tone"):
        lines.append(f"- Tone of voice: {touches['tone']}")
    if touches.get("brand"):
        lines.append(f"- Brand name: {touches['brand']}")
    if touches.get("cta"):
        lines.append(f"- The final call to action: {touches['cta']}")
    if touches.get("instructions"):
        lines.append(f"- Creator's own instructions: {touches['instructions']}")
    lines += ["</constraints>", "", "Return the plan as JSON."]
    return "\n".join(lines)


def write_plan(metrics: dict, blueprint: str, brief: str, touches: dict, client=None) -> dict:
    """Ask Claude for a plan that matches PLAN_SCHEMA."""
    import anthropic
    client = client or anthropic.Anthropic()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        messages=[{"role": "user", "content": build_prompt(metrics, blueprint, brief, touches)}],
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        cat = getattr(getattr(msg, "stop_details", None), "category", None)
        raise RuntimeError(f"Claude declined to write this plan (category: {cat}). Rephrase the brief.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("The plan was cut off at max_tokens. Ask for a shorter video.")
    text = next(b.text for b in msg.content if b.type == "text")
    return validate_plan(json.loads(text))


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or not isinstance(plan.get("scenes"), list) or not plan["scenes"]:
        raise ValueError("A plan needs a non-empty scenes list.")
    scenes = []
    for s in plan["scenes"][:60]:
        kind = s.get("kind") if s.get("kind") in SCENE_KINDS else "point"
        scenes.append({"kind": kind, "headline": str(s.get("headline", ""))[:200],
                       "body": str(s.get("body", ""))[:600],
                       "items": [str(i)[:120] for i in (s.get("items") or [])][:8],
                       "stat": str(s.get("stat", ""))[:40], "narration": str(s.get("narration", ""))[:2000]})
    return {"title": str(plan.get("title", "Untitled"))[:200], "logline": str(plan.get("logline", ""))[:400],
            "scenes": scenes}


# --------------------------------------------------------------------------- #
# 2. Build a HyperFrames project                                              #
# --------------------------------------------------------------------------- #

def timeline(plan: dict, metrics: dict) -> list[dict]:
    """Scene timings from narration length at the measured speaking rate."""
    wpm = metrics.get("wpm") or 150
    t, out = 0.0, []
    for s in plan["scenes"]:
        words = len(s["narration"].split())
        dur = round(max(2.5 if s["kind"] in ("title", "cta") else 3.0, words / wpm * 60 + 0.6), 2)
        out.append({"start": round(t, 2), "duration": dur})
        t += dur
    return out


def caption_chunks(text: str, start: float, dur: float, size: int = 6) -> list[dict]:
    words = text.split()
    if not words:
        return []
    chunks = [" ".join(words[i:i + size]) for i in range(0, len(words), size)]
    per = dur / len(chunks)
    return [{"start": round(start + i * per, 2), "duration": round(per, 2), "text": c} for i, c in enumerate(chunks)]


def _srt_t(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def scene_html(i: int, s: dict, start: float, dur: float) -> str:
    e = html.escape
    inner = []
    if s["kind"] == "stat" and s["stat"]:
        inner.append(f'<div class="stat">{e(s["stat"])}</div>')
    if s["headline"]:
        inner.append(f'<h1 class="headline"><span class="hl">{e(s["headline"])}</span></h1>')
    if s["kind"] == "quote" and s["body"]:
        inner.insert(0, f'<blockquote class="body">“{e(s["body"])}”</blockquote>')
    elif s["body"]:
        inner.append(f'<p class="body">{e(s["body"])}</p>')
    if s["items"]:
        inner.append('<ul class="items">' + "".join(f'<li class="item">{e(x)}</li>' for x in s["items"]) + "</ul>")
    return (f'<section id="s{i}" class="clip scene scene-{s["kind"]}" data-start="{start}" data-duration="{dur}" '
            f'data-track-index="0"><div class="frame">{"".join(inner)}</div></section>')


def scene_motion(i: int, s: dict, start: float, dur: float, beat: float) -> list[str]:
    """GSAP lines: entrances, then a punch-in on every beat to echo the source's cut rhythm."""
    sel = f"#s{i}"
    js = [f'tl.from("{sel} .frame", {{opacity: 0, duration: 0.25}}, {start});']
    t = start + 0.1
    for part in ("stat", "headline", "body"):
        if (part == "stat" and s["kind"] == "stat" and s["stat"]) or (part != "stat" and s.get(part)):
            js.append(f'tl.from("{sel} .{part}", {{y: 48, opacity: 0, duration: 0.5, ease: "power3.out"}}, {t:.2f});')
            t += min(0.45, beat / 2)
    for n in range(len(s["items"])):
        js.append(f'tl.from("{sel} .item:nth-child({n + 1})", {{x: -40, opacity: 0, duration: 0.4, ease: "power2.out"}}, {t:.2f});')
        t += min(beat, max(0.35, (dur - 1) / max(1, len(s["items"]))))
    k = start + beat
    while k < start + dur - 0.6:
        js.append(f'tl.fromTo("{sel} .frame", {{scale: 1.045}}, {{scale: 1, duration: 0.35, ease: "power2.out", '
                  f'immediateRender: false}}, {k:.2f});')
        k += beat
    return js


def build_project(plan: dict, touches: dict, metrics: dict, out_dir: Path | str,
                  logo: Path | str | None = None, gsap_path: str | None = None) -> Path:
    """Write a HyperFrames project. Returns its directory."""
    plan, touches = validate_plan(plan), clean_touches(touches)
    out = Path(out_dir)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    w, h = ASPECTS[touches["aspect"]]
    times = timeline(plan, metrics)
    total = round(times[-1]["start"] + times[-1]["duration"], 2)
    beat = float(metrics.get("shot_avg_s") or 2.5)
    beat = max(1.0, min(6.0, beat))
    e = html.escape

    gsap_src = GSAP_CDN
    gsap_path = gsap_path or os.environ.get("GSAP_PATH")
    if gsap_path and Path(gsap_path).exists():
        shutil.copy(gsap_path, out / "assets" / "gsap.min.js")
        gsap_src = "assets/gsap.min.js"
    logo_html = ""
    if logo and Path(logo).exists():
        ext = Path(logo).suffix.lower() if Path(logo).suffix.lower() in (".png", ".jpg", ".jpeg", ".svg", ".webp") else ".png"
        shutil.copy(logo, out / "assets" / f"logo{ext}")
        logo_html = (f'<img id="logo" class="clip" src="assets/logo{ext}" alt="" data-start="0" '
                     f'data-duration="{total}" data-track-index="2">')
    elif touches["brand"]:
        logo_html = (f'<div id="logo" class="clip brandmark" data-start="0" data-duration="{total}" '
                     f'data-track-index="2">{e(touches["brand"])}</div>')

    scenes = "\n".join(scene_html(i, s, t["start"], t["duration"]) for i, (s, t) in enumerate(zip(plan["scenes"], times)))
    caps = []
    for s, t in zip(plan["scenes"], times):
        caps += caption_chunks(s["narration"], t["start"], t["duration"])
    cap_html = "\n".join(f'<div id="cap{n}" class="clip cap" data-start="{c["start"]}" data-duration="{c["duration"]}" '
                         f'data-track-index="1"><span>{e(c["text"])}</span></div>'
                         for n, c in enumerate(caps)) if touches["captions"] else ""
    motion = []
    for i, (s, t) in enumerate(zip(plan["scenes"], times)):
        motion += scene_motion(i, s, t["start"], t["duration"], beat)
    portrait = h > w
    narrow = w <= 1080          # portrait and square share the narrow type scale
    font_q = touches["font"].replace(" ", "+")

    page = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={w}, height={h}" />
    <title>{e(plan["title"])}</title>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family={font_q}:wght@400;600;800&display=swap" />
    <script src="{gsap_src}"></script>
    <style>
      :root {{ --ground: {touches["background"]}; --ink: {touches["text"]}; --accent: {touches["accent"]};
        --font-display: "{touches["font"]}", system-ui, sans-serif; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: var(--ground); }}
      #root {{ position: relative; width: 100%; height: 100%; font-family: var(--font-display); color: var(--ink);
        background: radial-gradient(circle at 80% 10%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 55%), var(--ground); }}
      .scene {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: {(120 if portrait else 96) if narrow else 140}px; }}
      .frame {{ width: 100%; max-width: {900 if narrow else 1500}px; display: flex; flex-direction: column; gap: 36px; transform-origin: 50% 50%; }}
      .headline {{ font-size: {(96 if portrait else 80) if narrow else 112}px; line-height: 1.02; font-weight: 800; letter-spacing: -0.03em; }}
      .scene-title .headline {{ font-size: {(120 if portrait else 96) if narrow else 150}px; }}
      .scene-title .hl, .scene-cta .hl {{ background: linear-gradient(transparent 62%, var(--accent) 62%, var(--accent) 90%, transparent 90%);
        -webkit-box-decoration-break: clone; box-decoration-break: clone; }}
      .body {{ font-size: {(48 if portrait else 42) if narrow else 52}px; line-height: 1.3; font-weight: 400; opacity: .88; max-width: 28ch; }}
      blockquote.body {{ font-size: {(64 if portrait else 56) if narrow else 72}px; font-weight: 600; opacity: 1; max-width: 22ch; }}
      .items {{ list-style: none; display: flex; flex-direction: column; gap: 22px; }}
      .item {{ font-size: {(54 if portrait else 46) if narrow else 58}px; font-weight: 600; padding-left: 44px; position: relative; }}
      .item::before {{ content: ""; position: absolute; left: 0; top: .42em; width: 22px; height: 22px; background: var(--accent); }}
      .stat {{ font-size: {(220 if portrait else 180) if narrow else 260}px; line-height: .9; font-weight: 800; color: var(--accent); letter-spacing: -0.04em; }}
      .cap {{ position: absolute; left: 0; right: 0; bottom: {220 if portrait else 70}px; display: flex; justify-content: center; z-index: 5; }}
      .cap span {{ font-size: {(44 if portrait else 34) if narrow else 40}px; font-weight: 600; background: rgba(0,0,0,.62); color: #fff; padding: 10px 22px; border-radius: 8px; max-width: 80%; text-align: center; }}
      #logo {{ position: absolute; top: 56px; right: 64px; height: 72px; z-index: 6; }}
      .brandmark {{ font-size: 34px; font-weight: 800; letter-spacing: .02em; height: auto !important; }}
      #progress {{ position: absolute; left: 0; bottom: 0; height: 8px; width: 100%; background: var(--accent); transform-origin: 0 50%; z-index: 6; }}
      /* Your touches */
      {touches["custom_css"]}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{w}" data-height="{h}">
{scenes}
{cap_html}
{logo_html}
      <div id="progress" class="clip" data-start="0" data-duration="{total}" data-track-index="3"></div>
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#progress", {{ scaleX: 0 }}, {{ scaleX: 1, duration: {total}, ease: "none" }}, 0);
      {chr(10).join("      " + m for m in motion).lstrip()}
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""
    (out / "index.html").write_text(page)
    (out / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"}}, indent=2))
    (out / "plan.json").write_text(json.dumps({"plan": plan, "touches": touches, "metrics": metrics}, indent=2))
    md = [f"# {plan['title']}", "", plan["logline"], ""]
    srt, n = [], 1
    for i, (s, t) in enumerate(zip(plan["scenes"], times), 1):
        md += [f"## {i}. [{t['start']:.1f}s, {t['duration']:.1f}s] {s['kind']}: {s['headline']}", "", s["narration"], ""]
        for c in caption_chunks(s["narration"], t["start"], t["duration"]):
            srt += [str(n), f"{_srt_t(c['start'])} --> {_srt_t(c['start'] + c['duration'])}", c["text"], ""]
            n += 1
    (out / "script.md").write_text("\n".join(md))
    (out / "captions.srt").write_text("\n".join(srt))
    (out / "README.md").write_text(
        f"# {plan['title']}\n\nA HyperFrames project made by reverse-any-video.\n\n"
        f"```bash\nnpx hyperframes@{HYPERFRAMES_VERSION} preview   # edit and scrub in the browser\n"
        f"npx hyperframes@{HYPERFRAMES_VERSION} render -o video.mp4\n```\n\n"
        "Edit `index.html` to change words, colours (the `:root` block) or motion (the GSAP timeline at the end).\n")
    return out


def zip_project(project: Path, dest: Path) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(project.rglob("*")):
            if f.is_file() and f.suffix != ".mp4":
                z.write(f, f.relative_to(project))
    return dest


# --------------------------------------------------------------------------- #
# 3. Render                                                                   #
# --------------------------------------------------------------------------- #

def render_local(project: Path, out_mp4: Path, quality: str = "draft", log=print) -> Path:
    if not shutil.which("npx"):
        raise RuntimeError("Local rendering needs Node.js 22+ (npx), FFmpeg and Chrome.")
    cmd = ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render", "-o", str(out_mp4.resolve()), "-q", quality]
    log("render: " + " ".join(cmd[2:]))
    r = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=3600,
                       env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "CI": "1"})
    if r.returncode != 0 or not out_mp4.exists():
        raise RuntimeError("hyperframes render failed: " + (r.stderr or r.stdout)[-1500:])
    return out_mp4


SPRITE_BOOTSTRAP = r"""set -e
SUDO=$(command -v sudo || true)
need=1
if command -v node >/dev/null 2>&1; then [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 22 ] && need=0; fi
if [ "$need" = 1 ]; then curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash - && $SUDO apt-get install -y nodejs; fi
command -v ffmpeg >/dev/null 2>&1 || { $SUDO apt-get update && $SUDO apt-get install -y ffmpeg; }
mkdir -p ~/rav-renderer && cd ~/rav-renderer
[ -f package.json ] || npm init -y >/dev/null
npm ls hyperframes@__VERSION__ >/dev/null 2>&1 || npm install --no-audit --no-fund hyperframes@__VERSION__
HYPERFRAMES_SKIP_SKILLS=1 npx --no-install hyperframes browser ensure
echo ready
"""


def render_sprite(project: Path, out_mp4: Path, quality: str = "draft", name: str | None = None,
                  token: str | None = None, job: str = "job", client=None, log=print) -> Path:
    """Render on a Fly.io Sprite: create it once, install Node + HyperFrames + Chrome,
    upload the project, render, download the MP4."""
    from sprites import SpriteConfig, SpritesClient, SpriteError
    name = name or os.environ.get("SPRITE_NAME", "rav-render")
    client = client or SpritesClient(token=token or os.environ["SPRITES_TOKEN"])
    try:
        sprite = client.get_sprite(name)
        log(f"sprite: using {name}")
    except SpriteError:
        log(f"sprite: creating {name}")
        sprite = client.create_sprite(name, config=SpriteConfig(ram_mb=4096, cpus=2), wait_for_capacity=True)
    boot = sprite.run("bash", "-lc", SPRITE_BOOTSTRAP.replace("__VERSION__", HYPERFRAMES_VERSION),
                      capture_output=True, timeout=1200)
    if boot.returncode != 0:
        raise RuntimeError("sprite setup failed: " + _tail(boot))
    remote = f"/tmp/rav/{re.sub(r'[^A-Za-z0-9_-]', '', job) or 'job'}"
    root = sprite.filesystem(remote)
    files = [f for f in project.rglob("*") if f.is_file() and f.suffix != ".mp4"]
    for f in files:
        (root / str(f.relative_to(project))).write_bytes(f.read_bytes(), mkdir_parents=True)
    log(f"sprite: uploaded {len(files)} files, rendering")
    r = sprite.run("bash", "-lc", f"cd {remote} && HYPERFRAMES_SKIP_SKILLS=1 CI=1 "
                   f"~/rav-renderer/node_modules/.bin/hyperframes render -o out.mp4 -q {quality}",
                   capture_output=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError("sprite render failed: " + _tail(r))
    out_mp4.write_bytes((root / "out.mp4").read_bytes())
    sprite.run("rm", "-rf", remote, capture_output=True, timeout=120)
    log(f"sprite: downloaded {out_mp4.stat().st_size:,} bytes")
    return out_mp4


def _tail(r) -> str:
    def s(x):
        return x.decode(errors="replace") if isinstance(x, bytes) else (x or "")
    return (s(r.stderr) or s(r.stdout))[-1500:]


def pick_backend(requested: str | None = None) -> str:
    want = (requested or os.environ.get("RENDER_BACKEND", "auto")).lower()
    if want != "auto":
        return want
    if os.environ.get("SPRITES_TOKEN"):
        return "sprite"
    return "local" if shutil.which("npx") else "none"


def render(project: Path, out_mp4: Path, backend: str, quality: str = "draft", job: str = "job", log=print) -> Path | None:
    if backend == "sprite":
        return render_sprite(project, out_mp4, quality, job=job, log=log)
    if backend == "local":
        return render_local(project, out_mp4, quality, log=log)
    log("render: skipped (no backend). Render the project zip with `npx hyperframes render`.")
    return None


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--analysis", help="analysis.json from reverse_video.py (plans a new script)")
    src.add_argument("--plan", help="an existing plan.json (skips the Claude step)")
    ap.add_argument("--blueprint", help="SKILL.md blueprint (default: next to --analysis)")
    ap.add_argument("--brief", help="what the new video is about")
    ap.add_argument("--touches", help="JSON file of touches (keys as below)")
    for k in ("brand", "background", "text", "accent", "font", "aspect", "tone", "cta", "instructions"):
        ap.add_argument(f"--{k}")
    ap.add_argument("--duration", type=int, dest="duration_s")
    ap.add_argument("--css", help="file of custom CSS appended to the composition")
    ap.add_argument("--logo", help="logo image")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--render", default="auto", choices=["auto", "local", "sprite", "none"])
    ap.add_argument("--quality", default="draft", choices=["draft", "looks", "delivery", "standard", "high"])
    ap.add_argument("--out", default="out/new-video")
    a = ap.parse_args(argv)

    touches = json.loads(Path(a.touches).read_text()) if a.touches else {}
    for k in ("brand", "background", "text", "accent", "font", "aspect", "tone", "cta", "instructions", "duration_s"):
        if getattr(a, k) is not None:
            touches[k] = getattr(a, k)
    if a.css:
        touches["custom_css"] = Path(a.css).read_text()
    if a.no_captions:
        touches["captions"] = False
    touches = clean_touches(touches)
    out = Path(a.out)

    if a.plan:
        saved = json.loads(Path(a.plan).read_text())
        plan = saved.get("plan", saved)
        metrics = saved.get("metrics", {})
        touches = clean_touches({**saved.get("touches", {}), **{k: v for k, v in touches.items() if v != TOUCH_DEFAULTS.get(k)}})
    else:
        if not a.brief:
            ap.error("--brief is required with --analysis")
        analysis = json.loads(Path(a.analysis).read_text())
        metrics = metrics_from_analysis(analysis)
        bp = Path(a.blueprint) if a.blueprint else Path(a.analysis).with_name("SKILL.md")
        blueprint = bp.read_text() if bp.exists() else ""
        print(f"· plan: asking {MODEL}", file=sys.stderr)
        plan = write_plan(metrics, blueprint, a.brief, touches)
    project = build_project(plan, touches, metrics, out / "project", a.logo)
    zip_project(project, out / "project.zip")
    print(f"wrote {project}/index.html, script.md, captions.srt and {out}/project.zip")
    video = render(project, out / "video.mp4", pick_backend(a.render), a.quality,
                   log=lambda m: print(f"· {m}", file=sys.stderr))
    if video:
        print(f"wrote {video}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""A HyperFrames project built from the template: scenes with placeholders, the storyboard image, and animated subtitles.

Output (zipped as hyperframes_project.zip):
  index.html            the composition: one root with a paused GSAP timeline, scenes on track 0,
                        the storyboard reference image on track 2, subtitles on track 3
  assets/storyboard.png the storyboard sheet, shown for reference in the first seconds
  README.txt            how to fill the placeholders and render it

Placeholders such as {{headline_2}} and {{narration_2}} stay in the file until you fill them. Subtitles animate
word by word from the narration text in each scene, so they work for any length of text you put in.
"""
from __future__ import annotations

import html
import shutil
import zipfile
from pathlib import Path

GSAP_CDN = "https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"
SIZE = (1920, 1080)
REFERENCE_SECONDS = 4.0

CSS = """
html,body{margin:0;background:#0f1216;color:#f5f6f8;font-family:Inter,system-ui,sans-serif}
#root{position:relative;width:1920px;height:1080px;overflow:hidden}
.clip{position:absolute;inset:0}
.frame{position:absolute;inset:120px 160px;display:flex;flex-direction:column;justify-content:center;gap:28px}
.headline{font-size:96px;line-height:1.05;margin:0;font-weight:700}
.body{font-size:44px;line-height:1.35;margin:0;color:#c9ced8;max-width:1400px}
.cap{top:auto;bottom:90px;left:160px;right:160px;inset:auto 160px 90px 160px;text-align:center;font-size:48px;font-weight:600}
.cap .w{display:inline-block;margin:0 6px;opacity:0}
.ref{right:60px;top:60px;width:520px;inset:auto;height:auto;border:4px solid #f6c600;border-radius:8px;opacity:.95}
"""

SUBTITLE_JS = """
document.querySelectorAll('.cap').forEach(function (el) {
  var words = el.textContent.trim().split(/\\s+/);
  el.innerHTML = words.map(function (w) { return '<span class="w">' + w + '</span>'; }).join(' ');
});
"""


def _scene(i: int, s: dict, t: dict) -> str:
    inner = [f'<h1 class="headline">{{{{headline_{i}}}}}</h1>']
    if s.get("kind") == "title":
        inner.append('<p class="body">{{subtitle}}</p>')
    else:
        inner.append(f'<p class="body">{{{{body_{i}}}}}</p>')
    return (f'<section id="s{i}" class="clip scene" data-start="{t["start_s"]}" data-duration="{t["duration_s"]}" '
            f'data-track-index="0"><div class="frame">{"".join(inner)}</div></section>')


def _subtitle(i: int, t: dict) -> str:
    return (f'<div id="cap{i}" class="clip cap" data-start="{t["start_s"]}" data-duration="{t["duration_s"]}" '
            f'data-track-index="3">{{{{narration_{i}}}}}</div>')


def _motion(i: int, t: dict) -> list[str]:
    start, dur = t["start_s"], t["duration_s"]
    lines = [
        f'tl.from("#s{i} .frame", {{opacity: 0, duration: 0.4}}, {start});',
        f'tl.from("#s{i} .headline", {{y: 60, opacity: 0, duration: 0.6, ease: "power3.out"}}, {start + 0.15:.2f});',
        f'tl.from("#s{i} .body", {{y: 40, opacity: 0, duration: 0.6, ease: "power3.out"}}, {start + 0.35:.2f});',
        f'tl.from("#cap{i} .w", {{opacity: 0, y: 12, duration: 0.25, stagger: 0.08}}, {start + 0.5:.2f});',
    ]
    return lines


def index_html(template: dict, reference: bool) -> str:
    scenes = template["scenes"]
    timeline = template["timeline"]
    total = round(timeline[-1]["start_s"] + timeline[-1]["duration_s"], 2)
    parts = [_scene(i, s, t) for i, (s, t) in enumerate(zip(scenes, timeline), 1)]
    subs = [_subtitle(i, t) for i, t in enumerate(timeline, 1)]
    ref = ""
    if reference:
        ref = (f'<img id="storyboard-ref" class="clip ref" src="assets/storyboard.png" alt="Storyboard reference" '
               f'data-start="0" data-duration="{REFERENCE_SECONDS}" data-track-index="2">'
               '<!-- Reference only. Delete this line before you render the final video. -->')
    motion = "\n      ".join(m for i, t in enumerate(timeline, 1) for m in _motion(i, t))
    w, h = SIZE
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Template project</title>
<style>{CSS}</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{w}" data-height="{h}">
  {ref}
  {''.join(parts)}
  {''.join(subs)}
</div>
<script src="{GSAP_CDN}"></script>
<script>
  {SUBTITLE_JS}
  window.__timelines = window.__timelines || {{}};
  var tl = gsap.timeline({{ paused: true }});
  {motion}
  window.__timelines["main"] = tl;
</script>
</body>
</html>
"""


def readme_txt(template: dict) -> str:
    names = ", ".join(template.get("placeholders", []))
    return "\n".join([
        "HyperFrames project from your video analysis",
        "",
        "1. Open index.html. Replace each placeholder with your own text:",
        f"   {names}",
        "2. Keep each scene's timing. It comes from the timeline in hyperframes_template.json.",
        "3. Subtitles animate word by word from the narration text. Put your narration in each narration slot.",
        "4. Delete the storyboard reference image (the element with id storyboard-ref) before you render.",
        "5. Render with HyperFrames.",
        "",
        "The text in the file is a placeholder until you replace it. Nothing here comes from the analysed video.",
        "",
    ])


def build(template: dict, out_dir: Path, storyboard_png: Path | None) -> Path:
    """Write the project folder and zip it as hyperframes_project.zip beside it. Returns the zip path."""
    out_dir = Path(out_dir)
    project = out_dir / "hyperframes"
    if project.exists():
        shutil.rmtree(project)
    (project / "assets").mkdir(parents=True)
    reference = bool(storyboard_png and Path(storyboard_png).exists())
    if reference:
        shutil.copy(storyboard_png, project / "assets" / "storyboard.png")
    (project / "index.html").write_text(index_html(template, reference))
    (project / "README.txt").write_text(readme_txt(template))
    zpath = out_dir / "hyperframes_project.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(project.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(project).as_posix())
    shutil.rmtree(project)
    return zpath

"""A reusable HyperFrames template built from the measured structure of a video. No source text is used.

Everything in the template is a number, a role (hook, body, call to action) or a placeholder such as
{{headline_2}}. Fill the placeholders with your own content and render with create_video.py.

Outputs:
  hyperframes_template.json   a plan in create_video.py's schema, with placeholders and a "timeline" key
  hyperframes_prompt.md       the HyperFrames prompt: style and pacing, then one prompt block per scene
"""
from __future__ import annotations

import json

SCENE_KINDS_BY_ROLE = {"hook": "title", "body": "point", "cta": "cta"}


def _roles(sections: list[dict]) -> list[str]:
    """First section is the hook, last is the call to action (if there are three or more), the rest is body."""
    n = len(sections)
    if n == 0:
        return []
    if n == 1:
        return ["hook"]
    if n == 2:
        return ["hook", "cta"]
    return ["hook"] + ["body"] * (n - 2) + ["cta"]


def build(metrics: dict, sections: list[dict], shots: int | None, fps: float | None = None) -> dict:
    """metrics: wpm, cuts_per_min, shot_avg_s, hook_seconds, questions, duration_s (numbers only).
    sections: [{"start": s, "end": s}] from the script analysis. Labels are not used."""
    roles = _roles(sections)
    wpm = metrics.get("wpm") or 150
    scenes, timeline = [], []
    for i, (sec, role) in enumerate(zip(sections, roles), 1):
        dur = round(sec["end"] - sec["start"], 1)
        words = max(4, round(wpm * dur / 60))
        kind = SCENE_KINDS_BY_ROLE[role]
        scenes.append({
            "kind": kind,
            "headline": f"{{{{headline_{i}}}}}",
            "body": f"{{{{body_{i}}}}}" if kind != "title" else "{{subtitle}}",
            "items": [],
            "stat": "",
            "narration": f"{{{{narration_{i}}}}}",
        })
        timeline.append({"scene": i, "role": role, "start_s": round(sec["start"], 1), "duration_s": dur,
                         "target_words": words, "cuts": None})
    cuts_total = shots
    if cuts_total and sections and metrics.get("duration_s"):
        per_scene = cuts_total / len(sections)
        for t in timeline:
            t["cuts"] = round(per_scene)
    return {
        "title": "{{title}}",
        "logline": "{{logline}}",
        "scenes": scenes,
        "timeline": timeline,
        "style": {
            "wpm": wpm,
            "cuts_per_min": metrics.get("cuts_per_min"),
            "shot_avg_s": metrics.get("shot_avg_s"),
            "hook_seconds": metrics.get("hook_seconds"),
            "questions": metrics.get("questions"),
            "fps": fps,
            "duration_s": metrics.get("duration_s"),
        },
        "placeholders": sorted({"title", "logline", "subtitle"} | {f"{f}_{i}" for i in range(1, len(scenes) + 1)
                                 for f in ("headline", "body", "narration")}),
    }


def prompt_md(template: dict) -> str:
    st, tl = template["style"], template["timeline"]
    dur = st.get("duration_s") or sum(t["duration_s"] for t in tl)
    lines = [
        "# HyperFrames template prompt",
        "",
        "Built from the measured structure of the analysed video. It contains no words from that video.",
        "Replace each `{{placeholder}}` with your own content, then render with the template JSON.",
        "",
        "## Style and pacing",
        "",
        f"- Length: about {dur:.0f} seconds in {len(tl)} scenes.",
        f"- Speaking pace: about {st['wpm']} words per minute of narration.",
        f"- Cut rhythm: {st['cuts_per_min'] or 'unmeasured'} cuts per minute, average shot "
        f"{st['shot_avg_s'] or 'unmeasured'} seconds.",
        f"- Hook: the first {st['hook_seconds'] or 'unmeasured'} seconds carry the opening promise.",
        f"- Questions asked to the viewer: {st['questions'] if st['questions'] is not None else 'unmeasured'}.",
        "- Keep one punch-in on every beat and a clean cut between scenes, as measured.",
        "",
        "## One prompt for the whole video",
        "",
        "```",
        "Make a 16:9 explainer with " + str(len(tl)) + " scenes. Open with a hook of about "
        f"{st['hook_seconds'] or 8:.0f} seconds that states the promise in one line. Then keep the body scenes "
        "short, one idea each, with a cut every few seconds. End with a call to action. Use the pace and cut "
        "rhythm above. Title: {{title}}. Logline: {{logline}}.",
        "```",
        "",
        "## Scene prompts",
        "",
    ]
    for t in tl:
        i = t["scene"]
        lines += [
            f"### Scene {i}: {t['role']}, {t['duration_s']} s from {t['start_s']} s",
            "",
            "```",
            f"Kind: {template['scenes'][i - 1]['kind']}. Duration {t['duration_s']} seconds. "
            f"About {t['target_words']} words of narration. "
            + (f"About {t['cuts']} cuts. " if t.get("cuts") else "")
            + f"Headline: {{{{headline_{i}}}}}. Body: {{{{body_{i}}}}}. Narration: {{{{narration_{i}}}}}.",
            "```",
            "",
        ]
    lines += ["## Placeholders", "", ", ".join(f"`{{{{{p}}}}}`" for p in template["placeholders"]), ""]
    return "\n".join(lines)


def write(out_dir, metrics: dict, sections: list[dict], shots: int | None, fps: float | None) -> list[str]:
    from pathlib import Path
    out_dir = Path(out_dir)
    t = build(metrics, sections, shots, fps)
    (out_dir / "hyperframes_template.json").write_text(json.dumps(t, indent=2))
    (out_dir / "hyperframes_prompt.md").write_text(prompt_md(t))
    return ["hyperframes_template.json", "hyperframes_prompt.md"]

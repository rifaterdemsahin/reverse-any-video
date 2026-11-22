"""The customer's README.md and AGENTS.md, written into every job's bundle.

They tell a person and their AI agent how to use the other files to make their own video with HyperFrames.
They contain no words from the analysed video: only the file list, the placeholders and the rules.
"""
from __future__ import annotations

from pathlib import Path

FILE_GUIDE = [
    ("video.json", "the title, channel, date and a link to the thumbnail of the source video, as text."),
    ("script.md", "the script to write, one block per scene, with the time and the word target. Your own words."),
    ("prompter.md", "the same script set out for a teleprompter, with pauses marked."),
    ("storyboard.png", "one storyboard sheet with a card per scene: time, length and words per scene."),
    ("metrics.json", "length, pace, cut rate, shot length and hook timing, as numbers."),
    ("hyperframes_prompt.md", "the style, the pacing and one prompt for each scene."),
    ("hyperframes_template.json", "the scene plan with {{placeholders}} for your own text, and a timeline."),
    ("edit_decision_list.edl", "one event per shot, for any video editor. Needs an uploaded video."),
    ("storyboard.md", "one panel per shot: what is on screen, camera, and whether there is speech. Needs an uploaded video."),
]


def _present(out: Path) -> list[str]:
    return [name for name, _ in FILE_GUIDE if (out / name).exists()]


def readme_md(job_id: str, source: str | None, present: list[str], placeholders: list[str]) -> str:
    lines = [
        "# Your video analysis",
        "",
        f"Job: `{job_id}`",
    ]
    if source:
        lines.append(f"Source: {source} (analysed for structure and timing only)")
    lines += ["", "## What is in this zip", ""]
    for name, what in FILE_GUIDE:
        mark = "" if name in present else " (not in this job)"
        lines.append(f"- `{name}`: {what}{mark}")
    lines += [
        "",
        "## How to make your own video",
        "",
        "1. Read `hyperframes_prompt.md` for the pace, the cut rhythm and the scene order.",
        "2. Open `hyperframes_template.json` and fill in each placeholder with your own content.",
        "3. Give the filled plan to HyperFrames, or hand the whole folder to an AI agent with `AGENTS.md`.",
        "4. Check the timing against the `timeline` in the template before you render.",
        "",
        "## Rules",
        "",
        "- Every number here was measured. Nothing is guessed.",
        "- The analysis describes structure. It does not contain the original script, frames or transcript.",
        "- Write your own words. Do not copy sentences from the original video.",
        "- Check that you have the rights to any image, music or clip you add.",
        "",
    ]
    if placeholders:
        lines += ["## Placeholders", "", ", ".join(f"`{{{{{p}}}}}`" for p in placeholders), ""]
    return "\n".join(lines)


def agents_md(present: list[str], placeholders: list[str]) -> str:
    lines = [
        "# AGENTS.md: build a video from this analysis",
        "",
        "You are helping a person make their own video in the structure measured in this folder.",
        "",
        "## Inputs",
        "",
    ]
    for name, what in FILE_GUIDE:
        if name in present:
            lines.append(f"- `{name}`: {what}")
    lines += [
        "",
        "## Steps",
        "",
        "1. Read `hyperframes_template.json`. Note each scene's `kind`, `timeline` entry and `target_words`.",
        "2. Ask the person for: the title, the logline, and for each scene a headline, a body and narration.",
        "   Ask in one list, not one question at a time.",
        "3. Write the filled plan as JSON in the same shape as the template. Keep each scene's `kind`.",
        "   Keep the narration near `target_words` for its scene, so the timing still fits.",
        "4. Build the HyperFrames project from the filled plan. Keep the scene durations from `timeline`.",
        "5. Check that the total length is within 10% of `style.duration_s`.",
        "6. Report what you filled, what you could not fill, and any scene that does not fit its time.",
        "",
        "## Rules",
        "",
        "- Do not invent facts, figures or quotes. Use only what the person gives you.",
        "- Do not copy sentences from the original video. Write new narration.",
        "- Do not change the scene order or the pacing unless the person asks.",
        "- If a placeholder has no content, leave it visibly empty and say so. Never fill it with filler text.",
        "",
    ]
    if placeholders:
        lines += ["## Placeholders to fill", "", ", ".join(f"`{{{{{p}}}}}`" for p in placeholders), ""]
    return "\n".join(lines)


def write(out: Path, job_id: str, source: str | None, placeholders: list[str]) -> list[str]:
    out = Path(out)
    present = _present(out)
    (out / "README.md").write_text(readme_md(job_id, source, present, placeholders))
    (out / "AGENTS.md").write_text(agents_md(present, placeholders))
    return ["README.md", "AGENTS.md"]

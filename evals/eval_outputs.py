"""Evals for the customer deliverables. They check the rules in AGENTS.md against real data.

Data: examples/KnqTiAXUH7M/analysis.json, the analysis of the first test video (committed in the repo).
The transcript is used only as the thing that must NOT appear in the outputs.

Run: python -m unittest discover -s evals -p "eval_*.py" -v
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import create_video  # noqa: E402
import reverse_llm  # noqa: E402
import template  # noqa: E402

ANALYSIS = ROOT / "examples" / "KnqTiAXUH7M" / "analysis.json"
DELIVERABLES = {"storyboard.md", "edit_decision_list.edl", "metrics.json",
                "hyperframes_prompt.md", "hyperframes_template.json"}
NGRAM = 6   # a run of this many words from the transcript in an output is a leak


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def transcript_ngrams(segments: list[dict], n: int = NGRAM) -> set[tuple]:
    seq = words(" ".join(s["text"] for s in segments))
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def leaks(text: str, grams: set[tuple], n: int = NGRAM) -> list[str]:
    seq = words(text)
    return [" ".join(seq[i:i + n]) for i in range(len(seq) - n + 1) if tuple(seq[i:i + n]) in grams]


class Fixture:
    """Build the deliverables from the committed analysis, the way reverse_video.run does."""

    @classmethod
    def build(cls):
        a = json.loads(ANALYSIS.read_text())
        s, v = a["script"], a["video"]
        metrics = {"duration_s": v["duration_s"], "words": s["words"], "wpm": s["wpm"],
                   "questions": s["questions"], "hook_seconds": s["hook"]["seconds"],
                   "sections": len(s["sections"]), "ctas": len(s.get("ctas") or []),
                   "shots": v["shots"], "cuts_per_min": v["cuts_per_min"], "shot_avg_s": v["shot_avg_s"]}
        out = Path(tempfile.mkdtemp())
        (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
        template.write(out, metrics, [{"start": x["start"], "end": x["end"]} for x in s["sections"]],
                       v["shots"], v["fps"])
        # Storyboard text as the model would write it: from the shot list, with speech as yes or no.
        shots = reverse_llm.shots_from_bounds(v.get("shot_bounds") or [[0, v["duration_s"]]])
        (out / "edit_decision_list.edl").write_text(
            reverse_llm.edl("Eval", shots, v.get("fps") or 25))
        panels = "\n".join(f"## Shot {i:03d}\n- On screen: a close-up of an object\n- Speech in shot: yes"
                           for i in range(1, min(len(shots), 3) + 1))
        (out / "storyboard.md").write_text("# Storyboard\n\n" + panels + "\n")
        return out, a, metrics


class OutputRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out, cls.analysis, cls.metrics = Fixture.build()
        cls.grams = transcript_ngrams(cls.analysis["segments"])

    def test_only_deliverables_are_produced(self):
        names = {p.name for p in self.out.iterdir()}
        self.assertTrue(names <= DELIVERABLES, f"unexpected files: {names - DELIVERABLES}")
        self.assertNotIn("frames.zip", names)
        self.assertNotIn("script_clean.md", names)

    def test_no_transcript_run_of_six_words_in_any_text_output(self):
        for name in ["storyboard.md", "edit_decision_list.edl", "hyperframes_prompt.md", "hyperframes_template.json"]:
            text = (self.out / name).read_text()
            self.assertEqual(leaks(text, self.grams), [], f"{name} repeats transcript wording")

    def test_metrics_are_numbers_only(self):
        data = json.loads((self.out / "metrics.json").read_text())
        for key, value in data.items():
            self.assertTrue(value is None or isinstance(value, (int, float)), f"{key} is not a number")

    def test_template_is_a_valid_plan_with_placeholders(self):
        t = json.loads((self.out / "hyperframes_template.json").read_text())
        plan = create_video.validate_plan({"title": t["title"], "logline": t["logline"], "scenes": t["scenes"]})
        self.assertEqual(len(plan["scenes"]), len(t["scenes"]))
        for scene in t["scenes"]:
            self.assertIn("{{headline_", scene["headline"])
            self.assertIn("{{narration_", scene["narration"])
        self.assertIn("title", t["placeholders"])

    def test_template_timeline_adds_up_to_the_length(self):
        t = json.loads((self.out / "hyperframes_template.json").read_text())
        total = sum(x["duration_s"] for x in t["timeline"])
        self.assertAlmostEqual(total, self.metrics["duration_s"], delta=max(1.0, 0.05 * self.metrics["duration_s"]))

    def test_prompt_mentions_no_source_title_or_channel(self):
        text = (self.out / "hyperframes_prompt.md").read_text()
        title = (self.analysis["meta"].get("title") or "").lower()
        self.assertNotIn(title, text.lower())

    def test_edl_events_are_in_order_and_numbered(self):
        lines = (self.out / "edit_decision_list.edl").read_text().splitlines()
        events = [l for l in lines if re.match(r"^\d{3}  AX", l)]
        self.assertGreater(len(events), 0)
        self.assertEqual([int(e[:3]) for e in events], list(range(1, len(events) + 1)))
        record_in = [e.split()[-2] for e in events]
        self.assertEqual(record_in, sorted(record_in))          # record times never go backwards

    def test_storyboard_says_speech_yes_or_no_never_words(self):
        text = (self.out / "storyboard.md").read_text()
        self.assertIn("Speech in shot:", text)
        self.assertEqual(leaks(text, self.grams), [])


if __name__ == "__main__":
    unittest.main()

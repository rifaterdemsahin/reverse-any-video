"""LLM outputs: timecodes, EDL, sampling, JSON parsing, and the pipeline with a stubbed DeepInfra.

No network and no API key needed. The video is generated with ffmpeg, which the other video tests also need.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import deepinfra as di  # noqa: E402
import reverse_llm as rl  # noqa: E402


def make_clip(path: Path, seconds: float = 3.0):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=duration={seconds}:size=320x240:rate=25", "-c:v", "mpeg4", "-y", str(path)],
                   check=True)


class Timecodes(unittest.TestCase):
    def test_timecode(self):
        self.assertEqual(rl.timecode(0, 25), "00:00:00:00")
        self.assertEqual(rl.timecode(1.0, 25), "00:00:01:00")
        self.assertEqual(rl.timecode(61.6, 30), "00:01:01:18")   # 1848 frames at 30 fps
        self.assertEqual(rl.timecode(3725.0, 25), "01:02:05:00")

    def test_edl_lines_and_record_times(self):
        shots = [{"start": 0.0, "end": 1.0, "name": "Hook"}, {"start": 1.0, "end": 2.5, "name": "Reveal ümlaut"}]
        text = rl.edl("Test Title", shots, 25)
        lines = text.splitlines()
        self.assertEqual(lines[0], "TITLE: Test Title")
        self.assertEqual(lines[1], "FCM: NON-DROP FRAME")
        self.assertEqual(lines[3], "001  AX       V     C        00:00:00:00 00:00:01:00 00:00:00:00 00:00:01:00")
        self.assertEqual(lines[4], "* FROM CLIP NAME:  Hook")
        self.assertEqual(lines[6], "002  AX       V     C        00:00:01:00 00:00:02:12 00:00:01:00 00:00:02:12")
        self.assertIn("Reveal ml", lines[7])           # non-ASCII stripped from clip names

    def test_sample_indices_spread_evenly(self):
        self.assertEqual(rl.sample_indices(10, 4), [0, 3, 6, 9])
        self.assertEqual(rl.sample_indices(3, 40), [0, 1, 2])
        self.assertEqual(rl.sample_indices(5, 1), [0])

    def test_parse_json_handles_fences_and_prose(self):
        self.assertEqual(di.parse_json('```json\n[{"shot": 1}]\n```'), [{"shot": 1}])
        self.assertEqual(di.parse_json('Here you go: {"a": 2} thanks'), {"a": 2})
        with self.assertRaises(di.DeepInfraError):
            di.parse_json("no json at all")


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.td = Path(tempfile.mkdtemp())
        self.video = self.td / "clip.mp4"
        make_clip(self.video, 3.0)
        self.out = self.td / "out"
        self.out.mkdir()
        self.info = {"fps": 25, "shot_bounds": [[0.0, 1.0], [1.0, 2.2], [2.2, 3.0]]}
        self.segs = [{"start": 0.1, "end": 0.9, "text": "Stop scrolling"}, {"start": 1.3, "end": 2.0, "text": "Here is the thing"}]
        self._chat, self._key = di.chat, os.environ.get("DEEPINFRA_API_KEY")

    def tearDown(self):
        di.chat = self._chat
        shutil.rmtree(self.td, ignore_errors=True)

    def stub(self, answer_fn):
        calls = []

        def fake(messages, model, key, max_tokens=3000, timeout=180):
            calls.append(model)
            return answer_fn(messages, model)
        di.chat = fake
        return calls

    def test_full_package_with_stubbed_model(self):
        def answer(messages, model):
            if model == di.VISION_MODEL:
                return ('[{"shot": 1, "description": "A lake at dusk", "camera": "wide, static", '
                        '"on_screen_text": "", "purpose": "hook", "clip_name": "Lake at dusk"},'
                        ' {"shot": 3, "description": "Close-up of a face", "camera": "close-up", '
                        '"on_screen_text": "NEW", "purpose": "reveal", "clip_name": "Face reveal"}]')
            return "## Intro\n[00:00] Stop scrolling. Here is the thing."
        calls = self.stub(answer)
        summary = rl.build(self.out, "Demo", "https://example.com/v", self.video, self.info, self.segs, "key", None)

        self.assertTrue(summary["ok"], summary["errors"])
        self.assertIn(di.VISION_MODEL, calls)
        self.assertNotIn(di.TEXT_MODEL, calls)        # no text model: nothing reproduces the transcript
        self.assertEqual(summary["edl_events"], 3)
        self.assertFalse((self.out / "script_clean.md").exists())

        edl = (self.out / "edit_decision_list.edl").read_text()
        self.assertIn("* FROM CLIP NAME:  001 Lake at dusk", edl)
        self.assertIn("* FROM CLIP NAME:  003 Face reveal", edl)
        self.assertIn("Shot 002", edl)                  # no panel for shot 2 (only 3 shots, samples 1 and 3)

        board = (self.out / "storyboard.md").read_text()
        self.assertIn("## Shot 001", board)
        self.assertIn("Speech in shot: yes", board)
        self.assertNotIn("Stop scrolling", board)     # never the transcript words
        self.assertIn("On screen: Close-up of a face", board)
        self.assertIn("- Frame: `shot_001_", board)

        with zipfile.ZipFile(self.out / "frames.zip") as z:
            names = sorted(z.namelist())
        self.assertEqual(len(names), 3)
        self.assertTrue(names[0].startswith("shot_001_00-00-00"))

    def test_model_failure_keeps_the_rest(self):
        def boom(messages, model):
            raise di.DeepInfraError("DeepInfra HTTP 503 for x: busy")
        self.stub(boom)
        summary = rl.build(self.out, "Demo", None, self.video, self.info, self.segs, "key", None)
        self.assertFalse(summary["ok"])
        self.assertTrue(any("storyboard" in e for e in summary["errors"]))
        self.assertTrue((self.out / "edit_decision_list.edl").exists())   # the EDL needs no model
        self.assertTrue((self.out / "frames.zip").exists())
        self.assertFalse((self.out / "storyboard.md").exists())

    def test_transcript_only_skips_video_outputs(self):
        self.stub(lambda m, model: "## Script\n[00:00] Hello")
        summary = rl.build(self.out, "Text only", None, None, {}, self.segs, "key", None)
        self.assertEqual(summary["files"], [])          # transcript alone gives no LLM output


if __name__ == "__main__":
    unittest.main()

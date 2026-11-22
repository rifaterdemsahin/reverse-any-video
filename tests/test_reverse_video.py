"""Run with:  python -m unittest discover -s tests -v"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

import reverse_video as rv  # noqa: E402


class TranscriptParsing(unittest.TestCase):
    def test_youtube_copy(self):
        segs, fmt = rv.parse_transcript((FIX / "demo_script_youtube_copy.txt").read_text())
        self.assertEqual(fmt, "youtube-copy")
        self.assertEqual(len(segs), 11)
        self.assertEqual(segs[1]["start"], 7)
        self.assertEqual(segs[-1]["start"], 84)

    def test_vtt_dedupes_rolling_captions(self):
        segs, fmt = rv.parse_transcript((FIX / "demo.vtt").read_text())
        self.assertEqual(fmt, "vtt")
        self.assertEqual([s["text"] for s in segs],
                         ["Stop copying editing styles", "by guessing. Want to know why?",
                          "Here's how to measure any video."])

    def test_srt(self):
        segs, fmt = rv.parse_transcript((FIX / "demo.srt").read_text())
        self.assertEqual(fmt, "srt")
        self.assertEqual(segs[1]["start"], 3.5)

    def test_json3_and_json_list(self):
        j3 = {"events": [{"tStartMs": 0, "dDurationMs": 2000, "segs": [{"utf8": "Hello "}, {"utf8": "there"}]},
                         {"tStartMs": 2000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]}]}
        segs, fmt = rv.parse_transcript(json.dumps(j3))
        self.assertEqual((fmt, segs[0]["text"], segs[0]["end"]), ("youtube-json3", "Hello there", 2.0))
        segs, fmt = rv.parse_transcript(json.dumps([{"text": "a b", "start": 1, "duration": 2}]))
        self.assertEqual((fmt, segs[0]["end"]), ("json-list", 3.0))

    def test_plain_text_is_flagged_estimated(self):
        _, fmt = rv.parse_transcript("One sentence here. Another one there.")
        self.assertIn("estimated", fmt)


class ScriptAnalysis(unittest.TestCase):
    def setUp(self):
        self.segs, _ = rv.parse_transcript((FIX / "demo_script_youtube_copy.txt").read_text())
        self.a = rv.analyze_script(self.segs)

    def test_hook(self):
        self.assertTrue(self.a["hook"]["text"].startswith("Stop copying"))
        self.assertIn("promise", self.a["hook"]["kinds"])
        self.assertIn("contrarian / curiosity", self.a["hook"]["kinds"])

    def test_markers(self):
        self.assertEqual([round(x["t"]) for x in self.a["ctas"]], [52, 84])
        loops = {x["match"].lower() for x in self.a["open_loops"]}
        self.assertTrue({"i'll show you", "but first"} <= loops)
        self.assertEqual(self.a["questions"], 1)

    def test_sections_and_rate(self):
        self.assertGreaterEqual(len(self.a["sections"]), 3)
        self.assertTrue(100 < self.a["wpm"] < 250)

    def test_outputs_render(self):
        meta = {"id": "demo", "title": "Demo", "url": "https://example.com"}
        self.assertIn("Speaking rate", rv.blueprint_md(meta, self.a, {}))
        self.assertIn("## [0:00]", rv.script_md(meta, self.segs, self.a))
        self.assertIn("<blockquote>Stop copying", rv.report_html(meta, self.a, {}, self.segs))


class Ids(unittest.TestCase):
    def test_youtube_id(self):
        for u in ["https://www.youtube.com/watch?v=KnqTiAXUH7M", "https://youtu.be/KnqTiAXUH7M?t=3",
                  "https://youtube.com/shorts/KnqTiAXUH7M"]:
            self.assertEqual(rv.youtube_id(u), "KnqTiAXUH7M")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class VideoAnalysis(unittest.TestCase):
    """Builds a 10 s clip with cuts at 2, 3.5, 6 and 8 s and a silent gap at 4–5 s."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.path = Path(cls.td.name) / "synthetic.mp4"
        shots = [("red", 2), ("blue", 1.5), ("testsrc", 2.5), ("green", 2), ("smptebars", 2)]
        args, filt = [], []
        for i, (src, d) in enumerate(shots):
            v = f"testsrc=size=320x180:rate=25:duration={d}" if src == "testsrc" else \
                f"smptebars=size=320x180:rate=25:duration={d}" if src == "smptebars" else \
                f"color=c={src}:size=320x180:rate=25:duration={d}"
            args += ["-f", "lavfi", "-i", v]
            filt.append(f"[{i}:v]")
        audio = "sine=frequency=440:duration=10,volume='if(between(t,4,5),0,1)':eval=frame"
        args += ["-f", "lavfi", "-i", audio]
        fc = "".join(filt) + f"concat=n={len(shots)}:v=1:a=0[v]"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args, "-filter_complex", fc,
                        "-map", "[v]", "-map", f"{len(shots)}:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-shortest", str(cls.path)], check=True)
        cls.v = rv.analyze_video(cls.path)

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_cuts(self):
        self.assertEqual([round(c, 1) for c in self.v["cuts"]], [2.0, 3.5, 6.0, 8.0])
        self.assertEqual(self.v["shots"], 5)
        self.assertAlmostEqual(self.v["shot_avg_s"], 2.0, delta=0.05)

    def test_silence_and_frames(self):
        self.assertTrue(any(3.9 <= s["start"] <= 4.1 for s in self.v["silences"]))
        self.assertEqual(len(self.v["frames"]), 5)

    def test_cli_end_to_end(self):
        out = Path(self.td.name) / "out"
        code = rv.main([str(self.path), "--transcript", str(FIX / "demo.srt"), "--out", str(out)])
        self.assertEqual(code, 0)
        d = out / "synthetic"
        for f in ("analysis.json", "script.md", "SKILL.md", "report.html"):
            self.assertTrue((d / f).stat().st_size > 0, f)
        self.assertIn("cuts per minute", (d / "SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()

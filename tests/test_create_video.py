"""Tests for create_video.py. The real render test is opt-in:  RAV_RENDER_TEST=1"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

import create_video as cv  # noqa: E402

PLAN = json.loads((FIX / "demo_plan.json").read_text())
METRICS = {"wpm": 150, "hook_seconds": 12, "hook_kinds": ["promise"], "shot_avg_s": 2.2,
           "sections": [{"label": "Hook", "share": 0.2}], "open_loops": ["I'll show you"], "ctas": ["description"]}


class FakeStream:
    def __init__(self, text, stop="end_turn"):
        self.msg = SimpleNamespace(stop_reason=stop, stop_details=None,
                                   content=[SimpleNamespace(type="thinking", thinking=""),
                                            SimpleNamespace(type="text", text=text)])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClaude:
    def __init__(self, text, stop="end_turn"):
        self.calls = []
        outer = self

        class _M:
            def stream(self, **kw):
                outer.calls.append(kw)
                return FakeStream(text, stop)
        self.beta = SimpleNamespace(messages=_M())


class Touches(unittest.TestCase):
    def test_defaults_and_validation(self):
        t = cv.clean_touches({"accent": "red;}</style>", "font": "Comic Sans", "aspect": "cinema",
                              "duration_s": "9999", "custom_css": "h1{color:red}</style><script>", "captions": "false"})
        self.assertEqual(t["accent"], cv.TOUCH_DEFAULTS["accent"])
        self.assertEqual(t["font"], "Inter")
        self.assertEqual(t["aspect"], "landscape")
        self.assertEqual(t["duration_s"], 600)
        self.assertNotIn("</style", t["custom_css"].lower())
        self.assertFalse(t["captions"])


class Plan(unittest.TestCase):
    def test_prompt_carries_blueprint_numbers(self):
        p = cv.build_prompt(METRICS, "# blueprint", "Automate reports", cv.clean_touches({"duration_s": 60, "cta": "Book a demo"}))
        self.assertIn("about 150 words", p)
        self.assertIn("within 12 s", p)
        self.assertIn("Book a demo", p)

    def test_write_plan_request_and_parse(self):
        fake = FakeClaude(json.dumps(PLAN))
        plan = cv.write_plan(METRICS, "bp", "brief", cv.clean_touches({}), client=fake)
        self.assertEqual(len(plan["scenes"]), 5)
        kw = fake.calls[0]
        self.assertEqual(kw["model"], cv.MODEL)
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertNotIn("thinking", kw)

    def test_refusal_and_truncation(self):
        with self.assertRaisesRegex(RuntimeError, "declined"):
            cv.write_plan(METRICS, "", "b", cv.clean_touches({}), client=FakeClaude("{}", "refusal"))
        with self.assertRaisesRegex(RuntimeError, "cut off"):
            cv.write_plan(METRICS, "", "b", cv.clean_touches({}), client=FakeClaude("{}", "max_tokens"))

    def test_validate_plan(self):
        with self.assertRaises(ValueError):
            cv.validate_plan({"scenes": []})
        p = cv.validate_plan({"scenes": [{"kind": "bogus", "headline": "x"}]})
        self.assertEqual(p["scenes"][0]["kind"], "point")


class Build(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.out = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_project_files_and_timing(self):
        logo = self.out / "logo.png"
        logo.write_bytes(b"\x89PNG fake")
        touches = cv.clean_touches({"brand": "Acme <b>", "accent": "#ff5a1f", "aspect": "portrait",
                                    "custom_css": ".headline{letter-spacing:0}"})
        proj = cv.build_project(PLAN, touches, METRICS, self.out / "p", logo)
        html = (proj / "index.html").read_text()
        times = cv.timeline(cv.validate_plan(PLAN), METRICS)
        total = round(times[-1]["start"] + times[-1]["duration"], 2)
        self.assertIn(f'data-duration="{total}"', html)
        self.assertIn('data-width="1080" data-height="1920"', html)
        self.assertIn("--accent: #ff5a1f", html)
        self.assertIn('src="assets/logo.png"', html)
        self.assertIn(".headline{letter-spacing:0}", html)
        self.assertIn('window.__timelines["main"] = tl;', html)
        self.assertEqual(html.count('class="clip scene'), 5)
        self.assertIn("immediateRender: false", html)
        self.assertTrue((proj / "assets" / "logo.png").exists())
        srt = (proj / "captions.srt").read_text()
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> "))
        # narration of 20 words at 150 wpm = 8.0 s + 0.6 s
        self.assertEqual(times[0]["duration"], 8.6)
        z = cv.zip_project(proj, self.out / "p.zip")
        import zipfile
        self.assertIn("index.html", zipfile.ZipFile(z).namelist())

    def test_text_is_escaped(self):
        plan = {"title": "t", "logline": "", "scenes": [{"kind": "point", "headline": "<img src=x onerror=alert(1)>",
                                                         "body": "", "items": [], "stat": "", "narration": "hi"}]}
        html = (cv.build_project(plan, {}, {}, self.out / "x") / "index.html").read_text()
        self.assertNotIn("<img src=x", html)

    def test_backend_choice(self):
        with mock.patch.dict(os.environ, {"SPRITES_TOKEN": "t", "RENDER_BACKEND": "auto"}):
            self.assertEqual(cv.pick_backend(), "sprite")
        with mock.patch.dict(os.environ, {"RENDER_BACKEND": "none"}):
            self.assertEqual(cv.pick_backend(), "none")


class FakeSpritePath:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def __truediv__(self, other):
        return FakeSpritePath(self.store, f"{self.path}/{other}")

    def write_bytes(self, data, mkdir_parents=True):
        self.store[self.path] = data

    def read_bytes(self):
        return self.store[self.path]


class FakeSprite:
    def __init__(self):
        self.store, self.commands = {}, []

    def run(self, *args, capture_output=False, timeout=None, **kw):
        self.commands.append(args)
        if "render -o out.mp4" in args[-1]:
            remote = args[-1].split("cd ", 1)[1].split(" ", 1)[0]
            assert f"{remote}/index.html" in self.store
            self.store[f"{remote}/out.mp4"] = b"MP4DATA"
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    def filesystem(self, root):
        return FakeSpritePath(self.store, root)


class SpriteRender(unittest.TestCase):
    def test_render_sprite_creates_uploads_renders_downloads(self):
        from sprites import SpriteError
        sprite = FakeSprite()

        class Client:
            created = None

            def get_sprite(self, name):
                raise SpriteError("not found")

            def create_sprite(self, name, **kw):
                Client.created = (name, kw)
                return sprite
        with tempfile.TemporaryDirectory() as td:
            proj = cv.build_project(PLAN, {}, METRICS, Path(td) / "p")
            out = cv.render_sprite(proj, Path(td) / "v.mp4", name="rav-test", client=Client(), job="abc", log=lambda m: None)
            self.assertEqual(out.read_bytes(), b"MP4DATA")
        self.assertEqual(Client.created[0], "rav-test")
        self.assertEqual(Client.created[1]["config"].ram_mb, 4096)
        self.assertIn("hyperframes browser ensure", sprite.commands[0][-1])
        self.assertEqual(sprite.commands[-1][:3], ("rm", "-rf", "/tmp/rav/abc"))


@unittest.skipUnless(os.environ.get("RAV_RENDER_TEST") and shutil.which("npx"), "set RAV_RENDER_TEST=1 to render for real")
class RealRender(unittest.TestCase):
    def test_render_local(self):
        with tempfile.TemporaryDirectory() as td:
            plan = {"title": "t", "logline": "", "scenes": PLAN["scenes"][:2]}
            proj = cv.build_project(plan, {"brand": "Acme"}, METRICS, Path(td) / "p")
            out = cv.render_local(proj, Path(td) / "v.mp4", "draft", log=lambda m: None)
            self.assertGreater(out.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()

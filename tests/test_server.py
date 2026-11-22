"""API tests. Need: pip install -r requirements-dev.txt"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

_tmp = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _tmp.name
os.environ["ACCESS_TOKEN"] = "test-token"
os.environ["RENDER_BACKEND"] = "none"


@unittest.skipUnless(TestClient, "fastapi/httpx not installed")
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.c = TestClient(server.app)
        cls.h = {"X-Access-Token": "test-token"}

    def wait(self, job_id, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            j = self.c.get(f"/api/jobs/{job_id}").json()
            if j["status"] in ("done", "error"):
                return j
            time.sleep(0.1)
        self.fail("job did not finish")

    def test_health_and_page(self):
        h = self.c.get("/healthz").json()
        self.assertEqual(h["service"], "reverse-any-video")
        self.assertTrue(h["auth_required"])
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/reverse-any-video", r.text)
        self.assertEqual(self.c.get("/thumbnail.jpg").headers["content-type"], "image/jpeg")

    def test_token_and_validation(self):
        self.assertEqual(self.c.post("/api/jobs", data={"transcript": "hi"}).status_code, 401)
        self.assertEqual(self.c.post("/api/jobs", data={}, headers=self.h).status_code, 400)
        r = self.c.post("/api/jobs", data={"url": "https://example.com/x"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not allowed", r.json()["error"])
        self.assertEqual(self.c.post("/api/jobs", data={"url": "file:///etc/passwd"}, headers=self.h).status_code, 400)
        self.assertEqual(self.c.get("/api/jobs/nope").status_code, 404)

    def test_transcript_job(self):
        text = (FIX / "demo_script_youtube_copy.txt").read_text()
        r = self.c.post("/api/jobs", data={"transcript": text, "title": "Demo"}, headers=self.h)
        self.assertEqual(r.status_code, 202)
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        a = j["result"]["analysis"]
        self.assertEqual(a["meta"]["title"], "Demo")
        self.assertEqual(a["script"]["wpm"], 119)
        for name, url in j["files"].items():
            f = self.c.get(url)
            self.assertEqual(f.status_code, 200, name)
        self.assertEqual(self.c.get(f"/api/jobs/{j['id']}/files/../../etc/passwd").status_code, 404)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_video_upload_job(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "clip.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                            "-f", "lavfi", "-i", "color=c=red:size=160x90:rate=25:duration=2",
                            "-f", "lavfi", "-i", "color=c=blue:size=160x90:rate=25:duration=2",
                            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
            with path.open("rb") as f:
                r = self.c.post("/api/jobs", files={"video": ("clip.mp4", f, "video/mp4")},
                                data={"transcript": (FIX / "demo.srt").read_text()}, headers=self.h)
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        v = j["result"]["analysis"]["video"]
        self.assertEqual(v["shots"], 2)
        self.assertEqual(len(j["result"]["frames"]), 2)
        leftover = sorted(p.name for p in Path(self.server.jobs[j["id"]]["dir"]).iterdir())
        self.assertEqual(leftover, ["SKILL.md", "analysis.json", "report.html", "script.md"])


    def test_plan_job_uses_claude_step(self):
        import json
        from unittest import mock
        plan = json.loads((FIX / "demo_plan.json").read_text())
        with mock.patch.object(self.server.cv, "write_plan", return_value=plan) as wp:
            r = self.c.post("/api/plans", headers=self.h, data={
                "brief": "Automate the weekly report", "blueprint": "# bp",
                "metrics": json.dumps({"wpm": 150}), "touches": json.dumps({"accent": "#ff5a1f", "font": "Nope"})})
            self.assertEqual(r.status_code, 202, r.text)
            j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        args = wp.call_args.args
        self.assertEqual(args[2], "Automate the weekly report")
        self.assertEqual(args[3]["font"], "Inter")          # touches were cleaned
        self.assertEqual(len(j["result"]["plan"]["scenes"]), 5)
        self.assertIn("plan.json", j["files"])
        self.assertEqual(self.c.post("/api/plans", headers=self.h, data={"brief": "x", "metrics": "[1"}).status_code, 400)

    def test_render_job_builds_project(self):
        import io
        import json
        import zipfile
        plan = (FIX / "demo_plan.json").read_text()
        r = self.c.post("/api/renders", headers=self.h,
                        data={"plan": plan, "touches": json.dumps({"brand": "Acme"}), "metrics": json.dumps({"wpm": 150})},
                        files={"logo": ("logo.png", b"\x89PNG", "image/png")})
        self.assertEqual(r.status_code, 202, r.text)
        j = self.wait(r.json()["id"])
        self.assertEqual(j["status"], "done", j)
        self.assertEqual(j["result"]["backend"], "none")
        self.assertFalse(j["result"]["video"])
        self.assertNotIn("video.mp4", j["files"])
        z = zipfile.ZipFile(io.BytesIO(self.c.get(j["files"]["project.zip"]).content))
        self.assertIn("assets/logo.png", z.namelist())
        self.assertIn("index.html", z.namelist())
        self.assertIn("-->", self.c.get(j["files"]["captions.srt"]).text)
        bad = self.c.post("/api/renders", headers=self.h, data={"plan": json.dumps({"scenes": []})})
        self.assertEqual(bad.status_code, 400)
        bad = self.c.post("/api/renders", headers=self.h, data={"plan": plan}, files={"logo": ("x.exe", b"MZ", "application/octet-stream")})
        self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main()

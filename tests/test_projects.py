"""Project folders and Azure output saving, against an in-memory fake of the blob container.

Need: pip install -r requirements-dev.txt
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

import storage  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _tmp.name
os.environ["ACCESS_TOKEN"] = "test-token"
os.environ["AZURE_STORAGE_CONNECTION_STRING"] = "DefaultEndpointsProtocol=https;AccountName=fake;AccountKey=ZmFrZQ==;EndpointSuffix=core.windows.net"

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - ImportError, or RuntimeError when httpx2 is missing
    TestClient = None


class FakeBlob:
    def __init__(self, container, name):
        self.container, self.name = container, name

    def exists(self):
        return self.name in self.container.blobs

    def download_blob(self):
        return SimpleNamespace(readall=lambda: self.container.blobs[self.name])


class FakeContainer:
    """Just enough of azure's ContainerClient for ProjectStore."""

    def __init__(self):
        self.blobs = {}

    def upload_blob(self, name, data, overwrite=False):
        if name in self.blobs and not overwrite:
            raise FileExistsError(name)
        self.blobs[name] = data.read() if hasattr(data, "read") else data

    def get_blob_client(self, name):
        return FakeBlob(self, name)

    def list_blobs(self, name_starts_with=""):
        return [SimpleNamespace(name=n) for n in sorted(self.blobs) if n.startswith(name_starts_with)]

    def walk_blobs(self, name_starts_with="", delimiter="/"):
        folders = set()
        for n in self.blobs:
            if n.startswith(name_starts_with):
                rest = n[len(name_starts_with):]
                if delimiter in rest:
                    folders.add(name_starts_with + rest.split(delimiter)[0] + delimiter)
        for f in sorted(folders):
            yield SimpleNamespace(name=f)


class StoreUnit(unittest.TestCase):
    def setUp(self):
        self.container = FakeContainer()
        self.store = storage.ProjectStore(self.container)

    def test_slugify(self):
        self.assertEqual(storage.slugify("  My Video Project!! "), "my-video-project")
        self.assertEqual(storage.slugify("!!!"), "")

    def test_create_and_list_projects(self):
        rec = self.store.create_project("Hook Study")
        self.assertEqual(rec["slug"], "hook-study")
        self.assertIn("projects/hook-study/project.json", self.container.blobs)
        self.store.create_project("Second One")
        self.assertEqual([p["slug"] for p in self.store.list_projects()], ["hook-study", "second-one"])
        with self.assertRaises(storage.ProjectExists):
            self.store.create_project("hook study")  # same slug
        with self.assertRaises(ValueError):
            self.store.create_project("???")

    def test_get_project_and_jobs(self):
        self.store.create_project("Demo")
        out = Path(_tmp.name) / "unit-out"
        out.mkdir(exist_ok=True)
        (out / "script.md").write_text("# hi")
        (out / "SKILL.md").write_text("# skill")
        saved = self.store.save_outputs("demo", "job123", out, ["script.md", "SKILL.md", "report.html"])
        self.assertEqual(saved, ["projects/demo/jobs/job123/script.md", "projects/demo/jobs/job123/SKILL.md"])
        rec = self.store.get_project("demo")
        self.assertEqual(rec["jobs"], ["job123"])
        self.assertIsNone(self.store.get_project("missing"))
        self.assertIsNone(self.store.get_project("../etc"))

    def test_internal_files_go_under_internal_prefix(self):
        self.store.create_project("Internal")
        src = Path(_tmp.name) / "upload.mp4"
        src.write_bytes(b"video")
        saved = self.store.save_internal("job9", [src, Path(_tmp.name) / "missing.zip"])
        self.assertEqual(saved, ["internal/job9/upload.mp4"])
        self.assertEqual(self.container.blobs["internal/job9/upload.mp4"], b"video")
        self.assertFalse(any(n.startswith("projects/internal/jobs/job9") for n in self.container.blobs))

    def test_storage_not_configured(self):
        saved = os.environ.pop("AZURE_STORAGE_CONNECTION_STRING")
        try:
            with self.assertRaises(storage.StorageError):
                storage._connection_string()
        finally:
            os.environ["AZURE_STORAGE_CONNECTION_STRING"] = saved


@unittest.skipUnless(TestClient, "fastapi/httpx not installed")
class ProjectApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.container = FakeContainer()
        server._store = storage.ProjectStore(cls.container)
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

    def test_project_endpoints_need_token(self):
        self.assertEqual(self.c.post("/api/projects", data={"name": "x"}).status_code, 401)
        self.assertEqual(self.c.get("/api/projects").status_code, 401)
        self.assertEqual(self.c.get("/api/projects/x").status_code, 401)

    def test_create_list_get(self):
        r = self.c.post("/api/projects", data={"name": "Reverse Test"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["slug"], "reverse-test")
        self.assertEqual(self.c.post("/api/projects", data={"name": "Reverse Test"}, headers=self.h).status_code, 409)
        self.assertEqual(self.c.post("/api/projects", data={"name": "  "}, headers=self.h).status_code, 400)
        names = [p["slug"] for p in self.c.get("/api/projects", headers=self.h).json()["projects"]]
        self.assertIn("reverse-test", names)
        self.assertEqual(self.c.get("/api/projects/reverse-test", headers=self.h).json()["jobs"], [])
        self.assertEqual(self.c.get("/api/projects/nope", headers=self.h).status_code, 404)

    def test_job_in_project_saves_outputs(self):
        self.c.post("/api/projects", data={"name": "Saved Run"}, headers=self.h)
        r = self.c.post("/api/jobs", data={"transcript": "Stop scrolling. Here is the thing. Subscribe.",
                                           "project": "saved-run"}, headers=self.h)
        self.assertEqual(r.status_code, 202)
        job = self.wait(r.json()["id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["project"], "saved-run")
        names = sorted(job["saved_to"])
        self.assertTrue(all(n.startswith(f"projects/saved-run/jobs/{job['id']}/") for n in names))
        self.assertIn(f"projects/saved-run/jobs/{job['id']}/SKILL.md", self.container.blobs)
        self.assertIn(job["id"], self.c.get("/api/projects/saved-run", headers=self.h).json()["jobs"])

    def test_unknown_project_rejected_before_work(self):
        r = self.c.post("/api/jobs", data={"transcript": "hello there", "project": "ghost"}, headers=self.h)
        self.assertEqual(r.status_code, 404)

    def test_setup_page_and_menu(self):
        r = self.c.get("/setup")
        self.assertEqual(r.status_code, 200)
        self.assertIn("setup guide", r.text.lower())
        self.assertIn('href="/setup"', self.c.get("/").text)

    def test_capabilities_report_storage(self):
        self.assertTrue(self.c.get("/healthz").json()["azure_storage"])


if __name__ == "__main__":
    unittest.main()

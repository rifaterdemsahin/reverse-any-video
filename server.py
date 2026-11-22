"""HTTP server for reverse-any-video (deployable to Fly.io).

  GET  /                          the analyzer page (docs/index.html)
  GET  /healthz, /api/health      health and capability check
  POST /api/jobs                  start an analysis (multipart form, see below)
  GET  /api/jobs/{id}             job status, log and results
  GET  /api/jobs/{id}/files/{f}   report.html, SKILL.md, script.md, analysis.json,
                                  plan.json, captions.srt, project.zip, video.mp4
  POST /api/plans                 Claude writes a new script in the measured style
  POST /api/renders               build a HyperFrames project from a plan and render it
  GET  /api/jobs/{id}/files/{f}   report.html, SKILL.md, script.md or analysis.json
  POST /api/projects              create a project (needs X-Access-Token if set)
  GET  /api/projects              list projects
  GET  /api/projects/{slug}       one project and its job ids

POST /api/jobs fields (at least one of url, transcript, transcript_file, video):
  url              video URL (YouTube by default, see ALLOWED_URL_HOSTS)
  title            title to use when the source has none
  download         "true" to download the video and detect cuts with ffmpeg
  transcript       transcript text in any supported format
  transcript_file  transcript upload
  video            video file upload
  project          slug of an existing project: the outputs are saved to Azure under its folder

Environment:
  DATA_DIR           where job folders live (default /tmp/rav-jobs)
  WORKERS            concurrent analyses (default 2)
  MAX_UPLOAD_MB      upload limit (default 300)
  MAX_DURATION       longest video to download, seconds (default 1800)
  JOB_TTL            seconds to keep finished jobs (default 3600)
  ALLOWED_URL_HOSTS  comma-separated hosts, or * for any (default: YouTube hosts)
  ACCESS_TOKEN       if set, /api/jobs and /api/projects require header X-Access-Token
  YT_COOKIES         contents of a cookies.txt, for when YouTube asks to sign in
  ANTHROPIC_API_KEY  for POST /api/plans (Claude writes the script)
  RENDER_BACKEND     auto (default), sprite, local or none
  SPRITES_TOKEN      Fly.io Sprites token: renders run on a Sprite (SPRITE_NAME, default rav-render)
  RENDER_WORKERS     renders at once (default 1)
  AZURE_KEYVAULT_URL, AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
                     Key Vault that holds the storage connection string (see storage.py)
  AZURE_STORAGE_CONNECTION_STRING   alternative to Key Vault, for local runs
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import create_video as cv
import reverse_video as rv
import deepinfra
import pricing
import storage

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA = Path(os.environ.get("DATA_DIR", "/tmp/rav-jobs"))
WORKERS = int(os.environ.get("WORKERS", "2"))
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "300")) * 1024 * 1024
MAX_DURATION = int(os.environ.get("MAX_DURATION", "1800"))
JOB_TTL = int(os.environ.get("JOB_TTL", "3600"))
ALLOWED = {h.strip().lower() for h in os.environ.get(
    "ALLOWED_URL_HOSTS", "youtube.com,www.youtube.com,m.youtube.com,youtu.be,music.youtube.com").split(",") if h.strip()}
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN") or None
# What a job delivers. Numbers, structure and a template only: no transcript, no frames, no video.
OUTPUT_FILES = {"storyboard.md": "text/markdown", "edit_decision_list.edl": "text/plain",
                "metrics.json": "application/json", "hyperframes_prompt.md": "text/markdown",
                "hyperframes_template.json": "application/json"}
LOGO_TYPES = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
QUALITIES = {"draft", "looks", "delivery", "standard", "high"}

DATA.mkdir(parents=True, exist_ok=True)
COOKIES: str | None = None
if os.environ.get("YT_COOKIES"):
    _c = DATA / "cookies.txt"
    _c.write_text(os.environ["YT_COOKIES"].replace("\\n", "\n"))
    _c.chmod(0o600)
    COOKIES = str(_c)

app = FastAPI(title="reverse-any-video", docs_url="/api/docs", redoc_url=None)
pool = ThreadPoolExecutor(max_workers=WORKERS)
render_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("RENDER_WORKERS", "1")))
jobs: dict[str, dict] = {}
lock = threading.Lock()
_store: storage.ProjectStore | None = None
_store_lock = threading.Lock()


def get_store() -> storage.ProjectStore:
    """The Azure project store, created on first use (it contacts Key Vault and Azure)."""
    global _store
    if not storage.configured():
        raise storage.StorageError("Azure storage is not configured on this server.")
    with _store_lock:
        if _store is None:
            _store = storage.ProjectStore.from_env()
    return _store


def capabilities() -> dict:
    return {"service": "reverse-any-video", "ok": True, "ffmpeg": bool(shutil.which("ffmpeg")),
            "yt_dlp": bool(shutil.which("yt-dlp")), "js_runtime": bool(shutil.which("deno") or shutil.which("node")),
            "cookies": COOKIES is not None, "auth_required": ACCESS_TOKEN is not None,
            "llm": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "deepinfra": deepinfra.api_key() is not None,
            "model": cv.MODEL, "render_backend": cv.pick_backend(), "fonts": cv.FONTS, "aspects": list(cv.ASPECTS),
            "azure_storage": storage.configured(),
            "max_upload_mb": MAX_UPLOAD // (1024 * 1024), "max_duration_s": MAX_DURATION,
            "allowed_url_hosts": sorted(ALLOWED), "queued_or_running": sum(j["status"] in ("queued", "running") for j in jobs.values())}


@app.get("/healthz")
@app.get("/api/health")
def health():
    return capabilities()


def _check_token(token: str | None):
    if ACCESS_TOKEN and not (token and secrets.compare_digest(token, ACCESS_TOKEN)):
        raise HTTPException(401, "Missing or wrong X-Access-Token.")


def _check_url(url: str):
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise HTTPException(400, "url must start with http:// or https://")
    if "*" not in ALLOWED and p.hostname.lower() not in ALLOWED:
        raise HTTPException(400, f"Host {p.hostname} is not allowed. Allowed: {', '.join(sorted(ALLOWED))}")


def _save_upload(upload: UploadFile, dest: Path) -> Path:
    size = 0
    with dest.open("wb") as f:
        while chunk := upload.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"Upload is larger than {MAX_UPLOAD // (1024 * 1024)} MB.")
            f.write(chunk)
    return dest


def _cleanup():
    cutoff = time.time() - JOB_TTL
    with lock:
        old = [k for k, j in jobs.items() if j.get("finished") and j["finished"] < cutoff]
        for k in old:
            shutil.rmtree(jobs.pop(k)["dir"], ignore_errors=True)


def _work(job_id: str, source: str | None, transcript: str | None, video: Path | None, download: bool,
          title: str | None, project: str | None = None):
    job = jobs[job_id]
    job.update(status="running", started=time.time())
    try:
        result = rv.run(source, DATA, transcript, video, download, COOKIES, max_duration=MAX_DURATION,
                        job_id=job_id, log=lambda m: job["log"].append(m), title=title)
        out = Path(result["out_dir"])
        # Working files (source video, frames) go to Azure for the operator. Customers never get them.
        if storage.configured():
            try:
                internal = [out / "frames.zip"] + ([video] if video else [])
                job["internal_saved"] = get_store().save_internal(job_id, internal)
            except Exception as e:  # noqa: BLE001 - the deliverables still go out
                job["log"].append(f"internal storage failed: {type(e).__name__}")
        for f in out.iterdir():                      # keep outputs, drop large media
            if f.name not in OUTPUT_FILES:
                f.unlink(missing_ok=True)
        saved = []
        if project:
            job["log"].append(f"saving outputs to project {project}")
            saved = get_store().save_outputs(project, job_id, out, sorted(OUTPUT_FILES))
        job.update(status="done", project=project, saved_to=saved,
                   result={"metrics": json.loads((out / "metrics.json").read_text()) if (out / "metrics.json").exists() else {},
                           "llm": (result["analysis"].get("llm") or {}).get("files", []),
                           "has_transcript": result["has_transcript"], "has_video": result["has_video"]})
    except Exception as e:  # noqa: BLE001 - report every failure to the client
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        job["finished"] = time.time()
        if video:
            video.unlink(missing_ok=True)


@app.post("/api/jobs", status_code=202)
def create_job(url: str = Form(""), download: bool = Form(False), transcript: str = Form(""), title: str = Form(""),
               transcript_file: UploadFile | None = File(None), video: UploadFile | None = File(None),
               project: str = Form(""), x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    _cleanup()
    url = url.strip()
    if url:
        _check_url(url)
    project = project.strip() or None
    if project:
        if get_store().get_project(project) is None:
            raise HTTPException(404, f"No project called '{project}'. Create it first with POST /api/projects.")
    text = transcript.strip() or None
    if transcript_file is not None and transcript_file.filename:
        text = transcript_file.file.read(5 * 1024 * 1024).decode("utf-8", errors="replace")
    has_video = video is not None and bool(video.filename)
    if not (url or text or has_video):
        raise HTTPException(400, "Send a url, a transcript, or a video file.")

    job_id = uuid.uuid4().hex[:12]
    job_dir = DATA / job_id
    job_dir.mkdir(parents=True)
    video_path = None
    if has_video:
        suffix = re.sub(r"[^.\w]", "", Path(video.filename).suffix)[:8] or ".mp4"
        try:
            video_path = _save_upload(video, job_dir / f"upload{suffix}")
        except HTTPException:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise
    with lock:
        jobs[job_id] = {"id": job_id, "status": "queued", "created": time.time(), "dir": str(job_dir),
                        "log": [], "error": None, "result": None, "finished": None}
    pool.submit(_work, job_id, url or None, text, video_path, False, title.strip() or None, project)  # URLs: no download
    return {"id": job_id, "status": "queued", "status_url": f"/api/jobs/{job_id}", "project": project}


def _public(job: dict) -> dict:
    out = {k: job.get(k) for k in ("id", "status", "log", "error", "result", "project", "saved_to")}
    if job["status"] == "done":
        d = Path(job["dir"])
        out["files"] = {name: f"/api/jobs/{job['id']}/files/{name}" for name in OUTPUT_FILES if (d / name).exists()}
    return out


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job. Jobs are kept for an hour and are lost on restart.")
    return _public(job)


@app.get("/api/jobs/{job_id}/files/{name}")
def get_file(job_id: str, name: str):
    job = jobs.get(job_id)
    if not job or name not in OUTPUT_FILES:
        raise HTTPException(404, "Not found.")
    path = Path(job["dir"]) / name
    if not path.exists():
        raise HTTPException(404, "Not ready yet.")
    return FileResponse(path, media_type=OUTPUT_FILES[name])


# --------------------------------------------------------------------------- #
# Create: plan with Claude, then render with HyperFrames                      #
# --------------------------------------------------------------------------- #

def _json_form(value: str, name: str) -> dict:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"{name} is not valid JSON: {e.msg}")
    if not isinstance(data, dict):
        raise HTTPException(400, f"{name} must be a JSON object.")
    return data


def _new_job(kind: str) -> dict:
    _cleanup()
    job_id = uuid.uuid4().hex[:12]
    job_dir = DATA / job_id
    job_dir.mkdir(parents=True)
    job = {"id": job_id, "kind": kind, "status": "queued", "created": time.time(), "dir": str(job_dir),
           "log": [], "error": None, "result": None, "finished": None}
    with lock:
        jobs[job_id] = job
    return job


def _work_plan(job: dict, brief: str, blueprint: str, metrics: dict, touches: dict):
    job.update(status="running", started=time.time())
    try:
        job["log"].append(f"plan: asking {cv.MODEL}")
        plan = cv.write_plan(metrics, blueprint, brief, touches)
        (Path(job["dir"]) / "plan.json").write_text(json.dumps({"plan": plan, "touches": touches, "metrics": metrics}, indent=2))
        job["log"].append(f"plan: {len(plan['scenes'])} scenes")
        job.update(status="done", result={"plan": plan, "touches": touches, "metrics": metrics})
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        job["finished"] = time.time()


@app.post("/api/plans", status_code=202)
def create_plan(brief: str = Form(...), blueprint: str = Form(""), metrics: str = Form("{}"),
                touches: str = Form("{}"), x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    if not brief.strip():
        raise HTTPException(400, "Describe the new video in brief.")
    m, t = _json_form(metrics, "metrics"), cv.clean_touches(_json_form(touches, "touches"))
    job = _new_job("plan")
    pool.submit(_work_plan, job, brief[:4000], blueprint[:40000], m, t)
    return {"id": job["id"], "status": "queued", "status_url": f"/api/jobs/{job['id']}"}


def _work_render(job: dict, plan: dict, touches: dict, metrics: dict, logo: Path | None, quality: str):
    job.update(status="running", started=time.time())
    d = Path(job["dir"])
    try:
        project = cv.build_project(plan, touches, metrics, d / "project", logo)
        cv.zip_project(project, d / "project.zip")
        for name in ("plan.json", "script.md", "captions.srt"):
            shutil.copy(project / name, d / name)
        backend = cv.pick_backend()
        job["log"].append(f"built HyperFrames project; render backend: {backend}")
        video = cv.render(project, d / "video.mp4", backend, quality, job=job["id"], log=job["log"].append)
        shutil.rmtree(project, ignore_errors=True)
        job.update(status="done", result={"backend": backend, "video": bool(video),
                                          "timeline": cv.timeline(cv.validate_plan(plan), metrics)})
    except Exception as e:  # noqa: BLE001
        job.update(status="error", error=f"{type(e).__name__}: {e}")
    finally:
        job["finished"] = time.time()


@app.post("/api/renders", status_code=202)
def create_render(plan: str = Form(...), touches: str = Form("{}"), metrics: str = Form("{}"),
                  quality: str = Form("draft"), logo: UploadFile | None = File(None),
                  x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    p = _json_form(plan, "plan")
    try:
        p = cv.validate_plan(p.get("plan", p))
    except ValueError as e:
        raise HTTPException(400, str(e))
    t, m = cv.clean_touches(_json_form(touches, "touches")), _json_form(metrics, "metrics")
    if quality not in QUALITIES:
        raise HTTPException(400, f"quality must be one of {', '.join(sorted(QUALITIES))}")
    job = _new_job("render")
    logo_path = None
    if logo is not None and logo.filename:
        ext = Path(logo.filename).suffix.lower()
        if ext not in LOGO_TYPES:
            shutil.rmtree(job["dir"], ignore_errors=True)
            jobs.pop(job["id"], None)
            raise HTTPException(400, f"Logo must be one of {', '.join(sorted(LOGO_TYPES))}.")
        data = logo.file.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            shutil.rmtree(job["dir"], ignore_errors=True)
            jobs.pop(job["id"], None)
            raise HTTPException(413, "Logo is larger than 5 MB.")
        logo_path = Path(job["dir"]) / f"logo{ext}"
        logo_path.write_bytes(data)
    render_pool.submit(_work_render, job, p, t, m, logo_path, quality)
    return {"id": job["id"], "status": "queued", "status_url": f"/api/jobs/{job['id']}"}
@app.post("/api/projects", status_code=201)
def create_project(name: str = Form(""), x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    if not name.strip():
        raise HTTPException(400, "Send a project name.")
    try:
        return get_store().create_project(name)
    except storage.ProjectExists as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/projects")
def list_projects(x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    return {"projects": get_store().list_projects()}


@app.get("/api/projects/{slug}")
def get_project(slug: str, x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    project = get_store().get_project(slug)
    if project is None:
        raise HTTPException(404, f"No project called '{slug}'.")
    return project


@app.get("/")
def index():
    return FileResponse(DOCS / "index.html", media_type="text/html")


@app.get("/api/quote")
def quote(duration_s: float = 0, transcript_chars: int | None = None, shots: int | None = None,
          storyboard: bool = True):
    """Public price for one run, with every line item and assumption. No token: it sends nothing and stores nothing."""
    if not 0 < duration_s <= MAX_DURATION:
        raise HTTPException(400, f"duration_s must be between 1 and {MAX_DURATION} seconds.")
    return pricing.quote(pricing.estimate(duration_s, transcript_chars, shots, storyboard))


@app.get("/pricing")
def pricing_page():
    return FileResponse(DOCS / "pricing.html", media_type="text/html")


@app.get("/setup")
def setup_guide():
    return FileResponse(DOCS / "setup.html", media_type="text/html")


@app.get("/thumbnail.jpg")
def thumbnail():
    return FileResponse(DOCS / "thumbnail.jpg", media_type="image/jpeg")


@app.exception_handler(HTTPException)
def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(storage.StorageError)
def storage_error(_, exc: storage.StorageError):
    return JSONResponse({"error": str(exc)}, status_code=503)

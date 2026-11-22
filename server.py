"""HTTP server for reverse-any-video (deployable to Fly.io).

  GET  /                          the analyzer page (docs/index.html)
  GET  /healthz, /api/health      health and capability check
  POST /api/jobs                  start an analysis (multipart form, see below)
  GET  /api/jobs/{id}             job status, log and results
  GET  /api/jobs/{id}/files/{f}   report.html, SKILL.md, script.md or analysis.json

POST /api/jobs fields (at least one of url, transcript, transcript_file, video):
  url              video URL (YouTube by default, see ALLOWED_URL_HOSTS)
  title            title to use when the source has none
  download         "true" to download the video and detect cuts with ffmpeg
  transcript       transcript text in any supported format
  transcript_file  transcript upload
  video            video file upload

Environment:
  DATA_DIR           where job folders live (default /tmp/rav-jobs)
  WORKERS            concurrent analyses (default 2)
  MAX_UPLOAD_MB      upload limit (default 300)
  MAX_DURATION       longest video to download, seconds (default 1800)
  JOB_TTL            seconds to keep finished jobs (default 3600)
  ALLOWED_URL_HOSTS  comma-separated hosts, or * for any (default: YouTube hosts)
  ACCESS_TOKEN       if set, /api/jobs requires header X-Access-Token
  YT_COOKIES         contents of a cookies.txt, for when YouTube asks to sign in
"""
from __future__ import annotations

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

import reverse_video as rv

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
OUTPUT_FILES = {"report.html": "text/html", "SKILL.md": "text/markdown", "script.md": "text/markdown",
                "analysis.json": "application/json"}

DATA.mkdir(parents=True, exist_ok=True)
COOKIES: str | None = None
if os.environ.get("YT_COOKIES"):
    _c = DATA / "cookies.txt"
    _c.write_text(os.environ["YT_COOKIES"].replace("\\n", "\n"))
    _c.chmod(0o600)
    COOKIES = str(_c)

app = FastAPI(title="reverse-any-video", docs_url="/api/docs", redoc_url=None)
pool = ThreadPoolExecutor(max_workers=WORKERS)
jobs: dict[str, dict] = {}
lock = threading.Lock()


def capabilities() -> dict:
    return {"service": "reverse-any-video", "ok": True, "ffmpeg": bool(shutil.which("ffmpeg")),
            "yt_dlp": bool(shutil.which("yt-dlp")), "js_runtime": bool(shutil.which("deno") or shutil.which("node")),
            "cookies": COOKIES is not None, "auth_required": ACCESS_TOKEN is not None,
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
          title: str | None):
    job = jobs[job_id]
    job.update(status="running", started=time.time())
    try:
        result = rv.run(source, DATA, transcript, video, download, COOKIES, max_duration=MAX_DURATION,
                        job_id=job_id, log=lambda m: job["log"].append(m), title=title)
        out = Path(result["out_dir"])
        for f in out.iterdir():                      # keep outputs, drop large media
            if f.name not in OUTPUT_FILES:
                f.unlink(missing_ok=True)
        job.update(status="done", result={"analysis": result["analysis"], "frames": result["frames"],
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
               x_access_token: str | None = Header(None)):
    _check_token(x_access_token)
    _cleanup()
    url = url.strip()
    if url:
        _check_url(url)
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
    pool.submit(_work, job_id, url or None, text, video_path, download and bool(url), title.strip() or None)
    return {"id": job_id, "status": "queued", "status_url": f"/api/jobs/{job_id}"}


def _public(job: dict) -> dict:
    out = {k: job[k] for k in ("id", "status", "log", "error", "result")}
    if job["status"] == "done":
        out["files"] = {name: f"/api/jobs/{job['id']}/files/{name}" for name in OUTPUT_FILES}
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


@app.get("/")
def index():
    return FileResponse(DOCS / "index.html", media_type="text/html")


@app.get("/thumbnail.jpg")
def thumbnail():
    return FileResponse(DOCS / "thumbnail.jpg", media_type="image/jpeg")


@app.exception_handler(HTTPException)
def http_error(_, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

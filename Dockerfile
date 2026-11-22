FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY reverse_video.py create_video.py server.py storage.py deepinfra.py reverse_llm.py ./
COPY docs/index.html docs/setup.html docs/thumbnail.jpg ./docs/

RUN useradd --create-home --uid 10001 app && mkdir -p /tmp/rav-jobs && chown app /tmp/rav-jobs
USER app

ENV PORT=8080 DATA_DIR=/tmp/rav-jobs
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz')"
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]

# VIAHIND Vision API + camera workers (one process per site: camera workers run in-process).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# OpenCV runtime libraries and FFmpeg for RTSP/HTTP streams.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CPU PyTorch wheels keep the image smaller; use a CUDA base image for GPU inference.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 viahind && mkdir -p /app/storage && chown -R viahind /app/storage
USER viahind

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=4).status == 200 else 1)"
# Exactly one worker: multiple workers would start duplicate camera pipelines.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]

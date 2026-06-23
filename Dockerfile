# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu

FROM python:${PYTHON_VERSION}-slim-bookworm

ARG TORCH_INDEX

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir "setuptools<82" wheel \
    && pip install --no-cache-dir torch torchaudio --index-url "${TORCH_INDEX}" \
    && pip install --no-cache-dir -r requirements.txt

COPY server/ server/
COPY web/ web/

ENV PORT=8004 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/huggingface \
    TTS_DEVICE=cpu

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=900s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "server/tts_server.py"]

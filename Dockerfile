# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.11

# ── shared app layout ─────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY server/ server/
COPY web/ web/

ENV PORT=8004 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/huggingface

EXPOSE 8004

CMD ["python", "server/tts_server.py"]

# ── CPU (macOS arm64, Linux without GPU) ────────────────────────────────────
FROM base AS cpu

RUN pip install --no-cache-dir "setuptools<82" wheel \
    && pip install --no-cache-dir torch torchvision torchaudio \
       --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall \
       torch torchvision torchaudio \
       --index-url https://download.pytorch.org/whl/cpu

ENV TTS_DEVICE=cpu

# ── CUDA (Linux + NVIDIA, incl. RTX 50-series / sm_120) ─────────────────────
FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime AS cuda

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
COPY server/ server/
COPY web/ web/

# Install matched torch/torchvision/torchaudio from cu128 first and last so pip
# deps (chatterbox, transformers) cannot leave a broken ABI mix in site-packages.
RUN pip install --no-cache-dir "setuptools<82" wheel \
    && pip install --no-cache-dir torch torchvision torchaudio \
       --index-url https://download.pytorch.org/whl/cu128 \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall \
       torch torchvision torchaudio \
       --index-url https://download.pytorch.org/whl/cu128

RUN python -c "\
import torch, torchvision, torchaudio; \
from torchaudio.transforms import Spectrogram; \
from torchvision.transforms import InterpolationMode; \
import perth; \
from chatterbox.tts import ChatterboxTTS; \
print('deps ok', torch.__version__, torchvision.__version__, torchaudio.__version__)\
"

ENV PORT=8004 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/huggingface \
    TTS_DEVICE=cuda

EXPOSE 8004

CMD ["python", "server/tts_server.py"]

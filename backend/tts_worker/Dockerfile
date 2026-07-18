FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ARG COSYVOICE_COMMIT=074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.10 python3-pip git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /srv/CosyVoice \
    && git -C /srv/CosyVoice checkout ${COSYVOICE_COMMIT} \
    && git -C /srv/CosyVoice submodule update --init --recursive

COPY tts_worker/requirements.lock.txt /tmp/worker-requirements.txt
RUN python3.10 -m pip install --no-cache-dir -r /srv/CosyVoice/requirements.txt \
    && python3.10 -m pip install --no-cache-dir -r /tmp/worker-requirements.txt

COPY tts_worker /srv/worker/tts_worker
RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /data/tts \
    && chown -R app:app /srv/worker /data/tts

ENV PYTHONPATH=/srv/worker:/srv/CosyVoice:/srv/CosyVoice/third_party/Matcha-TTS
WORKDIR /srv/worker
USER app
EXPOSE 18081
CMD ["python3.10", "-m", "uvicorn", "tts_worker.server:app", "--host", "0.0.0.0", "--port", "18081"]

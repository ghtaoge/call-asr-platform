FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends python3.11 python3-pip \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml /app/
COPY app /app/app
COPY asr_service /app/asr_service
RUN python3.11 -m pip install --no-cache-dir ".[asr-service]"
RUN useradd --system --uid 10002 --create-home asr \
    && chown -R asr:asr /app
USER asr
EXPOSE 50051
ENTRYPOINT ["python3.11", "-m", "asr_service.server"]

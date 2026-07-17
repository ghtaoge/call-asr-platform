import os
from pathlib import Path
from threading import Lock

import torch
import torchaudio
from cosyvoice.cli.cosyvoice import AutoModel
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel


MODEL_ID = "Fun-CosyVoice3-0.5B-2512"
MODEL = AutoModel(model_dir=os.environ["COSYVOICE_MODEL_DIR"])
TOKEN = os.environ["COSYVOICE_WORKER_TOKEN"]
TTS_ROOT = Path(os.environ["COSYVOICE_TTS_ROOT"]).resolve()
INFERENCE_LOCK = Lock()
app = FastAPI(title="CosyVoice Worker")


class SynthesisRequest(BaseModel):
    text: str
    prompt_text: str
    prompt_path: Path
    output_path: Path


def _safe_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(TTS_ROOT):
        raise HTTPException(status_code=400, detail="invalid TTS path")
    return resolved


def _authorize(token: str | None) -> None:
    if not token or token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid worker token")


@app.get("/health")
def health(x_worker_token: str | None = Header(default=None)):
    _authorize(x_worker_token)
    return {"status": "ok", "model": MODEL_ID}


@app.post("/synthesize")
def synthesize(body: SynthesisRequest, x_worker_token: str | None = Header(default=None)):
    _authorize(x_worker_token)
    prompt_path = _safe_path(body.prompt_path)
    output_path = _safe_path(body.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = f"You are a helpful assistant.<|endofprompt|>{body.prompt_text}"
    with INFERENCE_LOCK:
        chunks = [
            item["tts_speech"]
            for item in MODEL.inference_zero_shot(
                body.text,
                prompt,
                str(prompt_path),
                stream=False,
            )
        ]
        if not chunks:
            raise HTTPException(status_code=500, detail="model returned no audio")
        torchaudio.save(str(output_path), torch.cat(chunks, dim=1).cpu(), MODEL.sample_rate)
    return {"ok": True, "model": MODEL_ID}

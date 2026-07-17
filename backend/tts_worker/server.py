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
SFT_MODEL_DIR = os.environ["COSYVOICE_SFT_MODEL_DIR"]
SFT_MODEL = None
TOKEN = os.environ["COSYVOICE_WORKER_TOKEN"]
TTS_ROOT = Path(os.environ["COSYVOICE_TTS_ROOT"]).resolve()
INFERENCE_LOCK = Lock()
app = FastAPI(title="CosyVoice Worker")


class SynthesisRequest(BaseModel):
    text: str
    prompt_text: str | None = None
    prompt_path: Path | None = None
    preset_speaker: str | None = None
    output_path: Path


def _safe_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(TTS_ROOT):
        raise HTTPException(status_code=400, detail="invalid TTS path")
    return resolved


def _authorize(token: str | None) -> None:
    if not token or token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid worker token")


def _get_sft_model():
    global SFT_MODEL
    if SFT_MODEL is None:
        SFT_MODEL = AutoModel(model_dir=SFT_MODEL_DIR)
    return SFT_MODEL


@app.get("/health")
def health(x_worker_token: str | None = Header(default=None)):
    _authorize(x_worker_token)
    return {
        "status": "ok",
        "model": MODEL_ID,
        "preset_model": "CosyVoice-300M-SFT",
        "preset_model_loaded": SFT_MODEL is not None,
    }


@app.post("/synthesize")
def synthesize(body: SynthesisRequest, x_worker_token: str | None = Header(default=None)):
    _authorize(x_worker_token)
    output_path = _safe_path(body.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with INFERENCE_LOCK:
        if body.preset_speaker:
            model = _get_sft_model()
            if body.preset_speaker not in model.list_available_spks():
                raise HTTPException(status_code=422, detail="preset speaker unavailable")
            results = model.inference_sft(body.text, body.preset_speaker, stream=False)
        else:
            if not body.prompt_path or not body.prompt_text:
                raise HTTPException(status_code=422, detail="reference voice is incomplete")
            prompt_path = _safe_path(body.prompt_path)
            prompt = f"You are a helpful assistant.<|endofprompt|>{body.prompt_text}"
            model = MODEL
            results = model.inference_zero_shot(
                body.text,
                prompt,
                str(prompt_path),
                stream=False,
            )
        chunks = [item["tts_speech"] for item in results]
        if not chunks:
            raise HTTPException(status_code=500, detail="model returned no audio")
        torchaudio.save(str(output_path), torch.cat(chunks, dim=1).cpu(), model.sample_rate)
    return {"ok": True, "model": MODEL_ID}

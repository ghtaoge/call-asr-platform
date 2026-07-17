param(
    [string]$CosyVoiceRoot = "$PSScriptRoot\..\vendor\CosyVoice",
    [string]$ModelDir = "$PSScriptRoot\..\vendor\pretrained_models\Fun-CosyVoice3-0.5B",
    [string]$TtsRoot = "$PSScriptRoot\..\data\tts",
    [string]$EnvName = "call-asr-cosyvoice",
    [int]$Port = 18081
)

$ErrorActionPreference = "Stop"
if (-not $env:COSYVOICE_WORKER_TOKEN) {
    throw "请先设置 COSYVOICE_WORKER_TOKEN，并与后端 CALL_ASR_COSYVOICE_WORKER_TOKEN 保持一致"
}
$env:COSYVOICE_MODEL_DIR = (Resolve-Path $ModelDir).Path
$env:COSYVOICE_TTS_ROOT = [IO.Path]::GetFullPath($TtsRoot)
$env:PYTHONPATH = "$CosyVoiceRoot;$CosyVoiceRoot\third_party\Matcha-TTS"

conda run -n $EnvName python -m uvicorn tts_worker.server:app --app-dir "$PSScriptRoot\.." --host 127.0.0.1 --port $Port

param(
    [string]$CosyVoiceRoot = "$PSScriptRoot\..\vendor\CosyVoice",
    [string]$ModelDir = "$PSScriptRoot\..\vendor\pretrained_models\Fun-CosyVoice3-0.5B",
    [string]$SftModelDir = "$PSScriptRoot\..\vendor\pretrained_models\CosyVoice-300M-SFT",
    [string]$EnvName = "call-asr-cosyvoice"
)

$ErrorActionPreference = "Stop"
$Commit = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
$Model = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
$SftModel = "iic/CosyVoice-300M-SFT"

if (-not (Test-Path $CosyVoiceRoot)) {
    git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git $CosyVoiceRoot
}
git -C $CosyVoiceRoot fetch origin $Commit
git -C $CosyVoiceRoot checkout $Commit
git -C $CosyVoiceRoot submodule update --init --recursive

$environments = conda env list --json | ConvertFrom-Json
if (-not ($environments.envs | Where-Object { $_ -like "*$EnvName" })) {
    conda create -n $EnvName -y python=3.10
}
conda run -n $EnvName python -m pip install -r "$CosyVoiceRoot\requirements.txt"
conda run -n $EnvName python -m pip install fastapi uvicorn
conda run -n $EnvName python -c "from modelscope import snapshot_download; snapshot_download('$Model', local_dir=r'$ModelDir')"
conda run -n $EnvName python -c "from modelscope import snapshot_download; snapshot_download('$SftModel', local_dir=r'$SftModelDir')"

Write-Host "CosyVoice setup complete. Run start_cosyvoice.ps1 to start the worker."

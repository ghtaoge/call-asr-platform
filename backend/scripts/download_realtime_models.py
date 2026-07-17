from modelscope import snapshot_download


MODELS = (
    "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "iic/speech_campplus_sv_zh-cn_16k-common",
)


for model in MODELS:
    print(f"Downloading {model}", flush=True)
    snapshot_download(model)

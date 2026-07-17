from app.asr.model_registry import ModelRegistry


def test_registry_loads_each_model_once():
    calls = []
    registry = ModelRegistry(device="cpu", factory=lambda **kwargs: calls.append(kwargs) or object())
    assert registry.sensevoice() is registry.sensevoice()
    assert registry.emotion() is registry.emotion()
    assert registry.streaming_asr() is registry.streaming_asr()
    assert registry.streaming_vad() is registry.streaming_vad()
    assert registry.speaker_embedding() is registry.speaker_embedding()
    assert len(calls) == 5
    assert calls[0]["model"] == "paraformer-zh"
    assert calls[0]["vad_model"] == "fsmn-vad"
    assert calls[0]["punc_model"] == "ct-punc"
    assert calls[1]["model"] == "iic/emotion2vec_plus_base"
    assert calls[2]["model"] == "paraformer-zh-streaming"
    assert calls[3]["model"] == "fsmn-vad"
    assert calls[4]["model"] == "cam++"

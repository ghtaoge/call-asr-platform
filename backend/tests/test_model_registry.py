from app.asr.model_registry import ModelRegistry


def test_registry_loads_each_model_once():
    calls = []
    registry = ModelRegistry(device="cpu", factory=lambda **kwargs: calls.append(kwargs) or object())
    assert registry.sensevoice() is registry.sensevoice()
    assert registry.emotion() is registry.emotion()
    assert len(calls) == 2

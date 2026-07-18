from pathlib import Path


def test_asr_proto_contains_streaming_sequence_batch_and_health_rpc():
    source = (Path(__file__).parents[3] / "proto" / "asr.proto").read_text(encoding="utf-8")
    assert "rpc StreamRecognize(stream AudioFrame) returns (stream RecognitionEvent)" in source
    assert "uint64 sequence = 5" in source
    assert "rpc BatchRecognize(BatchRequest) returns (BatchResponse)" in source
    assert "rpc Check(HealthRequest) returns (HealthResponse)" in source


def test_generated_bindings_import():
    from app.asr_rpc.generated import asr_pb2, asr_pb2_grpc

    assert asr_pb2.AudioFrame(sequence=7).sequence == 7
    assert hasattr(asr_pb2_grpc, "AsrServiceStub")

import struct
from dataclasses import dataclass


HEADER = struct.Struct(">BBHIQ")
PROTOCOL_VERSION = 1
MAX_PAYLOAD_BYTES = 4096


class FrameProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class AudioFrame:
    session_id: str
    sequence: int
    captured_at_ms: int
    payload: bytes


def decode_audio_frame(session_id: str, raw: bytes) -> AudioFrame:
    if len(raw) < HEADER.size:
        raise FrameProtocolError("音频帧头不完整")
    version, flags, reserved, sequence, captured_at_ms = HEADER.unpack_from(raw)
    payload = raw[HEADER.size:]
    if version != PROTOCOL_VERSION or flags != 0 or reserved != 0:
        raise FrameProtocolError("不支持的实时音频协议")
    if not payload or len(payload) > MAX_PAYLOAD_BYTES or len(payload) % 2:
        raise FrameProtocolError("实时 PCM 载荷无效")
    return AudioFrame(session_id, sequence, captured_at_ms, payload)

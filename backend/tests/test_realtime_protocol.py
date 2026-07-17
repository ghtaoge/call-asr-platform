import struct

import pytest

from app.realtime.protocol import AudioFrame, FrameProtocolError, decode_audio_frame


def test_decodes_v1_pcm_frame():
    payload = b"\x01\x00\x02\x00"
    raw = struct.pack(">BBHIQ", 1, 0, 0, 7, 1784300000000) + payload
    assert decode_audio_frame("s1", raw) == AudioFrame("s1", 7, 1784300000000, payload)


def test_rejects_invalid_version_and_large_payload():
    with pytest.raises(FrameProtocolError):
        decode_audio_frame("s1", struct.pack(">BBHIQ", 2, 0, 0, 1, 0) + b"\x00\x00")
    with pytest.raises(FrameProtocolError):
        decode_audio_frame("s1", struct.pack(">BBHIQ", 1, 0, 0, 1, 0) + b"x" * 4098)

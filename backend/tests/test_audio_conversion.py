import os
import wave
from io import BytesIO

import numpy as np

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.preprocessor import AudioPreprocessor


def _wav_bytes(samples: np.ndarray, sample_rate: int = 16_000) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.astype(np.int16).tobytes())
    return buffer.getvalue()


def _stereo_wav_bytes(left: np.ndarray, right: np.ndarray, sample_rate: int) -> bytes:
    interleaved = np.column_stack((left, right)).astype(np.int16).ravel()
    buffer = BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(interleaved.tobytes())
    return buffer.getvalue()


def _read_wav_samples(audio: bytes) -> np.ndarray:
    with wave.open(BytesIO(audio), "rb") as input_wav:
        return np.frombuffer(
            input_wav.readframes(input_wav.getnframes()), dtype=np.int16
        )


def test_convert_to_wav_preserves_16_bit_pcm_samples():
    sample_rate = 16_000
    time = np.arange(sample_rate) / sample_rate
    source = (8_000 * np.sin(2 * np.pi * 440 * time)).astype(np.int16)
    provider = SenseVoiceProvider.__new__(SenseVoiceProvider)

    wav_path = provider._convert_to_wav(_wav_bytes(source, sample_rate))
    try:
        with wave.open(wav_path, "rb") as converted_wav:
            converted = np.frombuffer(
                converted_wav.readframes(converted_wav.getnframes()), dtype=np.int16
            )
    finally:
        os.unlink(wav_path)

    np.testing.assert_allclose(converted, source, atol=1)


def test_split_channels_preserves_distinct_left_and_right_audio():
    sample_rate = 16_000
    time = np.arange(sample_rate) / sample_rate
    left = (8_000 * np.sin(2 * np.pi * 440 * time)).astype(np.int16)
    right = (6_000 * np.sin(2 * np.pi * 880 * time)).astype(np.int16)

    result = AudioPreprocessor().split_channels(
        _stereo_wav_bytes(left, right, sample_rate)
    )

    assert result.is_stereo is True
    np.testing.assert_allclose(_read_wav_samples(result.left), left, atol=1)
    np.testing.assert_allclose(_read_wav_samples(result.right), right, atol=1)

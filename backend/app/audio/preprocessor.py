import tempfile
import os
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class AudioProcessingResult:
    audio: bytes
    silence_ratio: float
    noise_level: Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ChannelSplitResult:
    """Result of splitting a stereo audio into left and right channels."""
    left: bytes   # Left channel (sales) as WAV bytes
    right: bytes  # Right channel (customer) as WAV bytes
    is_stereo: bool
    original: bytes  # Original audio bytes (used if mono)


class AudioPreprocessor:
    def process(self, audio: bytes) -> AudioProcessingResult:
        if not audio:
            return AudioProcessingResult(audio=b"", silence_ratio=1.0, noise_level="low")
        silence_ratio = 0.1 if len(audio) > 10 else 0.4
        noise_level: Literal["low", "medium", "high"] = "medium" if len(audio) > 0 else "low"
        return AudioProcessingResult(audio=audio, silence_ratio=silence_ratio, noise_level=noise_level)

    def split_channels(self, audio_bytes: bytes) -> ChannelSplitResult:
        """Split stereo audio into left (sales) and right (customer) channels.

        If the audio is mono, returns the original bytes for both channels.
        Uses PyAV (av library) which doesn't require external ffmpeg binary.
        """
        import av
        import numpy as np

        # Write audio bytes to temp file (PyAV needs a file path)
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(audio_bytes)
        tmp.close()

        try:
            container = av.open(tmp.name)
            stream = container.streams.audio[0]
            is_stereo = stream.channels == 2

            if is_stereo:
                # Decode all frames and split channels
                left_samples = []
                right_samples = []
                for frame in container.decode(audio=0):
                    # frame.to_ndarray returns shape (channels, samples)
                    arr = frame.to_ndarray()
                    if arr.shape[0] == 2:
                        left_samples.append(arr[0])
                        right_samples.append(arr[1])
                    else:
                        # If some frames are mono, duplicate
                        left_samples.append(arr[0])
                        right_samples.append(arr[0])

                if not left_samples:
                    return ChannelSplitResult(
                        left=audio_bytes, right=audio_bytes,
                        is_stereo=False, original=audio_bytes
                    )

                left_arr = np.concatenate(left_samples)
                right_arr = np.concatenate(right_samples)

                # Resample to 16kHz if needed (SenseVoice expects 16kHz)
                target_sr = 16000
                if stream.sample_rate != target_sr:
                    # Simple resampling by interpolation
                    left_arr = self._resample(left_arr, stream.sample_rate, target_sr)
                    right_arr = self._resample(right_arr, stream.sample_rate, target_sr)

                # Normalize to int16
                left_wav = self._to_wav_bytes(left_arr.astype(np.float32), target_sr)
                right_wav = self._to_wav_bytes(right_arr.astype(np.float32), target_sr)

                return ChannelSplitResult(
                    left=left_wav, right=right_wav,
                    is_stereo=True, original=audio_bytes
                )
            else:
                # Mono audio — return original for both
                return ChannelSplitResult(
                    left=audio_bytes, right=audio_bytes,
                    is_stereo=False, original=audio_bytes
                )
        except Exception:
            # If PyAV fails (e.g. unsupported format), return as mono
            return ChannelSplitResult(
                left=audio_bytes, right=audio_bytes,
                is_stereo=False, original=audio_bytes
            )
        finally:
            os.unlink(tmp.name)

    def _resample(self, arr: "np.ndarray", orig_sr: int, target_sr: int) -> "np.ndarray":
        """Simple linear interpolation resampling."""
        import numpy as np
        if orig_sr == target_sr:
            return arr
        ratio = target_sr / orig_sr
        n_orig = len(arr)
        n_target = int(n_orig * ratio)
        indices = np.linspace(0, n_orig - 1, n_target)
        return np.interp(indices, np.arange(n_orig), arr)

    def _to_wav_bytes(self, float_arr: "np.ndarray", sample_rate: int) -> bytes:
        """Convert float32 numpy array to WAV file bytes (16-bit PCM)."""
        import struct, numpy as np

        # Convert float32 to int16
        int_arr = np.clip(float_arr * 32767, -32768, 32767).astype(np.int16)
        num_samples = len(int_arr)
        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = num_samples * block_align

        # WAV header
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            'RIFF',
            36 + data_size,
            'WAVE',
            'fmt ',
            16,  # chunk size
            1,   # PCM format
            num_channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            'data',
            data_size,
        )
        return header + int_arr.tobytes()

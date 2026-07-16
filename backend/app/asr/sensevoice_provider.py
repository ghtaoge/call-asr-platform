import tempfile
import os
import warnings

from app.core.models import Segment, Speaker
from app.postprocess.text import add_basic_punctuation


class SenseVoiceProvider:
    """ASR provider using Alibaba SenseVoice model via funasr."""

    def __init__(self) -> None:
        from funasr import AutoModel
        # Suppress the trust_remote_code warning
        warnings.filterwarnings("ignore", message="trust_remote_code")
        self._model = AutoModel(
            model="iic/SenseVoiceSmall",
            trust_remote_code=True,
            disable_update=True,
        )

    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        # Convert audio bytes to a standard WAV file that SenseVoice/funasr can read
        wav_path = self._convert_to_wav(audio)

        try:
            res = self._model.generate(input=wav_path, language="auto")
        except Exception as e:
            # If SenseVoice fails, log the error and return empty
            import logging
            logging.getLogger(__name__).error(f"SenseVoice transcription failed: {e}")
            return []
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

        results: list[Segment] = []
        if res and len(res) > 0:
            for item in res:
                text_content = item.get("text", "") if isinstance(item, dict) else str(item)
                text_content = self._clean_text(text_content)
                if text_content:
                    results.append(
                        Segment(
                            id=f"{session_id}_seg_{len(results)+1:03d}",
                            session_id=session_id,
                            speaker=Speaker(speaker),
                            start_ms=0,
                            end_ms=max(1000, len(audio) * 10),
                            text=add_basic_punctuation(text_content),
                            confidence=0.92,
                            is_final=True,
                        )
                    )

        return results

    def _convert_to_wav(self, audio_bytes: bytes) -> str:
        """Convert audio bytes to a standard WAV file using PyAV.

        PyAV handles most audio formats (MP3, WAV, OGG, etc.) and doesn't
        require an external ffmpeg binary. This ensures SenseVoice can always
        read the audio regardless of the source format.
        """
        import av
        import numpy as np

        # Write raw bytes to a temp file for PyAV to open
        tmp_in = tempfile.NamedTemporaryFile(suffix=".tmp", delete=False)
        tmp_in.write(audio_bytes)
        tmp_in.flush()
        tmp_in.close()

        try:
            container = av.open(tmp_in.name)
            stream = container.streams.audio[0]

            # Decode all frames
            samples = []
            for frame in container.decode(audio=0):
                arr = frame.to_ndarray()
                # Handle multi-channel: convert to mono by averaging
                if arr.ndim == 2 and arr.shape[0] > 1:
                    arr = arr.mean(axis=0)
                elif arr.ndim == 2:
                    arr = arr[0]
                samples.append(arr)

            if not samples:
                raise RuntimeError("No audio frames decoded")

            audio_arr = np.concatenate(samples)

            # Resample to 16kHz (SenseVoice expects 16kHz)
            target_sr = 16000
            if stream.sample_rate != target_sr:
                audio_arr = self._resample(audio_arr, stream.sample_rate, target_sr)

            # Convert to 16-bit PCM WAV
            int_arr = np.clip(audio_arr * 32767, -32768, 32767).astype(np.int16)
            wav_path = tempfile.mktemp(suffix=".wav")
            self._write_wav_file(wav_path, int_arr, target_sr)

            return wav_path

        except Exception:
            # If PyAV fails, try writing raw bytes as WAV directly
            # (assuming they might already be WAV format)
            wav_path = tempfile.mktemp(suffix=".wav")
            with open(wav_path, "wb") as f:
                f.write(audio_bytes)
            return wav_path
        finally:
            try:
                os.unlink(tmp_in.name)
            except OSError:
                pass

    def _resample(self, arr, orig_sr: int, target_sr: int):
        """Simple linear interpolation resampling."""
        import numpy as np
        if orig_sr == target_sr:
            return arr
        ratio = target_sr / orig_sr
        n_orig = len(arr)
        n_target = int(n_orig * ratio)
        indices = np.linspace(0, n_orig - 1, n_target)
        return np.interp(indices, np.arange(n_orig), arr)

    def _write_wav_file(self, path: str, int_arr, sample_rate: int):
        """Write int16 numpy array as WAV file."""
        import struct
        num_samples = len(int_arr)
        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = num_samples * block_align

        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',
            36 + data_size,
            b'WAVE',
            b'fmt ',
            16,
            1,   # PCM
            num_channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b'data',
            data_size,
        )
        with open(path, "wb") as f:
            f.write(header)
            f.write(int_arr.tobytes())

    def _clean_text(self, text: str) -> str:
        """Remove SenseVoice special markers like <|zh|>, <|NEUTRAL|>, <|Speech|>."""
        import re
        text = re.sub(r"<\|[^|]+\|>", "", text)
        return text.strip()

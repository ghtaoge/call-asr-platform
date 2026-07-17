import tempfile
import os
import math
import re
import warnings
import wave
from collections.abc import Callable
from typing import Any

from app.core.models import Segment, Speaker


class SenseVoiceProvider:
    """ASR provider using Alibaba SenseVoice model via funasr."""

    def __init__(
        self,
        model: Any | None = None,
        model_loader: Callable[[], Any] | None = None,
    ) -> None:
        self._model = model
        self._model_loader = model_loader

    def _get_model(self) -> Any:
        if self._model is None and self._model_loader is not None:
            self._model = self._model_loader()
        if self._model is None:
            from funasr import AutoModel

            warnings.filterwarnings("ignore", message="trust_remote_code")
            self._model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                vad_kwargs={"max_single_segment_time": 30_000},
                trust_remote_code=True,
                disable_update=True,
            )
        return self._model

    def transcribe(self, audio: bytes, session_id: str, speaker: Speaker = Speaker.unknown) -> list[Segment]:
        # Convert audio bytes to a standard WAV file that SenseVoice/funasr can read
        wav_path = self._convert_to_wav(audio)

        try:
            return self.transcribe_file(wav_path, session_id, speaker)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def transcribe_file(
        self,
        path: str,
        session_id: str,
        speaker: Speaker = Speaker.unknown,
    ) -> list[Segment]:
        model = self._get_model()
        vad_intervals = self._vad_intervals(model, path)
        result = model.generate(
            input=path,
            language="zh",
            use_itn=True,
            merge_vad=False,
            batch_size_s=60,
        )
        raw_text = " ".join(
            str(item.get("text", "")) for item in result if isinstance(item, dict)
        )
        if raw_text and vad_intervals:
            segments = self._segments_from_vad_text(
                raw_text,
                vad_intervals,
                session_id,
                Speaker(speaker),
            )
            if segments:
                return segments
        return self._parse_result(result, session_id, Speaker(speaker), self._duration_ms(path))

    @staticmethod
    def _vad_intervals(model: Any, path: str) -> list[list[int]]:
        if not hasattr(model, "vad_model") or model.vad_model is None:
            return []
        try:
            result = model.inference(
                path,
                model=model.vad_model,
                kwargs=model.vad_kwargs,
                disable_pbar=True,
            )
        except Exception:
            return []
        if not result or not isinstance(result, list) or not isinstance(result[0], dict):
            return []
        intervals = result[0].get("value", [])
        return [
            [int(interval[0]), int(interval[1])]
            for interval in intervals
            if isinstance(interval, (list, tuple))
            and len(interval) >= 2
            and interval[1] > interval[0]
        ]

    @classmethod
    def _segments_from_vad_text(
        cls,
        raw_text: str,
        intervals: list[list[int]],
        session_id: str,
        speaker: Speaker,
    ) -> list[Segment]:
        marker_block = re.compile(
            r"(?:<\s*\|\s*[^<>]*?\s*\|\s*>\s*){2,}",
            flags=re.IGNORECASE,
        )
        matches = list(marker_block.finditer(raw_text))
        chunks: list[str] = []
        if matches:
            for index, match in enumerate(matches):
                end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
                chunks.append(cls._clean_text(raw_text[match.start():end]))
        else:
            chunks = [cls._clean_text(raw_text)]

        pairs: list[tuple[str, int, int]] = []
        nonempty_chunks = [chunk for chunk in chunks if chunk]
        if len(nonempty_chunks) == len(intervals):
            pairs = [
                (chunk, interval[0], interval[1])
                for chunk, interval in zip(nonempty_chunks, intervals, strict=True)
            ]
        elif nonempty_chunks and intervals:
            pairs = [
                ("".join(nonempty_chunks), intervals[0][0], intervals[-1][1])
            ]

        segments: list[Segment] = []
        for text, start_ms, end_ms in pairs:
            sentences = cls._split_sentences(text)
            weights = [max(1, len(re.sub(r"\W", "", sentence))) for sentence in sentences]
            total_weight = max(1, sum(weights))
            elapsed_weight = 0
            for sentence, weight in zip(sentences, weights, strict=True):
                sentence_start = start_ms + round((end_ms - start_ms) * elapsed_weight / total_weight)
                elapsed_weight += weight
                sentence_end = start_ms + round((end_ms - start_ms) * elapsed_weight / total_weight)
                segments.append(
                    Segment(
                        id=f"{session_id}_{speaker.value}_{len(segments) + 1:04d}",
                        session_id=session_id,
                        speaker=speaker,
                        start_ms=sentence_start,
                        end_ms=max(sentence_start + 1, sentence_end),
                        text=sentence,
                        confidence=0.92,
                        is_final=True,
                    )
                )
        return segments

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        primary = [
            match.group().strip()
            for match in re.finditer(r".+?(?:[。！？!?；;]+|$)", text, flags=re.DOTALL)
            if match.group().strip()
        ]
        sentences: list[str] = []
        for sentence in primary:
            if len(sentence) <= 36:
                sentences.append(sentence)
                continue
            clauses = [
                match.group().strip()
                for match in re.finditer(r".+?(?:[，、]|$)", sentence)
                if match.group().strip()
            ]
            current = ""
            for clause in clauses:
                if current and len(current) + len(clause) > 36:
                    sentences.append(current)
                    current = clause
                else:
                    current += clause
            if current:
                sentences.append(current)
        return sentences or ([text.strip()] if text.strip() else [])

    def _parse_result(
        self,
        result: Any,
        session_id: str,
        speaker: Speaker,
        duration_ms: int,
    ) -> list[Segment]:
        results: list[Segment] = []
        if not result or not isinstance(result, list):
            return results
        fallback_text = ""
        sentence_items: list[dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict):
                fallback_text = fallback_text or str(item)
                continue
            fallback_text = fallback_text or str(item.get("text", ""))
            structured = item.get("sentence_info") or item.get("sentences")
            if isinstance(structured, list):
                sentence_items.extend(entry for entry in structured if isinstance(entry, dict))
            elif "start" in item and "end" in item:
                sentence_items.append(item)
            elif isinstance(item.get("timestamp"), list):
                sentence_items.extend(
                    self._sentences_from_timestamps(str(item.get("text", "")), item["timestamp"])
                )
        for item in sentence_items:
            text_content = self._clean_text(str(item.get("text") or item.get("sentence") or ""))
            start_ms = int(item.get("start", 0))
            end_ms = int(item.get("end", 0))
            if not text_content or start_ms < 0 or end_ms <= start_ms:
                continue
            confidence = float(item.get("confidence", item.get("score", 0.92)))
            results.append(
                Segment(
                    id=f"{session_id}_{speaker.value}_{len(results) + 1:04d}",
                    session_id=session_id,
                    speaker=speaker,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text_content,
                    confidence=max(0.0, min(1.0, confidence)),
                    is_final=True,
                )
            )
        if not results:
            text_content = self._clean_text(fallback_text)
            if text_content:
                results.append(
                    Segment(
                        id=f"{session_id}_{speaker.value}_0001",
                        session_id=session_id,
                        speaker=speaker,
                        start_ms=0,
                        end_ms=max(1000, duration_ms),
                        text=text_content,
                        confidence=0.92,
                        is_final=True,
                    )
                )
        return results

    @classmethod
    def _sentences_from_timestamps(
        cls,
        raw_text: str,
        raw_timestamps: list[Any],
    ) -> list[dict[str, Any]]:
        text = cls._clean_text(raw_text)
        timestamps = [
            (int(value[0]), int(value[1]))
            for value in raw_timestamps
            if isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
            and value[1] > value[0]
        ]
        if not text or not timestamps:
            return []

        punctuation = set("，。！？；：、,.!?;:\"'“”‘’（）()《》")
        spoken_positions = [
            position for position, character in enumerate(text)
            if not character.isspace() and character not in punctuation
        ]
        if not spoken_positions:
            return []

        sentences: list[dict[str, Any]] = []
        for match in re.finditer(r".+?(?:[。！？!?；;]+|$)", text, flags=re.DOTALL):
            sentence = match.group().strip()
            if not sentence:
                continue
            spoken_start = sum(position < match.start() for position in spoken_positions)
            spoken_end = sum(position < match.end() for position in spoken_positions)
            ratio = len(timestamps) / len(spoken_positions)
            start_index = min(len(timestamps) - 1, int(spoken_start * ratio))
            end_index = min(
                len(timestamps) - 1,
                max(start_index, math.ceil(spoken_end * ratio) - 1),
            )
            sentences.append(
                {
                    "text": sentence,
                    "start": timestamps[start_index][0],
                    "end": timestamps[end_index][1],
                }
            )
        return sentences

    @staticmethod
    def _duration_ms(path: str) -> int:
        try:
            with wave.open(path, "rb") as audio:
                return int(audio.getnframes() * 1000 / audio.getframerate())
        except (wave.Error, OSError, ZeroDivisionError):
            return 1000

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
                if np.issubdtype(arr.dtype, np.integer):
                    scale = max(abs(np.iinfo(arr.dtype).min), np.iinfo(arr.dtype).max)
                    arr = arr.astype(np.float32) / scale
                else:
                    arr = arr.astype(np.float32)
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

    @staticmethod
    def _clean_text(text: str) -> str:
        """Remove SenseVoice special markers like <|zh|>, <|NEUTRAL|>, <|Speech|>."""
        text = re.sub(r"<\s*\|\s*[^<>]*?\s*\|\s*>", "", text)
        if re.search(r"[\u4e00-\u9fff]", text):
            text = text.replace(",", "，").replace("?", "？").replace("!", "！").replace(";", "；")
            text = re.sub(r"(?<!\d)\.(?!\d)", "。", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s*([，。！？；：])\s*", r"\1", text)
        text = re.sub(r"([，。！？；])\1+", r"\1", text)
        text = re.sub(r"，[。！？]", lambda match: match.group()[-1], text)
        text = re.sub(r"。[,，]+", "。", text)
        text = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
        return text.strip()

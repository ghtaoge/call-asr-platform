from collections.abc import Callable
from dataclasses import dataclass

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.preprocessor import AudioPreprocessor
from app.compliance.rules import ComplianceRuleEngine
from app.core.models import (
    EmotionResult,
    QualityScore,
    Segment,
    SegmentRiskArtifact,
    Speaker,
)
from app.emotion.acoustic_provider import AcousticEmotionProvider
from app.jobs.models import JobStage
from app.quality.scoring import QualityScorer
from app.sensitive.store import SensitiveStore


ProgressCallback = Callable[[JobStage, int], None]


class AnalysisPipelineError(RuntimeError):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


@dataclass(frozen=True)
class LocalAnalysisResult:
    segments: list[Segment]
    quality: QualityScore


@dataclass(frozen=True)
class TranscriptionResult:
    segments: list[Segment]
    channel_audio: dict[Speaker, bytes]
    silence_ratio: float
    noise_level: str


def merge_channel_segments(sales: list[Segment], customer: list[Segment]) -> list[Segment]:
    return sorted(
        [*sales, *customer],
        key=lambda item: (item.start_ms, item.end_ms, item.speaker.value),
    )


class AnalysisPipeline:
    def __init__(
        self,
        audio: AudioPreprocessor,
        asr: SenseVoiceProvider,
        emotion: AcousticEmotionProvider,
        sensitive_store: SensitiveStore,
        compliance: ComplianceRuleEngine,
        quality: QualityScorer,
        batch_rpc=None,
    ) -> None:
        self.audio = audio
        self.asr = asr
        self.emotion = emotion
        self.sensitive_store = sensitive_store
        self.compliance = compliance
        self.quality = quality
        self.batch_rpc = batch_rpc

    def run(
        self,
        audio_bytes: bytes,
        session_id: str,
        progress: ProgressCallback,
    ) -> LocalAnalysisResult:
        transcription = self.transcribe(audio_bytes, session_id, progress)
        progress(JobStage.analyzing_emotion, 72)
        emotions = self.analyze_emotion(transcription)
        progress(JobStage.scanning_risks, 82)
        risks = self.scan_risks(transcription.segments)
        for segment in transcription.segments:
            segment.emotion = emotions[segment.id]
            risk = risks[segment.id]
            segment.sensitive_hits = risk.sensitive_hits
            segment.compliance_hits = risk.compliance_hits
        quality = self.score_quality(transcription, transcription.segments)
        return LocalAnalysisResult(transcription.segments, quality)

    def transcribe(
        self,
        audio_bytes: bytes,
        session_id: str,
        progress: ProgressCallback,
    ) -> TranscriptionResult:
        progress(JobStage.preparing_audio, 5)
        channels = self.audio.split_required_stereo(audio_bytes)

        if self.batch_rpc is not None:
            remote_segments = self.batch_rpc.batch_recognize(
                "default",
                session_id,
                [(Speaker.sales.value, channels.right), (Speaker.customer.value, channels.left)],
            )
            segments = [
                Segment(
                    id=f"{session_id}_{item.speaker}_{index:04d}",
                    session_id=session_id,
                    speaker=Speaker(item.speaker),
                    start_ms=item.start_ms,
                    end_ms=max(item.start_ms + 1, item.end_ms),
                    text=item.text,
                    confidence=item.confidence,
                    language="zh",
                    target_language="zh",
                )
                for index, item in enumerate(remote_segments, start=1)
            ]
            return TranscriptionResult(
                segments=sorted(segments, key=lambda item: (item.start_ms, item.end_ms)),
                channel_audio={Speaker.sales: channels.right, Speaker.customer: channels.left},
                silence_ratio=0.0,
                noise_level="low",
            )

        # Gooeto 录音的固定协议是：第一（左）声道为客户，第二（右）声道为销售。
        # 角色必须在转写前绑定，后续摘要、敏感词和质检都会沿用此 speaker 值。
        progress(JobStage.transcribing_sales, 15)
        try:
            sales = self.asr.transcribe(channels.right, session_id, Speaker.sales)
        except Exception as exc:
            raise AnalysisPipelineError("asr_failed", "销售声道识别失败") from exc
        progress(JobStage.transcribing_customer, 40)
        try:
            customer = self.asr.transcribe(channels.left, session_id, Speaker.customer)
        except Exception as exc:
            raise AnalysisPipelineError("asr_failed", "客户声道识别失败") from exc

        progress(JobStage.merging_segments, 65)
        segments = merge_channel_segments(sales, customer)
        if not segments:
            raise AnalysisPipelineError("asr_failed", "录音中未识别到有效语音")
        processed = self.audio.process(audio_bytes)
        return TranscriptionResult(
            segments=segments,
            channel_audio={Speaker.sales: channels.right, Speaker.customer: channels.left},
            silence_ratio=processed.silence_ratio,
            noise_level=processed.noise_level,
        )

    def restore_transcription(
        self,
        audio_bytes: bytes,
        segments: list[Segment],
    ) -> TranscriptionResult:
        channels = self.audio.split_required_stereo(audio_bytes)
        processed = self.audio.process(audio_bytes)
        return TranscriptionResult(
            segments=segments,
            channel_audio={Speaker.sales: channels.right, Speaker.customer: channels.left},
            silence_ratio=processed.silence_ratio,
            noise_level=processed.noise_level,
        )

    def transcription_from_mono(
        self,
        audio_bytes: bytes,
        segments: list[Segment],
    ) -> TranscriptionResult:
        processed = self.audio.process(audio_bytes)
        return TranscriptionResult(
            segments=segments,
            channel_audio={
                Speaker.sales: audio_bytes,
                Speaker.customer: audio_bytes,
                Speaker.unknown: audio_bytes,
            },
            silence_ratio=processed.silence_ratio,
            noise_level=processed.noise_level,
        )

    def analyze_emotion(
        self,
        transcription: TranscriptionResult,
    ) -> dict[str, EmotionResult]:
        # 时间戳只对应原始声道，情绪切片不能使用双声道混音。
        try:
            emotion_results = self.emotion.analyze_many([
                (
                    transcription.channel_audio[segment.speaker],
                    segment.start_ms,
                    segment.end_ms,
                )
                for segment in transcription.segments
            ])
            if len(emotion_results) != len(transcription.segments):
                raise RuntimeError("emotion result count does not match segments")
            return {
                segment.id: emotion
                for segment, emotion in zip(
                    transcription.segments,
                    emotion_results,
                    strict=True,
                )
            }
        except Exception as exc:
            raise AnalysisPipelineError("emotion_failed", "通话情绪分析失败") from exc

    def scan_risks(
        self,
        segments: list[Segment],
    ) -> dict[str, SegmentRiskArtifact]:
        results: dict[str, SegmentRiskArtifact] = {}
        for segment in segments:
            segment.translation = ""
            segment.target_language = "zh"
            results[segment.id] = SegmentRiskArtifact(
                sensitive_hits=self.sensitive_store.scan(
                    segment.text,
                    segment.speaker,
                    segment.id,
                    segment.start_ms,
                    segment.end_ms,
                ),
                compliance_hits=self.compliance.check(segment),
            )
        return results

    def score_quality(
        self,
        transcription: TranscriptionResult,
        enriched_segments: list[Segment],
    ) -> QualityScore:
        return self.quality.score(
            enriched_segments,
            transcription.silence_ratio,
            transcription.noise_level,
        )

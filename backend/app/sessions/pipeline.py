from collections.abc import Callable
from dataclasses import dataclass

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.preprocessor import AudioPreprocessor
from app.compliance.rules import ComplianceRuleEngine
from app.core.models import QualityScore, Segment, Speaker
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
    ) -> None:
        self.audio = audio
        self.asr = asr
        self.emotion = emotion
        self.sensitive_store = sensitive_store
        self.compliance = compliance
        self.quality = quality

    def run(
        self,
        audio_bytes: bytes,
        session_id: str,
        progress: ProgressCallback,
    ) -> LocalAnalysisResult:
        progress(JobStage.preparing_audio, 5)
        channels = self.audio.split_required_stereo(audio_bytes)

        progress(JobStage.transcribing_sales, 15)
        try:
            sales = self.asr.transcribe(channels.left, session_id, Speaker.sales)
        except Exception as exc:
            raise AnalysisPipelineError("asr_failed", "销售声道识别失败") from exc
        progress(JobStage.transcribing_customer, 40)
        try:
            customer = self.asr.transcribe(channels.right, session_id, Speaker.customer)
        except Exception as exc:
            raise AnalysisPipelineError("asr_failed", "客户声道识别失败") from exc

        progress(JobStage.merging_segments, 65)
        segments = merge_channel_segments(sales, customer)
        if not segments:
            raise AnalysisPipelineError("asr_failed", "录音中未识别到有效语音")
        channel_audio = {Speaker.sales: channels.left, Speaker.customer: channels.right}

        progress(JobStage.analyzing_emotion, 72)
        try:
            for segment in segments:
                segment.emotion = self.emotion.analyze(
                    channel_audio[segment.speaker],
                    segment.start_ms,
                    segment.end_ms,
                )
        except Exception as exc:
            raise AnalysisPipelineError("emotion_failed", "通话情绪分析失败") from exc

        progress(JobStage.scanning_risks, 82)
        for segment in segments:
            segment.translation = ""
            segment.target_language = "zh"
            segment.sensitive_hits = self.sensitive_store.scan(
                segment.text,
                segment.speaker,
                segment.id,
                segment.start_ms,
                segment.end_ms,
            )
            segment.compliance_hits = self.compliance.check(segment)

        processed = self.audio.process(audio_bytes)
        quality = self.quality.score(segments, processed.silence_ratio, processed.noise_level)
        return LocalAnalysisResult(segments=segments, quality=quality)

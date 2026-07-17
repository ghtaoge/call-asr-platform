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
        # 每个句子的时间戳只对其原始声道有效。情绪切片必须回到对应声道，
        # 不能在双声道混音上按同一时间切片，否则另一方声音会污染判断。
        channel_audio = {Speaker.sales: channels.right, Speaker.customer: channels.left}

        progress(JobStage.analyzing_emotion, 72)
        try:
            # 按 ASR 句段逐段识别，前端才能绘制随通话时间变化的情绪曲线，
            # 而不是每个角色整段录音只有一个情绪结果。
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

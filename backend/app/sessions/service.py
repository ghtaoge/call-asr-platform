from uuid import uuid4

from app.asr.sensevoice_provider import SenseVoiceProvider
from app.audio.preprocessor import AudioPreprocessor
from app.compliance.rules import ComplianceRuleEngine
from app.core.models import CallSummary, QualityScore, Segment, Speaker
from app.emotion.provider import RuleEmotionProvider
from app.quality.scoring import QualityScorer
from app.sensitive.store import SensitiveStore
from app.sessions.repository import SessionRepository
from app.summary.generator import SummaryGenerator
from app.translation.provider import LocalTranslationProvider


class SessionService:
    def __init__(self, repository: SessionRepository, sensitive_store: SensitiveStore) -> None:
        self._repository = repository
        self._sensitive_store = sensitive_store
        self._audio = AudioPreprocessor()
        self._asr = SenseVoiceProvider()
        self._emotion = RuleEmotionProvider()
        self._translation = LocalTranslationProvider()
        self._compliance = ComplianceRuleEngine()
        self._quality = QualityScorer()
        self._summary = SummaryGenerator()

    async def analyze_offline(
        self,
        audio: bytes,
        target_language: str = "en",
        speaker: Speaker = Speaker.unknown,
        session_id: str | None = None,
        mode: str = "offline",
    ) -> tuple[str, list[Segment], QualityScore, CallSummary]:
        session_id = session_id or f"call_{uuid4().hex[:12]}"
        await self._repository.init()
        await self._repository.create_session(session_id, mode=mode)

        # Split stereo audio into left (sales) and right (customer) channels
        channels = self._audio.split_channels(audio)

        all_segments: list[Segment] = []

        if channels.is_stereo:
            # Dual-channel: transcribe left as sales, right as customer
            left_segments = self._asr.transcribe(channels.left, session_id=session_id, speaker=Speaker.sales)
            right_segments = self._asr.transcribe(channels.right, session_id=session_id, speaker=Speaker.customer)
            all_segments = left_segments + right_segments
        else:
            # Mono: transcribe with the provided speaker
            processed = self._audio.process(audio)
            all_segments = self._asr.transcribe(processed.audio, session_id=session_id, speaker=speaker)

        enriched = self.enrich_segments(all_segments, target_language)
        quality = self._quality.score(enriched, 0.1, "medium")
        summary = self._summary.generate(enriched)
        await self._repository.save_segments(session_id, enriched)
        await self._repository.save_quality(session_id, quality)
        await self._repository.save_summary(session_id, summary)
        await self._repository.set_status(session_id, "completed")
        return session_id, enriched, quality, summary

    def enrich_segments(self, segments: list[Segment], target_language: str) -> list[Segment]:
        enriched: list[Segment] = []
        for segment in segments:
            segment.translation = self._translation.translate(segment.text, target_language=target_language)
            segment.target_language = target_language
            segment.emotion = self._emotion.analyze(segment.text)
            segment.sensitive_hits = self._sensitive_store.scan(
                segment.text,
                segment.speaker,
                segment.id,
                segment.start_ms,
                segment.end_ms,
            )
            segment.compliance_hits = self._compliance.check(segment)
            enriched.append(segment)
        return enriched

    def summarize(self, segments: list[Segment]) -> CallSummary:
        return self._summary.generate(segments)

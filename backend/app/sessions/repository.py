import json
from pathlib import Path

import aiosqlite

from app.core.models import (
    CallSummary,
    EmotionResult,
    QualityScore,
    Segment,
    SegmentRiskArtifact,
)


class SessionRepository:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)

    async def init(self) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS segments (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS artifacts (
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, kind)
                )
                """
            )
            await db.commit()

    async def create_session(self, session_id: str, mode: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO sessions (id, mode, status) VALUES (?, ?, ?)",
                (session_id, mode, "created"),
            )
            await db.commit()

    async def set_status(self, session_id: str, status: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute("UPDATE sessions SET status = ? WHERE id = ?", (status, session_id))
            await db.commit()

    async def save_segments(self, session_id: str, segments: list[Segment]) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            for segment in segments:
                await db.execute(
                    "INSERT OR REPLACE INTO segments (id, session_id, payload) VALUES (?, ?, ?)",
                    (segment.id, session_id, segment.model_dump_json()),
                )
            await db.commit()

    async def list_segments(self, session_id: str) -> list[Segment]:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute("SELECT payload FROM segments WHERE session_id = ?", (session_id,))
            rows = await cursor.fetchall()
        segments = [Segment.model_validate_json(row[0]) for row in rows]
        return sorted(segments, key=lambda item: (item.start_ms, item.end_ms, item.speaker.value))

    async def save_emotions(
        self,
        session_id: str,
        values: dict[str, EmotionResult],
    ) -> None:
        payload = {key: value.model_dump(mode="json") for key, value in values.items()}
        await self._save_artifact(
            session_id,
            "emotions",
            json.dumps(payload, ensure_ascii=False),
        )

    async def get_emotions(self, session_id: str) -> dict[str, EmotionResult]:
        payload = await self._get_artifact(session_id, "emotions")
        if not payload:
            return {}
        return {
            key: EmotionResult.model_validate(value)
            for key, value in json.loads(payload).items()
        }

    async def save_risks(
        self,
        session_id: str,
        values: dict[str, SegmentRiskArtifact],
    ) -> None:
        payload = {key: value.model_dump(mode="json") for key, value in values.items()}
        await self._save_artifact(
            session_id,
            "risks",
            json.dumps(payload, ensure_ascii=False),
        )

    async def get_risks(self, session_id: str) -> dict[str, SegmentRiskArtifact]:
        payload = await self._get_artifact(session_id, "risks")
        if not payload:
            return {}
        return {
            key: SegmentRiskArtifact.model_validate(value)
            for key, value in json.loads(payload).items()
        }

    async def list_enriched_segments(self, session_id: str) -> list[Segment]:
        segments = await self.list_segments(session_id)
        emotions = await self.get_emotions(session_id)
        risks = await self.get_risks(session_id)
        for segment in segments:
            if emotion := emotions.get(segment.id):
                segment.emotion = emotion
            if risk := risks.get(segment.id):
                segment.sensitive_hits = risk.sensitive_hits
                segment.compliance_hits = risk.compliance_hits
        return segments

    async def save_quality(self, session_id: str, quality: QualityScore) -> None:
        await self._save_artifact(session_id, "quality", quality.model_dump_json())

    async def save_summary(self, session_id: str, summary: CallSummary) -> None:
        await self._save_artifact(session_id, "summary", summary.model_dump_json())

    async def get_quality(self, session_id: str) -> QualityScore | None:
        payload = await self._get_artifact(session_id, "quality")
        return QualityScore.model_validate_json(payload) if payload else None

    async def get_summary(self, session_id: str) -> CallSummary | None:
        payload = await self._get_artifact(session_id, "summary")
        return CallSummary.model_validate_json(payload) if payload else None

    async def _save_artifact(self, session_id: str, kind: str, payload: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO artifacts (session_id, kind, payload) VALUES (?, ?, ?)",
                (session_id, kind, payload),
            )
            await db.commit()

    async def _get_artifact(self, session_id: str, kind: str) -> str | None:
        async with aiosqlite.connect(self._database_path) as db:
            cursor = await db.execute(
                "SELECT payload FROM artifacts WHERE session_id = ? AND kind = ?",
                (session_id, kind),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

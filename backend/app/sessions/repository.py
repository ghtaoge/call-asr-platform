from pathlib import Path

import aiosqlite

from app.core.models import CallSummary, QualityScore, Segment


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
            cursor = await db.execute("SELECT payload FROM segments WHERE session_id = ? ORDER BY id", (session_id,))
            rows = await cursor.fetchall()
        return [Segment.model_validate_json(row[0]) for row in rows]

    async def save_quality(self, session_id: str, quality: QualityScore) -> None:
        await self._save_artifact(session_id, "quality", quality.model_dump_json())

    async def save_summary(self, session_id: str, summary: CallSummary) -> None:
        await self._save_artifact(session_id, "summary", summary.model_dump_json())

    async def _save_artifact(self, session_id: str, kind: str, payload: str) -> None:
        async with aiosqlite.connect(self._database_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO artifacts (session_id, kind, payload) VALUES (?, ?, ?)",
                (session_id, kind, payload),
            )
            await db.commit()

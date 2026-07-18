from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import uuid

import aiosqlite

from app.core.models import RiskLevel
from app.sensitive.normalizer import normalize_word


@dataclass(frozen=True, slots=True)
class SensitiveWordRow:
    id: str
    tenant_id: str
    word: str
    normalized_word: str
    level: RiskLevel
    category: str
    enabled: bool
    version: int
    updated_at: datetime


class SensitiveWordRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    async def init(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS sensitive_tenant_versions (
                    tenant_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sensitive_words (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    word TEXT NOT NULL,
                    normalized_word TEXT NOT NULL,
                    level TEXT NOT NULL,
                    category TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, normalized_word)
                );
                CREATE INDEX IF NOT EXISTS idx_sensitive_words_tenant_updated
                    ON sensitive_words(tenant_id, updated_at DESC, id DESC);
            """)
            await db.commit()

    async def list_words(self, tenant_id: str, *, limit: int = 50, cursor: str | None = None,
                         query: str | None = None, level: RiskLevel | None = None,
                         category: str | None = None, enabled: bool | None = None) -> tuple[list[SensitiveWordRow], str | None, int]:
        limit = max(1, min(limit, 200))
        conditions = ["tenant_id = ?"]
        params: list[object] = [tenant_id]
        if cursor:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            conditions.append("(updated_at < ? OR (updated_at = ? AND id < ?))")
            params.extend([decoded[0], decoded[0], decoded[1]])
        if query:
            conditions.append("normalized_word LIKE ?")
            params.append(f"%{normalize_word(query)}%")
        if level:
            conditions.append("level = ?")
            params.append(level.value)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if enabled is not None:
            conditions.append("enabled = ?")
            params.append(int(enabled))
        sql = "SELECT * FROM sensitive_words WHERE " + " AND ".join(conditions) + " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(limit + 1)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute(sql, params)).fetchall()
            version = int((await (await db.execute(
                "SELECT version FROM sensitive_tenant_versions WHERE tenant_id = ?", (tenant_id,)
            )).fetchone() or {"version": 0})["version"])
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if more and rows:
            last = rows[-1]
            next_cursor = base64.urlsafe_b64encode(json.dumps([last["updated_at"], last["id"]]).encode()).decode()
        return [self._row(row) for row in rows], next_cursor, version

    async def create(self, tenant_id: str, word: str, level: RiskLevel, category: str, enabled: bool) -> SensitiveWordRow:
        normalized = normalize_word(word)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            try:
                await db.execute("INSERT OR IGNORE INTO sensitive_tenant_versions(tenant_id,version) VALUES (?,0)", (tenant_id,))
                await db.execute("UPDATE sensitive_tenant_versions SET version = version + 1 WHERE tenant_id = ?", (tenant_id,))
                version = int((await (await db.execute("SELECT version FROM sensitive_tenant_versions WHERE tenant_id = ?", (tenant_id,))).fetchone())[0])
                identifier = str(uuid.uuid4())
                await db.execute("INSERT INTO sensitive_words VALUES (?,?,?,?,?,?,?,?,?)",
                                 (identifier, tenant_id, word, normalized, level.value, category, int(enabled), version, now))
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ValueError("敏感词已存在") from exc
        return SensitiveWordRow(identifier, tenant_id, word, normalized, level, category, enabled, version, datetime.fromisoformat(now))

    async def update(self, tenant_id: str, identifier: str, values: dict) -> SensitiveWordRow:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute("SELECT * FROM sensitive_words WHERE tenant_id = ? AND id = ?", (tenant_id, identifier))).fetchone()
            if not row:
                raise KeyError(identifier)
            word = values.get("word", row["word"])
            normalized = normalize_word(word)
            await db.execute("UPDATE sensitive_tenant_versions SET version = version + 1 WHERE tenant_id = ?", (tenant_id,))
            version = int((await (await db.execute("SELECT version FROM sensitive_tenant_versions WHERE tenant_id = ?", (tenant_id,))).fetchone())[0])
            now = datetime.now(timezone.utc).isoformat()
            await db.execute("UPDATE sensitive_words SET word=?,normalized_word=?,level=?,category=?,enabled=?,version=?,updated_at=? WHERE tenant_id=? AND id=?",
                             (word, (values.get("level") or row["level"]).value if isinstance(values.get("level"), RiskLevel) else values.get("level", row["level"]), values.get("category", row["category"]), int(values.get("enabled", bool(row["enabled"]))), version, now, tenant_id, identifier))
            await db.commit()
            updated = await (await db.execute("SELECT * FROM sensitive_words WHERE tenant_id = ? AND id = ?", (tenant_id, identifier))).fetchone()
        return self._row(updated)

    async def delete(self, tenant_id: str, identifier: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("DELETE FROM sensitive_words WHERE tenant_id = ? AND id = ?", (tenant_id, identifier))
            await db.execute("UPDATE sensitive_tenant_versions SET version = version + 1 WHERE tenant_id = ?", (tenant_id,))
            await db.commit()

    async def entries(self, tenant_id: str):
        async with aiosqlite.connect(self.database_path) as db:
            rows = await (await db.execute("SELECT word, level, category, enabled FROM sensitive_words WHERE tenant_id = ?", (tenant_id,))).fetchall()
            version_row = await (await db.execute("SELECT version FROM sensitive_tenant_versions WHERE tenant_id = ?", (tenant_id,))).fetchone()
        return rows, int(version_row[0]) if version_row else 0

    @staticmethod
    def _row(row) -> SensitiveWordRow:
        return SensitiveWordRow(row["id"], row["tenant_id"], row["word"], row["normalized_word"], RiskLevel(row["level"]), row["category"], bool(row["enabled"]), int(row["version"]), datetime.fromisoformat(row["updated_at"]))

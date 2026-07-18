from __future__ import annotations

from datetime import datetime, timezone
import uuid

import aiosqlite


class PbxCallRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    async def init(self):
        async with aiosqlite.connect(self.database_path) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS realtime_calls (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source TEXT NOT NULL,
              source_session_id TEXT NOT NULL, status TEXT NOT NULL,
              started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              customer_number TEXT NOT NULL DEFAULT '', sales_number TEXT NOT NULL DEFAULT '',
              role_pending INTEGER NOT NULL DEFAULT 0, media_interrupted INTEGER NOT NULL DEFAULT 0,
              asr_degraded INTEGER NOT NULL DEFAULT 0,
              UNIQUE(tenant_id, source, source_session_id)
            );
            CREATE TABLE IF NOT EXISTS realtime_events (
              call_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_type TEXT NOT NULL,
              payload TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(call_id, sequence)
            );
            """)
            await db.commit()

    async def start(self, tenant_id: str, payload):
        now = datetime.now(timezone.utc).isoformat()
        identifier = str(uuid.uuid4())
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("INSERT OR IGNORE INTO realtime_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (identifier, tenant_id, "siprec", payload.source_session_id, "active", now, now, payload.customer_number, payload.sales_number, int(payload.role_pending), 0, 0))
            row = await (await db.execute("SELECT * FROM realtime_calls WHERE tenant_id=? AND source='siprec' AND source_session_id=?", (tenant_id, payload.source_session_id))).fetchone()
            await db.commit()
        return row

    async def update(self, tenant_id: str, source_session_id: str, payload):
        now = datetime.now(timezone.utc).isoformat()
        fields = ["status=?", "updated_at=?"]; values = [payload.status, now]
        for field in ("role_pending", "media_interrupted", "asr_degraded"):
            value = getattr(payload, field, None)
            if value is not None: fields.append(f"{field}=?"); values.append(int(value))
        values.extend([tenant_id, source_session_id])
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(f"UPDATE realtime_calls SET {','.join(fields)} WHERE tenant_id=? AND source_session_id=?", values)
            await db.commit()
            return await (await db.execute("SELECT * FROM realtime_calls WHERE tenant_id=? AND source_session_id=?", (tenant_id, source_session_id))).fetchone()

    async def list(self, tenant_id: str, limit: int = 50):
        async with aiosqlite.connect(self.database_path) as db:
            return await (await db.execute("SELECT * FROM realtime_calls WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ?", (tenant_id, min(200, max(1, limit))))).fetchall()

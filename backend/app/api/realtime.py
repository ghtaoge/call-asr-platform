import base64

from fastapi import APIRouter, WebSocket

from app.core.config import get_settings
from app.core.models import Speaker
from app.sensitive.store import SensitiveStore
from app.sessions.repository import SessionRepository
from app.sessions.service import SessionService

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/realtime/{session_id}")
async def realtime_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    settings = get_settings()
    sensitive_store = SensitiveStore(settings.sensitive_words_path)
    sensitive_store.reload()
    repository = SessionRepository(settings.database_path)
    service = SessionService(repository, sensitive_store)
    await repository.init()
    await repository.create_session(session_id, "realtime")

    target_language = settings.target_language
    segments = []
    while True:
        message = await websocket.receive_json()
        event_type = message.get("type")
        if event_type == "start_session":
            target_language = message.get("target_language", target_language)
            await websocket.send_json({"type": "session_started", "session_id": session_id})
        elif event_type == "audio_chunk":
            speaker = Speaker(message.get("speaker", "unknown"))
            audio = base64.b64decode(message.get("audio", ""))
            _, chunk_segments, quality, _ = await service.analyze_offline(
                audio,
                target_language=target_language,
                speaker=speaker,
                session_id=session_id,
                mode="realtime",
            )
            for segment in chunk_segments:
                segment.session_id = session_id
                segment.speaker = speaker
                segment.id = f"{session_id}_seg_{len(segments) + 1:03d}"
                segments.append(segment)
                await websocket.send_json({"type": "final_segment", "segment": segment.model_dump(mode="json")})
                for hit in segment.sensitive_hits:
                    if hit.level in {"high", "critical"}:
                        await websocket.send_json({"type": "risk_alert", "hit": hit.model_dump(mode="json")})
            await websocket.send_json({"type": "quality_update", "quality": quality.model_dump(mode="json")})
        elif event_type == "end_session":
            await repository.save_segments(session_id, segments)
            final_summary = service.summarize(segments)
            await websocket.send_json({"type": "summary_ready", "summary": final_summary.model_dump(mode="json")})
            break
        else:
            await websocket.send_json({"type": "error", "message": f"unsupported event type: {event_type}"})

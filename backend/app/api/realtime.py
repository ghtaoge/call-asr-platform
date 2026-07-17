import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.manager import RealtimeManager


router = APIRouter(tags=["realtime"])


@router.websocket("/ws/realtime/{session_id}")
async def realtime_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    manager: RealtimeManager | None = getattr(websocket.app.state, "realtime_manager", None)
    if manager is None:
        await websocket.send_json({
            "type": "error",
            "code": "service_unavailable",
            "message": "实时识别服务尚未就绪",
        })
        await websocket.close(code=1013)
        return
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                events = await manager.accept(session_id, message["bytes"])
            elif message.get("text") is not None:
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError:
                    events = [{
                        "type": "error",
                        "code": "invalid_json",
                        "message": "实时控制消息格式错误",
                    }]
                else:
                    events = await manager.control(session_id, control)
            else:
                continue
            for event in events:
                await websocket.send_json(event)
            if any(event.get("type") == "session_ended" for event in events):
                await websocket.close(code=1000)
                return
    except WebSocketDisconnect:
        return

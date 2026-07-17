import struct

from fastapi.testclient import TestClient

from app.main import create_app


class FakeRealtimeManager:
    async def control(self, session_id, message):
        if message["type"] == "start_session":
            return [{"type": "session_started", "session_id": session_id, "sequence": -1}]
        if message["type"] == "end_session":
            return [{"type": "session_ended", "session_id": session_id, "job_id": "job_1"}]
        return [{"type": "session_resumed", "sequence": 0}]

    async def accept(self, session_id, raw):
        sequence = struct.unpack_from(">I", raw, 4)[0]
        return [{"type": "audio_ack", "sequence": sequence}]


def test_realtime_websocket_accepts_control_and_binary_frames():
    app = create_app()
    app.state.realtime_manager = FakeRealtimeManager()
    client = TestClient(app)
    frame = struct.pack(">BBHIQ", 1, 0, 0, 0, 1000) + b"\x00\x00" * 320

    with client.websocket_connect("/ws/realtime/s1") as websocket:
        websocket.send_json({
            "type": "start_session",
            "codec": "pcm_s16le",
            "sample_rate": 16000,
            "channels": 1,
        })
        assert websocket.receive_json()["type"] == "session_started"
        websocket.send_bytes(frame)
        assert websocket.receive_json() == {"type": "audio_ack", "sequence": 0}
        websocket.send_json({"type": "end_session"})
        ended = websocket.receive_json()
        assert ended["job_id"] == "job_1"

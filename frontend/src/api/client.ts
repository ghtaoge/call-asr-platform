import type { CallSummary, QualityScore, Segment, Speaker } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

export interface OfflineResult {
  session_id: string;
  segments: Segment[];
  quality: QualityScore;
  summary: CallSummary;
}

export async function uploadOffline(file: File): Promise<OfflineResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/sessions/offline`, {
    method: "POST",
    body: form
  });
  if (!response.ok) {
    throw new Error(`上传失败：${response.status}`);
  }
  return response.json();
}

export function openRealtimeSession(
  sessionId: string,
  speaker: Speaker,
  onEvent: (event: any) => void
) {
  const ws = new WebSocket(`${WS_BASE}/ws/realtime/${sessionId}`);
  ws.addEventListener("open", () => {
    ws.send(JSON.stringify({ type: "start_session", speaker, target_language: "en" }));
  });
  ws.addEventListener("message", (message) => onEvent(JSON.parse(message.data)));
  return ws;
}

import { useRef, useState } from "react";
import { openRealtimeSession, uploadOffline } from "./api/client";
import { RiskPanel } from "./components/RiskPanel";
import { Toolbar } from "./components/Toolbar";
import { TranscriptPanel } from "./components/TranscriptPanel";
import type { CallSummary, QualityScore, Segment, Speaker } from "./types";

export function App() {
  const [speaker, setSpeaker] = useState<Speaker>("sales");
  const [status, setStatus] = useState("准备就绪");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [quality, setQuality] = useState<QualityScore>();
  const [summary, setSummary] = useState<CallSummary>();
  const wsRef = useRef<WebSocket | null>(null);

  async function handleUpload(file: File) {
    setStatus("正在分析离线录音...");
    try {
      const result = await uploadOffline(file);
      setSegments(result.segments);
      setQuality(result.quality);
      setSummary(result.summary);
      setStatus(`分析完成：${result.session_id}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "上传失败");
    }
  }

  function handleRealtime() {
    const sessionId = `web_${Date.now()}`;
    wsRef.current?.close();
    wsRef.current = openRealtimeSession(sessionId, speaker, (event) => {
      if (event.type === "session_started") {
        setStatus(`实时会话已连接：${sessionId}`);
      }
      if (event.type === "final_segment") {
        setSegments((current) => [...current, event.segment]);
      }
      if (event.type === "quality_update") {
        setQuality(event.quality);
      }
      if (event.type === "summary_ready") {
        setSummary(event.summary);
      }
    });
    setStatus(`正在连接实时会话：当前角色 ${speaker}`);
  }

  return (
    <main className="workbench">
      <Toolbar
        status={status}
        speaker={speaker}
        onSpeakerChange={setSpeaker}
        onUpload={handleUpload}
        onRealtime={handleRealtime}
      />
      <section className="layout">
        <TranscriptPanel segments={segments} />
        <RiskPanel segments={segments} quality={quality} summary={summary} />
      </section>
    </main>
  );
}

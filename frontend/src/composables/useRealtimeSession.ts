import { computed, onBeforeUnmount, ref } from "vue";
import { API_BASE } from "../api/client";
import { encodeAudioFrame } from "../realtime/frame";
import type { Segment, Speaker } from "../types";

type RealtimeStatus = "idle" | "connecting" | "recording" | "paused" | "ending" | "ended" | "error";

export function useRealtimeSession() {
  const status = ref<RealtimeStatus>("idle");
  const segments = ref<Segment[]>([]);
  const partialText = ref("");
  const error = ref("");
  const elapsedSeconds = ref(0);
  const inputLevel = ref(0);
  const jobId = ref("");
  const sessionId = ref("");
  let socket: WebSocket | undefined;
  let stream: MediaStream | undefined;
  let audioContext: AudioContext | undefined;
  let worklet: AudioWorkletNode | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;
  let sequence = 0;
  let lastAck = -1;
  let intentionalClose = false;
  let reconnectAttempts = 0;
  let startTimeout: ReturnType<typeof setTimeout> | undefined;
  const bufferedFrames = new Map<number, ArrayBuffer>();

  const isActive = computed(() => ["connecting", "recording", "paused", "ending"].includes(status.value));

  function websocketUrl(id: string) {
    return `${API_BASE.replace(/^http/i, "ws")}/ws/realtime/${id}`;
  }

  async function start() {
    if (isActive.value) return;
    resetState();
    status.value = "connecting";
    sessionId.value = crypto.randomUUID();
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: true,
          autoGainControl: false
        }
      });
      audioContext = new AudioContext();
      await audioContext.audioWorklet.addModule("/pcm-worklet.js");
      const source = audioContext.createMediaStreamSource(stream);
      worklet = new AudioWorkletNode(audioContext, "pcm-worklet");
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      source.connect(worklet).connect(silentGain).connect(audioContext.destination);
      worklet.port.onmessage = (event: MessageEvent<Int16Array>) => handlePcm(event.data);
      await connect(false);
      startTimeout = setTimeout(() => {
        if (status.value === "connecting") {
          fail("实时模型加载超时，请稍后重试或检查模型是否已下载");
        }
      }, 60_000);
    } catch (cause) {
      fail(cause instanceof Error ? cause.message : "无法访问麦克风");
    }
  }

  function connect(resume: boolean): Promise<void> {
    return new Promise((resolve, reject) => {
      socket = new WebSocket(websocketUrl(sessionId.value));
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        reconnectAttempts = 0;
        socket?.send(JSON.stringify(resume ? {
          type: "resume_session_connection",
          last_ack: lastAck
        } : {
          type: "start_session",
          codec: "pcm_s16le",
          sample_rate: 16000,
          channels: 1,
          source: "browser_microphone"
        }));
        if (resume) resendBuffered();
        resolve();
      };
      socket.onmessage = (event) => handleEvent(JSON.parse(String(event.data)));
      socket.onerror = () => reject(new Error("实时识别连接失败"));
      socket.onclose = () => {
        if (!intentionalClose && ["recording", "paused"].includes(status.value)) {
          scheduleReconnect();
        }
      };
    });
  }

  function handlePcm(pcm: Int16Array) {
    if (!isActive.value || status.value === "paused" || status.value === "ending") return;
    let peak = 0;
    for (const sample of pcm) peak = Math.max(peak, Math.abs(sample));
    inputLevel.value = Math.min(1, peak / 32768);
    const current = sequence++;
    const frame = encodeAudioFrame(current, BigInt(Date.now()), pcm);
    bufferedFrames.set(current, frame);
    while (bufferedFrames.size > 500) {
      const first = bufferedFrames.keys().next().value as number | undefined;
      if (first === undefined) break;
      bufferedFrames.delete(first);
    }
    if (socket?.readyState === WebSocket.OPEN) socket.send(frame);
  }

  function handleEvent(event: Record<string, any>) {
    if (event.type === "session_started") {
      if (startTimeout) clearTimeout(startTimeout);
      startTimeout = undefined;
      lastAck = Number(event.sequence ?? -1);
      status.value = "recording";
      startTimer();
      return;
    }
    if (event.type === "audio_ack") {
      lastAck = Math.max(lastAck, Number(event.sequence));
      for (const key of bufferedFrames.keys()) {
        if (key <= lastAck) bufferedFrames.delete(key);
      }
      return;
    }
    if (event.type === "partial_transcript") {
      partialText.value = String(event.text || "");
      return;
    }
    if (event.type === "final_transcript") {
      const segment = event.segment as Segment;
      const index = segments.value.findIndex((item) => item.id === segment.id);
      if (index >= 0) segments.value[index] = segment;
      else segments.value.push(segment);
      partialText.value = "";
      return;
    }
    if (event.type === "risk_update") {
      const segment = segments.value.find((item) => item.id === event.segment_id);
      if (segment) {
        segment.sensitive_hits = event.sensitive_hits || [];
        segment.compliance_hits = event.compliance_hits || [];
      }
      return;
    }
    if (event.type === "speaker_mapping_updated") {
      const mapping = event.mapping as Record<string, Speaker>;
      segments.value = segments.value.map((segment) => ({
        ...segment,
        speaker: segment.speaker_cluster ? mapping[segment.speaker_cluster] ?? segment.speaker : segment.speaker
      }));
      return;
    }
    if (event.type === "session_paused") status.value = "paused";
    if (event.type === "session_resumed") status.value = "recording";
    if (event.type === "session_ended") {
      status.value = "ended";
      jobId.value = String(event.job_id || "");
      cleanupMedia();
      intentionalClose = true;
      socket?.close();
    }
    if (event.type === "error") fail(String(event.message || "实时识别失败"), false);
  }

  function pause() {
    if (status.value !== "recording") return;
    socket?.send(JSON.stringify({ type: "pause_session" }));
  }

  function resume() {
    if (status.value !== "paused") return;
    socket?.send(JSON.stringify({ type: "resume_session" }));
  }

  function mapSpeakers(mapping: { speaker_1: Speaker; speaker_2: Speaker }) {
    socket?.send(JSON.stringify({ type: "map_speakers", mapping }));
  }

  function end() {
    if (!["recording", "paused"].includes(status.value)) return;
    status.value = "ending";
    cleanupMedia();
    socket?.send(JSON.stringify({ type: "end_session" }));
  }

  function resendBuffered() {
    for (const [key, frame] of bufferedFrames) {
      if (key > lastAck && socket?.readyState === WebSocket.OPEN) socket.send(frame);
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= 6) {
      fail("实时连接已中断，请结束本次会话后重新开始");
      return;
    }
    reconnectAttempts += 1;
    setTimeout(() => void connect(true).catch(() => scheduleReconnect()), 1000);
  }

  function startTimer() {
    if (timer) return;
    timer = setInterval(() => { elapsedSeconds.value += 1; }, 1000);
  }

  function cleanupMedia() {
    if (startTimeout) clearTimeout(startTimeout);
    startTimeout = undefined;
    if (timer) clearInterval(timer);
    timer = undefined;
    stream?.getTracks().forEach((track) => track.stop());
    stream = undefined;
    void audioContext?.close();
    audioContext = undefined;
    worklet = undefined;
  }

  function fail(message: string, closeSocket = true) {
    error.value = message;
    status.value = "error";
    cleanupMedia();
    if (closeSocket) {
      intentionalClose = true;
      socket?.close();
    }
  }

  function resetState() {
    intentionalClose = false;
    reconnectAttempts = 0;
    sequence = 0;
    lastAck = -1;
    bufferedFrames.clear();
    segments.value = [];
    partialText.value = "";
    error.value = "";
    elapsedSeconds.value = 0;
    inputLevel.value = 0;
    jobId.value = "";
  }

  onBeforeUnmount(() => {
    intentionalClose = true;
    cleanupMedia();
    socket?.close();
  });

  return {
    status,
    segments,
    partialText,
    error,
    elapsedSeconds,
    inputLevel,
    jobId,
    isActive,
    start,
    pause,
    resume,
    end,
    mapSpeakers
  };
}

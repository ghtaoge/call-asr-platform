<script setup lang="ts">
import { ref } from "vue";
import { openRealtimeSession, uploadOffline, analyzeByUrl } from "./api/client";
import Toolbar from "./components/Toolbar.vue";
import TranscriptPanel from "./components/TranscriptPanel.vue";
import RiskPanel from "./components/RiskPanel.vue";
import type { CallSummary, QualityScore, Segment, Speaker } from "./types";

const speaker = ref<Speaker>("sales");
const status = ref("准备就绪");
const segments = ref<Segment[]>([]);
const quality = ref<QualityScore>();
const summary = ref<CallSummary>();
const audioUrl = ref("");
const isLoading = ref(false);

async function handleUpload(file: File) {
  status.value = "正在分析离线录音...";
  try {
    const result = await uploadOffline(file);
    segments.value = result.segments;
    quality.value = result.quality;
    summary.value = result.summary;
    status.value = `分析完成：${result.session_id}`;
  } catch (error) {
    status.value = error instanceof Error ? error.message : "上传失败";
  }
}

function handleRealtime() {
  const sessionId = `web_${Date.now()}`;
  openRealtimeSession(sessionId, speaker.value, (event) => {
    if (event.type === "session_started") {
      status.value = `实时会话已连接：${sessionId}`;
    }
    if (event.type === "final_segment") {
      segments.value = [...segments.value, event.segment];
    }
    if (event.type === "quality_update") {
      quality.value = event.quality;
    }
    if (event.type === "summary_ready") {
      summary.value = event.summary;
    }
  });
  status.value = `正在连接实时会话：当前角色 ${speaker.value}`;
}

async function handleUrlAnalyze() {
  if (!audioUrl.value || isLoading.value) return;
  if (!/^https?:\/\/.+/i.test(audioUrl.value)) {
    status.value = "URL 格式不合法，需要以 http:// 或 https:// 开头";
    return;
  }
  isLoading.value = true;
  status.value = "正在从 URL 下载并分析语音...";
  try {
    const result = await analyzeByUrl(audioUrl.value);
    segments.value = result.segments;
    quality.value = result.quality;
    summary.value = result.summary;
    status.value = `分析完成：${result.session_id}`;
  } catch (error) {
    status.value = error instanceof Error ? error.message : "URL 识别失败";
  } finally {
    isLoading.value = false;
  }
}
</script>

<template>
  <main class="workbench">
    <Toolbar
      :status="status"
      :speaker="speaker"
      :audio-url="audioUrl"
      :is-loading="isLoading"
      @update-speaker="speaker = $event"
      @update-audio-url="audioUrl = $event"
      @upload="handleUpload"
      @realtime="handleRealtime"
      @url-analyze="handleUrlAnalyze"
    />
    <section class="layout">
      <TranscriptPanel :segments="segments" />
      <RiskPanel :segments="segments" :quality="quality" :summary="summary" />
    </section>
  </main>
</template>

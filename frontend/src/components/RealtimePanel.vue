<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { AudioLines, CircleStop, Mic, Pause, Play, Radio } from "lucide-vue-next";
import { useRealtimeSession } from "../composables/useRealtimeSession";
import type { Speaker } from "../types";

const emit = defineEmits<{ jobReady: [jobId: string] }>();
const realtime = useRealtimeSession();
const speaker1 = ref<Speaker | "">("");
const speaker2 = ref<Speaker | "">("");

const elapsed = computed(() => {
  const minutes = Math.floor(realtime.elapsedSeconds.value / 60);
  const seconds = realtime.elapsedSeconds.value % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
});

const statusText = computed(() => ({
  idle: "等待开始",
  connecting: "正在加载实时模型",
  recording: "识别中",
  paused: "已暂停",
  ending: "正在结束通话",
  ended: "通话已结束",
  error: "实时识别失败"
}[realtime.status.value]));

watch(realtime.jobId, (jobId) => {
  if (jobId) emit("jobReady", jobId);
});

function updateMapping() {
  if (!speaker1.value || !speaker2.value || speaker1.value === speaker2.value) return;
  realtime.mapSpeakers({ speaker_1: speaker1.value, speaker_2: speaker2.value });
}

function speakerName(segment: (typeof realtime.segments.value)[number]) {
  if (segment.speaker === "sales") return "销售";
  if (segment.speaker === "customer") return "客户";
  if (segment.speaker_cluster === "speaker_1") return "说话人 1";
  if (segment.speaker_cluster === "speaker_2") return "说话人 2";
  return "未区分";
}

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
</script>

<template>
  <section class="realtimeWorkspace">
    <header class="realtimeControls">
      <div class="realtimeStatus">
        <Radio :size="18" />
        <div><strong>实时语音识别</strong><span>{{ realtime.error.value || statusText }}</span></div>
      </div>
      <div class="levelMeter" aria-label="麦克风音量">
        <span :style="{ width: `${Math.max(3, realtime.inputLevel.value * 100)}%` }" />
      </div>
      <time>{{ elapsed }}</time>
      <div class="recordActions">
        <button v-if="realtime.status.value === 'idle' || realtime.status.value === 'ended' || realtime.status.value === 'error'" class="recordButton" type="button" title="开始实时识别" @click="realtime.start">
          <Mic :size="18" />开始
        </button>
        <button v-if="realtime.status.value === 'recording'" type="button" title="暂停" @click="realtime.pause"><Pause :size="18" /></button>
        <button v-if="realtime.status.value === 'paused'" type="button" title="继续" @click="realtime.resume"><Play :size="18" /></button>
        <button v-if="realtime.isActive.value && realtime.status.value !== 'ending'" class="stopButton" type="button" title="结束通话" @click="realtime.end"><CircleStop :size="18" /></button>
      </div>
    </header>

    <div class="speakerMapping">
      <AudioLines :size="17" />
      <strong>角色映射</strong>
      <label>说话人 1<select v-model="speaker1" @change="updateMapping"><option value="">请选择</option><option value="sales">销售</option><option value="customer">客户</option></select></label>
      <label>说话人 2<select v-model="speaker2" @change="updateMapping"><option value="">请选择</option><option value="sales">销售</option><option value="customer">客户</option></select></label>
    </div>

    <section class="panel realtimeTranscript" aria-label="实时通话内容">
      <header class="panelHeader compact"><h2><AudioLines :size="18" />通话内容</h2><p>{{ realtime.segments.value.length }} 句</p></header>
      <div class="segmentList">
        <article v-for="segment in realtime.segments.value" :key="segment.id" :class="['realtimeSegment', segment.speaker]">
          <span class="speakerBadge">{{ speakerName(segment) }}</span>
          <p>{{ segment.text }}</p>
          <time>{{ formatTime(segment.start_ms) }} - {{ formatTime(segment.end_ms) }}</time>
        </article>
        <div v-if="realtime.partialText.value" data-partial class="partialTranscript">
          <span>正在确认</span><p>{{ realtime.partialText.value }}</p>
        </div>
        <div v-if="!realtime.segments.value.length && !realtime.partialText.value" class="emptyState">等待语音输入</div>
      </div>
    </section>
  </section>
</template>

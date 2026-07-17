<script setup lang="ts">
import { computed, ref } from "vue";
import { AudioLines } from "lucide-vue-next";
import { jobAudioUrl } from "./api/client";
import AudioPlayer from "./components/AudioPlayer.vue";
import EmotionChart from "./components/EmotionChart.vue";
import JobProgress from "./components/JobProgress.vue";
import ModuleState from "./components/ModuleState.vue";
import ModeSwitcher from "./components/ModeSwitcher.vue";
import QualityPanel from "./components/QualityPanel.vue";
import RealtimePanel from "./components/RealtimePanel.vue";
import SensitivePanel from "./components/SensitivePanel.vue";
import SummaryPanel from "./components/SummaryPanel.vue";
import Toolbar from "./components/Toolbar.vue";
import TranscriptPanel from "./components/TranscriptPanel.vue";
import TtsPanel from "./components/TtsPanel.vue";
import { useAnalysisJob } from "./composables/useAnalysisJob";
import type { Speaker } from "./types";

const audioUrl = ref("");
const mode = ref<"analysis" | "realtime" | "tts">("analysis");
const ttsText = ref("");
const activeTime = ref(0);
const transcriptMode = ref<"sentence" | "merged">("sentence");
const speakerFilter = ref<"all" | Speaker>("all");
const audioPlayer = ref<InstanceType<typeof AudioPlayer>>();
const {
  job,
  result,
  error,
  isWorking,
  statusText,
  submitFile,
  submitUrl,
  retrySummary,
  retryModule,
  attachJob
} = useAnalysisJob();

const sourceAudio = computed(() => job.value ? jobAudioUrl(job.value.job_id) : "");

function analyzeUrl() {
  const url = audioUrl.value.trim();
  if (!/^https?:\/\//i.test(url)) return;
  void submitUrl(url);
}

function seek(milliseconds: number) {
  audioPlayer.value?.seek(milliseconds);
}

function openRealtimeResult(jobId: string) {
  mode.value = "analysis";
  void attachJob(jobId);
}

function openTts(text: string) {
  ttsText.value = text;
  mode.value = "tts";
}
</script>

<template>
  <main class="workbench">
    <Toolbar
      :audio-url="audioUrl"
      :is-working="isWorking"
      :status="statusText"
      :show-source-actions="mode === 'analysis'"
      @update-audio-url="audioUrl = $event"
      @upload="submitFile"
      @url-analyze="analyzeUrl"
    />
    <ModeSwitcher :mode="mode" :tts-enabled="true" @change="mode = $event" />
    <RealtimePanel v-if="mode === 'realtime'" @job-ready="openRealtimeResult" />
    <template v-else-if="mode === 'analysis'">
    <JobProgress :job="job" :status="statusText" :has-error="Boolean(error)" />

    <div v-if="result" class="workspace">
      <AudioPlayer ref="audioPlayer" :src="sourceAudio" @time="activeTime = $event" />
      <section class="analysisLayout">
        <div class="primaryColumn">
          <TranscriptPanel
            :segments="result.segments"
            :active-time="activeTime"
            :mode="transcriptMode"
            :speaker="speakerFilter"
            @seek="seek"
            @update-mode="transcriptMode = $event"
            @update-speaker="speakerFilter = $event"
            @synthesize="openTts"
          />
          <EmotionChart v-if="result.emotion_status === 'completed'" :segments="result.segments" @seek="seek" />
          <ModuleState
            v-else
            module="emotion"
            label="情绪分析"
            :status="result.emotion_status"
            :error="result.module_errors.emotion?.message"
            @retry="retryModule"
          />
        </div>
        <aside class="insightPanel">
          <QualityPanel v-if="result.quality_status === 'completed' && result.quality" :quality="result.quality" />
          <ModuleState
            v-else
            module="quality"
            label="通话质检"
            :status="result.quality_status"
            :error="result.module_errors.quality?.message"
            @retry="retryModule"
          />
          <SensitivePanel v-if="result.risk_status === 'completed'" :segments="result.segments" @seek="seek" />
          <ModuleState
            v-else
            module="risk"
            label="风险分析"
            :status="result.risk_status"
            :error="result.module_errors.risk?.message"
            @retry="retryModule"
          />
          <SummaryPanel :summary="result.summary" :status="result.summary_status" @retry="retrySummary" />
        </aside>
      </section>
    </div>

    <section v-else-if="!isWorking" class="initialState">
      <AudioLines :size="38" />
      <h2>尚未提交通话录音</h2>
      <p>请粘贴语音链接，或上传本地双声道录音。</p>
    </section>
    </template>
    <TtsPanel v-else :initial-text="ttsText" />
  </main>
</template>

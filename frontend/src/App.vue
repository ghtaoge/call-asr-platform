<script setup lang="ts">
import { computed, ref } from "vue";
import { AudioLines } from "lucide-vue-next";
import { jobAudioUrl } from "./api/client";
import AudioPlayer from "./components/AudioPlayer.vue";
import EmotionChart from "./components/EmotionChart.vue";
import JobProgress from "./components/JobProgress.vue";
import QualityPanel from "./components/QualityPanel.vue";
import SensitivePanel from "./components/SensitivePanel.vue";
import SummaryPanel from "./components/SummaryPanel.vue";
import Toolbar from "./components/Toolbar.vue";
import TranscriptPanel from "./components/TranscriptPanel.vue";
import { useAnalysisJob } from "./composables/useAnalysisJob";
import type { Speaker } from "./types";

const audioUrl = ref("");
const activeTime = ref(0);
const transcriptMode = ref<"sentence" | "merged">("sentence");
const speakerFilter = ref<"all" | Speaker>("all");
const audioPlayer = ref<InstanceType<typeof AudioPlayer>>();
const { job, result, error, isWorking, statusText, submitFile, submitUrl, retrySummary } = useAnalysisJob();

const sourceAudio = computed(() => job.value ? jobAudioUrl(job.value.job_id) : "");

function analyzeUrl() {
  const url = audioUrl.value.trim();
  if (!/^https?:\/\//i.test(url)) return;
  void submitUrl(url);
}

function seek(milliseconds: number) {
  audioPlayer.value?.seek(milliseconds);
}
</script>

<template>
  <main class="workbench">
    <Toolbar
      :audio-url="audioUrl"
      :is-working="isWorking"
      :status="statusText"
      @update-audio-url="audioUrl = $event"
      @upload="submitFile"
      @url-analyze="analyzeUrl"
    />
    <JobProgress :job="job" :status="statusText" :has-error="Boolean(error)" />

    <div v-if="result" class="workspace">
      <AudioPlayer ref="audioPlayer" :src="sourceAudio" @time="activeTime = $event" />
      <section class="analysisLayout">
        <div class="primaryColumn">
          <EmotionChart :segments="result.segments" @seek="seek" />
          <TranscriptPanel
            :segments="result.segments"
            :active-time="activeTime"
            :mode="transcriptMode"
            :speaker="speakerFilter"
            @seek="seek"
            @update-mode="transcriptMode = $event"
            @update-speaker="speakerFilter = $event"
          />
        </div>
        <aside class="insightPanel">
          <QualityPanel :quality="result.quality" />
          <SensitivePanel :segments="result.segments" @seek="seek" />
          <SummaryPanel :summary="result.summary" :status="result.summary_status" @retry="retrySummary" />
        </aside>
      </section>
    </div>

    <section v-else-if="!isWorking" class="initialState">
      <AudioLines :size="38" />
      <h2>尚未提交通话录音</h2>
      <p>请粘贴语音链接，或上传本地双声道录音。</p>
    </section>
  </main>
</template>

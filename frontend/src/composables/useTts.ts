import { computed, onBeforeUnmount, ref } from "vue";
import { cloneTtsVoice, createTtsJob, getTtsHealth, getTtsJob, getTtsPresetVoices, ttsAudioUrl } from "../api/client";
import type { TtsHealth, TtsJobResponse, TtsPresetVoice, TtsVoiceResponse } from "../types";

export function useTts() {
  const voice = ref<TtsVoiceResponse>();
  const presets = ref<TtsPresetVoice[]>([]);
  const selectedPresetVoiceId = ref("");
  const job = ref<TtsJobResponse>();
  const health = ref<TtsHealth>();
  const error = ref("");
  let timer: ReturnType<typeof setTimeout> | undefined;
  let healthTimer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;

  const isWorking = computed(() => job.value?.status === "queued" || job.value?.status === "running");
  const audioUrl = computed(() => job.value?.status === "completed" ? ttsAudioUrl(job.value.job_id) : "");
  const downloadUrl = computed(() => job.value?.status === "completed" ? ttsAudioUrl(job.value.job_id, true) : "");

  async function loadPresets() {
    try {
      presets.value = await getTtsPresetVoices();
      if (!presets.value.some((item) => item.voice_id === selectedPresetVoiceId.value)) {
        selectedPresetVoiceId.value = presets.value[0]?.voice_id || "";
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "无法获取默认音色";
    }
  }

  async function loadHealth() {
    if (healthTimer) clearTimeout(healthTimer);
    try {
      health.value = await getTtsHealth();
    } catch (cause) {
      health.value = {
        status: "unavailable",
        queue_depth: 0,
        fallback_available: false,
        error_code: "health_request_failed",
        message: cause instanceof Error ? cause.message : "无法获取语音合成服务状态",
        checked_at: new Date().toISOString()
      };
    } finally {
      healthTimer = setTimeout(() => void loadHealth(), 5000);
    }
  }

  async function uploadVoice(file: File, consent: boolean) {
    stopPolling();
    error.value = "";
    job.value = undefined;
    try {
      voice.value = await cloneTtsVoice(file, consent);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "参考音频处理失败";
    }
  }

  async function synthesize(text: string, requestedVoiceId?: string) {
    const voiceId = requestedVoiceId || voice.value?.voice_id;
    if (!voiceId) return;
    stopPolling();
    generation += 1;
    const current = generation;
    error.value = "";
    try {
      job.value = await createTtsJob(voiceId, text.trim());
      await poll(job.value.job_id, current);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "语音合成任务创建失败";
    }
  }

  async function poll(jobId: string, current: number) {
    if (current !== generation) return;
    try {
      job.value = await getTtsJob(jobId);
      if (job.value.status === "queued" || job.value.status === "running") {
        timer = setTimeout(() => void poll(jobId, current), 1000);
      } else if (job.value.status === "failed") {
        error.value = job.value.error_message || "语音合成失败";
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "无法获取语音合成状态";
    }
  }

  function stopPolling() {
    if (timer) clearTimeout(timer);
    timer = undefined;
  }

  function resetResult() {
    stopPolling();
    generation += 1;
    job.value = undefined;
    error.value = "";
  }

  onBeforeUnmount(() => {
    stopPolling();
    if (healthTimer) clearTimeout(healthTimer);
  });
  return {
    voice,
    presets,
    selectedPresetVoiceId,
    health,
    job,
    error,
    isWorking,
    audioUrl,
    downloadUrl,
    loadPresets,
    loadHealth,
    uploadVoice,
    synthesize,
    resetResult
  };
}

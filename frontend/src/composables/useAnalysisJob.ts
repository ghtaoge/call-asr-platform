import { computed, onBeforeUnmount, ref } from "vue";
import {
  createUploadJob,
  createUrlJob,
  getJob,
  getJobResult,
  retrySummary as requestSummaryRetry
} from "../api/client";
import type { AnalysisResult, JobCreateResponse, JobStage, JobStatusResponse } from "../types";

const STAGE_LABELS: Record<JobStage, string> = {
  queued: "等待处理",
  preparing_audio: "正在准备双声道音频",
  transcribing_sales: "正在识别销售声道",
  transcribing_customer: "正在识别客户声道",
  merging_segments: "正在整理对话分段",
  analyzing_emotion: "正在分析情绪变化",
  scanning_risks: "正在识别敏感词与风险",
  generating_summary: "正在生成通话摘要",
  completed: "分析完成",
  failed: "分析失败"
};

export function useAnalysisJob() {
  const job = ref<JobStatusResponse>();
  const result = ref<AnalysisResult>();
  const error = ref("");
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let generation = 0;

  const isWorking = computed(() => job.value?.status === "queued" || job.value?.status === "running");
  const statusText = computed(() => {
    if (error.value) return error.value;
    if (!job.value) return "支持 WAV、MP3、M4A 等常见格式，双声道左侧为销售、右侧为客户";
    return STAGE_LABELS[job.value.stage];
  });

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = undefined;
  }

  async function submit(factory: () => Promise<JobCreateResponse>) {
    stopPolling();
    generation += 1;
    const current = generation;
    result.value = undefined;
    error.value = "";
    try {
      const created = await factory();
      job.value = { ...created, summary_status: "pending" };
      await poll(created.job_id, current);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "无法创建分析任务";
    }
  }

  async function poll(jobId: string, current: number) {
    if (current !== generation) return;
    try {
      const status = await getJob(jobId);
      if (current !== generation) return;
      job.value = status;
      if (status.status === "completed") {
        result.value = await getJobResult(jobId);
        if (status.summary_status === "running") {
          pollTimer = setTimeout(() => void poll(jobId, current), 1000);
        }
        return;
      }
      if (status.status === "failed" || status.status === "interrupted") {
        error.value = status.error_message || "通话分析未完成，请重新提交";
        return;
      }
      pollTimer = setTimeout(() => void poll(jobId, current), 1000);
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : "无法获取任务进度";
    }
  }

  async function retrySummary() {
    if (!job.value) return;
    error.value = "";
    const status = await requestSummaryRetry(job.value.job_id);
    job.value = status;
    generation += 1;
    await poll(status.job_id, generation);
  }

  onBeforeUnmount(stopPolling);
  return {
    job,
    result,
    error,
    isWorking,
    statusText,
    submitFile: (file: File) => submit(() => createUploadJob(file)),
    submitUrl: (url: string) => submit(() => createUrlJob(url)),
    retrySummary
  };
}

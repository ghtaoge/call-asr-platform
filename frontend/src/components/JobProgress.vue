<script setup lang="ts">
import { CheckCircle2, CircleAlert, LoaderCircle } from "lucide-vue-next";
import type { JobStatusResponse } from "../types";

defineProps<{ job?: JobStatusResponse; status: string; hasError: boolean }>();
</script>

<template>
  <section v-if="job || hasError" :class="['jobProgress', { failed: hasError }]" aria-live="polite">
    <CircleAlert v-if="hasError" :size="18" />
    <CheckCircle2 v-else-if="job?.status === 'completed'" :size="18" />
    <LoaderCircle v-else class="spin" :size="18" />
    <div class="jobProgressText">
      <strong>{{ status }}</strong>
      <span v-if="job">任务 {{ job.job_id }}</span>
    </div>
    <div v-if="job && job.status !== 'failed'" class="progressTrack" :aria-label="`分析进度 ${job.progress}%`">
      <span :style="{ width: `${job.progress}%` }" />
    </div>
    <b v-if="job">{{ job.progress }}%</b>
  </section>
</template>

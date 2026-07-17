<script setup lang="ts">
import { CircleAlert, Clock3, LoaderCircle, RotateCw } from "lucide-vue-next";
import type { ModuleStatus } from "../types";

const props = defineProps<{
  module: "emotion" | "risk" | "quality" | "summary";
  label: string;
  status: ModuleStatus;
  error?: string;
}>();
const emit = defineEmits<{
  retry: [module: "emotion" | "risk" | "quality" | "summary"];
}>();
</script>

<template>
  <section :data-module="module" class="moduleState" role="status">
    <LoaderCircle v-if="status === 'running'" class="spin" :size="18" />
    <Clock3 v-else-if="status === 'pending'" :size="18" />
    <CircleAlert v-else :size="18" />
    <div>
      <strong>{{ status === 'failed' ? `${label}失败` : `${label}${status === 'running' ? '中' : '等待中'}` }}</strong>
      <p v-if="status === 'failed'">{{ error || '本模块暂时不可用，通话内容不受影响。' }}</p>
    </div>
    <button v-if="status === 'failed'" type="button" @click="emit('retry', props.module)">
      <RotateCw :size="15" />重新分析
    </button>
  </section>
</template>

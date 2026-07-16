<script setup lang="ts">
import { Upload, Radio, Link } from "lucide-vue-next";
import type { Speaker } from "../types";

defineProps<{
  status: string;
  speaker: Speaker;
  audioUrl: string;
  isLoading: boolean;
}>();

const emit = defineEmits<{
  updateSpeaker: [value: Speaker];
  updateAudioUrl: [value: string];
  upload: [file: File];
  realtime: [];
  urlAnalyze: [];
}>();

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) emit("upload", file);
}
</script>

<template>
  <header class="toolbar">
    <div>
      <h1>通话语音智能分析</h1>
      <p>{{ status }}</p>
    </div>
    <div class="actions">
      <select
        :value="speaker"
        @change="emit('updateSpeaker', ($event.target as HTMLSelectElement).value as Speaker)"
        aria-label="当前说话人"
      >
        <option value="sales">销售</option>
        <option value="customer">客户</option>
        <option value="unknown">未知</option>
      </select>
      <input
        type="text"
        placeholder="输入语音文件 URL 地址"
        :value="audioUrl"
        @input="emit('updateAudioUrl', ($event.target as HTMLInputElement).value)"
        class="urlInput"
      />
      <button
        type="button"
        title="URL 识别"
        :disabled="!audioUrl || isLoading"
        @click="emit('urlAnalyze')"
      >
        <Link :size="18" />
        识别
      </button>
      <label class="fileButton" title="上传录音">
        <Upload :size="18" />
        上传
        <input type="file" accept="audio/*" @change="onFileChange" />
      </label>
      <button type="button" title="实时演示" @click="emit('realtime')">
        <Radio :size="18" />
        实时
      </button>
    </div>
  </header>
</template>

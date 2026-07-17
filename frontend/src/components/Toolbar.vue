<script setup lang="ts">
import { Link, LoaderCircle, Upload } from "lucide-vue-next";

defineProps<{
  audioUrl: string;
  isWorking: boolean;
  status: string;
  showSourceActions?: boolean;
}>();

const emit = defineEmits<{
  updateAudioUrl: [value: string];
  upload: [file: File];
  urlAnalyze: [];
}>();

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) emit("upload", file);
  input.value = "";
}
</script>

<template>
  <header class="toolbar">
    <div class="brand">
      <span class="brandMark">AI</span>
      <div>
        <h1>通话语音智能分析</h1>
        <p>{{ status }}</p>
      </div>
    </div>
    <div v-if="showSourceActions !== false" class="sourceActions">
      <div class="urlField">
        <Link :size="17" aria-hidden="true" />
        <input
          type="url"
          placeholder="粘贴可直接访问的语音 URL"
          :value="audioUrl"
          :disabled="isWorking"
          aria-label="语音 URL"
          @input="emit('updateAudioUrl', ($event.target as HTMLInputElement).value)"
          @keyup.enter="emit('urlAnalyze')"
        />
      </div>
      <button
        class="primaryButton"
        type="button"
        :disabled="!audioUrl.trim() || isWorking"
        @click="emit('urlAnalyze')"
      >
        <LoaderCircle v-if="isWorking" class="spin" :size="17" />
        <Link v-else :size="17" />
        识别链接
      </button>
      <label :class="['secondaryButton', { disabled: isWorking }]">
        <Upload :size="17" />
        上传录音
        <input type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg" :disabled="isWorking" @change="onFileChange" />
      </label>
    </div>
  </header>
</template>

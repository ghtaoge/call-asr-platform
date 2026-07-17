<script setup lang="ts">
import { AudioLines, FileAudio, Speech } from "lucide-vue-next";

defineProps<{ mode: "analysis" | "realtime" | "tts"; ttsEnabled?: boolean }>();
const emit = defineEmits<{ change: [mode: "analysis" | "realtime" | "tts"] }>();
</script>

<template>
  <nav class="modeSwitcher" aria-label="工作模式">
    <button :class="{ active: mode === 'analysis' }" type="button" @click="emit('change', 'analysis')">
      <FileAudio :size="17" />录音分析
    </button>
    <button :class="{ active: mode === 'realtime' }" type="button" @click="emit('change', 'realtime')">
      <AudioLines :size="17" />实时识别
    </button>
    <button :class="{ active: mode === 'tts' }" type="button" :disabled="!ttsEnabled" @click="emit('change', 'tts')">
      <Speech :size="17" />语音合成
    </button>
  </nav>
</template>

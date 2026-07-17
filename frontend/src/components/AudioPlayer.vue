<script setup lang="ts">
import { ref } from "vue";
import { Headphones } from "lucide-vue-next";

defineProps<{ src: string }>();
const emit = defineEmits<{ time: [milliseconds: number] }>();
const audio = ref<HTMLAudioElement>();

function seek(milliseconds: number) {
  if (!audio.value) return;
  audio.value.currentTime = milliseconds / 1000;
  void audio.value.play();
}

defineExpose({ seek });
</script>

<template>
  <section class="audioBar">
    <div class="sectionLabel"><Headphones :size="18" /> 原始录音</div>
    <audio
      ref="audio"
      :src="src"
      controls
      preload="metadata"
      @timeupdate="emit('time', ($event.target as HTMLAudioElement).currentTime * 1000)"
    />
  </section>
</template>

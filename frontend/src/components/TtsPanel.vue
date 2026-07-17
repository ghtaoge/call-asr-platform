<script setup lang="ts">
import { ref, watch } from "vue";
import { Download, LoaderCircle, Speech, Upload, Volume2 } from "lucide-vue-next";
import { useTts } from "../composables/useTts";

const props = defineProps<{ initialText?: string }>();
const text = ref(props.initialText || "");
const consent = ref(false);
const tts = useTts();

watch(() => props.initialText, (value) => {
  if (value !== undefined) text.value = value;
});

function selectReference(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (!consent.value) {
    input.value = "";
    return;
  }
  void tts.uploadVoice(file, true);
  input.value = "";
}
</script>

<template>
  <section class="ttsWorkspace">
    <header class="ttsHeader"><Speech :size="20" /><div><h2>语音合成</h2><p>CosyVoice 声音复刻</p></div></header>
    <div class="ttsForm">
      <label class="ttsTextLabel">合成文本<textarea v-model="text" maxlength="2000" placeholder="输入需要合成的中文内容" /></label>
      <div class="voiceReference">
        <label class="consentCheck"><input v-model="consent" type="checkbox" />我已获得该声音的使用授权</label>
        <label :class="['secondaryButton', { disabled: !consent }]">
          <Upload :size="17" />上传参考音频
          <input type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/aac,.wav,.mp3,.m4a,.aac" :disabled="!consent" @change="selectReference" />
        </label>
        <span v-if="tts.voice.value" class="voiceReady">音色已就绪</span>
      </div>
      <p v-if="!consent" class="ttsHint">请先确认声音使用授权</p>
      <p v-if="tts.voice.value" class="promptText">参考内容：{{ tts.voice.value.prompt_text }}</p>
      <p v-if="tts.error.value" class="ttsError">{{ tts.error.value }}</p>
      <button class="primaryButton ttsSubmit" type="button" :disabled="!tts.voice.value || !text.trim() || tts.isWorking.value" @click="tts.synthesize(text)">
        <LoaderCircle v-if="tts.isWorking.value" class="spin" :size="17" /><Volume2 v-else :size="17" />
        {{ tts.job.value?.status === 'queued' ? '等待合成' : tts.isWorking.value ? '正在合成' : '开始合成' }}
      </button>
    </div>
    <div v-if="tts.audioUrl.value" class="ttsResult">
      <audio :src="tts.audioUrl.value" controls />
      <a class="secondaryButton" :href="tts.downloadUrl.value"><Download :size="17" />下载音频</a>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { Download, LoaderCircle, Speech, Upload, UserRound, Volume2 } from "lucide-vue-next";
import { useTts } from "../composables/useTts";

const props = defineProps<{ initialText?: string }>();
const text = ref(props.initialText || "");
const consent = ref(false);
const voiceMode = ref<"preset" | "custom">("preset");
const tts = useTts();
const activeVoiceId = computed(() => voiceMode.value === "preset"
  ? tts.selectedPresetVoiceId.value
  : tts.voice.value?.voice_id || "");

onMounted(() => void tts.loadPresets());

watch(() => props.initialText, (value) => {
  if (value !== undefined) text.value = value;
});

watch(voiceMode, () => tts.resetResult());

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

function synthesize() {
  void tts.synthesize(text.value, activeVoiceId.value);
}
</script>

<template>
  <section class="ttsWorkspace">
    <header class="ttsHeader"><Speech :size="20" /><div><h2>语音合成</h2><p>CosyVoice 默认音色与声音复刻</p></div></header>
    <div class="ttsForm">
      <label class="ttsTextLabel">合成文本<textarea v-model="text" maxlength="2000" placeholder="输入需要合成的中文内容" /></label>
      <div class="voiceMode segmented" aria-label="音色来源">
        <button type="button" :class="{ active: voiceMode === 'preset' }" @click="voiceMode = 'preset'">默认音色</button>
        <button type="button" :class="{ active: voiceMode === 'custom' }" @click="voiceMode = 'custom'">自定义音色</button>
      </div>
      <label v-if="voiceMode === 'preset'" class="presetVoiceLabel">
        <span><UserRound :size="17" />选择默认音色</span>
        <select v-model="tts.selectedPresetVoiceId.value" aria-label="选择默认音色" @change="tts.resetResult">
          <option v-for="preset in tts.presets.value" :key="preset.id" :value="preset.voice_id">
            {{ preset.label }} · {{ preset.language }}
          </option>
        </select>
      </label>
      <p v-if="voiceMode === 'preset'" class="ttsHint">CosyVoice 未启动时，普通话和英语可使用 Windows 系统语音兜底。</p>
      <template v-else>
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
      </template>
      <p v-if="tts.error.value" class="ttsError">{{ tts.error.value }}</p>
      <button class="primaryButton ttsSubmit" type="button" :disabled="!activeVoiceId || !text.trim() || tts.isWorking.value" @click="synthesize">
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

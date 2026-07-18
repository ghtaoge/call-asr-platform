<script setup lang="ts">
import { computed, nextTick, watch } from "vue";
import { Clock3, MessageSquareText, Volume2 } from "lucide-vue-next";
import type { Segment, SensitiveHit, Speaker } from "../types";

const props = defineProps<{
  segments: Segment[];
  activeTime: number;
  mode: "sentence" | "merged";
  speaker: "all" | Speaker;
}>();
const emit = defineEmits<{
  seek: [milliseconds: number];
  updateMode: [value: "sentence" | "merged"];
  updateSpeaker: [value: "all" | Speaker];
  synthesize: [text: string];
}>();

interface DisplaySegment extends Segment {}

const filtered = computed(() => {
  const source = props.speaker === "all"
    ? props.segments
    : props.segments.filter((segment) => segment.speaker === props.speaker);
  // “逐句”保留后端的 VAD/标点切分；“合并”只合并时间线上相邻且角色相同的句子，
  // 因此切换模式会改变条目数，但不会打乱销售与客户的对话顺序。
  if (props.mode === "sentence") return source;
  const merged: DisplaySegment[] = [];
  for (const segment of source) {
    const previous = merged[merged.length - 1];
    if (!previous || previous.speaker !== segment.speaker) {
      merged.push({ ...segment, sensitive_hits: [...segment.sensitive_hits], compliance_hits: [...segment.compliance_hits] });
      continue;
    }
    // 合并文本插入了一个换行，敏感词索引必须同步偏移，否则标红位置会错位。
    const offset = previous.text.length + 1;
    previous.text += `\n${segment.text}`;
    previous.end_ms = segment.end_ms;
    previous.sensitive_hits.push(...segment.sensitive_hits.map((hit) => ({
      ...hit,
      start: hit.start + offset,
      end: hit.end + offset
    })));
    previous.compliance_hits.push(...segment.compliance_hits);
  }
  return merged;
});

const rowElements = new Map<string, HTMLElement>();
const activeSegmentId = computed(() => {
  // 在语句间静音或录音结尾继续保留最近一条已开始的语句，避免进度条移动后
  // 转写区突然失去定位。列表按开始时间排序，因此最后一次命中即为当前语境。
  let latestId: string | undefined;
  for (const segment of filtered.value) {
    if (segment.start_ms > props.activeTime) break;
    latestId = segment.id;
  }
  return latestId;
});

function setSegmentRow(id: string, element: unknown) {
  if (element instanceof HTMLElement) rowElements.set(id, element);
  else rowElements.delete(id);
}

watch(activeSegmentId, async (id) => {
  if (!id) return;
  await nextTick();
  rowElements.get(id)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

function speakerName(segment: DisplaySegment) {
  if (segment.speaker === "sales") return "销售";
  if (segment.speaker === "customer") return "客户";
  return segment.speaker_cluster === "speaker_2" ? "说话人 2" : segment.speaker_cluster === "speaker_1" ? "说话人 1" : "未知";
}

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function emotionName(label: string) {
  const names: Record<string, string> = {
    positive: "积极",
    neutral: "平静",
    negative: "消极",
    angry: "生气",
    anxious: "焦虑"
  };
  return names[label] ?? label;
}

function highlighted(segment: Segment): Array<{ text: string; hit?: SensitiveHit }> {
  const hits = [...segment.sensitive_hits]
    .sort((a, b) => a.start - b.start || b.end - a.end)
    .filter((hit, index, all) => index === 0 || hit.start >= all[index - 1].end);
  if (!hits.length) return [{ text: segment.text }];
  const parts: Array<{ text: string; hit?: SensitiveHit }> = [];
  let cursor = 0;
  for (const hit of hits) {
    if (hit.start > cursor) parts.push({ text: segment.text.slice(cursor, hit.start) });
    parts.push({ text: segment.text.slice(hit.start, hit.end), hit });
    cursor = hit.end;
  }
  if (cursor < segment.text.length) parts.push({ text: segment.text.slice(cursor) });
  return parts;
}
</script>

<template>
  <section class="panel transcriptPanel" aria-label="通话内容">
    <header class="panelHeader">
      <div>
        <h2><MessageSquareText :size="18" /> 通话内容</h2>
        <p>共 {{ filtered.length }} 个{{ mode === 'sentence' ? '语句' : '合并段' }}</p>
      </div>
      <div class="panelControls">
        <div class="segmented" aria-label="显示方式">
          <button :class="{ active: mode === 'sentence' }" @click="emit('updateMode', 'sentence')">逐句</button>
          <button :class="{ active: mode === 'merged' }" @click="emit('updateMode', 'merged')">合并</button>
        </div>
        <select :value="speaker" aria-label="筛选说话人" @change="emit('updateSpeaker', ($event.target as HTMLSelectElement).value as 'all' | Speaker)">
          <option value="all">全部角色</option>
          <option value="sales">仅销售</option>
          <option value="customer">仅客户</option>
        </select>
      </div>
    </header>
    <div v-if="!filtered.length" class="emptyState">暂无识别内容</div>
    <div v-else class="segmentList">
      <article
        v-for="segment in filtered"
        :key="segment.id"
        :ref="(element) => setSegmentRow(segment.id, element)"
        :class="['segmentRow', segment.speaker, { active: activeSegmentId === segment.id }]"
        @click="emit('seek', segment.start_ms)"
      >
        <span class="speakerBadge">{{ speakerName(segment) }}</span>
        <span class="segmentBody">
          <span class="segmentText">
            <template v-for="(part, index) in highlighted(segment)" :key="`${segment.id}-${index}`">
              <mark v-if="part.hit" :class="`hit-${part.hit.level}`" :title="`${part.hit.category} · ${part.hit.level}${part.hit.dictionary_version ? ` · 版本 ${part.hit.dictionary_version}` : ''}`">{{ part.text }}</mark>
              <span v-else>{{ part.text }}</span>
            </template>
          </span>
          <span v-if="segment.compliance_hits.length" class="complianceText">{{ segment.compliance_hits[0].message }}</span>
        </span>
        <span class="segmentAside">
          <span :class="['emotionTag', segment.emotion.label]">{{ emotionName(segment.emotion.label) }}</span>
          <span class="timeTag"><Clock3 :size="13" /> {{ formatTime(segment.start_ms) }} - {{ formatTime(segment.end_ms) }}</span>
          <button class="sentenceTtsButton" type="button" aria-label="朗读本句" title="朗读本句" @click.stop="emit('synthesize', segment.text)"><Volume2 :size="14" /></button>
        </span>
      </article>
    </div>
  </section>
</template>

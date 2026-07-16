<script setup lang="ts">
import type { Segment, SensitiveHit } from "../types";

defineProps<{
  segments: Segment[];
}>();

function speakerName(speaker: Segment["speaker"]) {
  return speaker === "sales" ? "销售" : speaker === "customer" ? "客户" : "未知";
}

	function renderHighlightedText(segment: Segment): Array<{ text: string; hit?: SensitiveHit }> {
	  if (segment.sensitive_hits.length === 0) {
	    return [{ text: segment.text }];
	  }
	  const ordered = [...segment.sensitive_hits].sort((a, b) => a.start - b.start);
	  const parts: Array<{ text: string; hit?: SensitiveHit }> = [];
	  let cursor = 0;
	  for (const hit of ordered) {
	    if (cursor < hit.start) {
	      parts.push({ text: segment.text.slice(cursor, hit.start) });
	    }
	    parts.push({ text: segment.text.slice(hit.start, hit.end), hit });
	    cursor = hit.end;
	  }
	  if (cursor < segment.text.length) {
	    parts.push({ text: segment.text.slice(cursor) });
	  }
	  return parts;
	}
</script>

<template>
  <section class="transcript" aria-label="通话内容">
    <h2>通话内容</h2>
    <p v-if="segments.length === 0" class="empty">上传录音或开始实时演示后，分段转写会显示在这里。</p>
    <div v-else class="segmentList">
      <article
        v-for="segment in segments"
        :key="segment.id"
        :class="['segment', segment.speaker]"
      >
        <div class="segmentMeta">
          <strong>{{ speakerName(segment.speaker) }}</strong>
          <span>{{ Math.round(segment.start_ms / 1000) }}s - {{ Math.round(segment.end_ms / 1000) }}s</span>
          <span>{{ segment.emotion.label }}</span>
        </div>
        <p>
          <template v-for="part in renderHighlightedText(segment)" :key="part.text + (part.hit?.start ?? '')">
            <mark v-if="part.hit" :class="`hit-${part.hit.level}`">{{ part.text }}</mark>
            <span v-else>{{ part.text }}</span>
          </template>
        </p>
        <small>{{ segment.translation }}</small>
      </article>
    </div>
  </section>
</template>

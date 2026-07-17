<script setup lang="ts">
import { computed } from "vue";
import { ShieldAlert } from "lucide-vue-next";
import type { RiskLevel, Segment } from "../types";

const props = defineProps<{ segments: Segment[] }>();
const emit = defineEmits<{ seek: [milliseconds: number] }>();
const order: Record<RiskLevel, number> = { critical: 4, high: 3, medium: 2, low: 1 };
const names: Record<RiskLevel, string> = { critical: "严重", high: "高风险", medium: "中风险", low: "低风险" };

const risks = computed(() => props.segments.flatMap((segment) => [
  ...segment.sensitive_hits.map((hit) => ({
    id: `${segment.id}-${hit.start}-${hit.word}`,
    level: hit.level,
    title: hit.word,
    description: hit.category,
    startMs: segment.start_ms,
    speaker: segment.speaker
  })),
  ...segment.compliance_hits.map((hit) => ({
    id: `${segment.id}-${hit.rule_id}`,
    level: hit.level,
    title: hit.message,
    description: hit.suggestion,
    startMs: segment.start_ms,
    speaker: segment.speaker
  }))
]).sort((a, b) => order[b.level] - order[a.level] || a.startMs - b.startMs));

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
</script>

<template>
  <section class="sideSection">
    <header class="sideHeader">
      <h2><ShieldAlert :size="18" /> 风险与敏感词</h2>
      <span class="countBadge">{{ risks.length }}</span>
    </header>
    <div class="riskLegend">
      <span v-for="level in (['low', 'medium', 'high', 'critical'] as RiskLevel[])" :key="level" :class="`legend-${level}`">{{ names[level] }}</span>
    </div>
    <p v-if="!risks.length" class="emptyCompact">本次通话未命中敏感词或合规规则</p>
    <div v-else class="riskItems">
      <button v-for="risk in risks" :key="risk.id" type="button" :class="['riskItem', `risk-${risk.level}`]" @click="emit('seek', risk.startMs)">
        <span class="riskLevel">{{ names[risk.level] }}</span>
        <span class="riskContent"><strong>{{ risk.title }}</strong><small>{{ risk.description }}</small></span>
        <time>{{ risk.speaker === 'sales' ? '销售' : '客户' }} {{ formatTime(risk.startMs) }}</time>
      </button>
    </div>
  </section>
</template>

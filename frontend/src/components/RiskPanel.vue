<script setup lang="ts">
import { ShieldAlert } from "lucide-vue-next";
import type { CallSummary, QualityScore, Segment } from "../types";

defineProps<{
  segments: Segment[];
  quality?: QualityScore;
  summary?: CallSummary;
}>();

function collectRisks(segments: Segment[]) {
  return segments.flatMap((segment) => [
    ...segment.sensitive_hits.map((hit) => `${hit.level}: ${hit.word}（${segment.speaker}）`),
    ...segment.compliance_hits.map((hit) => `${hit.level}: ${hit.message}`)
  ]);
}
</script>

<template>
  <aside class="risk" aria-label="风险与质检">
    <h2>
      <ShieldAlert :size="18" /> 风险与质检
    </h2>
    <div v-if="quality" class="score">{{ quality.score }}</div>
    <p v-if="collectRisks(segments).length === 0" class="empty">暂无风险命中。</p>
    <ul v-else class="riskList">
      <li v-for="(risk, index) in collectRisks(segments)" :key="`${risk}-${index}`">{{ risk }}</li>
    </ul>
    <section v-if="summary" class="summary">
      <h3>摘要</h3>
      <p>客户诉求：{{ summary.customer_needs.join("、") || "未识别" }}</p>
      <p>待跟进：{{ summary.follow_up_items.join("、") || "暂无" }}</p>
      <p>下一步：{{ summary.next_steps.join("、") }}</p>
    </section>
  </aside>
</template>

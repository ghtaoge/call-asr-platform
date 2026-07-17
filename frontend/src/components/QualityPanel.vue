<script setup lang="ts">
import { BadgeCheck } from "lucide-vue-next";
import type { QualityScore } from "../types";

defineProps<{ quality: QualityScore }>();
</script>

<template>
  <section class="sideSection qualitySection">
    <header class="sideHeader"><h2><BadgeCheck :size="18" /> 通话质检</h2><strong class="qualityScore">{{ quality.score }} 分</strong></header>
    <div class="qualityMetrics">
      <span><small>销售占比</small><b>{{ Math.round(quality.sales_talk_ratio * 100) }}%</b></span>
      <span><small>客户占比</small><b>{{ Math.round(quality.customer_talk_ratio * 100) }}%</b></span>
      <span><small>打断次数</small><b>{{ quality.interruptions }}</b></span>
    </div>
    <ul v-if="quality.suggestions.length" class="suggestions">
      <li v-for="suggestion in quality.suggestions" :key="suggestion">{{ suggestion }}</li>
    </ul>
  </section>
</template>

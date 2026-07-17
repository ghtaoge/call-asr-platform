<script setup lang="ts">
import { FileText, RefreshCw } from "lucide-vue-next";
import type { CallSummary, SummaryStatus } from "../types";

defineProps<{ summary?: CallSummary; status: SummaryStatus }>();
const emit = defineEmits<{ retry: [] }>();

type SummaryListKey = Exclude<keyof CallSummary, "overview">;
const sections: Array<{ key: SummaryListKey; name: string }> = [
  { key: "customer_needs", name: "客户诉求" },
  { key: "sales_promises", name: "销售承诺" },
  { key: "risk_points", name: "风险要点" },
  { key: "follow_up_items", name: "待跟进事项" },
  { key: "next_steps", name: "下一步建议" }
];
</script>

<template>
  <section class="sideSection summarySection">
    <header class="sideHeader">
      <h2><FileText :size="18" /> 通话摘要</h2>
      <div class="summaryHeaderActions">
        <span class="deepseekBadge">DeepSeek</span>
        <button
          v-if="status === 'failed' || status === 'completed'"
          class="summaryRetryButton"
          type="button"
          title="重新生成通话摘要"
          @click="emit('retry')"
        >
          <RefreshCw :size="14" />重新生成
        </button>
      </div>
    </header>
    <div v-if="status === 'failed'" class="summaryFailure">
      <p>本地识别已完成，摘要生成失败。</p>
    </div>
    <div v-else-if="status !== 'completed' || !summary" class="summaryLoading">摘要正在生成...</div>
    <div v-else class="summaryBody">
      <p class="overview">{{ summary.overview || "本次通话暂无概述。" }}</p>
      <div v-for="section in sections" :key="section.key" class="summaryGroup">
        <h3>{{ section.name }}</h3>
        <ul v-if="summary[section.key].length">
          <li v-for="item in summary[section.key]" :key="item">{{ item }}</li>
        </ul>
        <p v-else>未识别到相关内容</p>
      </div>
    </div>
  </section>
</template>

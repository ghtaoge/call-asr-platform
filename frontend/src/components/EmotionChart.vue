<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { init, use, type ECharts } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { Activity } from "lucide-vue-next";
import type { Segment } from "../types";

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

const props = defineProps<{ segments: Segment[] }>();
const emit = defineEmits<{ seek: [milliseconds: number] }>();
const container = ref<HTMLDivElement>();
let chart: ECharts | undefined;
let observer: ResizeObserver | undefined;

function points(speaker: "sales" | "customer") {
  return props.segments
    .filter((segment) => segment.speaker === speaker)
    .map((segment) => [((segment.start_ms + segment.end_ms) / 2000), segment.emotion.score, segment.start_ms]);
}

function render() {
  chart?.setOption({
    animationDuration: 350,
    color: ["#2563eb", "#16835f"],
    grid: { left: 42, right: 20, top: 38, bottom: 30 },
    legend: { top: 0, right: 8, itemWidth: 18, textStyle: { color: "#52606d" } },
    tooltip: {
      trigger: "axis",
      valueFormatter: (value: unknown) => {
        const score = Number(value);
        return score > 0.2 ? "积极" : score < -0.2 ? "消极" : "平静";
      }
    },
    xAxis: {
      type: "value",
      axisLabel: { formatter: (value: number) => `${Math.floor(value / 60)}:${String(Math.floor(value % 60)).padStart(2, "0")}` },
      splitLine: { lineStyle: { color: "#edf1f4" } }
    },
    yAxis: {
      type: "value",
      min: -1,
      max: 1,
      interval: 1,
      axisLabel: { formatter: (value: number) => value === 1 ? "积极" : value === -1 ? "消极" : "平静" },
      splitLine: { lineStyle: { color: "#edf1f4" } }
    },
    series: [
      { name: "销售", type: "line", smooth: 0.25, symbolSize: 7, data: points("sales") },
      { name: "客户", type: "line", smooth: 0.25, symbolSize: 7, data: points("customer") }
    ]
  });
}

onMounted(() => {
  if (!container.value) return;
  chart = init(container.value);
  chart.on("click", (params: { data?: unknown }) => {
    const data = params.data as number[] | undefined;
    if (data?.[2] !== undefined) emit("seek", data[2]);
  });
  observer = new ResizeObserver(() => chart?.resize());
  observer.observe(container.value);
  render();
});

watch(() => props.segments, render, { deep: true });
onBeforeUnmount(() => {
  observer?.disconnect();
  chart?.dispose();
});
</script>

<template>
  <section class="panel emotionPanel">
    <header class="panelHeader compact">
      <div>
        <h2><Activity :size="18" /> 情绪走势</h2>
        <p>点击节点可跳转到对应录音</p>
      </div>
    </header>
    <div ref="container" class="emotionChart" role="img" aria-label="销售与客户情绪变化曲线" />
  </section>
</template>

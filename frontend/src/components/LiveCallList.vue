<script setup lang="ts">
import { onMounted, ref } from "vue";
import { PhoneCall, RefreshCw } from "lucide-vue-next";
import { listPbxCalls } from "../api/client";
import type { PbxCall } from "../types";

const calls = ref<PbxCall[]>([]);
const loading = ref(false);
const error = ref("");
const statusNames: Record<string, string> = { connecting: "连接中", active: "通话中", finalizing: "整理中", completed: "已完成", failed: "异常" };

async function load() {
  if (!localStorage.getItem("call-asr-auth-token")) return;
  loading.value = true;
  try { calls.value = (await listPbxCalls()).items; } catch (cause) { error.value = cause instanceof Error ? cause.message : "PBX 通话加载失败"; } finally { loading.value = false; }
}
onMounted(() => void load());
</script>

<template>
  <section class="panel liveCallPanel" aria-label="PBX实时通话">
    <header class="panelHeader compact"><div><h2><PhoneCall :size="18" />PBX 实时通话</h2><p>来自外部电话系统的通话记录</p></div><button class="iconButton" type="button" aria-label="刷新 PBX 通话" title="刷新" :disabled="loading" @click="load"><RefreshCw :size="15" /></button></header>
    <div v-if="error" class="settingsError">{{ error }}</div>
    <div v-else-if="!calls.length" class="emptyCompact">暂无 PBX 实时通话</div>
    <div v-else class="liveCallList">
      <article v-for="call in calls" :key="call.id" class="liveCallRow">
        <div><strong>{{ call.source_session_id }}</strong><small>{{ call.source.toUpperCase() }} · {{ statusNames[call.status] }}</small></div>
        <span v-if="call.role_pending" class="liveFlag">角色待确认</span>
        <span v-if="call.asr_degraded" class="liveFlag risk-high">识别降级</span>
        <span v-if="call.media_interrupted" class="liveFlag risk-critical">媒体中断</span>
      </article>
    </div>
  </section>
</template>

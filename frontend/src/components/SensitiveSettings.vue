<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { Plus, RefreshCw, ShieldAlert, Trash2 } from "lucide-vue-next";
import { createSensitiveWord, deleteSensitiveWord, listSensitiveWords, updateSensitiveWord, type SensitiveWordRecord } from "../api/client";

const words = ref<SensitiveWordRecord[]>([]);
const nextCursor = ref<string>();
const version = ref(0);
const loading = ref(false);
const error = ref("");
const form = reactive({ word: "", level: "medium", category: "", enabled: true });
const levelNames: Record<string, string> = { low: "提示", medium: "警告", high: "高风险", critical: "严重" };

async function load(cursor?: string) {
  loading.value = true;
  error.value = "";
  try {
    const response = await listSensitiveWords({ limit: 50, cursor });
    words.value = cursor ? [...words.value, ...response.items] : response.items;
    nextCursor.value = response.next_cursor;
    version.value = response.version;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "敏感词加载失败";
  } finally {
    loading.value = false;
  }
}

async function addWord() {
  if (!form.word.trim() || !form.category.trim()) return;
  try {
    await createSensitiveWord({ ...form, word: form.word.trim(), category: form.category.trim() });
    form.word = "";
    form.category = "";
    await load();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "敏感词保存失败";
  }
}

async function toggle(word: SensitiveWordRecord) {
  await updateSensitiveWord(word.id, { enabled: !word.enabled });
  await load();
}

async function remove(word: SensitiveWordRecord) {
  await deleteSensitiveWord(word.id);
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section class="sensitiveSettings" aria-label="敏感词设置">
    <header class="settingsHeader">
      <div>
        <h2><ShieldAlert :size="19" /> 敏感词设置</h2>
        <p>当前词典版本 {{ version }}，命中后会在通话内容中按等级标色。</p>
      </div>
      <button class="secondaryButton" type="button" :disabled="loading" @click="load()"><RefreshCw :size="15" />刷新</button>
    </header>
    <form class="sensitiveForm" @submit.prevent="addWord">
      <label>敏感词<input v-model="form.word" maxlength="128" placeholder="例如：绝对有效" /></label>
      <label>等级<select v-model="form.level"><option v-for="(name, value) in levelNames" :key="value" :value="value">{{ name }}</option></select></label>
      <label>分类<input v-model="form.category" maxlength="64" placeholder="例如：承诺" /></label>
      <label class="enabledCheck"><input v-model="form.enabled" type="checkbox" />启用</label>
      <button class="primaryButton" type="submit" :disabled="!form.word.trim() || !form.category.trim()"><Plus :size="16" />添加</button>
    </form>
    <p v-if="error" class="settingsError">{{ error }}</p>
    <div v-if="!words.length && !loading" class="emptyState">暂无敏感词</div>
    <div v-else class="sensitiveTable" role="table">
      <div class="sensitiveTableRow sensitiveTableHead" role="row"><span>词语</span><span>等级</span><span>分类</span><span>版本</span><span>状态</span><span>操作</span></div>
      <div v-for="word in words" :key="word.id" class="sensitiveTableRow" role="row">
        <strong>{{ word.word }}</strong>
        <span :class="['levelSwatch', `level-${word.level}`]">{{ levelNames[word.level] }}</span>
        <span>{{ word.category }}</span>
        <span>v{{ word.version }}</span>
        <button class="statusButton" type="button" @click="toggle(word)">{{ word.enabled ? "已启用" : "已停用" }}</button>
        <button class="iconButton" type="button" aria-label="删除敏感词" title="删除敏感词" @click="remove(word)"><Trash2 :size="15" /></button>
      </div>
    </div>
    <button v-if="nextCursor" class="secondaryButton loadMoreButton" type="button" :disabled="loading" @click="load(nextCursor)">加载更多</button>
  </section>
</template>

<script setup lang="ts">
import { Check, Clock } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

export type OutlineVersionItem = {
  version_id: number
  version_no: number
  outline: string
  status: string
  created_at: string
}

const props = defineProps<{
  outline: string
  versions: OutlineVersionItem[]
  loading: boolean
}>()

const { locale, t } = useI18n()

// 大纲由 LLM 生成，可能包含 Markdown；关闭 html 解析，避免把模型文本当成真实 HTML 执行。
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedOutline = computed(() => markdown.render(props.outline))

const formatDate = (value: string) => {
  const formatterLocale = locale.value === 'zh' ? 'zh-CN' : 'en-US'
  return new Date(value).toLocaleString(formatterLocale)
}
</script>

<template>
  <section v-loading="loading" class="outline-panel panel">
    <header class="outline-panel__header">
      <div>
        <h3>{{ t('outline.panel.title') }}</h3>
        <p>{{ t('outline.panel.description') }}</p>
      </div>
      <el-button type="success" :icon="Check" :disabled="!outline">
        {{ t('outline.panel.confirm') }}
      </el-button>
    </header>

    <div class="outline-panel__content">
      <el-empty v-if="!outline" :description="t('outline.panel.empty')" />
      <el-scrollbar v-else class="outline-panel__outline-scroll" always>
        <article class="outline-panel__outline markdown-body" v-html="renderedOutline" />
      </el-scrollbar>

      <el-divider />

      <div class="outline-panel__versions">
        <h4>{{ t('outline.panel.recentVersions') }}</h4>
        <el-empty
          v-if="versions.length === 0"
          :description="t('outline.panel.emptyVersions')"
        />
        <div
          v-for="item in versions"
          v-else
          :key="item.version_id"
          class="outline-panel__version"
        >
          <span>v{{ item.version_no }}</span>
          <el-tag :type="item.status === 'active' ? 'success' : 'info'" effect="plain">
            {{ t(`outline.versionStatus.${item.status}`) }}
          </el-tag>
          <small>
            <el-icon><Clock /></el-icon>
            {{ formatDate(item.created_at) }}
          </small>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.outline-panel {
  min-height: 680px;
}

.outline-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px;
  border-bottom: 1px solid var(--panel-border);
}

.outline-panel__header h3,
.outline-panel__header p,
.outline-panel__versions h4 {
  margin: 0;
}

.outline-panel__header h3 {
  font-size: 18px;
}

.outline-panel__header p {
  margin-top: 6px;
  color: var(--text-soft);
}

.outline-panel__content {
  padding: 24px;
}

.outline-panel__outline-scroll {
  height: clamp(320px, 48vh, 560px);
  padding-right: 8px;
}

.outline-panel__outline {
  margin: 0;
  color: var(--text-regular);
  overflow-wrap: anywhere;
}

.markdown-body {
  line-height: 1.8;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 0 0 12px;
  color: var(--text-strong);
  line-height: 1.35;
}

.markdown-body :deep(h1) {
  font-size: 24px;
}

.markdown-body :deep(h2) {
  margin-top: 20px;
  font-size: 20px;
}

.markdown-body :deep(h3) {
  margin-top: 16px;
  font-size: 17px;
}

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol),
.markdown-body :deep(blockquote) {
  margin: 0 0 12px;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 22px;
}

.markdown-body :deep(li + li) {
  margin-top: 6px;
}

.markdown-body :deep(strong) {
  color: var(--text-strong);
}

.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 5px;
  background: #f1f5f9;
  color: #0f172a;
  font-size: 0.92em;
}

.markdown-body :deep(blockquote) {
  padding: 10px 14px;
  border-left: 3px solid #4f6bff;
  border-radius: 0 8px 8px 0;
  background: #f8fafc;
  color: var(--text-soft);
}

.outline-panel__versions {
  display: grid;
  gap: 12px;
}

.outline-panel__version {
  display: grid;
  grid-template-columns: 42px 82px 1fr;
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
}

.outline-panel__version small {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-soft);
}
</style>

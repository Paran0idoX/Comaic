<script setup lang="ts">
import { Check, Clock } from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatLocalDateTime } from '@/utils/datetime'

export type OutlineCharacterItem = {
  id: number
  outline_version_id: number
  character_key: string
  name: string
  role: string
  background: string
  appearance: string
  visual_anchors: string
  negative_constraints: string
  default_hairstyle: string
  default_clothing: string
  default_accessories: string
  default_color_palette: string
  created_at: string
  updated_at: string
}

export type OutlineVersionItem = {
  version_id: number
  version_no: number
  outline: string
  status: string
  created_at: string
  confirmed_at: string | null
  characters: OutlineCharacterItem[]
}

const props = defineProps<{
  outline: string
  versions: OutlineVersionItem[]
  loading: boolean
  confirming: boolean
}>()

const emit = defineEmits<{
  confirm: []
}>()

const { locale, t } = useI18n()

// 大纲由 LLM 生成，可能包含 Markdown；关闭 html 解析，避免把模型文本当成真实 HTML 执行。
const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const renderedOutline = computed(() => markdown.render(props.outline))
const currentVersion = computed(() => props.versions[0] ?? null)
const currentCharacters = computed(() => currentVersion.value?.characters ?? [])
const isConfirmed = computed(() => Boolean(currentVersion.value?.confirmed_at))

const formatDate = (value: string) => {
  return formatLocalDateTime(value, locale.value)
}
</script>

<template>
  <section v-loading="loading" class="outline-panel panel">
    <header class="outline-panel__header">
      <div>
        <h3>{{ t('outline.panel.title') }}</h3>
        <p>{{ t('outline.panel.description') }}</p>
      </div>
      <el-button
        type="success"
        :icon="Check"
        :loading="confirming"
        :disabled="!outline || isConfirmed"
        @click="emit('confirm')"
      >
        {{ isConfirmed ? t('outline.panel.confirmed') : t('outline.panel.confirm') }}
      </el-button>
    </header>

    <div class="outline-panel__content">
      <el-empty v-if="!outline" :description="t('outline.panel.empty')" />
      <el-scrollbar v-else class="outline-panel__outline-scroll" always>
        <article class="outline-panel__outline markdown-body" v-html="renderedOutline" />
      </el-scrollbar>

      <el-divider />

      <div class="outline-panel__characters">
        <h4>{{ t('outline.characters.title') }}</h4>
        <p>{{ t('outline.characters.description') }}</p>
        <el-empty
          v-if="currentCharacters.length === 0"
          :description="t('outline.characters.empty')"
        />
        <div v-else class="outline-panel__character-grid">
          <article
            v-for="character in currentCharacters"
            :key="character.id"
            class="outline-panel__character"
          >
            <header>
              <strong>{{ character.name }}</strong>
              <el-tag size="small" effect="plain">{{ character.character_key }}</el-tag>
            </header>
            <p><span>{{ t('outline.characters.role') }}</span>{{ character.role || '-' }}</p>
            <p><span>{{ t('outline.characters.background') }}</span>{{ character.background || '-' }}</p>
            <p><span>{{ t('outline.characters.appearance') }}</span>{{ character.appearance || '-' }}</p>
            <p><span>{{ t('outline.characters.defaults') }}</span>{{ [
              character.default_hairstyle,
              character.default_clothing,
              character.default_accessories,
              character.default_color_palette,
            ].filter(Boolean).join(' / ') || '-' }}</p>
            <p><span>{{ t('outline.characters.anchors') }}</span>{{ character.visual_anchors || '-' }}</p>
          </article>
        </div>
      </div>

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

.outline-panel__characters {
  display: grid;
  gap: 12px;
}

.outline-panel__characters h4,
.outline-panel__characters p {
  margin: 0;
}

.outline-panel__characters > p {
  color: var(--text-soft);
}

.outline-panel__character-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.outline-panel__character {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fafc;
}

.outline-panel__character header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.outline-panel__character p {
  color: var(--text-regular);
  line-height: 1.55;
}

.outline-panel__character span {
  display: block;
  margin-bottom: 2px;
  color: var(--text-soft);
  font-size: 12px;
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

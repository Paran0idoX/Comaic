<script setup lang="ts">
import { Check, Clock } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

export type OutlineVersionItem = {
  version_id: number
  version_no: number
  outline: string
  status: string
  created_at: string
}

defineProps<{
  outline: string
  versions: OutlineVersionItem[]
  loading: boolean
}>()

const { locale, t } = useI18n()

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
      <article v-else class="outline-panel__outline">{{ outline }}</article>

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

.outline-panel__outline {
  margin: 0;
  color: var(--text-regular);
  line-height: 1.8;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
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

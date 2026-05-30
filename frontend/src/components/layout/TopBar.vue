<script setup lang="ts">
import { Bell, Setting } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { setLocale, type SupportedLocale } from '@/i18n'

defineProps<{
  title: string
}>()

const { locale, t } = useI18n()

const currentLocale = computed({
  get: () => locale.value as SupportedLocale,
  set: (value: SupportedLocale) => setLocale(value),
})
</script>

<template>
  <header class="top-bar">
    <div>
      <p class="top-bar__eyebrow">{{ t('app.preview') }}</p>
      <h2>{{ title }}</h2>
    </div>

    <div class="top-bar__actions">
      <el-select v-model="currentLocale" class="top-bar__locale" size="small" aria-label="Language">
        <el-option :label="t('language.zh')" value="zh" />
        <el-option :label="t('language.en')" value="en" />
      </el-select>
      <el-tag effect="plain" type="success">{{ t('app.env') }}</el-tag>
      <el-button :icon="Bell" circle :aria-label="t('app.notifications')" />
      <el-button :icon="Setting" circle :aria-label="t('app.settings')" />
    </div>
  </header>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  gap: 18px;
  padding: 0 28px;
}

.top-bar h2,
.top-bar__eyebrow {
  margin: 0;
}

.top-bar h2 {
  margin-top: 4px;
  font-size: 18px;
}

.top-bar__eyebrow {
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 700;
}

.top-bar__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.top-bar__locale {
  width: 112px;
}
</style>

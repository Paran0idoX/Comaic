<script setup lang="ts">
import { Bell, Setting } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { setLocale, type SupportedLocale } from '@/i18n'

defineProps<{
  title: string
}>()

const { locale, t } = useI18n()
const router = useRouter()

const currentLocale = computed({
  get: () => locale.value as SupportedLocale,
  set: (value: SupportedLocale) => setLocale(value),
})
</script>

<template>
  <header class="top-bar">
    <div>
      <h2>{{ title }}</h2>
    </div>

    <div class="top-bar__actions">
      <el-select v-model="currentLocale" class="top-bar__locale" size="small" aria-label="Language">
        <el-option :label="t('language.zh')" value="zh" />
        <el-option :label="t('language.en')" value="en" />
      </el-select>
      <el-tag effect="plain" type="success">{{ t('app.env') }}</el-tag>
      <el-button :icon="Bell" circle :aria-label="t('app.notifications')" />
      <el-button
        :icon="Setting"
        circle
        :aria-label="t('app.settings')"
        @click="router.push('/settings')"
      />
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

.top-bar h2 {
  margin: 0;
  font-size: 18px;
  color: #101828;
}

.top-bar__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.top-bar__locale {
  width: 112px;
}

.top-bar :deep(.el-button.is-circle) {
  border-color: rgba(85, 120, 255, 0.18);
  background: rgba(255, 255, 255, 0.72);
  color: #475467;
}

.top-bar :deep(.el-button.is-circle:hover) {
  border-color: rgba(23, 109, 255, 0.38);
  color: var(--brand);
  box-shadow: 0 8px 20px rgba(23, 109, 255, 0.12);
}

.top-bar :deep(.el-tag) {
  border-color: rgba(25, 169, 116, 0.3);
  background: rgba(25, 169, 116, 0.08);
}
</style>

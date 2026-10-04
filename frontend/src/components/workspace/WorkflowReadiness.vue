<script setup lang="ts">
import { ArrowRight, Check, Clock, Warning } from '@element-plus/icons-vue'
import type { RouteLocationRaw } from 'vue-router'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import InfoTip from '@/components/workspace/InfoTip.vue'

export type ReadinessItem = {
  key: string
  label: string
  detail: string
  status: 'ready' | 'pending' | 'blocked' | 'info' | 'notStarted' | 'notRequired'
  to?: RouteLocationRaw
  actionLabel?: string
}

defineProps<{
  title: string
  description: string
  items: ReadinessItem[]
}>()

const router = useRouter()
const { t } = useI18n()
const statusKey = (status: ReadinessItem['status']) => {
  if (status === 'ready') return 'ux.ready'
  if (status === 'notStarted') return 'ux.notStarted'
  if (status === 'notRequired') return 'ux.notRequired'
  return 'ux.pending'
}

const iconFor = (status: ReadinessItem['status']) => {
  if (status === 'ready') return Check
  if (status === 'blocked') return Warning
  return Clock
}
</script>

<template>
  <section class="workflow-readiness panel" aria-live="polite">
    <header class="workflow-readiness__header">
      <div class="title-with-info">
        <h2>{{ title }}</h2>
        <InfoTip :content="description" :label="title" />
      </div>
    </header>
    <div class="workflow-readiness__items" :class="{ 'workflow-readiness__items--balanced': items.length === 4 }">
      <article
        v-for="item in items"
        :key="item.key"
        class="workflow-readiness__item"
        :class="`workflow-readiness__item--${item.status}`"
      >
        <el-icon class="workflow-readiness__icon"><component :is="iconFor(item.status)" /></el-icon>
        <div class="workflow-readiness__copy">
          <strong>{{ item.label }}</strong>
          <span>{{ item.detail || t(statusKey(item.status)) }}</span>
        </div>
        <el-button
          v-if="item.to && item.actionLabel"
          link
          type="primary"
          :icon="ArrowRight"
          @click="router.push(item.to)"
        >
          {{ item.actionLabel }}
        </el-button>
      </article>
    </div>
  </section>
</template>

<style scoped>
.workflow-readiness.panel {
  container-type: inline-size;
  padding: 0;
  overflow: hidden;
}

.workflow-readiness__header {
  padding: 16px 18px 12px;
}

.workflow-readiness__header h2,
.workflow-readiness__header p {
  margin: 0;
}

.workflow-readiness__header h2 {
  font-size: 17px;
}

.workflow-readiness__header p {
  margin-top: 5px;
  color: var(--text-soft);
  font-size: 13px;
}

.workflow-readiness__items {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 210px), 1fr));
  gap: 1px;
  border-top: 1px solid var(--panel-border);
  background: var(--panel-border);
}

.workflow-readiness__items--balanced { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.workflow-readiness__item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 14px 16px;
  background: #fff;
}

@container (max-width: 900px) {
  .workflow-readiness__items--balanced { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@container (max-width: 440px) {
  .workflow-readiness__items { grid-template-columns: minmax(0, 1fr); }
}

.workflow-readiness__item .el-button {
  grid-column: 2;
  justify-self: start;
  padding: 0;
}

.workflow-readiness__icon {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(23, 109, 255, 0.1);
  color: var(--brand);
}

.workflow-readiness__item--ready .workflow-readiness__icon {
  background: rgba(25, 169, 116, 0.12);
  color: var(--success);
}

.workflow-readiness__item--blocked .workflow-readiness__icon {
  background: rgba(245, 108, 108, 0.12);
  color: var(--el-color-danger);
}

.workflow-readiness__copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.workflow-readiness__copy strong,
.workflow-readiness__copy span {
  overflow: hidden;
  text-overflow: ellipsis;
}
.workflow-readiness__status { color: var(--text-soft); font-size: 11px; }
.workflow-readiness__item--ready .workflow-readiness__status { color: var(--success); }
.workflow-readiness__item--notStarted .workflow-readiness__icon,
.workflow-readiness__item--notRequired .workflow-readiness__icon {
  background: #f2f4f7; color: #667085;
}

.workflow-readiness__copy strong {
  color: var(--text-strong);
  font-size: 13px;
  white-space: nowrap;
}

.workflow-readiness__copy span {
  display: -webkit-box;
  color: var(--text-soft);
  font-size: 12px;
  line-height: 1.4;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
</style>

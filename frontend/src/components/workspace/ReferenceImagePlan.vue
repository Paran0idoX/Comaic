<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

type Reference = { order?: number; label?: string; asset_id?: number; id?: number; role?: string; purpose?: string; reason?: string; reason_code?: string; reason_params?: Record<string, string | number>; owner?: { category?: string; key?: string; name?: string } }
type Plan = { order_known?: boolean; capacity?: number; items?: Reference[]; omitted?: Reference[]; fallbacks?: Reference[] }
const props = defineProps<{ plan: unknown; actual?: boolean }>()
const { t, te } = useI18n()
const value = computed<Plan>(() => props.plan && typeof props.plan === 'object' ? props.plan as Plan : {})
const source = (item: Reference) => `/api/visual-bible/assets/${item.asset_id ?? item.id}/file`
const reason = (item: Reference) => {
  const key = `referenceInputs.${item.reason_code?.split('.').pop()}`
  return item.reason_code && te(key) ? t(key, item.reason_params ?? {}) : item.reason ?? ''
}
</script>

<template>
  <section class="reference-plan">
    <h3>{{ t(actual ? 'referenceInputs.actual' : 'referenceInputs.planned') }}</h3>
    <el-alert v-if="actual && value.order_known !== true" type="info" :closable="false" :title="t('referenceInputs.historical')" />
    <template v-else>
      <p v-if="actual && value.capacity !== undefined">{{ t('referenceInputs.capacity', { count: value.capacity }) }}</p>
      <div v-if="value.items?.length" class="reference-grid">
        <article v-for="(item, index) in value.items" :key="`${item.asset_id ?? item.id}-${index}`" class="reference-item">
          <el-image v-if="item.asset_id || item.id" :src="source(item)" :preview-src-list="[source(item)]" preview-teleported fit="contain" lazy>
            <template #error><span>{{ t('referenceInputs.file_unavailable') }}</span></template>
          </el-image>
          <div>
            <el-tag size="small">{{ t('referenceInputs.order', { order: item.order ?? index + 1 }) }}</el-tag>
            <strong>{{ item.owner?.name || item.owner?.key }}</strong>
            <p>{{ t(`referenceInputs.${item.purpose || 'identity'}`) }}<template v-if="item.role"> · {{ t(`visualBible.roleLabels.${item.role}`) }}</template></p>
            <p>{{ reason(item) }}</p>
          </div>
        </article>
      </div>
      <p v-else class="reference-empty">{{ t(actual ? 'referenceInputs.actualEmpty' : 'referenceInputs.empty') }}</p>
      <div v-if="value.omitted?.length" class="reference-notes">
        <h4>{{ t('referenceInputs.omitted') }}</h4>
        <p v-for="(item, index) in value.omitted" :key="index">{{ item.owner?.name || item.owner?.key }} · {{ reason(item) }}</p>
      </div>
      <div v-if="value.fallbacks?.length" class="reference-notes">
        <h4>{{ t('referenceInputs.fallbacks') }}</h4>
        <p v-for="(item, index) in value.fallbacks" :key="index">{{ item.owner?.name || item.owner?.key }} · {{ reason(item) }}</p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.reference-plan { margin: 16px 0; padding: 0 20px; }
.reference-plan h3 { margin: 0 0 12px; font-size: 15px; }
.reference-empty { margin: 0; color: var(--text-soft); font-size: 13px; }
.reference-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.reference-item { display: flex; gap: 12px; padding: 12px; border: 1px solid var(--el-border-color-light); border-radius: 8px; min-width: 0; }
.reference-item .el-image { width: 88px; height: 112px; flex-shrink: 0; background: var(--el-fill-color-light); }
.reference-item strong { display: block; margin-top: 6px; }
.reference-item p { font-size: 13px; line-height: 1.5; margin: 6px 0; overflow-wrap: anywhere; }
.reference-notes { color: var(--el-text-color-secondary); font-size: 13px; }
@media (max-width: 600px) { .reference-grid { grid-template-columns: 1fr; } }
</style>

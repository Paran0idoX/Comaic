<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { OutfitVariant, SceneVisualVersion, StyleProfile } from '@/api/visualBible'

const props = defineProps<{
  kind: 'outfit' | 'scene' | 'style'
  value: OutfitVariant | SceneVisualVersion | StyleProfile
}>()
const { t } = useI18n()

// 审核前展示完整设定；结构化内容按文本渲染，模型输出不会作为 HTML 执行。
const fields = computed(() => {
  if (props.kind === 'outfit') {
    const item = props.value as OutfitVariant
    return [
      ['garments', item.garment_components], ['layerOrder', item.layer_order],
      ['colors', item.colors], ['materials', item.materials], ['patterns', item.patterns],
      ['accessories', item.accessories], ['triggerTokens', item.trigger_tokens],
      ['negativeConstraints', item.negative_constraints],
    ]
  }
  if (props.kind === 'scene') {
    const item = props.value as SceneVisualVersion
    return [
      ['landmarks', item.landmarks], ['spatialRelations', item.spatial_relations],
      ['cameraPresets', item.camera_presets], ['objectStates', item.object_states],
      ['colorPalette', item.color_palette], ['lightingState', item.lighting_state],
    ]
  }
  const item = props.value as StyleProfile
  return [
    ['positiveTag', item.positive_tag], ['negativeTag', item.negative_tag],
    ['positiveNaturalLanguage', item.positive_natural_language],
    ['negativeNaturalLanguage', item.negative_natural_language],
    ['colorPalette', item.color_palette], ['lighting', item.lighting],
  ]
})

const formatValue = (value: unknown): string => {
  if (Array.isArray(value)) return value.map(formatValue).filter(Boolean).join('\n')
  if (value && typeof value === 'object') {
    return Object.entries(value).map(([key, item]) => `${key}: ${formatValue(item)}`).join('\n')
  }
  return value === null || value === undefined ? '' : String(value)
}
</script>

<template>
  <dl class="setting-details">
    <div v-for="[field, content] in fields" :key="String(field)">
      <dt>{{ t(`visualBible.details.${field}`) }}</dt>
      <dd>{{ formatValue(content) || t('visualBible.details.empty') }}</dd>
    </div>
  </dl>
</template>

<style scoped>
.setting-details { display: grid; gap: 16px; margin: 20px 0; }
.setting-details > div { border-bottom: 1px solid var(--panel-border); padding-bottom: 14px; }
.setting-details dt { color: var(--text-soft); font-size: 13px; margin-bottom: 7px; }
.setting-details dd { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
</style>

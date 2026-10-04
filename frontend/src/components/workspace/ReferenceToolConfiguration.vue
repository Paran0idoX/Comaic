<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps<{ modelValue: string; provider: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const { t } = useI18n()
const value = computed(() => {
  try { return JSON.parse(props.modelValue).reference_images ?? {} } catch { return {} }
})
const update = (key: string, next: unknown) => {
  try {
    const payload = JSON.parse(props.modelValue)
    payload.reference_images = { max_images: 0, label_format: 'image_N', requires_canvas: false, transport: 'none', edit_endpoint_path: '/images/edits', image_field_name: 'image[]', ...payload.reference_images, [key]: next }
    if (payload.reference_images.max_images > 0) payload.features = [...new Set([...(payload.features ?? ['txt2img']), 'reference_image'])]
    emit('update:modelValue', JSON.stringify(payload, null, 2))
  } catch { /* 原JSON语法错误留给现有校验提示，不覆盖用户输入。 */ }
}
</script>

<template>
  <el-collapse class="reference-tool">
    <el-collapse-item name="references">
      <template #title><span class="field-with-info">{{ t('toolReference.title') }}<InfoTip :content="t('toolReference.helpTransport')" :label="t('toolReference.title')" /></span></template>
      <div class="reference-tool-grid">
        <el-form-item :label="t('toolReference.maxImages')"><el-input-number :model-value="value.max_images ?? 0" :min="0" :max="100" @update:model-value="update('max_images', $event)" /></el-form-item>
        <el-form-item :label="t('toolReference.labelFormat')">
          <el-select :model-value="value.label_format ?? 'image_N'" @update:model-value="update('label_format', $event)">
            <el-option label="image N" value="image_N" /><el-option label="Picture N" value="picture_N" /><el-option label="[N]" value="bracket_N" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('toolReference.requiresCanvas')"><el-switch :model-value="value.requires_canvas ?? false" @update:model-value="update('requires_canvas', $event)" /></el-form-item>
        <template v-if="provider === 'openai_images_compatible'">
          <el-form-item :label="t('toolReference.transport')">
            <el-select :model-value="value.transport ?? 'none'" @update:model-value="update('transport', $event)">
              <el-option :label="t('referenceInputs.empty')" value="none" /><el-option label="multipart" value="multipart" /><el-option label="JSON data URL" value="json_data_url" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('toolReference.editEndpoint')"><el-input :model-value="value.edit_endpoint_path ?? '/images/edits'" @update:model-value="update('edit_endpoint_path', $event)" /></el-form-item>
          <el-form-item :label="t('toolReference.imageField')"><el-input :model-value="value.image_field_name ?? 'image[]'" @update:model-value="update('image_field_name', $event)" /></el-form-item>
        </template>
      </div>
      <p v-if="provider === 'comfyui'" class="title-with-info">{{ t('toolReference.slots') }}<InfoTip :content="t('toolReference.helpSlots')" :label="t('toolReference.slots')" /></p>
    </el-collapse-item>
  </el-collapse>
</template>

<style scoped>
.reference-tool { margin: 16px 0; }
.reference-tool-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 600px) { .reference-tool-grid { grid-template-columns: 1fr; } }
</style>

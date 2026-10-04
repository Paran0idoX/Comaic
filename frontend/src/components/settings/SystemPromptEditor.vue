<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { RefreshLeft, Check, Document } from '@element-plus/icons-vue'
import { apiErrorMessage } from '@/api/errors'
import { updateModelSystemPrompt, updateSystemPrompt, type SystemPrompt } from '@/api/settings'

const props = defineProps<{
  nodeId: string; item: SystemPrompt; title: string; path: string[]; configId?: number; draft: string; saving: boolean
}>()
const emit = defineEmits<{
  change: [value: { nodeId: string; value: string }]
  saved: [value: { nodeId: string; item: SystemPrompt }]
  busy: [value: { nodeId: string; busy: boolean }]
}>()
const { t } = useI18n()
const mode = ref('edit')
const dirty = computed(() => props.draft !== props.item.content)
const text = computed({
  get: () => props.draft,
  set: value => emit('change', { nodeId: props.nodeId, value }),
})
const save = async (content: string | null) => {
  // 保存目标在请求前固定；切换节点后，旧响应也只更新原节点与草稿。
  const target = { nodeId: props.nodeId, key: props.item.key, configId: props.configId }
  emit('busy', { nodeId: target.nodeId, busy: true })
  try {
    const item = target.configId === undefined
      ? await updateSystemPrompt(target.key, content)
      : await updateModelSystemPrompt(target.configId, target.key, content)
    emit('saved', { nodeId: target.nodeId, item })
    ElMessage.success(t('systemPrompts.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('systemPrompts.saveFailed')))
  } finally {
    emit('busy', { nodeId: target.nodeId, busy: false })
  }
}
</script>

<template>
  <div class="prompt-editor">
    <header class="prompt-editor__heading">
      <div class="prompt-editor__breadcrumb">{{ path.join(' / ') }}</div>
      <div class="prompt-editor__title-row">
        <h3>{{ title }}</h3>
        <span class="prompt-editor__status" :class="{ 'prompt-editor__status--custom': item.is_overridden }">
          {{ t(item.is_overridden ? 'systemPrompts.custom' : 'systemPrompts.default') }}
        </span>
        <span v-if="dirty" class="prompt-editor__unsaved">{{ t('systemPrompts.unsaved') }}</span>
      </div>
    </header>
    <div class="prompt-editor__workspace">
      <div class="prompt-editor__toolbar">
        <div class="prompt-editor__tabs" role="tablist">
          <button type="button" role="tab" :aria-selected="mode === 'edit'" :class="{ active: mode === 'edit' }" @click="mode = 'edit'">{{ t('systemPrompts.edit') }}</button>
          <button type="button" role="tab" :aria-selected="mode === 'default'" :class="{ active: mode === 'default' }" @click="mode = 'default'">{{ t('systemPrompts.viewDefault') }}</button>
        </div>
        <span class="prompt-editor__length">{{ t('systemPrompts.characters', { count: mode === 'edit' ? draft.length : item.default_content.length }) }}</span>
      </div>
      <el-input v-if="mode === 'edit'" v-model="text" type="textarea" :disabled="saving" :maxlength="200000"
        :aria-label="title" class="prompt-editor__text" :spellcheck="false" />
      <pre v-else class="prompt-editor__default">{{ item.default_content || t('systemPrompts.emptyDefault') }}</pre>
    </div>
    <div class="prompt-editor__metadata">
      <el-icon><Document /></el-icon>
      <span v-if="item.default_files.length" :title="item.default_files.join(', ')">{{ item.default_files.join(' · ') }}</span>
      <span v-else>{{ t('systemPrompts.emptyDefault') }}</span>
    </div>
    <footer class="prompt-editor__footer">
      <p>{{ t(configId === undefined ? 'systemPrompts.appliesNew' : 'systemPrompts.emptyHint') }}</p>
      <div class="prompt-editor__actions">
        <el-button text :icon="RefreshLeft" :disabled="saving || !item.is_overridden" @click="save(null)">{{ t('systemPrompts.restore') }}</el-button>
        <el-button v-if="dirty" text :disabled="saving" @click="text = item.content">{{ t('systemPrompts.discard') }}</el-button>
        <el-button type="primary" :icon="Check" :loading="saving"
          :disabled="mode !== 'edit' || !dirty || (configId === undefined && !draft.trim())" @click="save(draft)">{{ t('systemPrompts.save') }}</el-button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.prompt-editor { display: flex; flex-direction: column; min-width: 0; min-height: 0; padding: 24px; background: #fff; }
.prompt-editor__heading { margin-bottom: 20px; }
.prompt-editor__breadcrumb { color: #949eaf; font-size: 11px; line-height: 1.5; margin-bottom: 7px; }
.prompt-editor__title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; }
h3 { margin: 0; font-size: 18px; line-height: 1.5; font-weight: 650; overflow-wrap: anywhere; }
.prompt-editor__status { color: #8792a4; background: #f4f6f9; padding: 3px 7px; border-radius: 5px; font-size: 11px; }
.prompt-editor__status--custom { color: #4676bf; background: #edf4ff; }
.prompt-editor__unsaved { color: #b9842b; font-size: 11px; }
.prompt-editor__workspace { flex: 1; display: flex; flex-direction: column; min-height: 0; border: 1px solid #e6eaf1; border-radius: 8px; overflow: hidden; background: #fcfdff; }
.prompt-editor__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 14px; min-height: 43px; border-bottom: 1px solid #e9edf4; background: #f8fafd; }
.prompt-editor__tabs { display: flex; align-self: stretch; gap: 18px; }
.prompt-editor__tabs button { position: relative; border: 0; padding: 0 1px; background: transparent; color: #8994a6; font-size: 12px; cursor: pointer; white-space: nowrap; }
.prompt-editor__tabs button.active { color: #316ad1; font-weight: 600; }
.prompt-editor__tabs button.active::after { content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 2px; background: #4d83e4; border-radius: 2px; }
.prompt-editor__length { color: #9aa4b4; font-size: 11px; white-space: nowrap; }
.prompt-editor__text { flex: 1; min-height: 0; }
.prompt-editor__text :deep(textarea) { height: 100%; resize: none; border: none; box-shadow: none !important; padding: 18px 20px; background: #fcfdff; color: #43526a; font: 12px/1.9 ui-monospace, SFMono-Regular, Consolas, monospace; border-radius: 0; }
.prompt-editor__text :deep(textarea:focus) { outline: none; }
.prompt-editor__workspace:focus-within { border-color: #a8c2ee; }
.prompt-editor__default { flex: 1; min-height: 0; margin: 0; padding: 18px 20px; white-space: pre-wrap; overflow-wrap: anywhere; overflow: auto; color: #607086; font: 12px/1.9 ui-monospace, SFMono-Regular, Consolas, monospace; }
.prompt-editor__metadata { display: flex; align-items: center; gap: 6px; margin-top: 12px; min-width: 0; color: #9ca5b4; font-size: 10px; }
.prompt-editor__metadata span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-editor__metadata .el-icon { flex-shrink: 0; }
.prompt-editor__footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding-top: 20px; margin-top: 16px; border-top: 1px solid #edf0f5; }
.prompt-editor__footer p { font-size: 11px; line-height: 1.6; color: #929dad; margin: 0; }
.prompt-editor__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.prompt-editor__actions .el-button { margin-left: 0; font-size: 12px; border-radius: 6px; }
@media (max-width: 760px) {
  .prompt-editor { padding: 18px 16px; min-height: 570px; }
  .prompt-editor__toolbar { padding: 0 10px; gap: 8px; }
  .prompt-editor__tabs { gap: 12px; }
  .prompt-editor__text :deep(textarea), .prompt-editor__default { padding: 14px; }
  .prompt-editor__actions { margin-left: 0; }
}
</style>

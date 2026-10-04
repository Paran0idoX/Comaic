<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { apiErrorMessage } from '@/api/errors'
import { updateVisualProfile, type VisualProfile } from '@/api/referenceImages'

const props = defineProps<{ profiles: VisualProfile[]; disabled?: boolean; confirmReplacement: () => Promise<boolean> }>()
const emit = defineEmits<{ updated: [profiles: VisualProfile[]]; dirty: [value: boolean]; busy: [value: boolean] }>()
const { t } = useI18n()
const drafts = ref<VisualProfile[]>([])
const baseline = ref('')
const saving = ref(false)
const dirty = computed(() => JSON.stringify(drafts.value) !== baseline.value)
const views = ['identity_face', 'identity_full_body', 'identity_side', 'identity_back', 'scene_master', 'prop_reference']
const sourceLabel = (field: string) => t(`referenceLibrary.visual.sources.${field}`)
const reset = () => { drafts.value = JSON.parse(JSON.stringify(props.profiles)); baseline.value = JSON.stringify(drafts.value) }
watch(() => props.profiles, reset, { immediate: true })
watch(dirty, value => emit('dirty', value))
const save = async () => {
  if (saving.value || props.disabled || !dirty.value || !await props.confirmReplacement()) return
  saving.value = true; emit('busy', true)
  // 逐条保存后保留成功修订；遇到冲突不会再次使用过期修订提交。
  try {
    for (let index = 0; index < drafts.value.length; index++) {
      const profile = drafts.value[index]!
      if (JSON.stringify(profile) === JSON.stringify(props.profiles[index])) continue
      drafts.value[index] = await updateVisualProfile(profile)
    }
    baseline.value = JSON.stringify(drafts.value)
    emit('updated', JSON.parse(baseline.value))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.visual.saveFailed'))) }
  finally { saving.value = false; emit('busy', false) }
}
</script>

<template>
  <el-collapse v-if="profiles.length" class="visual-profile-editor">
    <el-collapse-item name="visual-summary">
      <template #title><span class="field-with-info">{{ t('referenceLibrary.visual.title') }}<InfoTip :content="t('referenceLibrary.visual.help')" :label="t('referenceLibrary.visual.title')" /></span></template>
      <section v-for="profile in drafts" :key="profile.id" class="visual-profile">
        <strong>{{ t(`referenceLibrary.visual.kinds.${profile.kind}`) }} · {{ t('referenceLibrary.visual.revision', { revision: profile.revision }) }}</strong>
        <div v-for="(fact, index) in profile.data.facts" :key="index" class="visual-fact">
          <div class="visual-fact-heading"><span>{{ fact.attribute }}<span v-if="fact.must_keep"> · {{ t('referenceLibrary.visual.mustKeep') }}</span></span>
            <el-select v-model="fact.polarity" :disabled="disabled || saving" :aria-label="t('referenceLibrary.visual.polarity')">
              <el-option value="required" :label="t('referenceLibrary.visual.required')" /><el-option value="forbidden" :label="t('referenceLibrary.visual.forbidden')" />
            </el-select><el-button link type="danger" :disabled="disabled || saving" @click="profile.data.facts.splice(index, 1)">{{ t('referenceLibrary.visual.remove') }}</el-button>
          </div>
          <p class="visual-source">{{ sourceLabel(fact.source_field) }}：{{ fact.source_excerpt }}</p>
          <el-select v-if="fact.options.length > 1" v-model="fact.selected" :disabled="disabled || saving" :aria-label="t('referenceLibrary.visual.choice')">
            <el-option v-for="(option, optionIndex) in fact.options" :key="optionIndex" :value="optionIndex" :label="option.natural" />
          </el-select>
          <p v-if="fact.options.length > 1" class="visual-help">{{ t('referenceLibrary.visual.defaultChoice', { value: fact.options[fact.default_index]?.natural }) }}</p>
          <span class="visual-help">{{ t('referenceLibrary.visual.description') }}</span>
          <el-input v-model="fact.options[fact.selected]!.natural" type="textarea" :rows="2" :disabled="disabled || saving" :aria-label="t('referenceLibrary.visual.description')" />
          <span class="visual-help">{{ t('referenceLibrary.visual.tags') }}</span>
          <el-input :model-value="fact.options[fact.selected]!.tags.join(', ')" :disabled="disabled || saving" :aria-label="t('referenceLibrary.visual.tags')"
            @update:model-value="(value: string) => fact.options[fact.selected]!.tags = value.split(',').map((tag: string) => tag.trim()).filter(Boolean)" />
          <el-select v-model="fact.views" multiple :disabled="disabled || saving" :aria-label="t('referenceLibrary.visual.views')">
            <el-option v-for="view in views.filter(view => profile.kind === 'character' || profile.kind === 'outfit' ? view.startsWith('identity_') : view === (profile.kind === 'prop_subject' ? 'prop_reference' : 'scene_master'))" :key="view" :value="view" :label="t(`visualBible.roleLabels.${view}`)" />
          </el-select>
        </div>
      </section>
      <div class="visual-actions"><el-button :disabled="!dirty || disabled || saving" @click="reset">{{ t('referenceLibrary.visual.reset') }}</el-button>
        <el-button type="primary" :disabled="!dirty || disabled" :loading="saving" @click="save">{{ t('referenceLibrary.visual.save') }}</el-button></div>
      <p v-if="dirty" class="visual-help">{{ t('referenceLibrary.visual.unsaved') }}</p>
    </el-collapse-item>
  </el-collapse>
</template>

<style scoped>
.visual-profile-editor { margin: 14px 0; }
.visual-help, .visual-source { font-size: 13px; line-height: 1.6; color: var(--text-soft); overflow-wrap: anywhere; }
.visual-profile { margin: 12px 0; }
.visual-fact { padding: 12px; margin: 10px 0; border: 1px solid var(--panel-border); border-radius: 6px; display: grid; gap: 8px; }
.visual-fact-heading { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.visual-fact-heading .el-select { width: 140px; }
.visual-source, .visual-help { margin: 0 0 8px; }
.visual-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>

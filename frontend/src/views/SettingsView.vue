<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Connection,
  Delete,
  InfoFilled,
  MoreFilled,
  Plus,
  RefreshRight,
  Select,
  Star,
} from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { apiErrorMessage } from '@/api/errors'
import {
  getConsistencySettings,
  updateConsistencySettings,
  type ConsistencyRuntimeReadiness,
  type ConsistencyThresholds,
} from '@/api/consistencyEvaluation'
import {
  activateLLMConfig,
  createLLMConfig,
  deleteLLMConfig,
  getAppSettings,
  listLLMConfigs,
  listLLMProviders,
  testLLMConfig,
  updateAppSettings,
  updateLLMConfig,
  type LLMConfig,
  type LLMProvider,
  type LLMProviderOption,
} from '@/api/settings'
import { formatLocalDateTime } from '@/utils/datetime'
import ImageToolManager from '@/components/settings/ImageToolManager.vue'
import SystemPromptManager from '@/components/settings/SystemPromptManager.vue'

const { locale, t } = useI18n()
const route = useRoute()

const loading = ref(false)
const saving = ref(false)
const savingAppSettings = ref(false)
const loadingConsistencySettings = ref(false)
const savingConsistencySettings = ref(false)
const testing = ref(false)
const activating = ref(false)
const deleting = ref(false)
const configs = ref<LLMConfig[]>([])
const providerOptions = ref<LLMProviderOption[]>([])
const activeConfigId = ref<number | null>(null)
const selectedConfigId = ref<number | null>(null)
const isCreating = ref(false)
const modelDraft = ref('')
const providerManuallySelected = ref(false)
const activeSettingsTab = ref<'general' | 'api' | 'image-tools' | 'prompts'>(
  ['general', 'api', 'image-tools', 'prompts'].includes(String(route.query.tab))
    ? String(route.query.tab) as 'general' | 'api' | 'image-tools' | 'prompts' : 'general',
)
watch(() => route.query.tab, (tab) => {
  if (tab === 'general' || tab === 'api' || tab === 'image-tools' || tab === 'prompts') activeSettingsTab.value = tab
})
const consistencyAdvancedSections = ref<string[]>([])
const appSettings = reactive({
  script_section_max_concurrency: 3,
})
const recommendedConsistencyThresholds: ConsistencyThresholds = {
  cids_cross_min: 0.45,
  cids_self_min: 0.6,
  csd_cross_min: 0.35,
  csd_self_min: 0.6,
  occm_min: 70,
  copy_paste_max: 0.3,
}
const consistencySettings = reactive<ConsistencyThresholds>({
  ...recommendedConsistencyThresholds,
})
const consistencyRuntime = ref<ConsistencyRuntimeReadiness | null>(null)
const consistencyMetricVersion = ref('')

const form = reactive({
  name: '',
  provider: 'openai_compatible' as LLMProvider,
  base_url: '',
  api_key: '',
  clear_api_key: false,
  model_names: [] as string[],
  default_model: '',
})

const selectedConfig = computed(
  () => configs.value.find((config) => config.id === selectedConfigId.value) ?? null,
)
const selectedProviderOption = computed(
  () => providerOptions.value.find((option) => option.value === form.provider) ?? null,
)
const selectedProviderRequiresBaseUrl = computed(
  () => selectedProviderOption.value?.requires_base_url ?? form.provider === 'openai_compatible',
)

const providerLabel = (provider: LLMProvider) => {
  return providerOptions.value.find((option) => option.value === provider)?.label ?? provider
}

const resetForm = () => {
  form.name = ''
  form.provider = 'openai_compatible'
  form.base_url = ''
  form.api_key = ''
  form.clear_api_key = false
  form.model_names = []
  form.default_model = ''
  modelDraft.value = ''
  providerManuallySelected.value = false
}

const fillForm = (config: LLMConfig) => {
  form.name = config.name
  form.provider = config.provider
  form.base_url = config.base_url
  form.api_key = config.api_key ?? ''
  form.clear_api_key = false
  form.model_names = [...config.model_names]
  form.default_model = config.default_model
  modelDraft.value = ''
  providerManuallySelected.value = true
}

const loadConfigs = async () => {
  loading.value = true
  try {
    const [result, providers, appResult] = await Promise.all([
      listLLMConfigs(),
      listLLMProviders(),
      getAppSettings(),
    ])
    providerOptions.value = providers
    appSettings.script_section_max_concurrency = appResult.script_section_max_concurrency
    configs.value = result.items
    activeConfigId.value = result.active_config_id
    const nextSelected =
      configs.value.find((config) => config.id === selectedConfigId.value) ??
      configs.value.find((config) => config.id === result.active_config_id) ??
      configs.value[0] ??
      null
    if (nextSelected !== null) {
      selectedConfigId.value = nextSelected.id
      isCreating.value = false
      fillForm(nextSelected)
    } else {
      selectedConfigId.value = null
      isCreating.value = true
      resetForm()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.loadFailed')))
  } finally {
    loading.value = false
  }
}

const saveAppSettings = async () => {
  savingAppSettings.value = true
  try {
    const result = await updateAppSettings({
      script_section_max_concurrency: appSettings.script_section_max_concurrency,
    })
    appSettings.script_section_max_concurrency = result.script_section_max_concurrency
    ElMessage.success(t('settings.messages.appSaved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.appSaveFailed')))
  } finally {
    savingAppSettings.value = false
  }
}

const applyConsistencySettings = (
  result: ConsistencyThresholds & {
    runtime: ConsistencyRuntimeReadiness
    metric_version: string
  },
) => {
  consistencySettings.cids_cross_min = result.cids_cross_min
  consistencySettings.cids_self_min = result.cids_self_min
  consistencySettings.csd_cross_min = result.csd_cross_min
  consistencySettings.csd_self_min = result.csd_self_min
  consistencySettings.occm_min = result.occm_min
  consistencySettings.copy_paste_max = result.copy_paste_max
  consistencyRuntime.value = result.runtime
  consistencyMetricVersion.value = result.metric_version
}

const loadConsistencySettings = async () => {
  loadingConsistencySettings.value = true
  try {
    const result = await getConsistencySettings()
    applyConsistencySettings(result)
    if (!result.runtime.ready && !consistencyAdvancedSections.value.includes('runtime')) {
      consistencyAdvancedSections.value.push('runtime')
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.consistencyLoadFailed')))
  } finally {
    loadingConsistencySettings.value = false
  }
}

const applyRecommendedConsistencySettings = () => {
  Object.assign(consistencySettings, recommendedConsistencyThresholds)
  if (!consistencyAdvancedSections.value.includes('thresholds')) {
    consistencyAdvancedSections.value.push('thresholds')
  }
  ElMessage.info(t('settings.messages.consistencyDefaultsApplied'))
}

const saveConsistencySettings = async () => {
  savingConsistencySettings.value = true
  try {
    applyConsistencySettings(await updateConsistencySettings({ ...consistencySettings }))
    ElMessage.success(t('settings.messages.consistencySaved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.consistencySaveFailed')))
  } finally {
    savingConsistencySettings.value = false
  }
}

const selectConfig = (config: LLMConfig) => {
  selectedConfigId.value = config.id
  isCreating.value = false
  fillForm(config)
}

const createNewConfig = () => {
  selectedConfigId.value = null
  isCreating.value = true
  resetForm()
  form.name = t('settings.llm.newConfigName')
}

const onProviderChange = () => {
  providerManuallySelected.value = true
  if (!selectedProviderRequiresBaseUrl.value) {
    form.base_url = ''
  }
}

const maybeRecommendProvider = (modelName: string) => {
  if (!isCreating.value || providerManuallySelected.value) {
    return
  }
  const lowerModelName = modelName.toLowerCase()
  const matchedProvider = providerOptions.value.find((option) =>
    option.model_prefixes.some((prefix) => lowerModelName.startsWith(prefix.toLowerCase())),
  )
  if (matchedProvider === undefined || matchedProvider.value === form.provider) {
    return
  }
  form.provider = matchedProvider.value
  if (!matchedProvider.requires_base_url) {
    form.base_url = ''
  }
  ElMessage.info(t('settings.messages.providerRecommended', { provider: matchedProvider.label }))
}

const normalizedModels = () => {
  const seen = new Set<string>()
  const models: string[] = []
  for (const modelName of form.model_names) {
    const normalized = modelName.trim()
    if (normalized && !seen.has(normalized)) {
      models.push(normalized)
      seen.add(normalized)
    }
  }
  return models
}

const addModelName = () => {
  const normalized = modelDraft.value.trim()
  if (!normalized) {
    return
  }
  if (!form.model_names.includes(normalized)) {
    form.model_names.push(normalized)
  }
  maybeRecommendProvider(normalized)
  if (!form.default_model) {
    form.default_model = normalized
  }
  modelDraft.value = ''
}

const removeModelName = (modelName: string) => {
  form.model_names = form.model_names.filter((item) => item !== modelName)
  if (form.default_model === modelName) {
    form.default_model = form.model_names[0] ?? ''
  }
}

const saveConfig = async () => {
  saving.value = true
  try {
    const models = normalizedModels()
    const payload = {
      name: form.name.trim(),
      provider: form.provider,
      base_url: selectedProviderRequiresBaseUrl.value ? form.base_url.trim() : form.base_url.trim() || null,
      model_names: models,
      default_model: form.default_model || models[0] || null,
      api_key: form.api_key.trim() || null,
      clear_api_key: form.clear_api_key,
    }
    const saved = isCreating.value
      ? await createLLMConfig({ ...payload, is_active: configs.value.length === 0 })
      : await updateLLMConfig(selectedConfigId.value as number, payload)
    selectedConfigId.value = saved.id
    isCreating.value = false
    ElMessage.success(t('settings.messages.saved'))
    await loadConfigs()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.saveFailed')))
  } finally {
    saving.value = false
  }
}

const activateSelectedConfig = async () => {
  if (selectedConfigId.value === null) {
    return
  }
  activating.value = true
  try {
    await activateLLMConfig(selectedConfigId.value)
    ElMessage.success(t('settings.messages.activated'))
    await loadConfigs()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.activateFailed')))
  } finally {
    activating.value = false
  }
}

const deleteSelectedConfig = async () => {
  if (selectedConfigId.value === null || selectedConfig.value === null) {
    return
  }
  deleting.value = true
  try {
    await ElMessageBox.confirm(
      t('settings.messages.deleteConfirm', { name: selectedConfig.value.name }),
      t('settings.actions.delete'),
      { type: 'warning' },
    )
    await deleteLLMConfig(selectedConfigId.value)
    selectedConfigId.value = null
    ElMessage.success(t('settings.messages.deleted'))
    await loadConfigs()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(apiErrorMessage(error, t, t('settings.errors.deleteFailed')))
    }
  } finally {
    deleting.value = false
  }
}

const testConfig = async () => {
  testing.value = true
  try {
    const model = form.default_model || form.model_names[0] || ''
    await testLLMConfig({
      config_id: isCreating.value ? null : selectedConfigId.value,
      provider: form.provider,
      base_url: selectedProviderRequiresBaseUrl.value ? form.base_url.trim() : form.base_url.trim() || null,
      model,
      api_key: form.api_key.trim() || null,
      clear_api_key: form.clear_api_key,
    })
    ElMessage.success(t('settings.messages.testSucceeded'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('settings.errors.testFailed')))
  } finally {
    testing.value = false
  }
}

const formatDate = (value: string | undefined) => {
  return value ? formatLocalDateTime(value, locale.value) : '-'
}

watch(activeSettingsTab, (tab) => {
  if (tab === 'general' && consistencyRuntime.value === null && !loadingConsistencySettings.value) {
    void loadConsistencySettings()
  }
})

onMounted(() => {
  void loadConfigs()
  if (activeSettingsTab.value === 'general') void loadConsistencySettings()
})
</script>

<template>
  <section v-loading="loading" class="settings-page">
    <div class="settings-shell">
      <aside class="panel settings-nav" :aria-label="t('settings.title')">
        <button
          type="button"
          class="settings-nav__item"
          :class="{ 'settings-nav__item--active': activeSettingsTab === 'general' }"
          @click="activeSettingsTab = 'general'"
        >
          {{ t('settings.tabs.general') }}
        </button>
        <button
          type="button"
          class="settings-nav__item"
          :class="{ 'settings-nav__item--active': activeSettingsTab === 'api' }"
          @click="activeSettingsTab = 'api'"
        >
          {{ t('settings.tabs.api') }}
        </button>
        <button
          type="button"
          class="settings-nav__item"
          :class="{ 'settings-nav__item--active': activeSettingsTab === 'image-tools' }"
          @click="activeSettingsTab = 'image-tools'"
        >
          {{ t('settings.tabs.imageTools') }}
        </button>
        <button type="button" class="settings-nav__item"
          :class="{ 'settings-nav__item--active': activeSettingsTab === 'prompts' }"
          @click="activeSettingsTab = 'prompts'">{{ t('systemPrompts.title') }}</button>
      </aside>

      <div class="settings-content">
        <SystemPromptManager v-if="activeSettingsTab === 'prompts'" />
        <ImageToolManager v-if="activeSettingsTab === 'image-tools'" />
        <template v-if="activeSettingsTab === 'general'">
        <section class="panel settings-card">
          <header class="panel-header">
            <div>
              <div class="title-with-info"><h2>{{ t('settings.generation.title') }}</h2><InfoTip :content="t('settings.generation.description')" :label="t('settings.generation.title')" /></div>
            </div>
          </header>
          <div class="settings-form settings-form--compact">
            <el-form label-position="top" class="settings-form-grid">
              <el-form-item :label="t('settings.generation.scriptSectionMaxConcurrency')">
                <template #label><span class="field-with-info">{{ t('settings.generation.scriptSectionMaxConcurrency') }}<InfoTip :content="t('settings.generation.scriptSectionMaxConcurrencyHint')" :label="t('settings.generation.scriptSectionMaxConcurrency')" /></span></template>
                <el-input-number
                  v-model="appSettings.script_section_max_concurrency"
                  :min="1"
                  :max="20"
                  :aria-label="t('settings.generation.scriptSectionMaxConcurrency')"
                />
              </el-form-item>
            </el-form>
          </div>
          <footer class="settings-footer">
            <div class="settings-actions">
              <InfoTip :content="t('settings.generation.appliesToNewTasks')" :label="t('settings.actions.saveGeneration')" />
              <el-button
                type="primary"
                :icon="Select"
                :loading="savingAppSettings"
                @click="saveAppSettings"
              >
                {{ t('settings.actions.saveGeneration') }}
              </el-button>
            </div>
          </footer>
        </section>

        <section v-loading="loadingConsistencySettings" class="panel settings-card">
          <header class="panel-header">
            <div>
              <div class="title-with-info"><h2>{{ t('settings.consistency.title') }}</h2><InfoTip :content="t('settings.consistency.description')" :label="t('settings.consistency.title')" /></div>
            </div>
            <el-tag
              :type="consistencyRuntime?.ready ? 'success' : 'danger'"
              effect="plain"
            >
              {{
                consistencyRuntime?.ready
                  ? t('settings.consistency.runtimeReady')
                  : t('settings.consistency.runtimeNotReady')
              }}
            </el-tag>
          </header>
          <div class="settings-form consistency-settings-form">


            <el-collapse v-model="consistencyAdvancedSections" class="settings-advanced-collapse">
              <el-collapse-item name="thresholds">
                <template #title>
                  <div class="collapse-title">
                    <strong>{{ t('settings.consistency.thresholdSection') }}</strong>
                    <InfoTip :content="t('settings.consistency.thresholdHint')" :label="t('settings.consistency.thresholdSection')" />
                  </div>
                </template>
                <div class="advanced-section-body">
                  <div class="advanced-section-actions">
                    <el-button :icon="RefreshRight" @click="applyRecommendedConsistencySettings">
                      {{ t('settings.consistency.restoreDefaults') }}
                    </el-button>
                  </div>
                  <el-form label-position="top" class="consistency-threshold-grid">
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.cidsCrossMin') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.cidsCross')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.cidsCross')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.cids_cross_min" :min="0" :max="1" :step="0.01" :precision="2" />
                    </el-form-item>
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.cidsSelfMin') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.cidsSelf')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.cidsSelf')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.cids_self_min" :min="0" :max="1" :step="0.01" :precision="2" />
                    </el-form-item>
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.csdCrossMin') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.csdCross')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.csdCross')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.csd_cross_min" :min="0" :max="1" :step="0.01" :precision="2" />
                    </el-form-item>
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.csdSelfMin') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.csdSelf')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.csdSelf')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.csd_self_min" :min="0" :max="1" :step="0.01" :precision="2" />
                    </el-form-item>
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.occmMin') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.occm')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.occm')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.occm_min" :min="0" :max="100" :step="1" :precision="1" />
                    </el-form-item>
                    <el-form-item>
                      <template #label>
                        <span class="metric-label">
                          {{ t('settings.consistency.copyPasteMax') }}
                          <el-tooltip :content="t('settings.consistency.metricHints.copyPaste')">
                            <el-icon tabindex="0" :aria-label="t('settings.consistency.metricHints.copyPaste')"><InfoFilled /></el-icon>
                          </el-tooltip>
                        </span>
                      </template>
                      <el-input-number v-model="consistencySettings.copy_paste_max" :min="0" :max="1" :step="0.01" :precision="2" />
                    </el-form-item>
                  </el-form>
                </div>
              </el-collapse-item>

              <el-collapse-item name="runtime">
                <template #title>
                  <div class="collapse-title">
                    <strong>{{ t('settings.consistency.runtimeSection') }}</strong>
                    <InfoTip :content="t('settings.consistency.runtimeSectionHint')" :label="t('settings.consistency.runtimeSection')" />
                  </div>
                </template>
                <div class="advanced-section-body">
                  <el-descriptions v-if="consistencyRuntime" :column="2" border>
                    <el-descriptions-item :label="t('settings.consistency.metricVersion')">
                      {{ consistencyMetricVersion }}
                    </el-descriptions-item>
                    <el-descriptions-item :label="t('settings.consistency.device')">
                      {{ consistencyRuntime.cuda_device || '-' }}
                    </el-descriptions-item>
                    <el-descriptions-item :label="t('settings.consistency.torchVersion')">
                      {{ consistencyRuntime.torch_version || '-' }}
                    </el-descriptions-item>
                    <el-descriptions-item :label="t('settings.consistency.arcfaceProvider')">
                      {{ consistencyRuntime.arcface_provider.toUpperCase() }}
                    </el-descriptions-item>
                    <el-descriptions-item :label="t('settings.consistency.python')">
                      {{ consistencyRuntime.python_executable }}
                    </el-descriptions-item>
                    <el-descriptions-item
                      v-if="
                        consistencyRuntime.missing_modules.length ||
                        consistencyRuntime.missing_source_files.length ||
                        consistencyRuntime.missing_weights.length ||
                        consistencyRuntime.invalid_source_files.length ||
                        consistencyRuntime.invalid_weights.length
                      "
                      :label="t('settings.consistency.runtimeIssues')"
                      :span="2"
                    >
                      {{
                        [
                          ...consistencyRuntime.missing_modules,
                          ...consistencyRuntime.missing_source_files,
                          ...consistencyRuntime.missing_weights,
                          ...consistencyRuntime.invalid_source_files,
                          ...consistencyRuntime.invalid_weights,
                        ].join(', ')
                      }}
                    </el-descriptions-item>
                  </el-descriptions>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
          <footer class="settings-footer">
            <div class="settings-actions">
              <InfoTip :content="t('settings.consistency.snapshotHint')" :label="t('settings.actions.saveConsistency')" />
              <el-button
                type="primary"
                :icon="Select"
                :loading="savingConsistencySettings"
                @click="saveConsistencySettings"
              >
                {{ t('settings.actions.saveConsistency') }}
              </el-button>
            </div>
          </footer>
        </section>
        </template>

        <template v-else-if="activeSettingsTab === 'api'">
          <div class="page-header">
            <div class="page-actions">
              <el-button :icon="Plus" @click="createNewConfig">
                {{ t('settings.actions.addConfig') }}
              </el-button>
            </div>
          </div>
          <div class="settings-layout" :class="{ 'settings-layout--single': configs.length === 0 }">
            <section v-if="configs.length" class="panel config-list">
              <header class="panel-header">
                <div>
                  <div class="title-with-info"><h2>{{ t('settings.llm.configs') }}</h2><InfoTip :content="t('settings.llm.configsDescription')" :label="t('settings.llm.configs')" /></div>
                </div>
              </header>
              <div class="config-items">
                <article
                  v-for="config in configs"
                  :key="config.id"
                  class="config-item"
                  :class="{ 'config-item--selected': config.id === selectedConfigId }"
                  @click="selectConfig(config)"
                >
                  <div class="config-item__title">
                    <strong>{{ config.name }}</strong>
                    <el-tag v-if="config.is_active" type="success" effect="plain">
                      {{ t('settings.llm.active') }}
                    </el-tag>
                  </div>
                  <p>{{ config.base_url }}</p>
                  <small>
                    {{ t('settings.llm.provider') }}: {{ providerLabel(config.provider) }}
                    ·
                    {{ t('settings.llm.modelCount', { count: config.model_names.length }) }}
                    · {{ t('settings.llm.defaultModel') }}: {{ config.default_model }}
                  </small>
                  <el-tag :type="config.api_key_set ? 'success' : 'warning'" effect="plain">
                    {{
                      config.api_key_set
                        ? t('settings.llm.keyConfigured')
                        : t('settings.llm.keyMissing')
                    }}
                  </el-tag>
                </article>
                <el-empty v-if="configs.length === 0" :description="t('settings.llm.emptyConfigs')" />
              </div>
            </section>

            <section class="panel settings-card">
              <header class="panel-header">
                <div class="title-with-info">
                  <h2>{{ isCreating ? t('settings.llm.createTitle') : t('settings.llm.editTitle') }}</h2>
                  <InfoTip :content="t('settings.llm.description')" :label="t('settings.tabs.api')" />
                </div>
                <el-tag
                  v-if="!isCreating && selectedConfig"
                  :type="selectedConfig.api_key_set ? 'success' : 'warning'"
                  effect="plain"
                >
                  {{
                    selectedConfig.api_key_set
                      ? t('settings.llm.keyConfigured')
                      : t('settings.llm.keyMissing')
                  }}
                </el-tag>
              </header>

              <el-form label-position="top" class="settings-form">
                <el-form-item :label="t('settings.llm.name')">
                  <el-input v-model="form.name" :aria-label="t('settings.llm.name')" />
                </el-form-item>
                <el-form-item :label="t('settings.llm.provider')">
                  <el-select
                    v-model="form.provider"
                    :aria-label="t('settings.llm.provider')"
                    @change="onProviderChange"
                  >
                    <el-option
                      v-for="provider in providerOptions"
                      :key="provider.value"
                      :label="provider.label"
                      :value="provider.value"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item
                  v-if="selectedProviderRequiresBaseUrl"
                  :label="t('settings.llm.baseUrl')"
                >
                <template #label><span class="field-with-info">{{ t('settings.llm.baseUrl') }}<InfoTip :content="t('settings.llm.baseUrlRequiredHint')" :label="t('settings.llm.baseUrl')" /></span></template>
                  <el-input
                    v-model="form.base_url"
                    :aria-label="t('settings.llm.baseUrl')"
                    placeholder="https://api.openai.com/v1"
                  />
                  </el-form-item>
                <el-form-item :label="t('settings.llm.apiKey')">
                <template #label><span class="field-with-info">{{ t('settings.llm.apiKey') }}<InfoTip :content="t('settings.llm.apiKeyVisibleHint')" :label="t('settings.llm.apiKey')" /></span></template>
                  <el-input
                    v-model="form.api_key"
                    type="password"
                    show-password
                    :disabled="form.clear_api_key"
                    :placeholder="t('settings.llm.newKeyPlaceholder')"
                    :aria-label="t('settings.llm.apiKey')"
                  />
                  </el-form-item>
                <el-form-item>
                  <el-checkbox v-model="form.clear_api_key">
                    {{ t('settings.llm.clearKey') }}
                  </el-checkbox>
                </el-form-item>
                <el-form-item :label="t('settings.llm.modelNames')">
                  <div class="model-editor">
                    <div class="model-tags">
                      <el-tag
                        v-for="modelName in form.model_names"
                        :key="modelName"
                        closable
                        @close="removeModelName(modelName)"
                      >
                        {{ modelName }}
                      </el-tag>
                    </div>
                    <div class="model-input">
                      <el-input
                        v-model="modelDraft"
                        :placeholder="t('settings.llm.modelPlaceholder')"
                        :aria-label="t('settings.llm.modelNames')"
                        @keyup.enter="addModelName"
                      />
                      <el-button :icon="Plus" @click="addModelName">
                        {{ t('settings.actions.addModel') }}
                      </el-button>
                    </div>
                  </div>
                </el-form-item>
                <el-form-item :label="t('settings.llm.defaultModel')">
                  <el-select
                    v-model="form.default_model"
                    :aria-label="t('settings.llm.defaultModel')"
                  >
                    <el-option
                      v-for="modelName in form.model_names"
                      :key="modelName"
                      :label="modelName"
                      :value="modelName"
                    />
                  </el-select>
                </el-form-item>
              </el-form>

              <footer class="settings-footer">
                <span class="updated-at">
                  {{ t('settings.llm.updatedAt') }}:
                  {{ isCreating ? '-' : formatDate(selectedConfig?.updated_at) }}
                </span>
                <div class="settings-actions">
                  <el-button :icon="Connection" :loading="testing" @click="testConfig">
                    {{ t('settings.actions.test') }}
                  </el-button>
                  <el-button
                    v-if="!isCreating && selectedConfig && !selectedConfig.is_active"
                    :icon="Star"
                    :loading="activating"
                    @click="activateSelectedConfig"
                  >
                    {{ t('settings.actions.activate') }}
                  </el-button>
                  <el-dropdown v-if="!isCreating" trigger="click">
                    <el-button :icon="MoreFilled" :disabled="deleting">
                      {{ t('settings.actions.more') }}
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item :icon="Delete" divided @click="deleteSelectedConfig">
                          {{ t('settings.actions.delete') }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <el-button type="primary" :icon="Select" :loading="saving" @click="saveConfig">
                    {{ t('settings.actions.save') }}
                  </el-button>
                </div>
              </footer>
            </section>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 24px;
}

.settings-shell {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.settings-content {
  container-type: inline-size;
  display: grid;
  gap: 18px;
  min-width: 0;
}

.settings-nav {
  display: grid;
  gap: 8px;
  padding: 10px;
}

.settings-nav__item {
  width: 100%;
  border: 0;
  border-radius: 8px;
  padding: 13px 14px;
  background: transparent;
  color: var(--text-soft);
  font: inherit;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

/* 浅色 hover 只用于未选中项，避免覆盖选中项的渐变背景与白色文字。 */
.settings-nav__item:not(.settings-nav__item--active):hover {
  color: var(--text-main);
  background: #eff6ff;
}

.settings-nav__item--active {
  color: #ffffff;
  background: linear-gradient(135deg, #1da8f2 0%, #7a2cff 100%);
  box-shadow: 0 14px 28px rgba(45, 111, 255, 0.22);
}

.settings-nav__item--active:hover {
  color: #ffffff;
}

.page-header,
.panel-header,
.settings-footer,
.config-item__title,
.page-actions,
.settings-actions,
.model-input {
  display: flex;
}

.page-header,
.panel-header,
.settings-footer,
.config-item__title {
  gap: 18px;
}

.page-header {
  justify-content: flex-end;
}

.panel-header,
.settings-footer,
.config-item__title {
  justify-content: space-between;
}

.page-header,
.panel-header,
.settings-footer,
.config-item__title {
  align-items: flex-start;
}

.page-actions,
.settings-actions,
.model-input {
  align-items: center;
  gap: 10px;
}

.settings-layout {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(520px, 860px);
  gap: 18px;
  align-items: start;
}
.settings-layout--single { grid-template-columns: minmax(0, 1fr); }

/* 设置面板宽度受侧栏影响，按可用空间切换列数。 */
@container (max-width: 900px) {
  .settings-content .settings-layout { grid-template-columns: minmax(0, 1fr); }
  .settings-content .consistency-threshold-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 580px) {
  .settings-content .consistency-threshold-grid { grid-template-columns: minmax(0, 1fr); }
}
.settings-form-grid { max-width: 100%; grid-template-columns: minmax(0, 360px); }
.panel-header { flex-wrap: wrap; }
.panel-header h2 { font-size: 18px; line-height: 1.4; }
.config-item { min-width: 0; overflow-wrap: anywhere; }
.settings-actions { flex-wrap: wrap; }
.settings-actions .el-button + .el-button { margin-left: 0; }

.panel-header h2,
.panel-header p,
.config-item p {
  margin: 0;
}

.panel-header p,
.form-hint,
.updated-at,
.config-item p,
.config-item small {
  color: var(--text-soft);
}

.panel {
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #ffffff;
}

.panel-header {
  padding: 22px 24px;
  border-bottom: 1px solid var(--panel-border);
}

.config-items {
  display: grid;
  gap: 10px;
  padding: 16px;
}

.config-item {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  cursor: pointer;
}

.config-item--selected {
  border-color: var(--el-color-primary);
  background: #eff6ff;
}

.settings-form {
  padding: 22px 24px 8px;
}

.settings-form--compact {
  padding-bottom: 0;
}

.settings-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 360px);
}

.consistency-settings-form {
  display: grid;
  gap: 18px;
}

.settings-advanced-collapse {
  border: 1px solid var(--panel-border);
  border-radius: 8px;
}

.settings-advanced-collapse :deep(.el-collapse-item__header) {
  min-height: 58px;
  height: auto;
  padding: 10px 16px;
  border-radius: 8px;
}

.settings-advanced-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

.collapse-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.collapse-title span {
  overflow: hidden;
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 400;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.advanced-section-body {
  padding: 2px 16px 18px;
}

.advanced-section-actions {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.consistency-threshold-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(180px, 1fr));
  gap: 0 16px;
}

.metric-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.metric-label .el-icon {
  color: var(--text-soft);
  cursor: help;
}

.form-hint {
  margin: 8px 0 0;
  font-size: 13px;
}

.model-editor {
  display: grid;
  width: 100%;
  gap: 10px;
}

.model-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 32px;
}

.settings-footer {
  align-items: center;
  padding: 0 24px 24px;
}

.settings-footer > .settings-actions {
  margin-left: auto;
}

@media (max-width: 1080px) {
  .settings-shell {
    grid-template-columns: 1fr;
  }

  .settings-nav {
    display: flex;
    overflow-x: auto;
  }

  .settings-nav__item {
    flex: 0 0 auto;
    width: auto;
    min-width: 132px;
    text-align: center;
  }

  .settings-layout {
    grid-template-columns: 1fr;
  }

  .consistency-threshold-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .page-header,
  .panel-header,
  .settings-footer {
    flex-direction: column;
  }

  .collapse-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .collapse-title span {
    max-width: 240px;
  }
}
</style>

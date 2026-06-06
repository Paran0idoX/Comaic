<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, Delete, Plus, Refresh, Select, Star } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import { apiErrorMessage } from '@/api/errors'
import {
  activateLLMConfig,
  createLLMConfig,
  deleteLLMConfig,
  listLLMConfigs,
  listLLMProviders,
  testLLMConfig,
  updateLLMConfig,
  type LLMConfig,
  type LLMProvider,
  type LLMProviderOption,
} from '@/api/settings'
import { formatLocalDateTime } from '@/utils/datetime'

const { locale, t } = useI18n()

const loading = ref(false)
const saving = ref(false)
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
    const [result, providers] = await Promise.all([listLLMConfigs(), listLLMProviders()])
    providerOptions.value = providers
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

onMounted(() => {
  void loadConfigs()
})
</script>

<template>
  <section v-loading="loading" class="settings-page">
    <div class="page-header">
      <div>
        <p class="eyebrow">{{ t('app.preview') }}</p>
        <h1 class="page-title">{{ t('settings.title') }}</h1>
        <p class="page-subtitle">{{ t('settings.subtitle') }}</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Plus" @click="createNewConfig">
          {{ t('settings.actions.addConfig') }}
        </el-button>
        <el-button :icon="Refresh" @click="loadConfigs">
          {{ t('settings.actions.refresh') }}
        </el-button>
      </div>
    </div>

    <div class="settings-layout">
      <section class="panel config-list">
        <header class="panel-header">
          <div>
            <h2>{{ t('settings.llm.configs') }}</h2>
            <p>{{ t('settings.llm.configsDescription') }}</p>
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
          <div>
            <h2>{{ isCreating ? t('settings.llm.createTitle') : t('settings.llm.editTitle') }}</h2>
            <p>{{ t('settings.llm.description') }}</p>
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
            <el-input v-model="form.name" />
          </el-form-item>
          <el-form-item :label="t('settings.llm.provider')">
            <el-select v-model="form.provider" @change="onProviderChange">
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
            <el-input v-model="form.base_url" placeholder="https://api.openai.com/v1" />
            <p class="form-hint">{{ t('settings.llm.baseUrlRequiredHint') }}</p>
          </el-form-item>
          <el-form-item :label="t('settings.llm.apiKey')">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              :disabled="form.clear_api_key"
              :placeholder="t('settings.llm.newKeyPlaceholder')"
            />
            <p class="form-hint">{{ t('settings.llm.apiKeyVisibleHint') }}</p>
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
                  @keyup.enter="addModelName"
                />
                <el-button :icon="Plus" @click="addModelName">
                  {{ t('settings.actions.addModel') }}
                </el-button>
              </div>
            </div>
          </el-form-item>
          <el-form-item :label="t('settings.llm.defaultModel')">
            <el-select v-model="form.default_model">
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
            <el-button
              v-if="!isCreating"
              type="danger"
              plain
              :icon="Delete"
              :loading="deleting"
              @click="deleteSelectedConfig"
            >
              {{ t('settings.actions.delete') }}
            </el-button>
            <el-button type="primary" :icon="Select" :loading="saving" @click="saveConfig">
              {{ t('settings.actions.save') }}
            </el-button>
          </div>
        </footer>
      </section>
    </div>
  </section>
</template>

<style scoped>
.settings-page {
  display: grid;
  gap: 24px;
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
  justify-content: space-between;
  gap: 18px;
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

.eyebrow,
.page-title,
.page-subtitle,
.panel-header h2,
.panel-header p,
.config-item p {
  margin: 0;
}

.eyebrow {
  color: var(--text-soft);
  font-size: 13px;
  font-weight: 700;
}

.page-title {
  margin-top: 6px;
  font-size: 30px;
}

.page-subtitle,
.panel-header p,
.form-hint,
.updated-at,
.config-item p,
.config-item small {
  color: var(--text-soft);
}

.page-subtitle {
  margin-top: 10px;
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

@media (max-width: 1080px) {
  .settings-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .page-header,
  .panel-header,
  .settings-footer {
    flex-direction: column;
  }
}
</style>

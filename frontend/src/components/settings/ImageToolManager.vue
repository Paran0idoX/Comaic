<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import { Delete, EditPen, MoreFilled, Plus, Search, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  createImageGenerationTool, deleteImageGenerationTool, listImageGenerationTools,
  updateImageGenerationTool, type ImageGenerationTool,
} from '@/api/imageGeneration'
import { apiErrorMessage } from '@/api/errors'
import ReferenceToolConfiguration from '@/components/workspace/ReferenceToolConfiguration.vue'

// 设置页集中维护工具；参考图和漫画工作台只读取并选择已有配置。
const { t } = useI18n()
const workflows = ref<ImageGenerationTool[]>([])
const loading = ref(false)
const providerLabel = (provider: ImageGenerationTool['provider']) =>
  t(provider === 'openai_images_compatible'
    ? 'imageGeneration.workflows.kindOpenAIImagesCompatible'
    : 'imageGeneration.workflows.kindComfyUI')
const loadWorkflows = async () => { workflows.value = await listImageGenerationTools() }
type WorkflowNode = {
  class_type?: unknown
  inputs?: Record<string, unknown>
}

type PromptNodeCandidate = {
  nodeId: string
  inputName: string
  text: string
}

type SeedNodeCandidate = {
  nodeId: string
  inputName: string
  classType: string
}


const workflowDialogVisible = ref(false)
const workflowDialogMode = ref<'create' | 'edit'>('create')
const workflowAdvancedSections = ref<string[]>([])
const savingWorkflow = ref(false)
const editingWorkflowId = ref<number | null>(null)

const workflowForm = reactive({
  name: '',
  provider: 'comfyui' as 'comfyui' | 'openai_images_compatible',
  prompt_type: 'natural_language' as 'tag' | 'natural_language' | 'hybrid',
  description: '',
  comfy_base_url: '',
  workflow_json: '',
  is_default: false,
  positive_node_id: '',
  positive_input_name: 'text',
  negative_node_id: '',
  negative_input_name: '',
  seed_node_id: '',
  seed_input_name: '',
  api_base_url: '',
  endpoint_path: '/images/generations',
  api_key: '',
  model: '',
  size: '1024x1024',
  response_format: 'b64_json',
  seed_field_name: '',
  negative_prompt_field_name: '',
  extra_body_json: '',
  capabilities_json: '{\n  "features": ["txt2img"],\n  "limits": {}\n}',
  bindings_json: '{\n  "schema_version": 1,\n  "bindings": []\n}',
})


const jsonObjectValue = (content: string) => {
  try {
    const parsed = JSON.parse(content) as unknown
    return parsed !== null && !Array.isArray(parsed) && typeof parsed === 'object'
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

const isJsonObjectText = (content: string) => jsonObjectValue(content) !== null


const workflowJsonValid = computed(
  () =>
    workflowForm.workflow_json.trim().length > 0 && isJsonObjectText(workflowForm.workflow_json),
)
const advancedJsonValid = computed(
  () =>
    isJsonObjectText(workflowForm.capabilities_json) &&
    isJsonObjectText(workflowForm.bindings_json),
)
const explicitBindings = computed(() => jsonObjectValue(workflowForm.bindings_json)?.bindings)
const hasExplicitBindings = computed(() => Array.isArray(explicitBindings.value) && explicitBindings.value.length > 0)
/** 显式 binding 与后端一样优先，避免要求重复填写旧字段或用旧字段掩盖缺项。 */
const hasBindingSource = (bindings: unknown, source: string) => Array.isArray(bindings) && bindings.some(binding =>
  binding && typeof binding === 'object' && binding.source === source &&
  typeof binding.node_id === 'string' && binding.node_id.trim() &&
  typeof binding.input_name === 'string' && binding.input_name.trim())
const promptMappingReady = computed(
  () =>
    hasExplicitBindings.value ? hasBindingSource(explicitBindings.value, 'prompt.positive') :
    (workflowForm.positive_node_id.trim().length > 0 &&
      workflowForm.positive_input_name.trim().length > 0),
)
const canParseWorkflowNodes = computed(
  () => workflowForm.provider === 'comfyui' && workflowJsonValid.value,
)
const canSaveWorkflow = computed(() => {
  if (!workflowForm.name.trim() || !advancedJsonValid.value || savingWorkflow.value) {
    return false
  }
  if (workflowForm.provider === 'comfyui') {
    const seedFieldsMatch = Boolean(workflowForm.seed_node_id.trim()) === Boolean(workflowForm.seed_input_name.trim())
    return workflowJsonValid.value && promptMappingReady.value && (hasExplicitBindings.value || seedFieldsMatch)
  }
  return (
    workflowForm.api_base_url.trim().length > 0 &&
    workflowForm.model.trim().length > 0 &&
    (!workflowForm.extra_body_json.trim() || isJsonObjectText(workflowForm.extra_body_json))
  )
})


const resetWorkflowForm = () => {
  workflowForm.name = ''
  workflowForm.provider = 'comfyui'
  workflowForm.prompt_type = 'natural_language'
  workflowForm.description = ''
  workflowForm.comfy_base_url = ''
  workflowForm.workflow_json = ''
  workflowForm.is_default = false
  workflowForm.positive_node_id = ''
  workflowForm.positive_input_name = 'text'
  workflowForm.negative_node_id = ''
  workflowForm.negative_input_name = ''
  workflowForm.seed_node_id = ''
  workflowForm.seed_input_name = ''
  workflowForm.api_base_url = ''
  workflowForm.endpoint_path = '/images/generations'
  workflowForm.api_key = ''
  workflowForm.model = ''
  workflowForm.size = '1024x1024'
  workflowForm.response_format = 'b64_json'
  workflowForm.seed_field_name = ''
  workflowForm.negative_prompt_field_name = ''
  workflowForm.extra_body_json = ''
  workflowForm.capabilities_json = '{\n  "features": ["txt2img"],\n  "limits": {}\n}'
  workflowForm.bindings_json = '{\n  "schema_version": 1,\n  "bindings": []\n}'
}

const parseWorkflowJson = (content: string) => {
  try {
    const parsed = JSON.parse(content) as unknown
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('Workflow JSON must be an object.')
    }
    return parsed as Record<string, WorkflowNode>
  } catch {
    ElMessage.error(t('imageGeneration.errors.workflowJsonInvalid'))
    return null
  }
}

const isTextEncodeNode = (node: WorkflowNode) => {
  const classType = String(node.class_type ?? '')
  const inputs = node.inputs
  return (
    inputs !== undefined &&
    typeof inputs.text === 'string' &&
    (classType === 'CLIPTextEncode' || classType.includes('TextEncode'))
  )
}

const looksLikeNegativePrompt = (text: string) => {
  const normalized = text.toLowerCase()
  return ['negative', 'low quality', 'bad anatomy', 'blurry', 'watermark', 'worst quality'].some(
    (keyword) => normalized.includes(keyword),
  )
}

const findPositivePromptCandidate = (workflow: Record<string, WorkflowNode>) => {
  const candidates: PromptNodeCandidate[] = Object.entries(workflow)
    .filter(([, node]) => isTextEncodeNode(node))
    .map(([nodeId, node]) => ({
      nodeId,
      inputName: 'text',
      text: String(node.inputs?.text ?? ''),
    }))

  if (candidates.length === 0) {
    return { candidate: null, multiple: false }
  }

  const positiveCandidates = candidates.filter(
    (candidate) => !looksLikeNegativePrompt(candidate.text),
  )
  const candidate = positiveCandidates[0] ?? candidates[0] ?? null
  return {
    candidate,
    multiple: candidates.length > 1,
  }
}

const isSeedNode = (node: WorkflowNode) => {
  const classType = String(node.class_type ?? '')
  const inputs = node.inputs
  return (
    inputs !== undefined &&
    ('seed' in inputs || 'noise_seed' in inputs) &&
    (classType === 'KSampler' || classType === 'KSamplerAdvanced' || classType.includes('Sampler'))
  )
}

const findSeedCandidate = (workflow: Record<string, WorkflowNode>) => {
  const candidates: SeedNodeCandidate[] = Object.entries(workflow)
    .filter(([, node]) => isSeedNode(node))
    .map(([nodeId, node]) => ({
      nodeId,
      inputName:
        String(node.class_type ?? '') === 'KSamplerAdvanced' && 'noise_seed' in (node.inputs ?? {})
          ? 'noise_seed'
          : 'seed' in (node.inputs ?? {})
            ? 'seed'
            : 'noise_seed',
      classType: String(node.class_type ?? ''),
    }))

  if (candidates.length === 0) {
    return { candidate: null, multiple: false }
  }

  const candidate =
    candidates.find((item) => item.classType === 'KSampler') ??
    candidates.find((item) => item.classType === 'KSamplerAdvanced') ??
    candidates[0] ??
    null
  return {
    candidate,
    multiple: candidates.length > 1,
  }
}

const applyPositivePromptCandidate = (workflow: Record<string, WorkflowNode>) => {
  const { candidate, multiple } = findPositivePromptCandidate(workflow)
  if (candidate === null) {
    ElMessage.warning(t('imageGeneration.messages.workflowPositiveNotFound'))
    return
  }

  workflowForm.positive_node_id = candidate.nodeId
  workflowForm.positive_input_name = candidate.inputName
  ElMessage.success(
    multiple
      ? t('imageGeneration.messages.workflowPositiveMultiple')
      : t('imageGeneration.messages.workflowPositiveParsed'),
  )
}

const applySeedCandidate = (workflow: Record<string, WorkflowNode>) => {
  const { candidate, multiple } = findSeedCandidate(workflow)
  if (candidate === null) {
    ElMessage.warning(t('imageGeneration.messages.workflowSeedNotFound'))
    return
  }

  workflowForm.seed_node_id = candidate.nodeId
  workflowForm.seed_input_name = candidate.inputName
  ElMessage.success(
    multiple
      ? t('imageGeneration.messages.workflowSeedMultiple')
      : t('imageGeneration.messages.workflowSeedParsed'),
  )
}

const applyWorkflowCandidates = (workflow: Record<string, WorkflowNode>) => {
  applyPositivePromptCandidate(workflow)
  applySeedCandidate(workflow)
}

const parseWorkflowNodesFromTextarea = () => {
  const workflow = parseWorkflowJson(workflowForm.workflow_json)
  if (workflow !== null) {
    applyWorkflowCandidates(workflow)
  }
}

const handleWorkflowFile = (file: File) => {
  const reader = new FileReader()
  reader.onload = () => {
    const content = String(reader.result ?? '')
    const workflow = parseWorkflowJson(content)
    if (workflow === null) {
      return
    }
    workflowForm.workflow_json = JSON.stringify(workflow, null, 2)
    applyWorkflowCandidates(workflow)
  }
  reader.onerror = () => {
    ElMessage.error(t('imageGeneration.errors.workflowJsonInvalid'))
  }
  reader.readAsText(file)
}

// auto-upload=false 时 before-upload 不会自动执行；用 on-change 读取浏览器本地文件。
const handleWorkflowFileChange = (uploadFile: UploadFile) => {
  if (uploadFile.raw === undefined) {
    ElMessage.error(t('imageGeneration.errors.workflowJsonInvalid'))
    return
  }
  handleWorkflowFile(uploadFile.raw)
}

const parseConfigurationObject = (content: string, field: string) => {
  try {
    const parsed = JSON.parse(content || '{}') as unknown
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error(`${field} must be an object`)
    }
    return parsed as Record<string, unknown>
  } catch {
    throw new Error(t('imageGeneration.errors.configurationJsonInvalid', { field }))
  }
}

const workflowPayload = () => ({
  name: workflowForm.name.trim(),
  provider: workflowForm.provider,
  prompt_type: workflowForm.prompt_type,
  description: workflowForm.description.trim() || null,
  is_default: workflowForm.is_default,
  capabilities: parseConfigurationObject(
    workflowForm.capabilities_json,
    t('imageGeneration.workflows.capabilities'),
  ),
  bindings: parseConfigurationObject(
    workflowForm.bindings_json,
    t('imageGeneration.workflows.bindings'),
  ),
  comfy_base_url: workflowForm.comfy_base_url.trim() || null,
  workflow_json: workflowForm.workflow_json.trim() || null,
  positive_node_id: workflowForm.positive_node_id.trim() || null,
  positive_input_name: workflowForm.positive_input_name.trim() || null,
  negative_node_id: workflowForm.negative_node_id.trim() || null,
  negative_input_name: workflowForm.negative_input_name.trim() || null,
  seed_node_id: workflowForm.seed_node_id.trim() || null,
  seed_input_name: workflowForm.seed_input_name.trim() || null,
  api_base_url: workflowForm.api_base_url.trim() || null,
  endpoint_path: workflowForm.endpoint_path.trim() || null,
  api_key: workflowForm.api_key.trim() || null,
  model: workflowForm.model.trim() || null,
  size: workflowForm.size.trim() || null,
  response_format: workflowForm.response_format.trim() || null,
  seed_field_name: workflowForm.seed_field_name.trim() || null,
  negative_prompt_field_name: workflowForm.negative_prompt_field_name.trim() || null,
  extra_body_json: workflowForm.extra_body_json.trim() || null,
})

const validateExtraBodyJson = () => {
  const content = workflowForm.extra_body_json.trim()
  if (!content) {
    return true
  }
  try {
    const parsed = JSON.parse(content) as unknown
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('Extra body must be a JSON object.')
    }
    workflowForm.extra_body_json = JSON.stringify(parsed, null, 2)
    return true
  } catch {
    ElMessage.warning(t('imageGeneration.errors.extraBodyJsonInvalid'))
    return false
  }
}


const openCreateWorkflow = () => {
  workflowDialogMode.value = 'create'
  editingWorkflowId.value = null
  resetWorkflowForm()
  workflowAdvancedSections.value = []
  workflowDialogVisible.value = true
}

const openEditWorkflow = (workflow: ImageGenerationTool) => {
  workflowDialogMode.value = 'edit'
  editingWorkflowId.value = workflow.id
  workflowForm.name = workflow.name
  workflowForm.provider = workflow.provider
  workflowForm.prompt_type = workflow.prompt_type
  workflowForm.description = workflow.description ?? ''
  workflowForm.comfy_base_url = workflow.comfy_base_url ?? ''
  workflowForm.workflow_json = workflow.workflow_json ?? ''
  workflowForm.is_default = workflow.is_default
  workflowForm.positive_node_id = workflow.positive_node_id ?? ''
  workflowForm.positive_input_name = workflow.positive_input_name ?? 'text'
  workflowForm.negative_node_id = workflow.negative_node_id ?? ''
  workflowForm.negative_input_name = workflow.negative_input_name ?? ''
  workflowForm.seed_node_id = workflow.seed_node_id ?? ''
  workflowForm.seed_input_name = workflow.seed_input_name ?? ''
  workflowForm.api_base_url = workflow.api_base_url ?? ''
  workflowForm.endpoint_path = workflow.endpoint_path ?? '/images/generations'
  workflowForm.api_key = workflow.api_key ?? ''
  workflowForm.model = workflow.model ?? ''
  workflowForm.size = workflow.size ?? '1024x1024'
  workflowForm.response_format = workflow.response_format ?? 'b64_json'
  workflowForm.seed_field_name = workflow.seed_field_name ?? ''
  workflowForm.negative_prompt_field_name = workflow.negative_prompt_field_name ?? ''
  workflowForm.extra_body_json = workflow.extra_body_json ?? ''
  workflowForm.capabilities_json = JSON.stringify(workflow.capabilities, null, 2)
  workflowForm.bindings_json = JSON.stringify(workflow.bindings, null, 2)
  workflowAdvancedSections.value = []
  workflowDialogVisible.value = true
}

const saveWorkflow = async () => {
  let payload: ReturnType<typeof workflowPayload>
  try {
    payload = workflowPayload()
  } catch (error) {
    ElMessage.warning(
      error instanceof Error ? error.message : t('imageGeneration.errors.configurationJsonInvalid'),
    )
    return
  }
  if (!payload.name) {
    ElMessage.warning(t('imageGeneration.errors.emptyWorkflow'))
    return
  }
  const hasExplicitBindings =
    Array.isArray(payload.bindings.bindings) && payload.bindings.bindings.length > 0
  if (
    payload.provider === 'comfyui' &&
    (!payload.workflow_json ||
      (!hasExplicitBindings && (!payload.positive_node_id || !payload.positive_input_name)))
  ) {
    ElMessage.warning(t('imageGeneration.errors.emptyWorkflow'))
    return
  }
  if (
    payload.provider === 'openai_images_compatible' &&
    (!payload.api_base_url || !payload.model)
  ) {
    ElMessage.warning(t('imageGeneration.errors.emptyTool'))
    return
  }
  if (payload.provider === 'openai_images_compatible' && !validateExtraBodyJson()) {
    return
  }
  savingWorkflow.value = true
  try {
    if (workflowDialogMode.value === 'create' || editingWorkflowId.value === null) {
      await createImageGenerationTool(payload)
    } else {
      await updateImageGenerationTool(editingWorkflowId.value, payload)
    }
    workflowDialogVisible.value = false
    await loadWorkflows()
    ElMessage.success(t('imageGeneration.messages.workflowSaved'))
  } catch {
    ElMessage.error(t('imageGeneration.errors.saveWorkflowFailed'))
  } finally {
    savingWorkflow.value = false
  }
}

const removeWorkflow = async (workflow: ImageGenerationTool) => {
  try {
    await ElMessageBox.confirm(
      t('imageGeneration.messages.deleteWorkflowConfirm', { name: workflow.name }),
      t('imageGeneration.actions.deleteWorkflow'),
      { type: 'warning' },
    )
    await deleteImageGenerationTool(workflow.id)
    await loadWorkflows()
    ElMessage.success(t('imageGeneration.messages.workflowDeleted'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('imageGeneration.errors.deleteWorkflowFailed'))
    }
  }
}


onMounted(async () => {
  loading.value = true
  try { await loadWorkflows() }
  catch (error) { ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.loadFailed'))) }
  finally { loading.value = false }
})
</script>

<template>
  <div v-loading="loading" class="image-tool-manager">
      <section class="panel workflow-panel">
        <header class="panel-header">
          <div>
            <div class="title-with-info"><h2>{{ t('imageGeneration.workflows.title') }}</h2><InfoTip :content="t('imageGeneration.workflows.description')" :label="t('imageGeneration.workflows.title')" /></div>
          </div>
          <el-button type="primary" plain :icon="Plus" @click="openCreateWorkflow">
            {{ t('imageGeneration.actions.addWorkflow') }}
          </el-button>
        </header>

        <div class="workflow-list">
          <article v-for="workflow in workflows" :key="workflow.id" class="workflow-item">
            <div>
              <div class="workflow-item__title">
                <strong>{{ workflow.name }}</strong>
                <el-tag size="small" effect="plain">{{ providerLabel(workflow.provider) }}</el-tag>
              </div>
              <el-tag v-if="workflow.is_default" type="success" effect="plain">
                {{ t('imageGeneration.workflows.default') }}
              </el-tag>
              <el-tag type="primary" effect="plain">
                {{ t(`imageSpecs.promptTypes.${workflow.prompt_type}`) }}
              </el-tag>
              <p v-if="workflow.description">{{ workflow.description }}</p>
            </div>
            <div class="workflow-actions">
              <el-button link type="primary" :icon="EditPen" @click="openEditWorkflow(workflow)">
                {{ t('projects.edit') }}
              </el-button>
              <el-dropdown trigger="click">
                <el-button link :icon="MoreFilled" :aria-label="t('imageGeneration.actions.more')" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="Delete" @click="removeWorkflow(workflow)">
                      {{ t('imageGeneration.actions.deleteWorkflow') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </article>
          <el-empty
            v-if="workflows.length === 0"
            :description="t('imageGeneration.workflows.empty')"
          />
        </div>
      </section>

    <el-dialog
      v-if="workflowDialogVisible"
      v-model="workflowDialogVisible"
      destroy-on-close
      :title="t('imageGeneration.workflows.editorTitle')"
      width="min(920px, 94vw)"
    >
      <el-form label-position="top">
        <h3 class="workflow-section-title">{{ t('imageGeneration.workflows.basicSection') }}</h3>
        <div class="workflow-form-grid">
          <el-form-item :label="t('imageGeneration.workflows.name')" required>
            <el-input
              v-model="workflowForm.name"
              :aria-label="t('imageGeneration.workflows.name')"
            />
          </el-form-item>
          <el-form-item :label="t('imageGeneration.workflows.kind')">
            <el-select
              v-model="workflowForm.provider"
              :aria-label="t('imageGeneration.workflows.kind')"
            >
              <el-option :label="t('imageGeneration.workflows.kindComfyUI')" value="comfyui" />
              <el-option
                :label="t('imageGeneration.workflows.kindOpenAIImagesCompatible')"
                value="openai_images_compatible"
              />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.workflows.promptType')" required>
            <el-select v-model="workflowForm.prompt_type">
              <el-option :label="t('imageSpecs.promptTypes.tag')" value="tag" />
              <el-option
                :label="t('imageSpecs.promptTypes.natural_language')"
                value="natural_language"
              />
              <el-option :label="t('imageSpecs.promptTypes.hybrid')" value="hybrid" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="workflowForm.is_default">
              {{ t('imageGeneration.workflows.default') }}
            </el-checkbox>
          </el-form-item>
        </div>
        <el-form-item :label="t('imageGeneration.workflows.descriptionLabel')">
          <el-input v-model="workflowForm.description" />
        </el-form-item>
        <ReferenceToolConfiguration v-model="workflowForm.capabilities_json" :provider="workflowForm.provider" />

        <template v-if="workflowForm.provider === 'comfyui'">
          <h3 class="workflow-section-title">
            {{ t('imageGeneration.workflows.connectionSection') }}
          </h3>
          <el-form-item :label="t('imageGeneration.workflows.comfyBaseUrl')">
            <el-input
              v-model="workflowForm.comfy_base_url"
              :placeholder="t('imageGeneration.workflows.comfyBaseUrlPlaceholder')"
            />
          </el-form-item>
          <el-form-item :label="t('imageGeneration.workflows.workflowJson')" required>
            <div class="workflow-json-tools">
              <el-upload
                drag
                accept=".json,application/json"
                :show-file-list="false"
                :auto-upload="false"
                :on-change="handleWorkflowFileChange"
                class="workflow-upload"
              >
                <el-icon class="workflow-upload__icon"><UploadFilled /></el-icon>
                <div class="workflow-upload__text">
                  {{ t('imageGeneration.workflows.uploadHint') }}
                </div>
              </el-upload>
              <el-button
                :icon="Search"
                :disabled="!canParseWorkflowNodes"
                @click="parseWorkflowNodesFromTextarea"
              >
                {{ t('imageGeneration.actions.parseWorkflowNodes') }}
              </el-button>
            </div>
            <el-input
              v-model="workflowForm.workflow_json"
              type="textarea"
              :rows="12"
              resize="none"
              :aria-label="t('imageGeneration.workflows.workflowJson')"
            />
            <p class="json-validation" :class="{ 'json-validation--invalid': !workflowJsonValid }">
              {{
                workflowJsonValid
                  ? t('imageGeneration.workflows.jsonValid')
                  : t('imageGeneration.workflows.workflowJsonRequired')
              }}
            </p>
          </el-form-item>
        </template>

        <template v-else>
          <h3 class="workflow-section-title">
            {{ t('imageGeneration.workflows.connectionSection') }}
          </h3>
          <div class="workflow-node-grid">
            <el-form-item :label="t('imageGeneration.workflows.apiBaseUrl')" required>
              <el-input
                v-model="workflowForm.api_base_url"
                placeholder="https://api.example.com/v1"
              />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.workflows.endpointPath')">
              <el-input v-model="workflowForm.endpoint_path" />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.workflows.model')" required>
              <el-input v-model="workflowForm.model" />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.workflows.apiKey')">
              <el-input v-model="workflowForm.api_key" type="password" show-password />
            </el-form-item>
          </div>
        </template>

        <el-collapse v-model="workflowAdvancedSections" class="workflow-advanced">
          <el-collapse-item
            v-if="workflowForm.provider === 'comfyui'"
            name="node-mapping"
            :title="t('imageGeneration.workflows.nodeMappingSection')"
          >
            <el-alert
              v-if="!promptMappingReady"
              type="warning"
              :closable="false"
              :title="t('imageGeneration.workflows.nodeMappingRequired')"
            />
            <div class="workflow-node-grid">
              <el-form-item
                :label="t('imageGeneration.workflows.positiveNode')"
                :required="!hasExplicitBindings"
              >
                <el-input v-model="workflowForm.positive_node_id" />
              </el-form-item>
              <el-form-item
                :label="t('imageGeneration.workflows.positiveInput')"
                :required="!hasExplicitBindings"
              >
                <el-input v-model="workflowForm.positive_input_name" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.negativeNode')">
                <el-input v-model="workflowForm.negative_node_id" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.negativeInput')">
                <el-input v-model="workflowForm.negative_input_name" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.seedNode')">
                <el-input v-model="workflowForm.seed_node_id" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.seedInput')">
                <el-input v-model="workflowForm.seed_input_name" />
              </el-form-item>
            </div>
          </el-collapse-item>

          <el-collapse-item
            v-else
            name="provider-options"
            :title="t('imageGeneration.workflows.providerOptionsSection')"
          >
            <div class="workflow-node-grid">
              <el-form-item :label="t('imageGeneration.workflows.size')">
                <el-input v-model="workflowForm.size" placeholder="1024x1024" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.responseFormat')">
                <el-select v-model="workflowForm.response_format" allow-create filterable>
                  <el-option label="b64_json" value="b64_json" />
                  <el-option label="url" value="url" />
                </el-select>
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.seedFieldName')">
                <el-input v-model="workflowForm.seed_field_name" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.negativePromptFieldName')">
                <el-input v-model="workflowForm.negative_prompt_field_name" />
              </el-form-item>
            </div>
            <el-form-item :label="t('imageGeneration.workflows.extraBodyJson')">
              <el-input
                v-model="workflowForm.extra_body_json"
                type="textarea"
                :rows="7"
                resize="none"
              />
              <p
                v-if="workflowForm.extra_body_json.trim()"
                class="json-validation"
                :class="{
                  'json-validation--invalid': !isJsonObjectText(workflowForm.extra_body_json),
                }"
              >
                {{
                  isJsonObjectText(workflowForm.extra_body_json)
                    ? t('imageGeneration.workflows.jsonValid')
                    : t('imageGeneration.workflows.jsonInvalid')
                }}
              </p>
            </el-form-item>
          </el-collapse-item>

          <el-collapse-item
            name="structured-json"
            :title="t('imageGeneration.workflows.advancedSection')"
          >
            <template #title><span class="field-with-info">{{ t('imageGeneration.workflows.advancedSection') }}<InfoTip :content="t('imageGeneration.workflows.advancedHint')" :label="t('imageGeneration.workflows.advancedSection')" /></span></template>
            <div class="workflow-structured-grid">
              <el-form-item :label="t('imageGeneration.workflows.capabilities')">
                <el-input
                  v-model="workflowForm.capabilities_json"
                  type="textarea"
                  :rows="8"
                  resize="none"
                />
                <p
                  class="json-validation"
                  :class="{
                    'json-validation--invalid': !isJsonObjectText(workflowForm.capabilities_json),
                  }"
                >
                  {{
                    isJsonObjectText(workflowForm.capabilities_json)
                      ? t('imageGeneration.workflows.jsonValid')
                      : t('imageGeneration.workflows.jsonInvalid')
                  }}
                </p>
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.bindings')">
                <el-input
                  v-model="workflowForm.bindings_json"
                  type="textarea"
                  :rows="8"
                  resize="none"
                />
                <p
                  class="json-validation"
                  :class="{
                    'json-validation--invalid': !isJsonObjectText(workflowForm.bindings_json),
                  }"
                >
                  {{
                    isJsonObjectText(workflowForm.bindings_json)
                      ? t('imageGeneration.workflows.jsonValid')
                      : t('imageGeneration.workflows.jsonInvalid')
                  }}
                </p>
              </el-form-item>
            </div>
          </el-collapse-item>
        </el-collapse>

        <el-alert
          v-if="!canSaveWorkflow && !savingWorkflow"
          class="workflow-form-status"
          type="info"
          :closable="false"
          :title="t('imageGeneration.workflows.formIncomplete')"
        />
      </el-form>
      <template #footer>
        <el-button @click="workflowDialogVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button
          type="primary"
          :loading="savingWorkflow"
          :disabled="!canSaveWorkflow"
          @click="saveWorkflow"
        >
          {{ t('projects.save') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.image-tool-manager { min-width: 0; }
.workflow-panel { padding: 20px; }
.panel-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.panel-header h2 { margin: 0; font-size: 18px; }
.panel-header p { margin: 6px 0 0; color: var(--text-soft); font-size: 13px; line-height: 1.6; }
.workflow-list { display: grid; gap: 12px; margin-top: 18px; }
.workflow-item { display: flex; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid var(--panel-border); border-radius: 8px; }
.workflow-item p { margin: 6px 0 0; color: var(--text-soft); }
.workflow-item__title, .workflow-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.workflow-form-grid, .workflow-node-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.workflow-structured-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.workflow-json-tools { display: grid; gap: 12px; width: 100%; }
.workflow-section-title { margin: 20px 0 14px; color: var(--text-main); font-size: 15px; }
.workflow-section-title:first-child { margin-top: 0; }
.workflow-advanced { margin-top: 18px; border: 1px solid var(--panel-border); border-radius: 8px; }
.workflow-advanced :deep(.el-collapse-item__header) { padding: 0 14px; }
.workflow-advanced :deep(.el-collapse-item__content) { padding: 14px; }
.workflow-form-status { margin-top: 16px; }
.json-validation { width: 100%; margin: 6px 0 0; color: var(--el-color-success); font-size: 12px; }
.json-validation--invalid { color: var(--el-color-danger); }
.workflow-upload { width: 100%; }
.workflow-upload__icon { margin-bottom: 10px; color: var(--text-soft); font-size: 36px; }
.workflow-upload__text { color: var(--text-soft); font-size: 13px; }
@media (max-width: 760px) {
  .workflow-panel { padding: 16px; }
  .panel-header { flex-wrap: wrap; }
  .workflow-form-grid, .workflow-node-grid, .workflow-structured-grid { grid-template-columns: 1fr; }
  .workflow-item { flex-wrap: wrap; }
}
</style>

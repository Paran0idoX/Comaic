<script setup lang="ts">
import { Delete, EditPen, Picture, Plus, Search, Select, UploadFilled, VideoPause, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  createImageGenerationTool,
  deleteImageGenerationTool,
  getGenerationRun,
  listImageGenerationTools,
  listImageGenerationPages,
  selectGeneratedImage,
  streamContinueImagesForTask,
  streamGenerateImagesForPage,
  streamGenerateImagesForTask,
  suspendImageGenerationTask,
  updateImageGenerationTool,
  type ImageGenerationTool,
  type GeneratedImage,
  type GenerationRun,
  type ImageGenerationPage,
} from '@/api/imageGeneration'
import { apiErrorMessage } from '@/api/errors'
import { listProjects, type Project } from '@/api/projects'
import { listProjectScriptTasks, type ScriptTask } from '@/api/scripts'
import {
  promoteGeneratedImage,
  type VisualAssetRole,
  type VisualEntityType,
} from '@/api/visualBible'
import { formatLocalNowTime } from '@/utils/datetime'
import { useProjectContextStore } from '@/stores/projectContext'

type TimelineLevel = 'primary' | 'success' | 'warning' | 'danger' | 'info'

type ProgressEvent = {
  id: number
  title: string
  content: string
  timestamp: string
  type: TimelineLevel
}

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

const { locale, t } = useI18n()
const projectContext = useProjectContextStore()
const { selectedProjectId } = storeToRefs(projectContext)

const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const workflows = ref<ImageGenerationTool[]>([])
const pages = ref<ImageGenerationPage[]>([])
const selectedTaskId = ref<number | null>(null)
const selectedWorkflowId = ref<number | null>(null)
const currentGenerationTaskId = ref<number | null>(null)
const loading = ref(false)
const loadingTasks = ref(false)
const loadingPages = ref(false)
const generating = ref(false)
const continuing = ref(false)
const suspending = ref(false)
const workflowDialogVisible = ref(false)
const workflowDialogMode = ref<'create' | 'edit'>('create')
const workflowAdvancedSections = ref<string[]>([])
const savingWorkflow = ref(false)
const editingWorkflowId = ref<number | null>(null)
const detailImage = ref<GeneratedImage | null>(null)
const detailVisible = ref(false)
const generationRun = ref<GenerationRun | null>(null)
const provenanceVisible = ref(false)
const provenanceLoading = ref(false)
const promoteImage = ref<GeneratedImage | null>(null)
const promoteVisible = ref(false)
const promoting = ref(false)
const progressEvents = ref<ProgressEvent[]>([])
const eventSequence = ref(1)

const generationForm = reactive({
  poll_interval_seconds: 2,
  wait_timeout_seconds: 600,
  candidates_per_page: 1,
  generation_mode: 'preview' as 'preview' | 'final',
  seed_strategy: 'per_page' as 'per_page' | 'shared_candidate',
})

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

const promoteForm = reactive({
  entity_type: 'character' as VisualEntityType,
  entity_id: null as number | null,
  entity_key: '',
  role: 'identity_face' as VisualAssetRole,
  approve: false,
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

const selectedProject = computed(
  () => projects.value.find((project) => project.id === selectedProjectId.value) ?? null,
)
const selectedWorkflow = computed(
  () => workflows.value.find((workflow) => workflow.id === selectedWorkflowId.value) ?? null,
)
const sortedPages = computed(() => [...pages.value].sort((left, right) => left.page_no - right.page_no))
const generationRunning = computed(() => generating.value || continuing.value)
const pageSpecificationReady = (page: ImageGenerationPage) =>
  page.latest_spec_id !== null &&
  (generationForm.generation_mode === 'preview' || page.spec_warnings.length === 0)
const canGenerate = computed(
  () =>
    selectedTaskId.value !== null &&
    selectedWorkflowId.value !== null &&
    pages.value.length > 0 &&
    pages.value.every(pageSpecificationReady) &&
    !generationRunning.value,
)
const pagesNeedingContinuation = computed(() =>
  pages.value.filter(
    (page) =>
      pageSpecificationReady(page) &&
      page.completed_candidates < generationForm.candidates_per_page,
  ),
)
const canContinueGeneration = computed(
  () =>
    selectedTaskId.value !== null &&
    selectedWorkflowId.value !== null &&
    pagesNeedingContinuation.value.length > 0 &&
    !generationRunning.value,
)
const workflowJsonValid = computed(
  () =>
    workflowForm.workflow_json.trim().length > 0 && isJsonObjectText(workflowForm.workflow_json),
)
const advancedJsonValid = computed(
  () =>
    isJsonObjectText(workflowForm.capabilities_json) &&
    isJsonObjectText(workflowForm.bindings_json),
)
const hasExplicitBindings = computed(() => {
  const bindings = jsonObjectValue(workflowForm.bindings_json)
  return Array.isArray(bindings?.bindings) && bindings.bindings.length > 0
})
const promptMappingReady = computed(
  () =>
    hasExplicitBindings.value ||
    (workflowForm.positive_node_id.trim().length > 0 &&
      workflowForm.positive_input_name.trim().length > 0),
)
const seedMappingReady = computed(
  () => workflowForm.seed_node_id.trim().length > 0 && workflowForm.seed_input_name.trim().length > 0,
)
const canParseWorkflowNodes = computed(
  () => workflowForm.provider === 'comfyui' && workflowJsonValid.value,
)
const canSaveWorkflow = computed(() => {
  if (!workflowForm.name.trim() || !advancedJsonValid.value || savingWorkflow.value) {
    return false
  }
  if (workflowForm.provider === 'comfyui') {
    return workflowJsonValid.value && promptMappingReady.value && seedMappingReady.value
  }
  return (
    workflowForm.api_base_url.trim().length > 0 &&
    workflowForm.model.trim().length > 0 &&
    (!workflowForm.extra_body_json.trim() || isJsonObjectText(workflowForm.extra_body_json))
  )
})

const nowLabel = () => formatLocalNowTime(locale.value)

const shortText = (value: string | null, maxLength = 120) => {
  if (!value) {
    return t('imageGeneration.emptyText')
  }
  const compact = value.replace(/\s+/g, ' ').trim()
  return compact.length > maxLength ? `${compact.slice(0, maxLength)}...` : compact
}

const taskLabel = (task: ScriptTask) =>
  `#${task.id} · ${task.mode} · ${task.total_pages} ${t('imageGeneration.generation.pagesUnit')}`

const providerLabel = (provider: ImageGenerationTool['provider']) =>
  provider === 'openai_images_compatible'
    ? t('imageGeneration.workflows.kindOpenAIImagesCompatible')
    : t('imageGeneration.workflows.kindComfyUI')

const eventType = (event: string): TimelineLevel => {
  if (event === 'done' || event === 'image' || event === 'page_done') {
    return 'success'
  }
  if (event === 'suspended') {
    return 'warning'
  }
  if (event === 'error') {
    return 'danger'
  }
  return 'primary'
}

const describePayload = (event: string, payload: Record<string, unknown>) => {
  if (typeof payload.code === 'string') {
    const key = `backendErrors.${payload.code}`
    const translated = t(key)
    if (translated !== key) {
      return translated
    }
  }
  if (event === 'start') {
    return t('imageGeneration.events.startText', {
      taskId: String(payload.task_id ?? '-'),
      total: String(payload.total ?? '-'),
    })
  }
  if (event === 'page_task') {
    return t('imageGeneration.events.pageTaskText', {
      pageNo: String(payload.page_no ?? '-'),
      taskId: String(payload.page_task_id ?? '-'),
    })
  }
  if (event === 'image') {
    return t('imageGeneration.events.imageText', {
      pageNo: String(payload.page_no ?? '-'),
      imageId: String(payload.id ?? '-'),
    })
  }
  if (event === 'queued') {
    return t('imageGeneration.events.queuedText', {
      pageNo: String(payload.page_no ?? '-'),
      promptId: String(payload.comfy_prompt_id ?? '-'),
    })
  }
  if (event === 'polling') {
    return t('imageGeneration.events.pollingText', {
      pageNo: String(payload.page_no ?? '-'),
      count: String(payload.poll_count ?? '-'),
    })
  }
  if (event === 'progress') {
    return t('imageGeneration.events.progressText', {
      completed: String(payload.completed ?? '-'),
      total: String(payload.total ?? '-'),
      succeeded: String(payload.succeeded ?? '-'),
      failed: String(payload.failed ?? '-'),
    })
  }
  if (event === 'error') {
    return String(payload.message ?? t('imageGeneration.errors.generateFailed'))
  }
  if (event === 'suspended') {
    return t('imageGeneration.events.suspendedText', {
      taskId: String(payload.task_id ?? '-'),
    })
  }
  return String(payload.message ?? payload.status ?? '')
}

const addProgressEvent = (event: string, payload: Record<string, unknown> = {}) => {
  const titleKey = `imageGeneration.events.${event}`
  const translated = t(titleKey)
  progressEvents.value.unshift({
    id: eventSequence.value,
    title: translated === titleKey ? event : translated,
    content: describePayload(event, payload),
    timestamp: nowLabel(),
    type: eventType(event),
  })
  eventSequence.value += 1
}

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
  return ['negative', 'low quality', 'bad anatomy', 'blurry', 'watermark', 'worst quality'].some((keyword) =>
    normalized.includes(keyword),
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

  const positiveCandidates = candidates.filter((candidate) => !looksLikeNegativePrompt(candidate.text))
  const candidate = positiveCandidates[0] ?? candidates[0] ?? null
  return {
    candidate,
    multiple: candidates.length > 1,
  }
}

const isSeedNode = (node: WorkflowNode) => {
  const classType = String(node.class_type ?? '')
  const inputs = node.inputs
  return inputs !== undefined && ('seed' in inputs || 'noise_seed' in inputs) && (
    classType === 'KSampler' ||
    classType === 'KSamplerAdvanced' ||
    classType.includes('Sampler')
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

const streamPayload = () => ({
  tool_preset_id: selectedWorkflowId.value ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  wait_timeout_seconds: generationForm.wait_timeout_seconds,
  candidates_per_page: generationForm.candidates_per_page,
  generation_mode: generationForm.generation_mode,
  seed_strategy: generationForm.seed_strategy,
})

const ensureWorkflowSeedConfigured = () => {
  const workflow = selectedWorkflow.value
  if (workflow === null) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
    return false
  }
  if (
    workflow.provider === 'comfyui' &&
    (!workflow.seed_node_id || !workflow.seed_input_name)
  ) {
    ElMessage.warning(t('imageGeneration.errors.workflowSeedRequired'))
    return false
  }
  return true
}

const loadProjects = async () => {
  projects.value = await listProjects()
  if (!projects.value.some((project) => project.id === selectedProjectId.value)) {
    selectedProjectId.value = projects.value[0]?.id ?? null
  }
}

const loadWorkflows = async () => {
  workflows.value = await listImageGenerationTools()
  const defaultWorkflow = workflows.value.find((workflow) => workflow.is_default) ?? workflows.value[0]
  if (selectedWorkflowId.value === null && defaultWorkflow !== undefined) {
    selectedWorkflowId.value = defaultWorkflow.id
  }
}

const loadTasks = async () => {
  if (selectedProjectId.value === null) {
    tasks.value = []
    selectedTaskId.value = null
    return
  }
  loadingTasks.value = true
  try {
    tasks.value = await listProjectScriptTasks(selectedProjectId.value, { status: 'succeeded' })
    selectedTaskId.value = tasks.value[0]?.id ?? null
  } finally {
    loadingTasks.value = false
  }
}

const loadPages = async () => {
  if (selectedTaskId.value === null) {
    pages.value = []
    return
  }
  loadingPages.value = true
  try {
    pages.value = await listImageGenerationPages(selectedTaskId.value, {
      promptType: selectedWorkflow.value?.prompt_type,
      generationMode: generationForm.generation_mode,
    })
  } catch {
    pages.value = []
    ElMessage.error(t('imageGeneration.errors.loadPagesFailed'))
  } finally {
    loadingPages.value = false
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadProjects(), loadWorkflows()])
    await loadTasks()
    await loadPages()
  } catch {
    ElMessage.error(t('imageGeneration.errors.loadFailed'))
  } finally {
    loading.value = false
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
    ElMessage.warning(error instanceof Error ? error.message : t('imageGeneration.errors.configurationJsonInvalid'))
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
  if (payload.provider === 'openai_images_compatible' && (!payload.api_base_url || !payload.model)) {
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
    if (selectedWorkflowId.value === workflow.id) {
      selectedWorkflowId.value = null
    }
    await loadWorkflows()
    ElMessage.success(t('imageGeneration.messages.workflowDeleted'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('imageGeneration.errors.deleteWorkflowFailed'))
    }
  }
}

const upsertImage = (payload: Record<string, unknown>) => {
  const pageNo = Number(payload.page_no)
  const page = pages.value.find((item) => item.page_no === pageNo)
  if (page === undefined) {
    return
  }
  const image = payload as unknown as GeneratedImage
  const index = page.images.findIndex((item) => item.id === image.id)
  if (index >= 0) {
    page.images.splice(index, 1, image)
  } else {
    page.images.unshift(image)
  }
}

const generateBatch = async () => {
  if (!canGenerate.value || selectedTaskId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectTaskAndWorkflow'))
    return
  }
  if (!ensureWorkflowSeedConfigured()) {
    return
  }
  generating.value = true
  try {
    await streamGenerateImagesForTask(selectedTaskId.value, streamPayload(), {
      onEvent: (event, payload) => {
        addProgressEvent(event, payload)
        if (event === 'start') {
          const taskId = Number(payload.task_id)
          currentGenerationTaskId.value = Number.isFinite(taskId) ? taskId : null
        }
        if (event === 'image') {
          upsertImage(payload)
        }
        if (event === 'done') {
          void loadPages()
          ElMessage.success(t('imageGeneration.messages.generated'))
        }
        if (event === 'suspended') {
          generating.value = false
          continuing.value = false
          suspending.value = false
          void loadPages()
          ElMessage.warning(t('imageGeneration.messages.suspended'))
        }
      },
      onError: (error) => {
        const message = apiErrorMessage(error, t, t('imageGeneration.errors.generateFailed'))
        addProgressEvent('error', {
          code: error.code,
          message,
        })
        ElMessage.error(message)
      },
    })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.generateFailed')))
  } finally {
    generating.value = false
    suspending.value = false
  }
}

const continueBatch = async () => {
  if (selectedTaskId.value === null || selectedWorkflowId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectTaskAndWorkflow'))
    return
  }
  if (pagesNeedingContinuation.value.length === 0) {
    ElMessage.info(t('imageGeneration.messages.noPagesToContinue'))
    return
  }
  if (!canContinueGeneration.value) {
    return
  }
  if (!ensureWorkflowSeedConfigured()) {
    return
  }
  continuing.value = true
  try {
    await streamContinueImagesForTask(selectedTaskId.value, streamPayload(), {
      onEvent: (event, payload) => {
        addProgressEvent(event, payload)
        if (event === 'start') {
          const taskId = Number(payload.task_id)
          currentGenerationTaskId.value = Number.isFinite(taskId) ? taskId : null
        }
        if (event === 'image') {
          upsertImage(payload)
        }
        if (event === 'done') {
          void loadPages()
          const total = Number(payload.total ?? 0)
          ElMessage.success(
            total === 0
              ? t('imageGeneration.messages.noPagesToContinue')
              : t('imageGeneration.messages.continued'),
          )
        }
        if (event === 'suspended') {
          generating.value = false
          continuing.value = false
          suspending.value = false
          void loadPages()
          ElMessage.warning(t('imageGeneration.messages.suspended'))
        }
      },
      onError: (error) => {
        const message = apiErrorMessage(error, t, t('imageGeneration.errors.continueFailed'))
        addProgressEvent('error', {
          code: error.code,
          message,
        })
        ElMessage.error(message)
      },
    })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.continueFailed')))
  } finally {
    continuing.value = false
    suspending.value = false
  }
}

const generatePage = async (page: ImageGenerationPage) => {
  if (generationRunning.value) {
    return
  }
  if (selectedWorkflowId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
    return
  }
  if (!ensureWorkflowSeedConfigured()) {
    return
  }
  generating.value = true
  try {
    await streamGenerateImagesForPage(page.page_id, streamPayload(), {
      onEvent: (event, payload) => {
        addProgressEvent(event, payload)
        if (event === 'image') {
          upsertImage(payload)
        }
        if (event === 'done') {
          void loadPages()
          ElMessage.success(t('imageGeneration.messages.generated'))
        }
      },
      onError: (error) => {
        const message = apiErrorMessage(error, t, t('imageGeneration.errors.generateFailed'))
        addProgressEvent('error', {
          code: error.code,
          message,
        })
        ElMessage.error(message)
      },
    })
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.generateFailed')))
  } finally {
    generating.value = false
  }
}

const suspendGeneration = async () => {
  if (currentGenerationTaskId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.noCurrentTask'))
    return
  }
  suspending.value = true
  try {
    await suspendImageGenerationTask(currentGenerationTaskId.value)
    ElMessage.info(t('imageGeneration.messages.suspendRequested'))
  } catch {
    suspending.value = false
    ElMessage.error(t('imageGeneration.errors.suspendFailed'))
  }
}

const selectFinalImage = async (page: ImageGenerationPage, image: GeneratedImage) => {
  try {
    const nextPage = await selectGeneratedImage(page.page_id, image.id)
    const index = pages.value.findIndex((item) => item.page_id === nextPage.page_id)
    if (index >= 0) {
      pages.value.splice(index, 1, nextPage)
    }
    ElMessage.success(t('imageGeneration.messages.imageSelected'))
  } catch {
    ElMessage.error(t('imageGeneration.errors.selectImageFailed'))
  }
}

const openDetail = (image: GeneratedImage) => {
  detailImage.value = image
  detailVisible.value = true
}

const openProvenance = async (image: GeneratedImage) => {
  if (image.generation_run_id === null) return
  provenanceVisible.value = true
  provenanceLoading.value = true
  generationRun.value = null
  try {
    generationRun.value = await getGenerationRun(image.generation_run_id)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.loadProvenanceFailed')))
  } finally {
    provenanceLoading.value = false
  }
}

const openPromote = (image: GeneratedImage) => {
  promoteImage.value = image
  promoteForm.entity_type = 'character'
  promoteForm.entity_id = null
  promoteForm.entity_key = ''
  promoteForm.role = 'identity_face'
  promoteForm.approve = false
  promoteVisible.value = true
}

const savePromotion = async () => {
  const image = promoteImage.value
  if (image === null || (promoteForm.entity_id === null && !promoteForm.entity_key.trim())) {
    ElMessage.warning(t('imageGeneration.errors.promoteOwnerRequired'))
    return
  }
  promoting.value = true
  try {
    await promoteGeneratedImage(image.id, {
      entity_type: promoteForm.entity_type,
      entity_id: promoteForm.entity_id,
      entity_key: promoteForm.entity_key.trim() || null,
      role: promoteForm.role,
      approve: promoteForm.approve,
    })
    promoteVisible.value = false
    ElMessage.success(t('imageGeneration.messages.promoted'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.promoteFailed')))
  } finally {
    promoting.value = false
  }
}

watch(selectedProjectId, () => {
  pages.value = []
  void loadTasks()
})

watch(selectedTaskId, () => {
  void loadPages()
})

watch(selectedWorkflowId, () => {
  void loadPages()
})

watch(() => generationForm.generation_mode, () => {
  void loadPages()
})

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <section v-loading="loading" class="image-generation-page">
    <div class="image-generation-grid">
      <section class="panel generation-config">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.generation.title') }}</h2>
            <p>{{ t('imageGeneration.generation.description') }}</p>
          </div>
        </header>

        <el-form label-position="top">
          <el-form-item :label="t('imageGeneration.generation.project')">
            <el-select v-model="selectedProjectId" filterable>
              <el-option v-for="project in projects" :key="project.id" :label="project.title" :value="project.id" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.generation.scriptTask')">
            <el-select v-model="selectedTaskId" :loading="loadingTasks" filterable>
              <el-option v-for="task in tasks" :key="task.id" :label="taskLabel(task)" :value="task.id" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.generation.workflow')">
            <el-select v-model="selectedWorkflowId" filterable>
              <el-option
                v-for="workflow in workflows"
                :key="workflow.id"
                :label="`${workflow.name} · ${providerLabel(workflow.provider)} · ${t(`imageSpecs.promptTypes.${workflow.prompt_type}`)}`"
                :value="workflow.id"
              />
            </el-select>
          </el-form-item>
          <div class="generation-config__numbers">
            <el-form-item :label="t('imageGeneration.generation.pollInterval')">
              <el-input-number v-model="generationForm.poll_interval_seconds" :min="0.5" :max="20" :step="0.5" />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.waitTimeout')">
              <el-input-number v-model="generationForm.wait_timeout_seconds" :min="30" :max="3600" :step="30" />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.candidates')">
              <el-input-number v-model="generationForm.candidates_per_page" :min="1" :max="4" />
            </el-form-item>
          </div>
          <div class="generation-config__numbers">
            <el-form-item :label="t('imageGeneration.generation.mode')">
              <el-segmented
                v-model="generationForm.generation_mode"
                :options="[
                  { label: t('imageGeneration.generation.preview'), value: 'preview' },
                  { label: t('imageGeneration.generation.final'), value: 'final' },
                ]"
              />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.seedStrategy')">
              <el-select v-model="generationForm.seed_strategy">
                <el-option :label="t('imageGeneration.generation.perPageSeed')" value="per_page" />
                <el-option
                  :label="t('imageGeneration.generation.sharedCandidateSeed')"
                  value="shared_candidate"
                />
              </el-select>
            </el-form-item>
          </div>
        </el-form>

        <el-alert
          v-if="generationForm.generation_mode === 'final'"
          type="warning"
          :closable="false"
          :title="t('imageGeneration.generation.finalHint')"
        />
        <el-alert
          v-if="selectedWorkflow"
          class="model-license-alert"
          type="info"
          :closable="false"
          :title="t('imageGeneration.generation.toolPromptType', {
            provider: providerLabel(selectedWorkflow.provider),
            promptType: t(`imageSpecs.promptTypes.${selectedWorkflow.prompt_type}`),
          })"
        />

        <div class="generation-actions">
          <el-button
            class="ai-gradient-button"
            type="primary"
            :icon="Picture"
            :loading="generating"
            :disabled="!canGenerate"
            @click="generateBatch"
          >
            {{ t('imageGeneration.actions.generate') }}
          </el-button>
          <el-button
            v-if="pagesNeedingContinuation.length > 0"
            type="primary"
            plain
            :icon="Picture"
            :loading="continuing"
            :disabled="!canContinueGeneration"
            @click="continueBatch"
          >
            {{ t('imageGeneration.actions.continue') }}
          </el-button>
          <el-button
            v-if="generationRunning"
            type="warning"
            :icon="VideoPause"
            :loading="suspending"
            :disabled="currentGenerationTaskId === null || suspending"
            @click="suspendGeneration"
          >
            {{ t('imageGeneration.actions.suspend') }}
          </el-button>
        </div>
      </section>

      <section class="panel workflow-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.workflows.title') }}</h2>
            <p>{{ t('imageGeneration.workflows.description') }}</p>
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
              <p>{{ workflow.description || t('imageGeneration.emptyText') }}</p>
            </div>
            <div class="workflow-actions">
              <el-button link type="primary" :icon="EditPen" @click="openEditWorkflow(workflow)">
                {{ t('projects.edit') }}
              </el-button>
              <el-button link type="danger" :icon="Delete" @click="removeWorkflow(workflow)">
                {{ t('imageGeneration.actions.deleteWorkflow') }}
              </el-button>
            </div>
          </article>
          <el-empty v-if="workflows.length === 0" :description="t('imageGeneration.workflows.empty')" />
        </div>
      </section>

      <section class="panel progress-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.progress.title') }}</h2>
            <p>{{ t('imageGeneration.progress.description') }}</p>
          </div>
        </header>
        <el-scrollbar height="360px">
          <el-empty v-if="progressEvents.length === 0" :description="t('imageGeneration.progress.empty')" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="event in progressEvents"
              :key="event.id"
              :timestamp="event.timestamp"
              :type="event.type"
            >
              <strong>{{ event.title }}</strong>
              <p>{{ event.content }}</p>
            </el-timeline-item>
          </el-timeline>
        </el-scrollbar>
      </section>

      <section class="panel result-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.pages.title') }}</h2>
            <p>{{ selectedProject?.title || t('imageGeneration.pages.noProject') }}</p>
          </div>
        </header>

        <el-table v-loading="loadingPages" :data="sortedPages" height="620">
          <el-table-column prop="page_no" :label="t('imageGeneration.pages.pageNo')" width="80" />
          <el-table-column :label="t('imageGeneration.pages.prompt')" min-width="240">
            <template #default="{ row }">
              <div class="spec-readiness">
                <el-tag size="small" :type="row.latest_spec_id ? 'success' : 'danger'">
                  {{ row.latest_spec_id ? `ImageSpec #${row.latest_spec_id}` : t('imageGeneration.pages.specMissing') }}
                </el-tag>
                <el-tag v-if="row.spec_warnings.length" size="small" type="warning">
                  {{ t('imageGeneration.pages.warningCount', { count: row.spec_warnings.length }) }}
                </el-tag>
                <span>{{ shortText(row.positive_prompt) }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('imageGeneration.pages.images')" min-width="360">
            <template #default="{ row }">
              <div class="image-strip">
                <article v-for="image in row.images" :key="image.id" class="image-card">
                  <el-image :src="image.image_url || ''" fit="cover" class="image-card__img" />
                  <div class="image-card__actions">
                    <el-tag v-if="image.is_selected" size="small" type="success">
                      {{ t('imageGeneration.pages.selected') }}
                    </el-tag>
                    <el-button link type="primary" :icon="View" @click="openDetail(image)">
                      {{ t('imageGeneration.actions.view') }}
                    </el-button>
                    <el-button
                      v-if="image.generation_run_id"
                      link
                      type="primary"
                      @click="openProvenance(image)"
                    >
                      {{ t('imageGeneration.actions.provenance') }}
                    </el-button>
                    <el-button link type="warning" @click="openPromote(image)">
                      {{ t('imageGeneration.actions.promote') }}
                    </el-button>
                    <el-button link type="success" :icon="Select" @click="selectFinalImage(row, image)">
                      {{ t('imageGeneration.actions.select') }}
                    </el-button>
                  </div>
                </article>
                <span v-if="row.images.length === 0" class="muted">{{ t('imageGeneration.pages.noImages') }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('imageGeneration.pages.actions')" width="130" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :disabled="generating || !pageSpecificationReady(row)"
                @click="generatePage(row)"
              >
                {{ t('imageGeneration.actions.generatePage') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <el-dialog
      v-if="workflowDialogVisible"
      v-model="workflowDialogVisible"
      destroy-on-close
      :title="t('imageGeneration.workflows.editorTitle')"
      width="920px"
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
              <el-option :label="t('imageSpecs.promptTypes.natural_language')" value="natural_language" />
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
        <el-alert
          type="info"
          :closable="false"
          :title="t('imageGeneration.workflows.structuredHint')"
        />
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
              v-if="!promptMappingReady || !seedMappingReady"
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
              <el-form-item
                :label="t('imageGeneration.workflows.seedNode')"
                required
              >
                <el-input v-model="workflowForm.seed_node_id" />
              </el-form-item>
              <el-form-item
                :label="t('imageGeneration.workflows.seedInput')"
                required
              >
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
            <el-alert
              type="info"
              :closable="false"
              :title="t('imageGeneration.workflows.advancedHint')"
            />
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

    <el-dialog
      v-model="detailVisible"
      :title="t('imageGeneration.detail.title')"
      width="min(920px, 92vw)"
      top="4vh"
      class="image-detail-dialog"
    >
      <el-image v-if="detailImage?.image_url" :src="detailImage.image_url" fit="contain" class="detail-image" />
      <pre class="image-meta">{{ detailImage }}</pre>
    </el-dialog>

    <el-drawer
      v-model="provenanceVisible"
      size="58%"
      :title="generationRun ? `GenerationRun #${generationRun.id}` : t('imageGeneration.provenance.title')"
    >
      <section v-loading="provenanceLoading" class="provenance-content">
        <template v-if="generationRun">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('imageGeneration.provenance.status')">
              {{ generationRun.status }}
            </el-descriptions-item>
            <el-descriptions-item label="ImageSpec">#{{ generationRun.image_spec_id }}</el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.workflows.kind')">{{ generationRun.provider }}</el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.workflows.promptType')">{{ generationRun.prompt_type }}</el-descriptions-item>
            <el-descriptions-item label="Seed">
              {{ generationRun.seed }} · {{ generationRun.seed_strategy }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.provenance.workflowHash')">
              {{ generationRun.workflow_hash || '-' }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.provenance.externalRequest')">
              {{ generationRun.external_request_id || '-' }}
            </el-descriptions-item>
          </el-descriptions>
          <h3>{{ t('imageGeneration.provenance.degradations') }}</h3>
          <pre>{{ JSON.stringify(generationRun.degradations, null, 2) }}</pre>
          <h3>{{ t('imageGeneration.provenance.assets') }}</h3>
          <pre>{{ JSON.stringify(generationRun.resolved_assets, null, 2) }}</pre>
          <h3>{{ t('imageGeneration.provenance.bindings') }}</h3>
          <pre>{{ JSON.stringify(generationRun.bindings, null, 2) }}</pre>
          <h3>Workflow</h3>
          <pre>{{ JSON.stringify(generationRun.workflow, null, 2) }}</pre>
        </template>
      </section>
    </el-drawer>

    <el-dialog
      v-model="promoteVisible"
      :title="t('imageGeneration.promotion.title')"
      width="620px"
    >
      <el-alert type="info" :closable="false" :title="t('imageGeneration.promotion.hint')" />
      <el-form label-position="top" class="promotion-form">
        <div class="workflow-node-grid">
          <el-form-item :label="t('imageGeneration.promotion.entityType')">
            <el-select v-model="promoteForm.entity_type">
              <el-option label="Character" value="character" />
              <el-option label="Outfit" value="outfit" />
              <el-option label="Scene" value="scene" />
              <el-option label="Style" value="style" />
              <el-option label="Prop" value="prop" />
              <el-option label="Control" value="control" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.ownerId')">
            <el-input-number v-model="promoteForm.entity_id" :min="1" controls-position="right" />
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.ownerKey')">
            <el-input v-model="promoteForm.entity_key" />
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.role')">
            <el-select v-model="promoteForm.role" filterable>
              <el-option
                v-for="role in ['identity_face', 'identity_half_body', 'identity_full_body', 'outfit_front', 'outfit_back', 'outfit_detail', 'scene_master', 'style_reference', 'prop_reference', 'pose', 'depth', 'canny', 'lineart', 'segmentation', 'mask']"
                :key="role"
                :label="role"
                :value="role"
              />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-checkbox v-model="promoteForm.approve">
              {{ t('imageGeneration.promotion.approve') }}
            </el-checkbox>
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="promoteVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" :loading="promoting" @click="savePromotion">
          {{ t('imageGeneration.actions.promote') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.image-generation-page {
  display: grid;
  gap: 28px;
}

.page-header,
.panel-header {
  display: flex;
  gap: 16px;
}

.page-header {
  justify-content: flex-end;
}

.panel-header {
  justify-content: space-between;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.panel-header p,
.muted {
  color: var(--text-soft);
}

.image-generation-grid {
  display: grid;
  grid-template-columns: minmax(360px, 0.8fr) minmax(420px, 1fr);
  gap: 18px;
  align-items: start;
}

.panel {
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  padding: 22px;
}

.result-panel {
  grid-column: 1 / -1;
}

.generation-config__numbers,
.workflow-form-grid,
.workflow-node-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.generation-config__numbers,
.workflow-structured-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.model-license-alert,
.promotion-form {
  margin-top: 14px;
}

.workflow-json-tools {
  display: grid;
  gap: 12px;
  width: 100%;
}

.workflow-section-title {
  margin: 20px 0 14px;
  color: var(--text-main);
  font-size: 15px;
}

.workflow-section-title:first-child {
  margin-top: 0;
}

.workflow-advanced {
  margin-top: 18px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
}

.workflow-advanced :deep(.el-collapse-item__header) {
  padding: 0 14px;
}

.workflow-advanced :deep(.el-collapse-item__content) {
  padding: 14px;
}

.workflow-form-status {
  margin-top: 16px;
}

.json-validation {
  width: 100%;
  margin: 6px 0 0;
  color: var(--el-color-success);
  font-size: 12px;
}

.json-validation--invalid {
  color: var(--el-color-danger);
}

.workflow-upload {
  width: 100%;
}

.workflow-upload__icon {
  margin-bottom: 8px;
  font-size: 28px;
  color: var(--text-soft);
}

.workflow-upload__text {
  color: var(--text-regular);
}

.generation-actions {
  display: flex;
  gap: 10px;
}

.workflow-list {
  display: grid;
  gap: 12px;
  margin-top: 18px;
}

.workflow-item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
}

.workflow-item p {
  margin: 6px 0 0;
  color: var(--text-soft);
}

.workflow-item__title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.workflow-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.image-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.spec-readiness {
  display: grid;
  justify-items: start;
  gap: 6px;
}

.image-card {
  width: 132px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  overflow: hidden;
  background: #f8fafc;
}

.image-card__img {
  width: 132px;
  height: 132px;
  display: block;
}

.image-card__actions {
  display: grid;
  gap: 4px;
  padding: 8px;
}

.detail-image {
  display: flex;
  justify-content: center;
  width: 100%;
  max-height: 76vh;
  overflow: hidden;
  background: #0b1220;
  border-radius: 8px;
}

.detail-image :deep(.el-image__inner) {
  width: auto;
  max-width: 100%;
  max-height: 76vh;
  object-fit: contain;
}

.image-meta {
  max-height: 160px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.provenance-content {
  min-height: 180px;
}

.provenance-content pre {
  max-height: 360px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #0b1220;
  color: #d9e6f4;
  white-space: pre-wrap;
  word-break: break-word;
}

:deep(.image-detail-dialog .el-dialog__body) {
  max-height: calc(100vh - 140px);
  overflow: auto;
}

@media (max-width: 1180px) {
  .image-generation-grid,
  .generation-config__numbers,
  .workflow-structured-grid,
  .workflow-node-grid {
    grid-template-columns: 1fr;
  }
}
</style>

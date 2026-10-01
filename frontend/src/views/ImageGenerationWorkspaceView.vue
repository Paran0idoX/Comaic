<script setup lang="ts">
import {
  Delete,
  EditPen,
  MoreFilled,
  Picture,
  Plus,
  Search,
  Select,
  UploadFilled,
  VideoPause,
  View,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  createImageGenerationTool,
  deleteImageGenerationTool,
  getGenerationRun,
  listGenerationBatches,
  listImageGenerationTools,
  listImageGenerationPages,
  selectGeneratedImage,
  streamContinueImagesForBatch,
  streamGenerateImagesForPage,
  streamGenerateImagesForTask,
  suspendImageGenerationTask,
  updateImageGenerationTool,
  type ImageGenerationTool,
  type GeneratedImage,
  type GenerationRun,
  type GenerationTask,
  type ImageGenerationPage,
  type ImageGenerationStreamCallbacks,
} from '@/api/imageGeneration'
import {
  adoptConsistencyTrack,
  createConsistencyEvaluation,
  getConsistencyEvaluation,
  getConsistencyGate,
  getConsistencyReadiness,
  listConsistencyEvaluations,
  type ConsistencyEvaluationTask,
  type ConsistencyGate,
  type ConsistencyMetricKey,
  type ConsistencyReadiness,
  type ConsistencyTrack,
} from '@/api/consistencyEvaluation'
import { apiErrorMessage } from '@/api/errors'
import { listProjectScriptTasks, type ScriptTask } from '@/api/scripts'
import { listProjectCharacterReferenceCharacters, type CharacterReferenceCharacter } from '@/api/characterReference'
import { listReferenceSubjects, listReferenceCategories, type ReferenceSubject, type ReferenceCategoryDefinition } from '@/api/referenceImages'
import {
  promoteGeneratedImage,
  listOutfits, type OutfitVariant,
  type VisualAssetRole,
  type VisualEntityType,
} from '@/api/visualBible'
import { formatLocalNowTime } from '@/utils/datetime'
import { useProjectContextStore } from '@/stores/projectContext'
import { useActivityCenterStore, type ActivityStatus } from '@/stores/activityCenter'
import WorkflowReadiness, {
  type ReadinessItem,
} from '@/components/workspace/WorkflowReadiness.vue'
import ReferenceImagePlan from '@/components/workspace/ReferenceImagePlan.vue'
import ReferenceToolConfiguration from '@/components/workspace/ReferenceToolConfiguration.vue'

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
const route = useRoute()
const router = useRouter()
const projectContext = useProjectContextStore()
const activityCenter = useActivityCenterStore()
const { selectedProjectId, projects } = storeToRefs(projectContext)

const tasks = ref<ScriptTask[]>([])
const workflows = ref<ImageGenerationTool[]>([])
const pages = ref<ImageGenerationPage[]>([])
const batches = ref<GenerationTask[]>([])
const selectedTaskId = ref<number | null>(null)
const selectedBatchId = ref<number | null>(null)
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
const promotionProjectId = ref<number | null>(null)
const promotionCharacters = ref<CharacterReferenceCharacter[]>([])
const promotionSubjects = ref<ReferenceSubject[]>([])
const promotionCatalog = ref<ReferenceCategoryDefinition[]>([])
const promotionOutfits = ref<OutfitVariant[]>([])
const promoting = ref(false)
const progressEvents = ref<ProgressEvent[]>([])
const eventSequence = ref(1)
const consistencyReadiness = ref<ConsistencyReadiness | null>(null)
const consistencyTask = ref<ConsistencyEvaluationTask | null>(null)
const consistencyGate = ref<ConsistencyGate | null>(null)
const consistencyLoading = ref(false)
const consistencySubmitting = ref(false)
const adoptingTrackId = ref<number | null>(null)
const activeGenerationTab = ref<'generate' | 'consistency' | 'results' | 'tools'>(
  ['generate', 'consistency', 'results', 'tools'].includes(String(route.query.tab))
    ? (String(route.query.tab) as 'generate' | 'consistency' | 'results' | 'tools')
    : 'generate',
)
const pageSearch = ref(localStorage.getItem('comaic-image-page-search') ?? '')
const pageStatusFilter = ref<'all' | 'ready' | 'missing' | 'generated' | 'selected'>('all')
const pageTablePage = ref(1)
const pageTablePageSize = ref(20)
let consistencyPollToken = 0
let projectLoadToken = 0
let pageLoadToken = 0
let batchLoadToken = 0
let viewMounted = true
let restoringProject = false
type GenerationContext = { projectId: number; scriptTaskId: number; batchId: number | null; completed: number; total: number }
const runningGeneration = ref<GenerationContext | null>(null)
const configurationOpen = ref(true)
const taskLocationUnavailable = ref(false)
const batchLocationUnavailable = ref(false)
const targetUnavailable = computed(() => taskLocationUnavailable.value || batchLocationUnavailable.value)
const queryId = (value: unknown) => {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}
const generationContextVisible = (context: GenerationContext) => viewMounted &&
  context.projectId === selectedProjectId.value && context.scriptTaskId === selectedTaskId.value &&
  (context.batchId === null || context.batchId === selectedBatchId.value)
const visibleGenerationRunning = computed(() => runningGeneration.value !== null && generationContextVisible(runningGeneration.value) && generationRunning.value)
const legacyActivityLocation = computed(() => route.query.activity_legacy === '1')

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
  reference_subject_id: null as number | null,
  outfit_variant_id: null as number | null,
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
const selectedBatch = computed(
  () => batches.value.find((batch) => batch.id === selectedBatchId.value) ?? null,
)
const sortedPages = computed(() =>
  [...pages.value].sort((left, right) => left.page_no - right.page_no),
)
const generationRunning = computed(() => generating.value || continuing.value)
const pageSpecificationReady = (page: ImageGenerationPage) =>
  page.latest_spec_id !== null &&
  (generationForm.generation_mode === 'preview' || page.spec_warnings.length === 0)
const specReadyPageCount = computed(
  () => pages.value.filter((page) => pageSpecificationReady(page)).length,
)
const generatedPageCount = computed(
  () => pages.value.filter((page) => page.images.length > 0).length,
)
const selectedImagePageCount = computed(
  () => pages.value.filter((page) => page.selected_image_id !== null).length,
)
const filteredPages = computed(() => {
  const query = pageSearch.value.trim().toLowerCase()
  return sortedPages.value.filter((page) => {
    const statusMatches =
      pageStatusFilter.value === 'all' ||
      (pageStatusFilter.value === 'ready' && pageSpecificationReady(page)) ||
      (pageStatusFilter.value === 'missing' && !pageSpecificationReady(page)) ||
      (pageStatusFilter.value === 'generated' && page.images.length > 0) ||
      (pageStatusFilter.value === 'selected' && page.selected_image_id !== null)
    if (!statusMatches) return false
    if (!query) return true
    return [page.page_no, page.positive_prompt]
      .filter((value) => value !== null)
      .some((value) => String(value).toLowerCase().includes(query))
  })
})
const paginatedPages = computed(() => {
  const start = (pageTablePage.value - 1) * pageTablePageSize.value
  return filteredPages.value.slice(start, start + pageTablePageSize.value)
})
const canGenerate = computed(
  () =>
    selectedTaskId.value !== null &&
    selectedWorkflowId.value !== null &&
    pages.value.length > 0 &&
    pages.value.every(pageSpecificationReady) &&
    !generationRunning.value,
)
const generationReadinessItems = computed<ReadinessItem[]>(() => [
  {
    key: 'task',
    label: t('imageGeneration.readiness.scriptTask'),
    detail: selectedTaskId.value
      ? t('imageGeneration.readiness.selectedTask', { id: selectedTaskId.value })
      : t('imageGeneration.readiness.taskMissing'),
    status: selectedTaskId.value ? 'ready' : 'blocked',
    to: selectedTaskId.value ? undefined : { path: '/scripts', query: { project_id: selectedProjectId.value ?? undefined } },
    actionLabel: selectedTaskId.value ? undefined : t('imageGeneration.readiness.openScripts'),
  },
  {
    key: 'specs',
    label: t('imageGeneration.readiness.specs'),
    detail: t('imageGeneration.readiness.specProgress', {
      ready: specReadyPageCount.value,
      total: pages.value.length,
    }),
    status:
      pages.value.length > 0 && specReadyPageCount.value === pages.value.length
        ? 'ready'
        : 'blocked',
    to: { path: '/image-specs', query: { project_id: selectedProjectId.value ?? undefined, script_task_id: selectedTaskId.value ?? undefined } },
    actionLabel: t('imageGeneration.readiness.openSpecs'),
  },
  {
    key: 'tool',
    label: t('imageGeneration.readiness.tool'),
    detail: selectedWorkflow.value?.name ?? t('imageGeneration.readiness.toolMissing'),
    status: selectedWorkflow.value ? 'ready' : 'blocked',
    to: { path: '/image-generation', query: { ...route.query, tab: 'tools' } },
    actionLabel: t('imageGeneration.readiness.manageTools'),
  },
  {
    key: 'results',
    label: t('imageGeneration.readiness.results'),
    detail: t('imageGeneration.readiness.resultProgress', {
      generated: generatedPageCount.value,
      selected: selectedImagePageCount.value,
      total: pages.value.length,
    }),
    status: generatedPageCount.value > 0 ? 'info' : 'pending',
    to: { path: '/image-generation', query: { ...route.query, tab: 'results' } },
    actionLabel: t('imageGeneration.readiness.openResults'),
  },
])
const batchCanContinue = computed(
  () =>
    selectedBatch.value !== null && ['failed', 'suspended'].includes(selectedBatch.value.status),
)
const canContinueGeneration = computed(
  () =>
    selectedBatch.value !== null &&
    selectedBatch.value.tool_preset_id !== null &&
    batchCanContinue.value &&
    !generationRunning.value,
)
const consistencyRunning = computed(() =>
  ['pending', 'waiting_resource', 'running'].includes(consistencyTask.value?.status ?? ''),
)
const consistencyResultCurrent = computed(
  () =>
    consistencyTask.value?.status === 'succeeded' &&
    consistencyTask.value.source_hash === consistencyReadiness.value?.source_hash &&
    consistencyTask.value.metric_version === consistencyReadiness.value?.metric_version,
)
const canEvaluateConsistency = computed(
  () =>
    selectedBatch.value !== null &&
    consistencyReadiness.value?.ready === true &&
    !consistencyRunning.value &&
    !consistencyResultCurrent.value &&
    !consistencySubmitting.value,
)
const consistencyMetricKeys: ConsistencyMetricKey[] = [
  'cids_cross',
  'cids_self',
  'csd_cross',
  'csd_self',
  'occm',
  'copy_paste',
]
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
  () =>
    workflowForm.seed_node_id.trim().length > 0 && workflowForm.seed_input_name.trim().length > 0,
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

const imagePreviewUrls = (images: GeneratedImage[]) =>
  images.map((item) => item.image_url || '').filter((url) => url.length > 0)

const taskLabel = (task: ScriptTask) =>
  `#${task.id} · ${task.total_pages} ${t('imageGeneration.generation.pagesUnit')}`

const batchLabel = (batch: GenerationTask) =>
  `#${batch.id} · ${t(batch.generation_mode === 'final' ? 'ux.strict' : 'ux.relaxed')} · ${t(
    'imageGeneration.consistency.candidateCount',
    { count: batch.candidate_count },
  )} · ${t(`imageGeneration.consistency.statuses.${batch.status}`)}`

const consistencyStatusType = (status: string): TimelineLevel => {
  if (status === 'succeeded' || status === 'passed') return 'success'
  if (status === 'failed' || status === 'error') return 'danger'
  if (status === 'suspended') return 'warning'
  if (status === 'running' || status === 'waiting_resource') return 'primary'
  return 'info'
}

const consistencyIssueText = (issue: { code?: string | null; message?: string | null }) => {
  if (issue.code) {
    const key = `backendErrors.${issue.code}`
    const translated = t(key)
    if (translated !== key) return translated
  }
  return issue.message || t('imageGeneration.consistency.unknownIssue')
}

const metricApplicable = (track: ConsistencyTrack, key: ConsistencyMetricKey) =>
  track.details.applicability?.[key] !== false

const metricPassed = (track: ConsistencyTrack, key: ConsistencyMetricKey) =>
  track.details.checks?.[key]?.passed === true

const metricType = (track: ConsistencyTrack, key: ConsistencyMetricKey): TimelineLevel => {
  if (!metricApplicable(track, key)) return 'info'
  return metricPassed(track, key) ? 'success' : 'danger'
}

const formatMetric = (track: ConsistencyTrack, key: ConsistencyMetricKey) => {
  if (!metricApplicable(track, key)) return t('imageGeneration.consistency.notApplicable')
  const value = track.metrics[key]
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-'
  return key === 'occm' ? value.toFixed(1) : value.toFixed(4)
}

const metricThreshold = (key: ConsistencyMetricKey) => {
  const thresholds = consistencyTask.value?.thresholds
  if (thresholds === undefined) return null
  const fieldByMetric = {
    cids_cross: 'cids_cross_min',
    cids_self: 'cids_self_min',
    csd_cross: 'csd_cross_min',
    csd_self: 'csd_self_min',
    occm: 'occm_min',
    copy_paste: 'copy_paste_max',
  } as const
  return thresholds[fieldByMetric[key]]
}

const metricColumnLabel = (key: ConsistencyMetricKey) => {
  const label = t(`imageGeneration.consistency.metrics.${key}`)
  const threshold = metricThreshold(key)
  if (threshold === null) return label
  return `${label} ${key === 'copy_paste' ? '≤' : '≥'} ${threshold}`
}

const shortHash = (value: string | null) => (value ? `${value.slice(0, 12)}…` : '-')

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

const streamPayload = () => ({
  tool_preset_id: selectedWorkflowId.value ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  wait_timeout_seconds: generationForm.wait_timeout_seconds,
  candidates_per_page: generationForm.candidates_per_page,
  generation_mode: generationForm.generation_mode,
  seed_strategy: generationForm.seed_strategy,
})

const continuationPayload = (batch: GenerationTask) => ({
  tool_preset_id: batch.tool_preset_id ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  wait_timeout_seconds: generationForm.wait_timeout_seconds,
  candidates_per_page: batch.candidate_count,
  generation_mode: batch.generation_mode ?? 'preview',
  seed_strategy: batch.seed_strategy ?? 'per_page',
})

const ensureWorkflowSeedConfigured = () => {
  const workflow = selectedWorkflow.value
  if (workflow === null) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
    return false
  }
  if (workflow.provider === 'comfyui' && (!workflow.seed_node_id || !workflow.seed_input_name)) {
    ElMessage.warning(t('imageGeneration.errors.workflowSeedRequired'))
    return false
  }
  return true
}

const loadProjects = async () => {
  await projectContext.refreshProjects()
}

const loadWorkflows = async () => {
  workflows.value = await listImageGenerationTools()
  const defaultWorkflow =
    workflows.value.find((workflow) => workflow.is_default) ?? workflows.value[0]
  if (selectedWorkflowId.value === null && defaultWorkflow !== undefined) {
    selectedWorkflowId.value = defaultWorkflow.id
  }
}

const loadTasks = async () => {
  const projectId = selectedProjectId.value
  const token = ++projectLoadToken
  restoringProject = true
  if (projectId === null) {
    tasks.value = []
    selectedTaskId.value = null
    return
  }
  loadingTasks.value = true
  try {
    const items = await listProjectScriptTasks(projectId, { status: 'succeeded' })
    if (token !== projectLoadToken || projectId !== selectedProjectId.value) return
    tasks.value = items
    const requested = queryId(route.query.project_id) === projectId ? queryId(route.query.script_task_id) : null
    taskLocationUnavailable.value = !legacyActivityLocation.value && requested !== null && !items.some((item) => item.id === requested)
    selectedTaskId.value = legacyActivityLocation.value || taskLocationUnavailable.value ? null : items.some((item) => item.id === requested) ? requested :
      items.some((item) => item.id === selectedTaskId.value) ? selectedTaskId.value : items[0]?.id ?? null
  } finally {
    if (token === projectLoadToken) {
      loadingTasks.value = false
      restoringProject = false
    }
  }
}

const loadPages = async () => {
  const taskId = selectedTaskId.value
  const projectId = selectedProjectId.value
  const token = ++pageLoadToken
  if (taskId === null) {
    pages.value = []
    return
  }
  loadingPages.value = true
  try {
    const items = await listImageGenerationPages(taskId, {
      promptType: selectedWorkflow.value?.prompt_type,
      generationMode: generationForm.generation_mode,
    })
    if (token !== pageLoadToken || taskId !== selectedTaskId.value || projectId !== selectedProjectId.value) return
    pages.value = batchLocationUnavailable.value ? [] : items
  } catch {
    if (token !== pageLoadToken) return
    pages.value = []
    ElMessage.error(t('imageGeneration.errors.loadPagesFailed'))
  } finally {
    if (token === pageLoadToken) loadingPages.value = false
  }
}

const clearConsistencyState = () => {
  consistencyPollToken += 1
  consistencyReadiness.value = null
  consistencyTask.value = null
  consistencyGate.value = null
}

const pollConsistencyTask = async (taskId: number, token: number) => {
  try {
    while (token === consistencyPollToken) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000))
      if (token !== consistencyPollToken) return
      const next = await getConsistencyEvaluation(taskId)
      if (token !== consistencyPollToken) return
      consistencyTask.value = next
      if (!['pending', 'waiting_resource', 'running'].includes(next.status)) return
    }
  } catch (error) {
    if (token === consistencyPollToken) {
      ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.consistency.errors.loadTask')))
    }
  }
}

const loadConsistencyState = async () => {
  const batchId = selectedBatchId.value
  const scriptTaskId = selectedTaskId.value
  consistencyPollToken += 1
  const token = consistencyPollToken
  if (batchId === null || scriptTaskId === null) {
    consistencyReadiness.value = null
    consistencyTask.value = null
    consistencyGate.value = null
    return
  }
  consistencyLoading.value = true
  try {
    const [readiness, taskItems, gate] = await Promise.all([
      getConsistencyReadiness(batchId),
      listConsistencyEvaluations(batchId),
      getConsistencyGate(scriptTaskId),
    ])
    if (token !== consistencyPollToken) return
    consistencyReadiness.value = readiness
    consistencyGate.value = gate
    consistencyTask.value =
      taskItems.find((item) => item.id === queryId(route.query.evaluation_task_id)) ?? [...taskItems].sort(
        (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
      )[0] ?? null
    if (consistencyTask.value !== null && consistencyRunning.value) {
      void pollConsistencyTask(consistencyTask.value.id, token)
    }
  } catch (error) {
    if (token === consistencyPollToken) {
      consistencyReadiness.value = null
      consistencyTask.value = null
      ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.consistency.errors.load')))
    }
  } finally {
    if (token === consistencyPollToken) consistencyLoading.value = false
  }
}

const loadBatches = async () => {
  const taskId = selectedTaskId.value
  const projectId = selectedProjectId.value
  const token = ++batchLoadToken
  if (taskId === null) {
    batches.value = []
    selectedBatchId.value = null
    clearConsistencyState()
    return
  }
  const previous = selectedBatchId.value
  try {
    const items = await listGenerationBatches(taskId)
    if (token !== batchLoadToken || taskId !== selectedTaskId.value || projectId !== selectedProjectId.value) return
    batches.value = items
    const requested = queryId(route.query.batch_id)
    batchLocationUnavailable.value = !legacyActivityLocation.value && requested !== null && !items.some((batch) => batch.id === requested)
    if (batchLocationUnavailable.value) pages.value = []
    const next = legacyActivityLocation.value || batchLocationUnavailable.value ? null : items.some((batch) => batch.id === requested) ? requested : batches.value.some((batch) => batch.id === previous)
      ? previous
      : (batches.value[0]?.id ?? null)
    selectedBatchId.value = next
    syncContextQuery()
    for (const batch of items) syncGenerationActivity(batch, pages.value.length)
    if (next === previous) await loadConsistencyState()
  } catch (error) {
    if (token !== batchLoadToken) return
    batches.value = []
    selectedBatchId.value = null
    clearConsistencyState()
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.consistency.errors.loadBatches')))
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadProjects(), loadWorkflows()])
    await loadTasks()
    await Promise.all([loadPages(), loadBatches()])
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

const upsertImage = (context: GenerationContext, payload: Record<string, unknown>) => {
  if (!generationContextVisible(context)) return
  // 页码在不同项目里会重复，图片必须按页面主键匹配。
  const page = pages.value.find((item) => item.page_id === Number(payload.page_id))
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

const streamCallbacks = (context: GenerationContext, failureKey: string): ImageGenerationStreamCallbacks => ({
  onEvent: (event, payload) => {
    if (event === 'start') {
      const batchId = queryId(payload.task_id)
      if (batchId !== null) {
        context.batchId = batchId
        currentGenerationTaskId.value = batchId
        if (viewMounted && selectedProjectId.value === context.projectId && selectedTaskId.value === context.scriptTaskId) {
          selectedBatchId.value = batchId
          void loadBatches()
        }
      }
    }
    if (event === 'image') context.completed += 1
    if (context.batchId !== null) {
      activityCenter.upsertActivity({
        id: `image-generation-${context.batchId}`, kind: 'imageGeneration', label: `#${context.batchId} · ${context.completed}/${context.total}`,
        status: event === 'done' ? 'succeeded' : event === 'suspended' ? 'suspended' : event === 'error' ? 'failed' : 'running',
        progress: context.total > 0 ? Math.min(100, context.completed / context.total * 100) : null,
        route: `/image-generation?project_id=${context.projectId}&script_task_id=${context.scriptTaskId}&batch_id=${context.batchId}&tab=${event === 'done' ? 'results' : 'generate'}`,
        projectId: context.projectId, scriptTaskId: context.scriptTaskId, batchId: context.batchId, updatedAt: new Date().toISOString(),
      })
    }
    if (!generationContextVisible(context)) return
    addProgressEvent(event, payload)
    if (event === 'image') upsertImage(context, payload)
    if (event === 'done' || event === 'suspended') {
      void loadPages()
      void loadBatches()
      if (event === 'done') {
        configurationOpen.value = false
        activeGenerationTab.value = 'results'
        ElMessage.success(t('imageGeneration.messages.generated'))
      } else ElMessage.warning(t('imageGeneration.messages.suspended'))
    }
  },
  onError: (error) => {
    if (context.batchId !== null) {
      activityCenter.upsertActivity({
        id: `image-generation-${context.batchId}`, kind: 'imageGeneration', label: `#${context.batchId}`, status: 'failed', progress: null,
        route: `/image-generation?project_id=${context.projectId}&script_task_id=${context.scriptTaskId}&batch_id=${context.batchId}&tab=generate`,
        projectId: context.projectId, scriptTaskId: context.scriptTaskId, batchId: context.batchId, updatedAt: new Date().toISOString(),
      })
    }
    if (!generationContextVisible(context)) return
    const message = apiErrorMessage(error, t, t(failureKey))
    addProgressEvent('error', { code: error.code, message })
    ElMessage.error(message)
  },
})

const executeGeneration = async (context: GenerationContext, operation: (callbacks: ImageGenerationStreamCallbacks) => Promise<void>, continuingBatch = false) => {
  runningGeneration.value = context
  currentGenerationTaskId.value = context.batchId
  progressEvents.value = []
  generating.value = !continuingBatch
  continuing.value = continuingBatch
  const failureKey = continuingBatch ? 'imageGeneration.errors.continueFailed' : 'imageGeneration.errors.generateFailed'
  try {
    await operation(streamCallbacks(context, failureKey))
    const items = await listGenerationBatches(context.scriptTaskId)
    for (const item of items) syncGenerationActivity(item, context.total)
    if (generationContextVisible(context)) await Promise.all([loadPages(), loadBatches()])
  } catch (error) {
    if (generationContextVisible(context)) ElMessage.error(apiErrorMessage(error, t, t(failureKey)))
  } finally {
    if (runningGeneration.value === context) {
      generating.value = false
      continuing.value = false
      suspending.value = false
      runningGeneration.value = null
      currentGenerationTaskId.value = null
    }
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
  if (selectedProjectId.value === null) return
  const context = reactive({ projectId: selectedProjectId.value, scriptTaskId: selectedTaskId.value, batchId: null as number | null, completed: 0, total: pages.value.length * generationForm.candidates_per_page })
  const payload = streamPayload()
  await executeGeneration(context, (callbacks) => streamGenerateImagesForTask(context.scriptTaskId, payload, callbacks))
}

const continueBatch = async () => {
  const batch = selectedBatch.value
  if (batch === null || batch.tool_preset_id === null) {
    ElMessage.warning(t('imageGeneration.errors.selectTaskAndWorkflow'))
    return
  }
  if (!batchCanContinue.value) {
    ElMessage.info(t('imageGeneration.messages.noPagesToContinue'))
    return
  }
  if (!canContinueGeneration.value) {
    return
  }
  const batchWorkflow = workflows.value.find((workflow) => workflow.id === batch.tool_preset_id)
  if (
    batchWorkflow === undefined ||
    (batchWorkflow.provider === 'comfyui' &&
      (!batchWorkflow.seed_node_id || !batchWorkflow.seed_input_name))
  ) {
    ElMessage.warning(t('imageGeneration.errors.workflowSeedRequired'))
    return
  }
  if (batch.script_task_id === null) return
  const context = reactive({ projectId: batch.project_id, scriptTaskId: batch.script_task_id, batchId: batch.id as number | null, completed: 0, total: pages.value.length * batch.candidate_count })
  const payload = continuationPayload(batch)
  await executeGeneration(context, (callbacks) => streamContinueImagesForBatch(batch.id, payload, callbacks), true)
}

const evaluateConsistency = async () => {
  const batchId = selectedBatchId.value
  const projectId = selectedProjectId.value
  const token = consistencyPollToken
  if (batchId === null || !canEvaluateConsistency.value) {
    ElMessage.warning(t('imageGeneration.consistency.errors.notReady'))
    return
  }
  consistencySubmitting.value = true
  try {
    const task = await createConsistencyEvaluation(batchId)
    if (projectId !== selectedProjectId.value || batchId !== selectedBatchId.value || token !== consistencyPollToken) {
      activityCenter.upsertActivity({ id: `consistency-${task.id}`, kind: 'consistencyEvaluation', label: `#${task.id}`, status: normalizeActivityStatus(task.status), progress: null,
        route: `/image-generation?project_id=${projectId}&script_task_id=${task.script_task_id}&batch_id=${batchId}&evaluation_task_id=${task.id}&tab=consistency`,
        projectId, scriptTaskId: task.script_task_id, batchId, evaluationTaskId: task.id, updatedAt: task.updated_at })
      return
    }
    consistencyTask.value = task
    if (['pending', 'waiting_resource', 'running'].includes(task.status)) {
      consistencyPollToken += 1
      void pollConsistencyTask(task.id, consistencyPollToken)
    }
    ElMessage.success(t('imageGeneration.consistency.messages.started'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.consistency.errors.start')))
  } finally {
    consistencySubmitting.value = false
  }
}

const adoptTrack = async (track: ConsistencyTrack) => {
  if (!track.passed || consistencyTask.value?.status !== 'succeeded') return
  const projectId = selectedProjectId.value
  const scriptTaskId = selectedTaskId.value
  const evaluationId = consistencyTask.value.id
  adoptingTrackId.value = track.id
  try {
    const adopted = await adoptConsistencyTrack(track.id)
    if (projectId !== selectedProjectId.value || scriptTaskId !== selectedTaskId.value || evaluationId !== consistencyTask.value?.id) return
    if (consistencyTask.value !== null) {
      const index = consistencyTask.value.tracks.findIndex((item) => item.id === adopted.id)
      if (index >= 0) consistencyTask.value.tracks.splice(index, 1, adopted)
    }
    await loadPages()
    if (scriptTaskId !== null) {
      const gate = await getConsistencyGate(scriptTaskId)
      if (projectId === selectedProjectId.value && scriptTaskId === selectedTaskId.value) consistencyGate.value = gate
    }
    ElMessage.success(
      t('imageGeneration.consistency.messages.adopted', {
        candidate: track.candidate_index,
      }),
    )
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.consistency.errors.adopt')))
  } finally {
    adoptingTrackId.value = null
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
  if (selectedProjectId.value === null || selectedTaskId.value === null) return
  const context = reactive({ projectId: selectedProjectId.value, scriptTaskId: selectedTaskId.value, batchId: null as number | null, completed: 0, total: generationForm.candidates_per_page })
  const payload = streamPayload()
  await executeGeneration(context, (callbacks) => streamGenerateImagesForPage(page.page_id, payload, callbacks))
}

const suspendGeneration = async () => {
  const taskId = visibleGenerationRunning.value ? runningGeneration.value?.batchId ?? null : (selectedBatch.value?.status === 'running' ? selectedBatch.value.id : null)
  if (taskId === null) {
    ElMessage.warning(t('imageGeneration.errors.noCurrentTask'))
    return
  }
  suspending.value = true
  try {
    await suspendImageGenerationTask(taskId)
    ElMessage.info(t('imageGeneration.messages.suspendRequested'))
  } catch {
    suspending.value = false
    ElMessage.error(t('imageGeneration.errors.suspendFailed'))
  }
}

const selectFinalImage = async (page: ImageGenerationPage, image: GeneratedImage) => {
  const projectId = selectedProjectId.value
  const scriptTaskId = selectedTaskId.value
  try {
    const nextPage = await selectGeneratedImage(page.page_id, image.id)
    if (projectId !== selectedProjectId.value || scriptTaskId !== selectedTaskId.value) return
    const index = pages.value.findIndex((item) => item.page_id === nextPage.page_id)
    if (index >= 0) {
      pages.value.splice(index, 1, nextPage)
    }
    if (scriptTaskId !== null) {
      const gate = await getConsistencyGate(scriptTaskId)
      if (projectId === selectedProjectId.value && scriptTaskId === selectedTaskId.value) consistencyGate.value = gate
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

const promotionRoles = computed(() => promotionCatalog.value.find(item => item.entity_type === promoteForm.entity_type)?.roles ?? [])
const promotionOwners = computed(() => promoteForm.entity_type === 'character'
  ? promotionCharacters.value.map(item => ({ id: item.id, name: item.name }))
  : promotionSubjects.value.filter(item => item.entity_type === promoteForm.entity_type).map(item => ({ id: item.id, name: item.name })))
watch(() => promoteForm.entity_type, () => {
  promoteForm.entity_id = null
  promoteForm.reference_subject_id = null
  promoteForm.outfit_variant_id = null
  promoteForm.role = promotionRoles.value[0]?.role ?? 'identity_face'
})

const openPromote = async (image: GeneratedImage) => {
  const projectId = selectedProjectId.value
  if (projectId === null) return
  promotionProjectId.value = projectId
  promoteImage.value = image
  promoteForm.entity_type = 'character'
  promoteForm.entity_id = null
  promoteForm.entity_key = ''
  promoteForm.reference_subject_id = null
  promoteForm.outfit_variant_id = null
  promoteForm.role = 'identity_face'
  promoteForm.approve = false
  promoteVisible.value = true
  promotionCharacters.value = []
  promotionSubjects.value = []
  try {
    const [characters, subjects, catalog, outfits] = await Promise.all([listProjectCharacterReferenceCharacters(projectId), listReferenceSubjects(projectId), listReferenceCategories(), listOutfits(projectId)])
    if (projectId !== selectedProjectId.value || image !== promoteImage.value) return
    promotionCharacters.value = characters
    promotionSubjects.value = subjects
    promotionCatalog.value = catalog
    promotionOutfits.value = outfits
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.promoteFailed'))) }
}

const normalizeActivityStatus = (status: string): ActivityStatus => {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'suspended') return 'suspended'
  if (status === 'running' || status === 'waiting_resource') return 'running'
  return 'pending'
}

const syncGenerationActivity = (batch: GenerationTask, pageCount: number) => {
  const total = Math.max(1, pageCount)
  const completed = batch.status === 'succeeded' ? total : (selectedBatchId.value === batch.id ? generatedPageCount.value : 0)
  activityCenter.upsertActivity({
    id: `image-generation-${batch.id}`,
    kind: 'imageGeneration',
    label: batchLabel(batch),
    status: normalizeActivityStatus(batch.status),
    progress: batch.status === 'running' && completed === 0 ? null : (completed / total) * 100,
    route: `/image-generation?project_id=${batch.project_id}&script_task_id=${batch.script_task_id ?? ''}&batch_id=${batch.id}&tab=${batch.status === 'succeeded' ? 'results' : 'generate'}`,
    projectId: batch.project_id,
    scriptTaskId: batch.script_task_id ?? undefined,
    batchId: batch.id,
    updatedAt: batch.updated_at,
  })
}

const syncConsistencyActivity = () => {
  const task = consistencyTask.value
  if (!task) return
  const projectId = batches.value.find((item) => item.id === task.batch_task_id)?.project_id ?? selectedProjectId.value
  const completed = Number(task.progress.completed_tracks ?? 0)
  const total = Number(task.progress.total_tracks ?? task.tracks.length ?? 0)
  activityCenter.upsertActivity({
    id: `consistency-${task.id}`,
    kind: 'consistencyEvaluation',
    label: `#${task.id} · ${completed}/${total}`,
    status: normalizeActivityStatus(task.status),
    progress: total > 0 ? (completed / total) * 100 : null,
    route: `/image-generation?project_id=${projectId}&script_task_id=${task.script_task_id}&batch_id=${task.batch_task_id}&evaluation_task_id=${task.id}&tab=consistency`,
    projectId,
    scriptTaskId: task.script_task_id,
    batchId: task.batch_task_id,
    evaluationTaskId: task.id,
    updatedAt: task.updated_at,
  })
}

const savePromotion = async () => {
  const image = promoteImage.value
  if (image === null || promotionProjectId.value !== selectedProjectId.value || (promoteForm.entity_id === null && promoteForm.reference_subject_id === null)) {
    ElMessage.warning(t('imageGeneration.errors.promoteOwnerRequired'))
    return
  }
  promoting.value = true
  try {
    await promoteGeneratedImage(image.id, {
      entity_type: promoteForm.entity_type,
      entity_id: promoteForm.entity_id,
      entity_key: promoteForm.entity_key.trim() || null,
      reference_subject_id: promoteForm.reference_subject_id,
      outfit_variant_id: promoteForm.outfit_variant_id,
      role: promoteForm.role,
      approve: promoteForm.approve,
    })
    promoteVisible.value = false
    if (selectedBatchId.value !== null) void loadConsistencyState()
    ElMessage.success(t('imageGeneration.messages.promoted'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageGeneration.errors.promoteFailed')))
  } finally {
    promoting.value = false
  }
}

const syncContextQuery = () => {
  if (route.path !== '/image-generation' || restoringProject) return
  const query = { ...route.query, project_id: selectedProjectId.value?.toString(), script_task_id: taskLocationUnavailable.value ? route.query.script_task_id : selectedTaskId.value?.toString(), batch_id: targetUnavailable.value && selectedBatchId.value === null ? route.query.batch_id : selectedBatchId.value?.toString(), tab: activeGenerationTab.value, activity_legacy: selectedTaskId.value === null ? route.query.activity_legacy : undefined }
  if (Object.entries(query).some(([key, value]) => route.query[key] !== value)) void router.replace({ query })
}

const applyRouteContext = () => {
  if (route.path !== '/image-generation') return
  const projectId = queryId(route.query.project_id)
  if (projectId !== null && projectId !== selectedProjectId.value) {
    selectedProjectId.value = projectId
    return
  }
  const taskId = queryId(route.query.script_task_id)
  if (legacyActivityLocation.value) {
    taskLocationUnavailable.value = false
    batchLocationUnavailable.value = false
    selectedTaskId.value = null
    selectedBatchId.value = null
    pages.value = []
    batches.value = []
    if (['generate', 'consistency', 'results', 'tools'].includes(String(route.query.tab))) activeGenerationTab.value = String(route.query.tab) as typeof activeGenerationTab.value
    return
  }
  if (taskId !== null && !loadingTasks.value && !tasks.value.some((item) => item.id === taskId)) {
    taskLocationUnavailable.value = true
    selectedTaskId.value = null
    pages.value = []
    return
  }
  if (taskId !== null && tasks.value.some((item) => item.id === taskId) && taskId !== selectedTaskId.value) {
    taskLocationUnavailable.value = false
    selectedTaskId.value = taskId
    return
  }
  const batchId = queryId(route.query.batch_id)
  if (batchId !== null && selectedTaskId.value !== null && !batches.value.some((item) => item.id === batchId) && runningGeneration.value?.batchId !== batchId) {
    batchLocationUnavailable.value = true
    selectedBatchId.value = null
    pages.value = []
    return
  }
  if (batchId !== null && batches.value.some((item) => item.id === batchId)) {
    batchLocationUnavailable.value = false
    if (batchId !== selectedBatchId.value) selectedBatchId.value = batchId
    else if (route.query.tab === 'consistency') void loadConsistencyState()
  }
  if (['generate', 'consistency', 'results', 'tools'].includes(String(route.query.tab))) activeGenerationTab.value = String(route.query.tab) as typeof activeGenerationTab.value
}

watch(selectedProjectId, () => {
  restoringProject = true
  taskLocationUnavailable.value = false
  batchLocationUnavailable.value = false
  ++pageLoadToken
  ++batchLoadToken
  tasks.value = []
  pages.value = []
  batches.value = []
  selectedBatchId.value = null
  progressEvents.value = []
  configurationOpen.value = true
  if (queryId(route.query.project_id) !== selectedProjectId.value) {
    void router.replace({ query: { ...route.query, project_id: selectedProjectId.value?.toString(), script_task_id: undefined, batch_id: undefined, evaluation_task_id: undefined } })
  }
  clearConsistencyState()
  void loadTasks()
})

watch(selectedTaskId, () => {
  if (selectedTaskId.value !== null && queryId(route.query.script_task_id) !== selectedTaskId.value) taskLocationUnavailable.value = false
  batchLocationUnavailable.value = false
  ++pageLoadToken
  ++batchLoadToken
  pages.value = []
  progressEvents.value = []
  batches.value = []
  selectedBatchId.value = queryId(route.query.script_task_id) === selectedTaskId.value ? queryId(route.query.batch_id) : null
  syncContextQuery()
  clearConsistencyState()
  void Promise.all([loadPages(), loadBatches()])
})

watch(selectedBatchId, () => {
  if (selectedBatchId.value !== null && queryId(route.query.batch_id) !== selectedBatchId.value) batchLocationUnavailable.value = false
  const batch = selectedBatch.value
  if (batch !== null) {
    if (batch.tool_preset_id !== null) selectedWorkflowId.value = batch.tool_preset_id
    if (batch.generation_mode !== null) generationForm.generation_mode = batch.generation_mode
    if (batch.seed_strategy !== null) generationForm.seed_strategy = batch.seed_strategy
    generationForm.candidates_per_page = batch.candidate_count
    configurationOpen.value = batch.status !== 'succeeded'
  }
  syncContextQuery()
  if (selectedBatchId.value !== null) void loadPages()
  void loadConsistencyState()
})

watch(selectedWorkflowId, () => {
  void loadPages()
})

watch(
  () => generationForm.generation_mode,
  () => {
    void loadPages()
  },
)

watch(activeGenerationTab, (tab) => {
  if (route.query.tab !== tab) syncContextQuery()
})

watch(
  () => route.query,
  applyRouteContext,
  { deep: true },
)

watch([pageSearch, pageStatusFilter], () => {
  pageTablePage.value = 1
  localStorage.setItem('comaic-image-page-search', pageSearch.value)
})

watch([selectedBatch, generatedPageCount], () => { if (selectedBatch.value) syncGenerationActivity(selectedBatch.value, pages.value.length) })
watch(consistencyTask, syncConsistencyActivity, { deep: true })

onMounted(async () => {
  const requestedProject = queryId(route.query.project_id)
  if (requestedProject !== null) selectedProjectId.value = requestedProject
  await refreshAll()
  applyRouteContext()
})

onBeforeUnmount(() => {
  viewMounted = false
  ++projectLoadToken
  ++pageLoadToken
  ++batchLoadToken
  consistencyPollToken += 1
})
</script>

<template>
  <section v-loading="loading" class="image-generation-page">
    <el-alert v-if="legacyActivityLocation" type="info" :closable="false" :title="t('activityCenter.legacyLocation')" />
    <el-alert v-if="targetUnavailable" type="warning" :closable="false" :title="t('activityCenter.targetUnavailable')" />
    <div class="workspace-context panel">
      <div class="workspace-context__title"><strong>{{ t('ux.currentProject') }} · {{ selectedProject?.title || '—' }}</strong></div>
      <el-select v-model="selectedTaskId" :loading="loadingTasks" :placeholder="t('imageGeneration.generation.scriptTask')" :aria-label="t('imageGeneration.generation.scriptTask')" filterable>
        <el-option v-for="task in tasks" :key="task.id" :label="taskLabel(task)" :value="task.id" />
      </el-select>
      <el-select v-model="selectedBatchId" clearable filterable :placeholder="t('imageGeneration.generation.batchPlaceholder')" :aria-label="t('imageGeneration.generation.batch')">
        <el-option v-for="batch in batches" :key="batch.id" :label="batchLabel(batch)" :value="batch.id" />
      </el-select>
      <div class="generation-actions">
        <el-button v-if="activeGenerationTab === 'generate'" class="ai-gradient-button" type="primary" :icon="Picture" :loading="visibleGenerationRunning && generating" :disabled="!canGenerate" @click="generateBatch">{{ t('imageGeneration.actions.generate') }}</el-button>
        <el-button v-if="batchCanContinue" type="primary" plain :icon="Picture" :loading="visibleGenerationRunning && continuing" :disabled="!canContinueGeneration" @click="continueBatch">{{ t('imageGeneration.actions.continue') }}</el-button>
        <el-button v-if="visibleGenerationRunning || selectedBatch?.status === 'running'" type="warning" :icon="VideoPause" :loading="suspending" :disabled="suspending" @click="suspendGeneration">{{ t('imageGeneration.actions.suspend') }}</el-button>
        <el-button v-if="generatedPageCount && activeGenerationTab !== 'results'" type="primary" @click="activeGenerationTab = 'results'">{{ t('ux.nextStep') }} · {{ t('imageGeneration.readiness.openResults') }}</el-button>
      </div>
    </div>
    <WorkflowReadiness
      :title="t('imageGeneration.readiness.title')"
      :description="t('imageGeneration.readiness.description')"
      :items="generationReadinessItems"
    />

    <el-tabs v-model="activeGenerationTab" class="workspace-tabs generation-tabs">
      <el-tab-pane :label="t('imageGeneration.tabs.generate')" name="generate" />
      <el-tab-pane name="consistency">
        <template #label>
          {{ t('imageGeneration.tabs.consistency') }}
          <el-badge v-if="consistencyTask" :is-dot="consistencyRunning" />
        </template>
      </el-tab-pane>
      <el-tab-pane name="results">
        <template #label>
          {{ t('imageGeneration.tabs.results') }}
          <el-badge :value="generatedPageCount" :hidden="generatedPageCount === 0" />
        </template>
      </el-tab-pane>
      <el-tab-pane :label="t('imageGeneration.tabs.tools')" name="tools" />
    </el-tabs>

    <div class="image-generation-grid">
      <section v-show="activeGenerationTab === 'generate'" class="panel generation-config">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.generation.title') }}</h2>
            <p>{{ t('imageGeneration.generation.description') }}</p>
          </div>
          <el-button link type="primary" @click="configurationOpen = !configurationOpen">{{ t('ux.showConfiguration') }}</el-button>
        </header>

        <div v-show="configurationOpen">
        <el-form label-position="top">
          <div class="generation-main-fields">
            <el-form-item :label="t('imageGeneration.generation.workflow')">
              <el-select v-model="selectedWorkflowId" filterable>
                <el-option v-for="workflow in workflows" :key="workflow.id" :label="workflow.name" :value="workflow.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.candidates')">
              <el-input-number v-model="generationForm.candidates_per_page" :min="1" :max="4" />
            </el-form-item>
            <el-form-item :label="t('ux.referenceCheck')">
              <el-segmented v-model="generationForm.generation_mode" :options="[
                { label: t('ux.relaxed'), value: 'preview' },
                { label: t('ux.strict'), value: 'final' },
              ]" />
            </el-form-item>
          </div>
          <p class="reference-help">{{ t('ux.referenceCheckHelp') }}</p>
          <el-collapse class="generation-advanced">
            <el-collapse-item :title="t('ux.advancedSettings')" name="advanced">
              <div class="generation-config__numbers">
                <el-form-item :label="t('imageGeneration.generation.pollInterval')">
                  <el-input-number v-model="generationForm.poll_interval_seconds" :min="0.5" :max="20" :step="0.5" />
                </el-form-item>
                <el-form-item :label="t('imageGeneration.generation.waitTimeout')">
                  <el-input-number v-model="generationForm.wait_timeout_seconds" :min="30" :max="3600" :step="30" />
                </el-form-item>
                <el-form-item :label="t('imageGeneration.generation.seedStrategy')">
                  <el-select v-model="generationForm.seed_strategy">
                    <el-option :label="t('imageGeneration.generation.perPageSeed')" value="per_page" />
                    <el-option :label="t('imageGeneration.generation.sharedCandidateSeed')" value="shared_candidate" />
                  </el-select>
                </el-form-item>
              </div>
              <p v-if="selectedWorkflow" class="reference-help">{{ t('imageGeneration.generation.toolPromptType', { provider: providerLabel(selectedWorkflow.provider), promptType: t(`imageSpecs.promptTypes.${selectedWorkflow.prompt_type}`) }) }}</p>
            </el-collapse-item>
          </el-collapse>
        </el-form>

        <el-alert
          v-if="generationForm.generation_mode === 'final'"
          type="warning"
          :closable="false"
          :title="t('imageGeneration.generation.finalHint')"
        />
        <div class="generation-scope">
          <div>
            <span>{{ t('imageGeneration.generation.scopePages') }}</span>
            <strong>{{ pages.length }}</strong>
          </div>
          <div>
            <span>{{ t('imageGeneration.generation.scopeCandidates') }}</span>
            <strong>{{ generationForm.candidates_per_page }}</strong>
          </div>
          <div>
            <span>{{ t('imageGeneration.generation.scopeRequests') }}</span>
            <strong>{{ pages.length * generationForm.candidates_per_page }}</strong>
          </div>
        </div>

        </div>
        <div v-if="!canGenerate && !generationRunning" class="generation-blocker">
          <span>
            {{
              specReadyPageCount < pages.length
                ? t('imageGeneration.readiness.blockedBySpecs', {
                    count: pages.length - specReadyPageCount,
                  })
                : t('imageGeneration.readiness.completeSelections')
            }}
          </span>
          <el-button
            v-if="specReadyPageCount < pages.length"
            link
            type="primary"
            @click="router.push({ path: '/image-specs', query: { project_id: selectedProjectId ?? undefined, script_task_id: selectedTaskId ?? undefined } })"
          >{{ t('imageGeneration.readiness.openSpecs') }}</el-button>
        </div>
      </section>

      <section v-show="activeGenerationTab === 'tools'" class="panel workflow-panel">
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

      <section v-if="progressEvents.length && (runningGeneration === null || generationContextVisible(runningGeneration))" v-show="activeGenerationTab === 'generate'" class="panel progress-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.progress.title') }}</h2>
            <p>{{ t('imageGeneration.progress.description') }}</p>
          </div>
        </header>
        <el-scrollbar height="240px">
          <el-empty
            v-if="progressEvents.length === 0"
            :description="t('imageGeneration.progress.empty')"
          />
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

      <section v-show="activeGenerationTab === 'consistency'" class="panel consistency-panel">
        <header class="panel-header consistency-header">
          <div>
            <h2>{{ t('imageGeneration.consistency.title') }}</h2>
            <p>{{ t('imageGeneration.consistency.description') }}</p>
          </div>
          <div class="consistency-header__actions">
            <el-tag
              v-if="consistencyGate"
              :type="consistencyGate.passed ? 'success' : 'info'"
              effect="plain"
            >
              {{
                consistencyGate.passed
                  ? t('imageGeneration.consistency.gatePassed', {
                      candidate: consistencyGate.candidate_index,
                    })
                  : t('imageGeneration.consistency.gatePending')
              }}
            </el-tag>
            <el-button
              :disabled="selectedBatchId === null"
              :loading="consistencyLoading"
              @click="loadConsistencyState"
            >
              {{ t('imageGeneration.consistency.refresh') }}
            </el-button>
          </div>
        </header>

        <el-empty
          v-if="selectedBatch === null"
          :description="t('imageGeneration.consistency.noBatch')"
        />
        <div v-else v-loading="consistencyLoading" class="consistency-content">
          <div class="consistency-meta">
            <el-tag effect="plain">{{ batchLabel(selectedBatch) }}</el-tag>
            <el-tag
              :type="consistencyReadiness?.runtime?.ready ? 'success' : 'danger'"
              effect="plain"
            >
              {{
                consistencyReadiness?.runtime?.ready
                  ? t('imageGeneration.consistency.runtimeReady', {
                      device: consistencyReadiness.runtime.cuda_device,
                    })
                  : t('imageGeneration.consistency.runtimeNotReady')
              }}
            </el-tag>
            <el-tag v-if="consistencyReadiness?.reference_baseline" type="success" effect="plain">
              {{
                t('imageGeneration.consistency.referenceBaseline', {
                  count: consistencyReadiness.reference_baseline.reference_count,
                })
              }}
            </el-tag>
            <span class="muted">
              {{ t('imageGeneration.consistency.sourceHash') }}:
              {{ shortHash(consistencyReadiness?.source_hash ?? null) }}
            </span>
          </div>

          <el-alert
            v-for="issue in consistencyReadiness?.errors ?? []"
            :key="`error-${issue.code}-${JSON.stringify(issue.details ?? {})}`"
            type="error"
            :closable="false"
            :title="consistencyIssueText(issue)"
          />
          <el-alert
            v-for="issue in consistencyReadiness?.warnings ?? []"
            :key="`warning-${issue.code}-${JSON.stringify(issue.details ?? {})}`"
            type="warning"
            :closable="false"
            :title="consistencyIssueText(issue)"
          />

          <div
            v-if="(consistencyReadiness?.incomplete_tracks.length ?? 0) > 0"
            class="incomplete-tracks"
          >
            <strong>{{ t('imageGeneration.consistency.incompleteTracks') }}</strong>
            <el-tag
              v-for="track in consistencyReadiness?.incomplete_tracks ?? []"
              :key="track.candidate_index"
              type="warning"
              effect="plain"
            >
              {{
                t('imageGeneration.consistency.incompleteTrack', {
                  candidate: track.candidate_index,
                  pages: track.missing_pages.join(', '),
                })
              }}
            </el-tag>
          </div>

          <div class="consistency-actions">
            <el-button
              type="primary"
              :loading="consistencySubmitting || consistencyRunning"
              :disabled="!canEvaluateConsistency"
              @click="evaluateConsistency"
            >
              {{
                consistencyResultCurrent
                  ? t('imageGeneration.consistency.evaluated')
                  : consistencyTask?.status === 'succeeded'
                    ? t('imageGeneration.consistency.evaluateAgain')
                    : t('imageGeneration.consistency.evaluate')
              }}
            </el-button>
            <span class="muted">{{ t('imageGeneration.consistency.manualHint') }}</span>
          </div>

          <div v-if="consistencyTask" class="consistency-task-meta">
            <el-tag :type="consistencyStatusType(consistencyTask.status)">
              {{ t(`imageGeneration.consistency.statuses.${consistencyTask.status}`) }}
            </el-tag>
            <span>Task #{{ consistencyTask.id }}</span>
            <span>{{ consistencyTask.metric_version }}</span>
            <span>
              {{ t('imageGeneration.consistency.phase') }}:
              {{ consistencyTask.progress.phase ?? '-' }}
            </span>
          </div>
          <el-alert
            v-if="consistencyTask?.error_message"
            type="error"
            :closable="false"
            :title="
              consistencyIssueText({
                code: consistencyTask.error_code,
                message: consistencyTask.error_message,
              })
            "
          />

          <el-table
            v-if="(consistencyTask?.tracks.length ?? 0) > 0"
            :data="consistencyTask?.tracks ?? []"
            border
          >
            <el-table-column
              prop="candidate_index"
              :label="t('imageGeneration.consistency.candidate')"
              width="110"
            />
            <el-table-column :label="t('imageGeneration.consistency.trackStatus')" width="120">
              <template #default="{ row }">
                <div class="track-status-cell">
                  <el-tag :type="consistencyStatusType(row.status)">
                    {{ t(`imageGeneration.consistency.statuses.${row.status}`) }}
                  </el-tag>
                  <small v-if="row.error_message">
                    {{ consistencyIssueText({ code: row.error_code, message: row.error_message }) }}
                  </small>
                </div>
              </template>
            </el-table-column>
            <el-table-column
              v-for="metric in consistencyMetricKeys"
              :key="metric"
              min-width="130"
            >
              <template #header>
                <el-tooltip
                  :content="t(`imageGeneration.consistency.metricHelp.${metric}`)"
                  placement="top"
                >
                  <span class="metric-header">{{ metricColumnLabel(metric) }}</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                <el-tag :type="metricType(row, metric)" effect="plain">
                  {{ formatMetric(row, metric) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column :label="t('imageGeneration.consistency.trackImages')" width="110">
              <template #default="{ row }">
                {{ Object.keys(row.image_ids).length }}
              </template>
            </el-table-column>
            <el-table-column
              :label="t('imageGeneration.consistency.actions')"
              width="150"
              fixed="right"
            >
              <template #default="{ row }">
                <el-tag v-if="row.adopted_at" type="success" size="small">
                  {{ t('imageGeneration.consistency.adopted') }}
                </el-tag>
                <el-button
                  v-else
                  link
                  type="success"
                  :loading="adoptingTrackId === row.id"
                  :disabled="!row.passed || consistencyTask?.status !== 'succeeded'"
                  @click="adoptTrack(row)"
                >
                  {{ t('imageGeneration.consistency.adoptTrack') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else-if="consistencyTask === null"
            :description="t('imageGeneration.consistency.noEvaluation')"
          />
        </div>
      </section>

      <section v-show="activeGenerationTab === 'results'" class="panel result-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.pages.title') }}</h2>
            <p>{{ selectedProject?.title || t('imageGeneration.pages.noProject') }}</p>
          </div>
        </header>

        <div class="result-toolbar workspace-toolbar">
          <el-input
            v-model="pageSearch"
            clearable
            :prefix-icon="Search"
            :placeholder="t('imageGeneration.pages.search')"
            :aria-label="t('imageGeneration.pages.search')"
          />
          <el-select v-model="pageStatusFilter" :aria-label="t('imageGeneration.pages.filter')">
            <el-option :label="t('imageGeneration.pages.filters.all')" value="all" />
            <el-option :label="t('imageGeneration.pages.filters.ready')" value="ready" />
            <el-option :label="t('imageGeneration.pages.filters.missing')" value="missing" />
            <el-option :label="t('imageGeneration.pages.filters.generated')" value="generated" />
            <el-option :label="t('imageGeneration.pages.filters.selected')" value="selected" />
          </el-select>
          <span class="workspace-toolbar__spacer" />
          <span class="muted">{{ t('imageGeneration.pages.resultCount', { count: filteredPages.length }) }}</span>
        </div>

        <el-table
          v-if="paginatedPages.length > 0"
          v-loading="loadingPages"
          :data="paginatedPages"
          height="620"
        >
          <el-table-column prop="page_no" :label="t('imageGeneration.pages.pageNo')" width="80" />
          <el-table-column :label="t('imageGeneration.pages.prompt')" min-width="240">
            <template #default="{ row }">
              <div class="spec-readiness">
                <el-tag size="small" :type="row.latest_spec_id ? 'success' : 'danger'">
                  {{
                    row.latest_spec_id
                      ? `ImageSpec #${row.latest_spec_id}`
                      : t('imageGeneration.pages.specMissing')
                  }}
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
                  <el-image
                    :src="image.image_url || ''"
                    :preview-src-list="imagePreviewUrls(row.images)"
                    fit="cover"
                    preview-teleported
                    class="image-card__img"
                  />
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
                    <el-button
                      link
                      type="success"
                      :icon="Select"
                      @click="selectFinalImage(row, image)"
                    >
                      {{ t('imageGeneration.actions.select') }}
                    </el-button>
                  </div>
                </article>
                <span v-if="row.images.length === 0" class="muted">{{
                  t('imageGeneration.pages.noImages')
                }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="t('imageGeneration.pages.actions')" width="130" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :disabled="generationRunning || !pageSpecificationReady(row)"
                @click="generatePage(row)"
              >
                {{ t('imageGeneration.actions.generatePage') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else :description="t('imageGeneration.pages.emptyFiltered')">
          <el-button
            v-if="specReadyPageCount < pages.length"
            type="primary"
            plain
            @click="router.push({ path: '/image-specs', query: { project_id: selectedProjectId ?? undefined, script_task_id: selectedTaskId ?? undefined } })"
          >{{ t('imageGeneration.readiness.openSpecs') }}</el-button>
        </el-empty>
        <div v-if="filteredPages.length > pageTablePageSize" class="result-pagination">
          <el-pagination
            v-model:current-page="pageTablePage"
            v-model:page-size="pageTablePageSize"
            :total="filteredPages.length"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next, jumper"
            background
          />
        </div>
      </section>
    </div>

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
              <el-form-item :label="t('imageGeneration.workflows.seedNode')" required>
                <el-input v-model="workflowForm.seed_node_id" />
              </el-form-item>
              <el-form-item :label="t('imageGeneration.workflows.seedInput')" required>
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
      <el-image
        v-if="detailImage?.image_url"
        :src="detailImage.image_url"
        fit="contain"
        class="detail-image"
      />
      <el-collapse><el-collapse-item :title="t('ux.advancedSettings')" name="details"><pre class="image-meta">{{ detailImage }}</pre></el-collapse-item></el-collapse>
    </el-dialog>

    <el-drawer
      v-model="provenanceVisible"
      size="min(860px, 94vw)"
      :title="
        generationRun ? `GenerationRun #${generationRun.id}` : t('imageGeneration.provenance.title')
      "
    >
      <section v-loading="provenanceLoading" class="provenance-content">
        <template v-if="generationRun">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('imageGeneration.provenance.status')">
              {{ generationRun.status }}
            </el-descriptions-item>
            <el-descriptions-item label="ImageSpec"
              >#{{ generationRun.image_spec_id }}</el-descriptions-item
            >
            <el-descriptions-item :label="t('imageGeneration.workflows.kind')">{{
              generationRun.provider
            }}</el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.workflows.promptType')">{{
              generationRun.prompt_type
            }}</el-descriptions-item>
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
          <ReferenceImagePlan :plan="generationRun.applied_spec.reference_inputs" actual />
          <h3>{{ t('imageSpecs.positivePrompt') }}</h3>
          <pre>{{ (generationRun.applied_spec.prompt as Record<string, unknown> | undefined)?.positive }}</pre>
          <el-collapse><el-collapse-item :title="`${t('ux.advancedSettings')} · JSON`" name="json">
            <h3>{{ t('imageGeneration.provenance.bindings') }}</h3>
            <pre>{{ JSON.stringify(generationRun.bindings, null, 2) }}</pre>
            <h3>Workflow</h3>
            <pre>{{ JSON.stringify(generationRun.workflow, null, 2) }}</pre>
          </el-collapse-item></el-collapse>
        </template>
      </section>
    </el-drawer>

    <el-dialog v-model="promoteVisible" :title="t('imageGeneration.promotion.title')" width="min(620px, 94vw)">
      <el-alert type="info" :closable="false" :title="t('imageGeneration.promotion.hint')" />
      <el-form label-position="top" class="promotion-form">
        <div class="workflow-node-grid">
          <el-form-item :label="t('imageGeneration.promotion.entityType')">
            <el-select v-model="promoteForm.entity_type">
              <el-option v-for="item in promotionCatalog" :key="item.entity_type" :label="t(`visualBible.entityLabels.${item.entity_type}`)" :value="item.entity_type" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.ownerId')">
            <el-select v-if="promoteForm.entity_type === 'character'" v-model="promoteForm.entity_id" filterable><el-option v-for="owner in promotionOwners" :key="owner.id" :label="owner.name" :value="owner.id" /></el-select>
            <el-select v-else v-model="promoteForm.reference_subject_id" filterable><el-option v-for="owner in promotionOwners" :key="owner.id" :label="owner.name" :value="owner.id" /></el-select>
          </el-form-item>
          <el-form-item v-if="promoteForm.entity_type === 'character'" :label="t('visualBible.tabs.outfits')">
            <el-select v-model="promoteForm.outfit_variant_id" clearable><el-option v-for="outfit in promotionOutfits.filter(item => item.outline_character_id === promoteForm.entity_id)" :key="outfit.id" :label="outfit.name" :value="outfit.id" /></el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.role')">
            <el-select v-model="promoteForm.role" filterable>
              <el-option
                v-for="item in promotionRoles"
                :key="item.role"
                :label="t(`visualBible.roleLabels.${item.role}`)"
                :value="item.role"
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
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: 18px;
}

.generation-tabs :deep(.el-tabs__content) {
  display: none;
}

.generation-tabs :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.generation-tabs :deep(.el-badge__content) {
  transform: translateY(-5px) translateX(6px) scale(0.82);
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
  grid-template-columns: minmax(0, 1fr);
  gap: 18px;
  align-items: start;
}

.panel {
  min-width: 0;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  padding: 22px;
}

.result-panel,
.consistency-panel,
.workflow-panel {
  grid-column: 1 / -1;
}

.progress-panel {
  position: static;
}

.workspace-context { display: grid; grid-template-columns: minmax(160px, .8fr) minmax(170px, 1fr) minmax(180px, 1.1fr); align-items: center; gap: 12px; padding: 16px 20px; }
.workspace-context__title { min-width: 0; overflow-wrap: anywhere; }
.workspace-context .generation-actions { grid-column: 1 / -1; margin: 0; }
.generation-main-fields { display: grid; grid-template-columns: minmax(200px, 1fr) minmax(150px, .7fr) minmax(170px, .8fr); gap: 16px; }
.generation-advanced { margin-top: 12px; }
.reference-help { margin: 0 0 12px; font-size: 13px; color: var(--text-soft); }

.consistency-header,
.consistency-header__actions,
.consistency-meta,
.consistency-actions,
.consistency-task-meta,
.incomplete-tracks {
  align-items: center;
}

.consistency-header__actions,
.consistency-meta,
.consistency-actions,
.consistency-task-meta,
.incomplete-tracks {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.consistency-content {
  display: grid;
  gap: 14px;
  margin-top: 18px;
}

.consistency-task-meta {
  color: var(--text-soft);
  font-size: 13px;
}

.track-status-cell {
  display: grid;
  justify-items: start;
  gap: 6px;
}

.track-status-cell small {
  color: var(--el-color-danger);
  line-height: 1.35;
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
  flex-wrap: wrap;
  gap: 10px;
}

.generation-scope {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 14px 0;
}

.generation-scope > div {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fbff;
}

.generation-scope span,
.generation-blocker {
  color: var(--text-soft);
  font-size: 12px;
}

.generation-blocker {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.generation-blocker .el-button {
  padding: 0;
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

.result-toolbar {
  margin: 16px 0 12px;
  padding: 10px 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fbfcff;
}

.result-toolbar :deep(.el-input) {
  width: min(100%, 320px);
}

.result-toolbar :deep(.el-select) {
  width: 170px;
}

.result-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.metric-header {
  border-bottom: 1px dotted currentColor;
  cursor: help;
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
    grid-template-columns: minmax(0, 1fr);
  }

  .image-generation-grid,
  .generation-config,
  .progress-panel {
    min-width: 0;
  }

  .progress-panel {
    position: static;
  }
}

@media (max-width: 640px) {
  .workspace-context, .generation-main-fields { grid-template-columns: 1fr; }
  .generation-scope {
    grid-template-columns: 1fr;
  }

  .result-toolbar :deep(.el-input),
  .result-toolbar :deep(.el-select) {
    width: 100%;
  }
}
</style>

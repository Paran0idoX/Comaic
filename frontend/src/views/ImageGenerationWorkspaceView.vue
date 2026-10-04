<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import ComicQuickPicker from '@/components/workspace/ComicQuickPicker.vue'
import {
  Delete,
  EditPen,
  MoreFilled,
  Picture,
  Search,
  Select,
  VideoPause,
  View,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import {
  getGenerationRun,
  listGenerationBatches,
  listImageGenerationTools,
  listImageGenerationPages,
  selectGeneratedImage,
  streamContinueImagesForBatch,
  streamGenerateImagesForPage,
  streamGenerateImagesForTask,
  suspendImageGenerationTask,
  type GenerateImagesPayload,
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
  getConsistencyReadiness,
  listConsistencyEvaluations,
  type ConsistencyEvaluationTask,
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

type TimelineLevel = 'primary' | 'success' | 'warning' | 'danger' | 'info'

type ProgressEvent = {
  id: number
  title: string
  content: string
  timestamp: string
  type: TimelineLevel
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
const selectedPageIds = ref<number[]>([])
const pageRangeStart = ref<number | null>(null)
const pageRangeEnd = ref<number | null>(null)
const selectedBatchId = ref<number | null>(null)
const selectedWorkflowId = ref<number | null>(null)
const currentGenerationTaskId = ref<number | null>(null)
const loading = ref(false)
const loadingTasks = ref(false)
const loadingPages = ref(false)
const selectingImageId = ref<number | null>(null)
const quickDialog = ref(false)
const quickPageId = ref<number | null>(null)
const quickPageIds = ref<number[]>([])
const quickReachedEnd = ref(false)
let quickSession = 0
const generating = ref(false)
const continuing = ref(false)
const suspending = ref(false)
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
const consistencyLoading = ref(false)
const consistencySubmitting = ref(false)
const adoptingTrackId = ref<number | null>(null)
const activeGenerationTab = ref<'consistency' | 'results'>(
  ['consistency', 'results'].includes(String(route.query.tab))
    ? (String(route.query.tab) as 'consistency' | 'results')
    : 'results',
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
type ExternalBatchPoll = {
  projectId: number
  scriptTaskId: number
  batchId: number
  token: number
  signature: string
  lastPagesAt: number
  pausedAt: number | null
  hasProgress: boolean
  inFlight: boolean
}
let externalBatchPoll: ExternalBatchPoll | null = null
let externalBatchPollTimer: ReturnType<typeof setTimeout> | null = null
let externalBatchPollToken = 0
type GenerationContext = { projectId: number; scriptTaskId: number; batchId: number | null; completed: number; total: number }
const runningGeneration = ref<GenerationContext | null>(null)
const progressDrawerOpen = ref(false)
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
  width: 1024,
  height: 1536,
  poll_interval_seconds: 2,
  wait_timeout_seconds: 600,
  candidates_per_page: 1,
  seed_strategy: 'per_page' as 'per_page' | 'shared_candidate',
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
const maxPageNumber = computed(() => sortedPages.value.at(-1)?.page_no ?? 0)
const pageRangeValid = computed(() =>
  pageRangeStart.value !== null && pageRangeEnd.value !== null &&
  Number.isInteger(pageRangeStart.value) && Number.isInteger(pageRangeEnd.value) &&
  pageRangeStart.value >= 1 && pageRangeStart.value <= pageRangeEnd.value &&
  pageRangeEnd.value <= maxPageNumber.value)
const pagesInRange = computed(() => pageRangeValid.value
  ? sortedPages.value.filter(page => page.page_no >= pageRangeStart.value! && page.page_no <= pageRangeEnd.value!)
  : [])
const canSelectPageRange = computed(() => !generationRunning.value && !loadingPages.value && pagesInRange.value.length > 0)
const selectPageRange = () => {
  if (!canSelectPageRange.value) return
  // 按真实页码跨分页选择，替换旧选择，避免把范围外页面意外提交给生图服务。
  selectedPageIds.value = pagesInRange.value.map(page => page.page_id)
}
// 页面接口按工具的 Prompt 类型取提示词；缺少参考图的提示不阻止出图。
const pageSpecificationReady = (page: ImageGenerationPage) => page.latest_spec_id !== null && !page.spec_stale
const specReadyPageCount = computed(
  () => pages.value.filter((page) => pageSpecificationReady(page)).length,
)
const generatedPageCount = computed(
  () => pages.value.filter((page) => page.images.length > 0).length,
)
// 未选终稿不代表缺图，默认只补齐没有任何候选的页面。
const targetPages = computed(() => selectedPageIds.value.length > 0
  ? sortedPages.value.filter(page => selectedPageIds.value.includes(page.page_id))
  : sortedPages.value.filter(page => page.images.length === 0))
const togglePageSelection = (pageId: number, checked: boolean) => {
  selectedPageIds.value = checked
    ? [...new Set([...selectedPageIds.value, pageId])]
    : selectedPageIds.value.filter(id => id !== pageId)
}
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
// 打开时固定筛选范围，避免保存或后台刷新改变待浏览的页面集合。
const quickPages = computed(() => sortedPages.value.filter(page => quickPageIds.value.includes(page.page_id)))
const quickPage = computed(() => quickPages.value.find(page => page.page_id === quickPageId.value) ?? null)
const canOpenQuickPicker = computed(() => !loadingPages.value && !targetUnavailable.value &&
  selectingImageId.value === null && filteredPages.value.some(page => page.images.length > 0))
const closeQuickPicker = () => {
  quickSession += 1
  quickDialog.value = false
  quickPageId.value = null
  quickPageIds.value = []
  quickReachedEnd.value = false
}
const openQuickPicker = () => {
  if (!canOpenQuickPicker.value) return
  closeQuickPicker()
  quickPageIds.value = filteredPages.value.map(page => page.page_id)
  quickPageId.value = (quickPages.value.find(page => page.images.length && page.selected_image_id === null) ??
    quickPages.value.find(page => page.images.length))?.page_id ?? null
  quickDialog.value = true
}
const changeQuickPage = (pageId: number) => {
  if (!quickDialog.value || selectingImageId.value !== null || loadingPages.value || !quickPages.value.some(page => page.page_id === pageId)) return
  quickPageId.value = pageId
  quickReachedEnd.value = false
}
const moveQuickPage = (direction: -1 | 1) => {
  const index = quickPages.value.findIndex(page => page.page_id === quickPageId.value)
  const next = index >= 0 ? quickPages.value[index + direction] : undefined
  if (next) changeQuickPage(next.page_id)
}
const canGenerate = computed(
  () =>
    selectedTaskId.value !== null &&
    selectedWorkflowId.value !== null &&
    targetPages.value.length > 0 &&
    targetPages.value.every(pageSpecificationReady) &&
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
    detail: t('imageGeneration.readiness.specProgress', { ready: specReadyPageCount.value, total: pages.value.length }),
    status: pages.value.length > 0 && specReadyPageCount.value === pages.value.length ? 'ready' : 'blocked',
    to: { path: '/image-specs', query: { project_id: selectedProjectId.value ?? undefined, script_task_id: selectedTaskId.value ?? undefined } },
    actionLabel: t('imageGeneration.readiness.openSpecs'),
  },
  {
    key: 'tool',
    label: t('imageGeneration.readiness.tool'),
    detail: selectedWorkflow.value?.name ?? t('imageGeneration.readiness.toolMissing'),
    status: selectedWorkflow.value ? 'ready' : 'blocked',
    to: { path: '/settings', query: { tab: 'image-tools' } },
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
    status: pages.value.length > 0 && selectedImagePageCount.value === pages.value.length
      ? 'ready'
      : generatedPageCount.value > 0 ? 'info' : 'pending',
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
  `#${batch.id} · ${t(
    'imageGeneration.consistency.candidateCount',
    { count: batch.candidate_count },
  )} · ${t(`imageGeneration.batchStatuses.${batch.status}`)}`

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

const trackStatusLabel = (track: ConsistencyTrack) => track.status === 'passed'
  ? t('imageGeneration.consistency.benchmarkReached')
  : track.status === 'failed'
    ? t('imageGeneration.consistency.benchmarkNotReached')
    : t(`imageGeneration.consistency.statuses.${track.status}`)

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

// done 只表示流已结束；旧后端也可能携带 succeeded 状态和非零失败数。
const generationHasFailures = (payload: Record<string, unknown>) =>
  payload.status === 'failed' || Number(payload.failed ?? 0) > 0

const eventType = (event: string, payload: Record<string, unknown>): TimelineLevel => {
  if (event === 'done' && generationHasFailures(payload)) {
    return 'danger'
  }
  if (event === 'done' || event === 'image' || event === 'page_done') {
    return 'success'
  }
  if (event === 'suspended' || event === 'busy' || event === 'recovery_blocked') {
    return 'warning'
  }
  if (event === 'error') {
    return 'danger'
  }
  return 'primary'
}

const describePayload = (event: string, payload: Record<string, unknown>) => {
  if (event === 'done' && generationHasFailures(payload)) {
    return t('imageGeneration.messages.generatedWithFailures')
  }
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
      promptId: String(payload.external_request_id ?? payload.comfy_prompt_id ?? '-'),
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
  // 编译细节仍可在准备页查看，主流程只展示能说明进度或失败的事件。
  const titleKey = `imageGeneration.events.${event === 'done' && generationHasFailures(payload) ? 'doneWithFailures' : event}`
  const translated = t(titleKey)
  progressEvents.value.unshift({
    id: eventSequence.value,
    title: translated === titleKey ? event : translated,
    content: describePayload(event, payload),
    timestamp: nowLabel(),
    type: eventType(event, payload),
  })
  eventSequence.value += 1
}

const streamPayload = () => ({
  width: generationForm.width,
  height: generationForm.height,
  tool_preset_id: selectedWorkflowId.value ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  wait_timeout_seconds: generationForm.wait_timeout_seconds,
  candidates_per_page: generationForm.candidates_per_page,
  seed_strategy: generationForm.seed_strategy,
})

const continuationPayload = (batch: GenerationTask) => ({
  tool_preset_id: batch.tool_preset_id ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  wait_timeout_seconds: generationForm.wait_timeout_seconds,
  candidates_per_page: batch.candidate_count,
  seed_strategy: batch.seed_strategy ?? 'per_page',
})

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

const loadPages = async ({ silent = false, isCurrent = () => true }: { silent?: boolean; isCurrent?: () => boolean } = {}) => {
  const taskId = selectedTaskId.value
  const projectId = selectedProjectId.value
  const token = ++pageLoadToken
  if (taskId === null) {
    pages.value = []
    return false
  }
  if (!silent) loadingPages.value = true
  try {
    const items = await listImageGenerationPages(taskId, {
      promptType: selectedWorkflow.value?.prompt_type,
    })
    if (token !== pageLoadToken || taskId !== selectedTaskId.value || projectId !== selectedProjectId.value || !isCurrent()) return false
    pages.value = batchLocationUnavailable.value ? [] : items
    selectedPageIds.value = selectedPageIds.value.filter(id => pages.value.some(page => page.page_id === id))
    return true
  } catch {
    if (token === pageLoadToken && isCurrent() && !silent) {
      pages.value = []
      ElMessage.error(t('imageGeneration.errors.loadPagesFailed'))
    }
    return false
  } finally {
    if (token === pageLoadToken && !silent) loadingPages.value = false
  }
}

const batchProgressSignature = (batch: GenerationTask) => JSON.stringify([
  batch.status, batch.progress?.completed_candidates, batch.progress?.images_count, batch.progress?.latest_image_id,
])

const stopExternalBatchPolling = () => {
  externalBatchPollToken += 1
  if (externalBatchPollTimer !== null) clearTimeout(externalBatchPollTimer)
  externalBatchPollTimer = null
  externalBatchPoll = null
}

const externalBatchPollCurrent = (context: ExternalBatchPoll) => viewMounted &&
  context.token === externalBatchPollToken && context.projectId === selectedProjectId.value &&
  context.scriptTaskId === selectedTaskId.value && context.batchId === selectedBatchId.value && !visibleGenerationRunning.value

// 无本页 SSE 时只轮询摘要；旧后端最多每 30 秒拉一次完整页面，避免反复传输长篇 Prompt。
const pollExternalBatch = async () => {
  const context = externalBatchPoll
  if (context === null || context.inFlight || !externalBatchPollCurrent(context)) return
  if (externalBatchPollTimer !== null) clearTimeout(externalBatchPollTimer)
  externalBatchPollTimer = null
  context.inFlight = true
  let keepPolling = true
  let nextDelay = 5000
  try {
    const items = await listGenerationBatches(context.scriptTaskId)
    if (!externalBatchPollCurrent(context)) return
    const next = items.find(item => item.id === context.batchId && item.project_id === context.projectId)
    if (!next) { keepPolling = false; return }
    context.hasProgress = Boolean(next.progress)
    const now = Date.now()
    const signature = batchProgressSignature(next)
    if (signature !== context.signature || (!next.progress && now - context.lastPagesAt >= 30000)) {
      if (loadingPages.value) return
      const loaded = await loadPages({ silent: true, isCurrent: () => externalBatchPollCurrent(context) })
      if (!externalBatchPollCurrent(context)) return
      if (!loaded) { nextDelay = 30000; return }
      context.signature = signature
      context.lastPagesAt = now
    }
    batches.value = batches.value.map(item => item.id === next.id ? next : item)
    syncGenerationActivity(next, pages.value.length)
    if (next.status === 'suspended') {
      context.pausedAt ??= now
      // 已知当前请求未结束时持续跟进；只有旧后端无法确认活动请求时才限制收尾窗口。
      keepPolling = next.progress ? next.progress.active_runs > 0 : now - context.pausedAt < 90000
    } else {
      context.pausedAt = null
      keepPolling = ['pending', 'running'].includes(next.status)
    }
  } catch {
    // 短暂断网时保留已显示的候选；后台刷新不连续弹错，降低频率后重试。
    nextDelay = 30000
  } finally {
    context.inFlight = false
    if (externalBatchPollCurrent(context)) {
      if (context.pausedAt !== null && Date.now() - context.pausedAt >= 90000) {
        if (!context.hasProgress) keepPolling = false
        // 慢任务或远端孤儿请求可持续存在，暂停较久后降低只读查询频率。
        else nextDelay = Math.max(nextDelay, 15000)
      }
      if (keepPolling) externalBatchPollTimer = setTimeout(() => void pollExternalBatch(), nextDelay)
      else stopExternalBatchPolling()
    }
  }
}

const startExternalBatchPolling = (force = false) => {
  stopExternalBatchPolling()
  const batch = selectedBatch.value
  if (!viewMounted || visibleGenerationRunning.value || selectedProjectId.value === null || selectedTaskId.value === null || batch === null) return
  if (!force && !(['pending', 'running'].includes(batch.status) || (batch.status === 'suspended' && (!batch.progress || batch.progress.active_runs > 0)))) return
  externalBatchPoll = {
    projectId: selectedProjectId.value, scriptTaskId: selectedTaskId.value, batchId: batch.id,
    token: externalBatchPollToken, signature: batchProgressSignature(batch), lastPagesAt: Date.now(),
    pausedAt: batch.status === 'suspended' ? Date.now() : null, hasProgress: Boolean(batch.progress), inFlight: false,
  }
  externalBatchPollTimer = setTimeout(() => void pollExternalBatch(), 5000)
}

const refreshExternalBatchOnFocus = () => {
  startExternalBatchPolling(true)
  void pollExternalBatch()
}

const clearConsistencyState = () => {
  consistencyPollToken += 1
  consistencyReadiness.value = null
  consistencyTask.value = null
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
  if (activeGenerationTab.value !== 'consistency') return
  const batchId = selectedBatchId.value
  const scriptTaskId = selectedTaskId.value
  consistencyPollToken += 1
  const token = consistencyPollToken
  if (batchId === null || scriptTaskId === null) {
    consistencyReadiness.value = null
    consistencyTask.value = null
    return
  }
  consistencyLoading.value = true
  try {
    const [readiness, taskItems] = await Promise.all([
      getConsistencyReadiness(batchId),
      listConsistencyEvaluations(batchId),
    ])
    if (token !== consistencyPollToken) return
    consistencyReadiness.value = readiness
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
      if (typeof payload.batch_size === 'number') { context.total = payload.batch_size; context.completed = 0 }
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
        status: event === 'done' ? (generationHasFailures(payload) ? 'failed' : 'succeeded') : event === 'suspended' ? 'suspended' : event === 'error' ? 'failed' : 'running',
        progress: context.total > 0 ? Math.min(100, context.completed / context.total * 100) : null,
        route: `/image-generation?project_id=${context.projectId}&script_task_id=${context.scriptTaskId}&batch_id=${context.batchId}&tab=results`,
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
        activeGenerationTab.value = 'results'
        if (generationHasFailures(payload)) {
          ElMessage.warning(t('imageGeneration.messages.generatedWithFailures'))
        } else ElMessage.success(t('imageGeneration.messages.generated'))
      } else ElMessage.warning(t('imageGeneration.messages.suspended'))
    }
  },
  onError: (error) => {
    // 排他锁或恢复保护只拒绝本次继续，不代表原批次生成失败，也没有重新提交外部请求。
    if (['image_generation.batch_busy', 'image_generation.batch_recovery_unavailable', 'image_generation.batch_recovery_unsupported'].includes(error.code ?? '')) {
      if (generationContextVisible(context)) {
        const message = apiErrorMessage(error, t, t(failureKey))
        addProgressEvent(error.code === 'image_generation.batch_busy' ? 'busy' : 'recovery_blocked', { code: error.code, message })
        ElMessage.warning(message)
      }
      return
    }
    if (context.batchId !== null) {
      activityCenter.upsertActivity({
        id: `image-generation-${context.batchId}`, kind: 'imageGeneration', label: `#${context.batchId}`, status: 'failed', progress: null,
        route: `/image-generation?project_id=${context.projectId}&script_task_id=${context.scriptTaskId}&batch_id=${context.batchId}&tab=results`,
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
  activeGenerationTab.value = 'results'
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
  if (targetPages.value.some(page => !pageSpecificationReady(page))) {
    ElMessage.warning(t('imageGeneration.errors.prepareFirst'))
    return
  }
  if (!canGenerate.value || selectedTaskId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectTaskAndWorkflow'))
    return
  }
  if (selectedProjectId.value === null) return
  const pageIds = targetPages.value.map(page => page.page_id)
  const context = reactive({ projectId: selectedProjectId.value, scriptTaskId: selectedTaskId.value, batchId: null as number | null, completed: 0, total: pageIds.length * generationForm.candidates_per_page })
  const payload = { ...streamPayload(), page_ids: pageIds }
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
  // 续跑由后端校验冻结的绑定；当前工具改动不能否决历史批次的原始输入。
  if (batchWorkflow === undefined) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
    return
  }
  if (batch.script_task_id === null) return
  const context = reactive({ projectId: batch.project_id, scriptTaskId: batch.script_task_id, batchId: batch.id as number | null, completed: 0, total: Math.max(0, (batch.batch_size ?? pages.value.length * batch.candidate_count) - (batch.progress?.completed_candidates ?? 0)) })
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
  if (!['passed', 'failed'].includes(track.status) || consistencyTask.value?.status !== 'succeeded') return
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
  if (!pageSpecificationReady(page)) {
    ElMessage.warning(t('imageGeneration.errors.prepareFirst'))
    return
  }
  if (generationRunning.value) {
    return
  }
  if (selectedWorkflowId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
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
  const projectId = selectedProjectId.value
  const scriptTaskId = selectedTaskId.value
  suspending.value = true
  try {
    await suspendImageGenerationTask(taskId)
    if (projectId === selectedProjectId.value && scriptTaskId === selectedTaskId.value) {
      ElMessage.info(t('imageGeneration.messages.suspendRequested'))
      await loadBatches()
    }
  } catch {
    ElMessage.error(t('imageGeneration.errors.suspendFailed'))
  } finally {
    // 刷新或第二个标签页可能没有本地 SSE，不能依赖流结束来清除请求加载状态。
    suspending.value = false
  }
}

const selectFinalImage = async (page: ImageGenerationPage, image: GeneratedImage) => {
  if (selectingImageId.value !== null || page.selected_image_id === image.id) return false
  const projectId = selectedProjectId.value
  const scriptTaskId = selectedTaskId.value
  selectingImageId.value = image.id
  try {
    const nextPage = await selectGeneratedImage(page.page_id, image.id)
    if (!viewMounted || projectId !== selectedProjectId.value || scriptTaskId !== selectedTaskId.value) return false
    const index = pages.value.findIndex((item) => item.page_id === nextPage.page_id)
    if (index >= 0) {
      pages.value.splice(index, 1, nextPage)
    }
    ElMessage.success(t('imageGeneration.messages.imageSelected'))
    return true
  } catch {
    if (viewMounted && projectId === selectedProjectId.value && scriptTaskId === selectedTaskId.value) {
      ElMessage.error(t('imageGeneration.errors.selectImageFailed'))
    }
    return false
  } finally {
    selectingImageId.value = null
  }
}

/** 保存成功后才前进；关闭重开或切换上下文时，旧请求不得移动新弹窗。 */
const confirmQuickImage = async (imageId: number) => {
  const page = quickPage.value
  const image = page?.images.find(item => item.id === imageId)
  if (!quickDialog.value || loadingPages.value || targetUnavailable.value || !page || !image) return
  const session = quickSession
  const succeeded = await selectFinalImage(page, image)
  if (!succeeded || !quickDialog.value || session !== quickSession || quickPageId.value !== page.page_id) return
  const index = quickPages.value.findIndex(item => item.page_id === page.page_id)
  const next = index >= 0 ? quickPages.value[index + 1] : undefined
  if (next) changeQuickPage(next.page_id)
  else quickReachedEnd.value = true
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
  const total = Math.max(1, batch.progress ? batch.batch_size : pageCount)
  const completed = batch.status === 'succeeded' ? total : batch.progress?.completed_candidates ?? (selectedBatchId.value === batch.id ? generatedPageCount.value : 0)
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
  if (route.query.tab === 'tools') {
    void router.replace({ path: '/settings', query: { tab: 'image-tools' } })
    return
  }
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
    if (['generate', 'consistency', 'results'].includes(String(route.query.tab))) activeGenerationTab.value = route.query.tab === 'consistency' ? 'consistency' : 'results'
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
  }
  if (['generate', 'consistency', 'results'].includes(String(route.query.tab))) activeGenerationTab.value = route.query.tab === 'consistency' ? 'consistency' : 'results'
}

watch([selectedProjectId, selectedTaskId, selectedBatchId], closeQuickPicker, { flush: 'sync' })

watch(selectedProjectId, () => {
  pageRangeStart.value = null
  pageRangeEnd.value = null
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
  if (queryId(route.query.project_id) !== selectedProjectId.value) {
    void router.replace({ query: { ...route.query, project_id: selectedProjectId.value?.toString(), script_task_id: undefined, batch_id: undefined, evaluation_task_id: undefined } })
  }
  clearConsistencyState()
  void loadTasks()
})

watch(selectedTaskId, () => {
  selectedPageIds.value = []
  pageRangeStart.value = null
  pageRangeEnd.value = null
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

// 深链先恢复 ID，批次对象随后才返回；继续入口沿用原冻结输入。
// 只跟踪对象 ID，常规状态刷新不会覆盖用户为下一次生成修改的配置。
watch([selectedBatchId, () => selectedBatch.value?.id ?? null], () => {
  if (selectedBatchId.value !== null && queryId(route.query.batch_id) !== selectedBatchId.value) batchLocationUnavailable.value = false
  const batch = selectedBatch.value
  if (batch !== null) {
    if (batch.tool_preset_id !== null) selectedWorkflowId.value = batch.tool_preset_id
    if (batch.seed_strategy !== null) generationForm.seed_strategy = batch.seed_strategy
    generationForm.candidates_per_page = batch.candidate_count
  }
  syncContextQuery()
  if (selectedBatchId.value !== null) void loadPages()
  void loadConsistencyState()
})

watch(selectedWorkflowId, () => {
  void loadPages()
})

watch(activeGenerationTab, (tab) => {
  if (route.query.tab !== tab) syncContextQuery()
  if (tab === 'consistency') void loadConsistencyState()
})

watch(() => route.query.evaluation_task_id, () => {
  void loadConsistencyState()
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

// 50 页批次分页后切换到较短批次或增大每页数量，不能停留在不存在的页码。
watch([() => filteredPages.value.length, pageTablePageSize], () => {
  pageTablePage.value = Math.min(pageTablePage.value, Math.max(1, Math.ceil(filteredPages.value.length / pageTablePageSize.value)))
})

watch([selectedBatch, generatedPageCount], () => { if (selectedBatch.value) syncGenerationActivity(selectedBatch.value, pages.value.length) })
watch(consistencyTask, syncConsistencyActivity, { deep: true })
watch([selectedProjectId, selectedTaskId, selectedBatchId, () => selectedBatch.value?.status, visibleGenerationRunning], () => startExternalBatchPolling())

onMounted(async () => {
  const requestedProject = queryId(route.query.project_id)
  if (requestedProject !== null) selectedProjectId.value = requestedProject
  await refreshAll()
  applyRouteContext()
  if (typeof window !== 'undefined') window.addEventListener('focus', refreshExternalBatchOnFocus)
})

onBeforeUnmount(() => {
  viewMounted = false
  closeQuickPicker()
  stopExternalBatchPolling()
  if (typeof window !== 'undefined') window.removeEventListener('focus', refreshExternalBatchOnFocus)
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
        <el-button class="ai-gradient-button" type="primary" :icon="Picture" :loading="visibleGenerationRunning && generating" :disabled="!canGenerate" @click="generateBatch">{{ t('imageGeneration.actions.generate') }}</el-button>
        <el-button v-if="batchCanContinue" type="primary" plain :icon="Picture" :loading="visibleGenerationRunning && continuing" :disabled="!canContinueGeneration" @click="continueBatch">{{ t('imageGeneration.actions.continue') }}</el-button>
        <el-button v-if="visibleGenerationRunning || selectedBatch?.status === 'running'" type="warning" :icon="VideoPause" :loading="suspending" :disabled="suspending || (visibleGenerationRunning && runningGeneration?.batchId === null)" @click="suspendGeneration">{{ t('imageGeneration.actions.suspend') }}</el-button>
        <el-button @click="progressDrawerOpen = true">{{ t('imageGeneration.progress.title') }}</el-button>
      </div>
    </div>
    <WorkflowReadiness
      :title="t('imageGeneration.readiness.title')"
      :description="t('imageGeneration.readiness.description')"
      :items="generationReadinessItems"
    />

      <section class="panel generation-config">
        <header class="panel-header">
          <div>
            <div class="title-with-info"><h2>{{ t('imageGeneration.generation.title') }}</h2><InfoTip :content="t('imageGeneration.generation.description')" :label="t('imageGeneration.generation.title')" /></div>
          </div>
          <div class="generation-config-actions">
            <el-button link @click="router.push({ path: '/settings', query: { tab: 'image-tools' } })">{{ t('imageGeneration.readiness.manageTools') }}</el-button>
          </div>
        </header>

        <el-form label-position="top">
          <div class="generation-main-fields">
            <el-form-item :label="t('imageGeneration.generation.workflow')">
              <template #label><span class="field-with-info">{{ t('imageGeneration.generation.workflow') }}<InfoTip :content="t('ux.optionalReferencesHelp')" :label="t('imageGeneration.generation.workflow')" /></span></template>
              <el-select v-model="selectedWorkflowId" filterable>
                <el-option v-for="workflow in workflows" :key="workflow.id" :label="workflow.name" :value="workflow.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.candidates')">
              <el-input-number v-model="generationForm.candidates_per_page" :min="1" :max="4" />
            </el-form-item>
            <el-form-item :label="t('referenceLibrary.width')">
              <el-input-number v-model="generationForm.width" :min="256" :max="2048" :step="32" step-strictly />
            </el-form-item>
            <el-form-item :label="t('referenceLibrary.height')">
              <el-input-number v-model="generationForm.height" :min="256" :max="2048" :step="32" step-strictly />
            </el-form-item>
          </div>
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

        <div class="generation-scope">
          <div>
            <span>{{ t('imageGeneration.generation.scopePages') }}</span>
            <strong>{{ targetPages.length }}</strong>
          </div>
          <div>
            <span>{{ t('imageGeneration.generation.scopeCandidates') }}</span>
            <strong>{{ generationForm.candidates_per_page }}</strong>
          </div>
          <div>
            <span>{{ t('imageGeneration.generation.scopeRequests') }}</span>
            <strong>{{ targetPages.length * generationForm.candidates_per_page }}</strong>
          </div>
        </div>

        <div class="generation-blocker">
          <span>{{ selectedPageIds.length
            ? t('imageGeneration.generation.selectedScope', { count: targetPages.length })
            : t('imageGeneration.generation.missingScope', { count: targetPages.length }) }}</span>
          <el-button link type="primary" @click="activeGenerationTab = 'results'">{{ t('imageGeneration.actions.choosePages') }}</el-button>
          <el-button v-if="selectedPageIds.length" link @click="selectedPageIds = []">{{ t('imageGeneration.actions.clearSelection') }}</el-button>
        </div>
        <p v-if="!canGenerate && !generationRunning" class="reference-help">{{ targetPages.some(page => page.spec_stale)
          ? t('imageGeneration.pages.staleHelp') : selectedTaskId && selectedWorkflowId && pages.length && !targetPages.length
          ? t('imageGeneration.generation.allHaveImages') : t('imageGeneration.readiness.completeSelections') }}</p>
      </section>

    <el-tabs v-model="activeGenerationTab" class="workspace-tabs generation-tabs">
      <el-tab-pane name="results">
        <template #label>
          {{ t('imageGeneration.tabs.results') }}
          <el-badge :value="generatedPageCount" :hidden="generatedPageCount === 0" />
        </template>
      </el-tab-pane>
      <el-tab-pane name="consistency">
        <template #label>
          {{ t('imageGeneration.tabs.consistency') }}
          <el-badge v-if="consistencyTask" :is-dot="consistencyRunning" />
        </template>
      </el-tab-pane>
    </el-tabs>

    <div class="image-generation-grid">


      <el-drawer v-model="progressDrawerOpen" :title="t('imageGeneration.progress.title')" direction="rtl" size="min(480px, 96vw)" append-to-body>
        <el-empty
          v-if="progressEvents.length === 0 || (runningGeneration !== null && !generationContextVisible(runningGeneration))"
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
      </el-drawer>

      <section v-show="activeGenerationTab === 'consistency'" class="panel consistency-panel">
        <header class="panel-header consistency-header">
          <div>
            <div class="title-with-info"><h2>{{ t('imageGeneration.consistency.title') }}</h2><InfoTip :content="t('imageGeneration.consistency.description')" :label="t('imageGeneration.consistency.title')" /></div>
          </div>
          <div class="consistency-header__actions">
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
            <InfoTip :content="t('imageGeneration.consistency.manualHint')" :label="t('imageGeneration.consistency.evaluate')" />
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

          <div
            v-if="(consistencyTask?.tracks.length ?? 0) > 0"
            class="consistency-tracks"
          >
            <article v-for="track in consistencyTask?.tracks ?? []" :key="track.id" class="consistency-track">
              <header class="consistency-track__header">
                <div class="consistency-track__title">
                  <strong>{{ t('imageGeneration.consistency.candidate') }} #{{ track.candidate_index }}</strong>
                  <el-tag :type="consistencyStatusType(track.status)" size="small">{{ trackStatusLabel(track) }}</el-tag>
                  <span class="muted">{{ t('imageGeneration.consistency.trackImages') }} · {{ Object.keys(track.image_ids).length }}</span>
                </div>
                <el-tag v-if="track.adopted_at" type="success" size="small">
                  {{ t('imageGeneration.consistency.adopted') }}
                </el-tag>
                <el-button
                  v-else
                  plain
                  type="success"
                  :loading="adoptingTrackId === track.id"
                  :disabled="!['passed', 'failed'].includes(track.status) || consistencyTask?.status !== 'succeeded'"
                  @click="adoptTrack(track)"
                >
                  {{ t('imageGeneration.consistency.adoptTrack') }}
                </el-button>
              </header>
              <p v-if="track.error_message" class="track-error">{{ consistencyIssueText({ code: track.error_code, message: track.error_message }) }}</p>
              <div class="consistency-metrics">
                <div v-for="metric in consistencyMetricKeys" :key="metric" class="consistency-metric">
                  <el-tooltip :content="t(`imageGeneration.consistency.metricHelp.${metric}`)" placement="top">
                    <span class="metric-header" tabindex="0">{{ metricColumnLabel(metric) }}</span>
                  </el-tooltip>
                  <el-tag :type="metricType(track, metric)" effect="plain">{{ formatMetric(track, metric) }}</el-tag>
                </div>
              </div>
            </article>
          </div>
          <el-empty
            v-else-if="consistencyTask === null"
            :description="t('imageGeneration.consistency.noEvaluation')"
          />
        </div>
      </section>

      <section v-if="activeGenerationTab === 'results'" class="panel result-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('imageGeneration.pages.title') }}</h2>
            <p>{{ selectedProject?.title || t('imageGeneration.pages.noProject') }}</p>
          </div>
          <el-button :icon="Select" :disabled="!canOpenQuickPicker" @click="openQuickPicker">
            {{ t('imageGeneration.quick.title') }}
          </el-button>
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
          <el-button :disabled="generationRunning || !filteredPages.length" @click="selectedPageIds = [...new Set([...selectedPageIds, ...filteredPages.map(page => page.page_id)])]">{{ t('imageGeneration.actions.selectFiltered') }}</el-button>
          <el-button v-if="selectedPageIds.length" :disabled="generationRunning" @click="selectedPageIds = []">{{ t('imageGeneration.actions.clearSelection') }}</el-button>
          <el-button type="primary" :disabled="!selectedPageIds.length || !canGenerate" @click="generateBatch">{{ t('imageGeneration.actions.generateSelected', { count: selectedPageIds.length }) }}</el-button>
          <span class="workspace-toolbar__spacer" />
          <span class="muted">{{ t('imageGeneration.pages.resultCount', { count: filteredPages.length }) }}</span>
        </div>

        <form class="page-range-selector" @submit.prevent="selectPageRange">
          <span>{{ t('imageGeneration.pageRange.label') }}</span>
          <el-input-number v-model="pageRangeStart" :min="1" :max="maxPageNumber || 1" :step="1" step-strictly
            :controls="false" :disabled="generationRunning || loadingPages || !pages.length"
            :placeholder="t('imageGeneration.pageRange.start')" :aria-label="t('imageGeneration.pageRange.start')" />
          <span>{{ t('imageGeneration.pageRange.to') }}</span>
          <el-input-number v-model="pageRangeEnd" :min="1" :max="maxPageNumber || 1" :step="1" step-strictly
            :controls="false" :disabled="generationRunning || loadingPages || !pages.length"
            :placeholder="t('imageGeneration.pageRange.end')" :aria-label="t('imageGeneration.pageRange.end')" />
          <el-button native-type="submit" :disabled="!canSelectPageRange">{{ t('imageGeneration.pageRange.select') }}</el-button>
          <span class="page-range-selector__hint" :class="{ 'page-range-selector__hint--invalid': pageRangeStart !== null && pageRangeEnd !== null && !pageRangeValid }">
            {{ pageRangeStart !== null && pageRangeEnd !== null && !pageRangeValid
              ? t('imageGeneration.pageRange.invalid', { max: maxPageNumber })
              : pageRangeValid && !pagesInRange.length ? t('imageGeneration.pageRange.empty') : t('imageGeneration.pageRange.hint') }}
          </span>
        </form>

        <div
          v-if="paginatedPages.length > 0"
          v-loading="loadingPages"
          class="page-results"
        >
          <article v-for="page in paginatedPages" :key="page.page_id" class="page-result" :class="{ 'page-result--multiple': page.images.length > 1 }">
            <header class="page-result__header">
              <div class="page-result__title">
                <el-checkbox :model-value="selectedPageIds.includes(page.page_id)" :disabled="generationRunning" :aria-label="t('imageGeneration.actions.selectPage', { page: page.page_no })" @change="togglePageSelection(page.page_id, Boolean($event))" />
                <h3>{{ t('imageGeneration.pages.pageLabel', { page: page.page_no }) }}</h3>
                <el-tag size="small" :type="page.spec_stale ? 'warning' : page.latest_spec_id ? 'success' : 'info'">
                  {{
                    page.spec_stale
                      ? t('imageGeneration.pages.specStale') : page.latest_spec_id
                      ? t('imageGeneration.pages.promptReady')
                      : t('imageGeneration.pages.specMissing')
                  }}
                </el-tag>
                <el-tag v-if="page.spec_warnings.length" size="small" type="warning">
                  {{ t('imageGeneration.pages.warningCount', { count: page.spec_warnings.length }) }}
                </el-tag>
              </div>
              <el-button size="small" plain type="primary" :disabled="generationRunning || !selectedWorkflowId || !pageSpecificationReady(page)" @click="generatePage(page)">{{ t('imageGeneration.actions.generatePage') }}</el-button>
            </header>
            <details v-if="page.positive_prompt" class="page-prompt">
              <summary>{{ t('imageGeneration.pages.prompt') }}<span>{{ shortText(page.positive_prompt, 90) }}</span></summary>
              <p>{{ page.positive_prompt }}</p>
            </details>
            <div class="image-strip" :class="{ 'image-strip--single': page.images.length === 1 }">
                <article v-for="(image, index) in page.images" :key="image.id" class="image-card" :class="{ 'image-card--selected': image.is_selected }">
                  <el-image
                    :src="image.image_url || ''"
                    :preview-src-list="imagePreviewUrls(page.images)"
                    :initial-index="Math.max(0, imagePreviewUrls(page.images).indexOf(image.image_url || ''))"
                    :alt="t('imageGeneration.pages.candidateImage', { page: page.page_no, index: index + 1 })"
                    fit="contain"
                    lazy
                    preview-teleported
                    class="image-card__img"
                  />
                  <div class="image-card__actions">
                    <el-tag v-if="image.is_selected" class="image-card__selection" type="success">
                      {{ t('imageGeneration.pages.selected') }}
                    </el-tag>
                    <el-button v-else class="image-card__selection" type="success" plain :icon="Select" :loading="selectingImageId === image.id" :disabled="selectingImageId !== null" @click="selectFinalImage(page, image)">
                      {{ t('imageGeneration.actions.select') }}
                    </el-button>
                    <div class="image-card__secondary">
                      <el-button link type="primary" :icon="View" @click="openDetail(image)">{{ t('imageGeneration.actions.view') }}</el-button>
                      <el-dropdown trigger="click">
                        <el-button link :icon="MoreFilled" :aria-label="t('imageGeneration.actions.more')">{{ t('imageGeneration.actions.more') }}</el-button>
                        <template #dropdown><el-dropdown-menu>
                          <el-dropdown-item v-if="image.generation_run_id" @click="openProvenance(image)">{{ t('imageGeneration.actions.provenance') }}</el-dropdown-item>
                          <el-dropdown-item @click="openPromote(image)">{{ t('imageGeneration.actions.promote') }}</el-dropdown-item>
                        </el-dropdown-menu></template>
                      </el-dropdown>
                    </div>
                  </div>
                </article>
                <span v-if="page.images.length === 0" class="muted page-result__empty">{{
                  t('imageGeneration.pages.noImages')
                }}</span>
            </div>
          </article>
        </div>
        <el-empty v-else :description="t('imageGeneration.pages.emptyFiltered')">
          <el-button
            v-if="specReadyPageCount < pages.length"
            type="primary"
            plain
            @click="router.push({ path: '/image-specs', query: { project_id: selectedProjectId ?? undefined, script_task_id: selectedTaskId ?? undefined } })"
          >{{ t('imageGeneration.readiness.openSpecs') }}</el-button>
        </el-empty>
        <div v-if="filteredPages.length > 10" class="result-pagination">
          <el-pagination
            v-model:current-page="pageTablePage"
            v-model:page-size="pageTablePageSize"
            :total="filteredPages.length"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :pager-count="5"
            background
          />
        </div>
      </section>
    </div>



    <ComicQuickPicker v-if="quickDialog" :pages="quickPages" :page-id="quickPageId"
      :saving-image-id="selectingImageId" :loading="loadingPages" :reached-end="quickReachedEnd"
      @close="closeQuickPicker" @page="changeQuickPage" @move="moveQuickPage" @confirm="confirmQuickImage" />

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
        generationRun ? `${t('imageGeneration.provenance.title')} #${generationRun.id}` : t('imageGeneration.provenance.title')
      "
    >
      <section v-loading="provenanceLoading" class="provenance-content">
        <template v-if="generationRun">
          <el-descriptions :column="2" border>
            <el-descriptions-item :label="t('imageGeneration.provenance.status')">
              {{ generationRun.status }}
            </el-descriptions-item>
            <el-descriptions-item :label="t('imageGeneration.provenance.preparedPrompt')"
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
      <template #header><div class="title-with-info"><span>{{ t('imageGeneration.promotion.title') }}</span><InfoTip :content="t('imageGeneration.promotion.hint')" :label="t('imageGeneration.promotion.title')" /></div></template>
      <el-form label-position="top" class="promotion-form">
        <div class="workflow-node-grid">
          <el-form-item :label="t('imageGeneration.promotion.entityType')">
            <el-select v-model="promoteForm.entity_type">
              <el-option v-for="item in promotionCatalog" :key="item.entity_type" :label="t(`visualBible.entityLabels.${item.entity_type}`)" :value="item.entity_type" />
            </el-select>
          </el-form-item>
          <el-form-item :label="t('imageGeneration.promotion.ownerId')" required>
            <el-select v-if="promoteForm.entity_type === 'character'" v-model="promoteForm.entity_id" filterable><el-option v-for="owner in promotionOwners" :key="owner.id" :label="owner.name" :value="owner.id" /></el-select>
            <el-select v-else v-model="promoteForm.reference_subject_id" filterable><el-option v-for="owner in promotionOwners" :key="owner.id" :label="owner.name" :value="owner.id" /></el-select>
          </el-form-item>
          <el-form-item v-if="promoteForm.entity_type === 'character'" :label="t('referenceLibrary.applicability')">
            <template #label><span class="field-with-info">{{ t('referenceLibrary.applicability') }}<InfoTip :content="t('referenceLibrary.outfitHelp')" :label="t('referenceLibrary.applicability')" /></span></template>
            <el-select v-model="promoteForm.outfit_variant_id" clearable :placeholder="t('referenceLibrary.anyOutfit')"><el-option v-for="outfit in promotionOutfits.filter(item => item.outline_character_id === promoteForm.entity_id)" :key="outfit.id" :label="outfit.name" :value="outfit.id" /></el-select>
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
        <el-button type="primary" :loading="promoting" :disabled="promoteForm.entity_type === 'character' ? promoteForm.entity_id === null : promoteForm.reference_subject_id === null" @click="savePromotion">
          {{ t('imageGeneration.actions.promote') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.image-generation-page {
  container-type: inline-size;
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
  flex-wrap: wrap;
  align-items: flex-start;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.panel-header p,
.muted {
  color: var(--text-soft);
  overflow-wrap: anywhere;
}

.panel-header h2 { font-size: 18px; line-height: 1.4; }
.panel-header p { margin-top: 6px; font-size: 13px; line-height: 1.6; }

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
  padding: 20px;
}

.result-panel,
.consistency-panel,
.workflow-panel {
  grid-column: 1 / -1;
}

.generation-config { margin-bottom: 18px; }

.workspace-context { display: grid; grid-template-columns: minmax(160px, .8fr) minmax(170px, 1fr) minmax(180px, 1.1fr); align-items: center; gap: 12px; padding: 16px 20px; }
.workspace-context__title { min-width: 0; overflow-wrap: anywhere; }
.workspace-context .generation-actions { grid-column: 1 / -1; margin: 0; }
.workspace-context .generation-actions:empty { display: none; }
.generation-main-fields { display: grid; grid-template-columns: minmax(200px, 1fr) minmax(150px, .7fr); gap: 16px; }
.generation-config-actions { display: flex; flex-wrap: wrap; gap: 12px; }
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
  overflow-wrap: anywhere;
}

.track-error {
  color: var(--el-color-danger);
  line-height: 1.5;
  font-size: 13px;
  overflow-wrap: anywhere;
}

.consistency-tracks { display: grid; gap: 16px; min-width: 0; }
.consistency-track { padding: 16px; border: 1px solid var(--panel-border); border-radius: 10px; background: #fbfcff; min-width: 0; }
.consistency-track__header, .consistency-track__title { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.consistency-track__header { justify-content: space-between; margin-bottom: 14px; }
.consistency-track__title { font-size: 13px; }
.consistency-track__title strong { font-size: 15px; }
.consistency-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.consistency-metric { display: grid; justify-items: start; align-content: space-between; gap: 12px; min-width: 0; padding: 14px; background: white; border: 1px solid var(--panel-border); border-radius: 8px; }
.consistency-metric .metric-header { font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.consistency-metric .el-tag { font-size: 16px; font-variant-numeric: tabular-nums; font-weight: 600; }
.consistency-meta :deep(.el-tag), .incomplete-tracks :deep(.el-tag), .consistency-header__actions :deep(.el-tag) { height: auto; min-height: 24px; white-space: normal; }
.consistency-meta :deep(.el-tag__content), .incomplete-tracks :deep(.el-tag__content), .consistency-header__actions :deep(.el-tag__content) { white-space: normal; overflow-wrap: anywhere; line-height: 1.6; }

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
.generation-actions .el-button + .el-button { margin-left: 0; }

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
  flex: 1 1 240px;
  min-width: 0;
  width: auto;
}

.result-toolbar :deep(.el-select) {
  width: 170px;
}

.page-range-selector { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 16px; font-size: 13px; }
.page-range-selector :deep(.el-input-number) { width: 110px; }
.page-range-selector__hint { color: var(--text-secondary); }
.page-range-selector__hint--invalid { color: var(--el-color-danger); }

.result-pagination {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}
.result-pagination :deep(.el-pagination) { flex-wrap: wrap; justify-content: center; gap: 8px; }

.metric-header {
  border-bottom: 1px dotted currentColor;
  cursor: help;
}

.image-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 320px));
  justify-content: center;
  gap: 14px;
  align-items: start;
}

.image-strip--single { grid-template-columns: minmax(0, 320px); justify-content: center; }
.page-results { display: grid; grid-template-columns: minmax(0, 1fr); align-items: start; gap: 18px; }
.page-result--multiple { grid-column: 1 / -1; }
.page-result { min-width: 0; padding: 16px; border: 1px solid var(--panel-border); border-radius: 10px; background: #fcfdff; }
.page-result__header, .page-result__title { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.page-result__header { justify-content: space-between; margin-bottom: 14px; }
.page-result__title h3 { margin: 0 2px 0 0; font-size: 16px; }
.page-result__empty { font-size: 13px; padding: 16px 0; }
.page-prompt { margin-bottom: 14px; font-size: 12px; color: var(--text-soft); }
.page-prompt summary { cursor: pointer; line-height: 1.7; }
.page-prompt summary span { margin-left: 10px; overflow-wrap: anywhere; }
.page-prompt p { max-height: 240px; overflow: auto; padding: 12px; margin: 8px 0 0; border-radius: 6px; background: var(--el-fill-color-light); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }

.image-card {
  min-width: 0;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  overflow: hidden;
  background: white;
}
.image-card--selected { border-color: var(--el-color-success-light-3); box-shadow: 0 0 0 1px var(--el-color-success-light-7); }

.image-card__img {
  width: 100%;
  aspect-ratio: 4 / 5;
  display: block;
  background: #f0f3f8;
}

.image-card__actions {
  display: grid;
  gap: 10px;
  padding: 10px;
}
.image-card__selection { width: 100%; min-height: 32px; }
.image-card__secondary { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
.image-card__actions .el-button + .el-button { margin-left: 0; }

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
  .generation-config {
    min-width: 0;
  }

}

@container (min-width: 820px) {
  .page-results { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@container (max-width: 860px) {
  .workspace-context { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workspace-context__title { grid-column: 1 / -1; }
  .generation-main-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .generation-main-fields > :first-child { grid-column: 1 / -1; }
}

@container (max-width: 600px) {
  .workspace-context, .generation-main-fields { grid-template-columns: 1fr; }
  .panel { padding: 14px; }
  .page-result, .consistency-track { padding: 12px; }
  .consistency-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .generation-scope {
    grid-template-columns: 1fr;
  }

  .result-toolbar :deep(.el-input),
  .result-toolbar :deep(.el-select) {
    width: 100%;
    flex-basis: 100%;
  }
  .result-toolbar .workspace-toolbar__spacer { display: none; }
  .result-pagination { justify-content: center; }
  .result-pagination :deep(.el-pagination__total), .result-pagination :deep(.el-pagination__sizes) { flex-basis: 100%; margin: 0; text-align: center; }
  .page-prompt summary span { display: none; }
}
</style>

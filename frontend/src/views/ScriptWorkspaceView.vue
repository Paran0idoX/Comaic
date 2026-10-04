<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import {
  Delete,
  Document,
  EditPen,
  MoreFilled,
  Plus,
  Refresh,
  Search,
  Tickets,
  VideoPause,
  View,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, nextTick, onActivated, onDeactivated, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { resolveOutlineSession, type OutlineVersion } from '@/api/outline'
import { ApiError, apiErrorMessage } from '@/api/errors'
import {
  clearPageScript,
  createPageScript,
  deleteAllProjectPages,
  deleteScriptTaskSections,
  listProjectScriptTasks,
  listScriptTaskPages,
  listScriptTaskCharacters,
  listScriptTaskScenes,
  listScriptTaskSections,
  suspendScriptTask,
  streamBatchScriptGeneration,
  streamContinueScriptGeneration,
  streamReviewScriptPages,
  updatePageScript,
  type ScriptPage,
  type ScriptCharacter,
  type ScriptScene,
  type ScriptSection,
  type ScriptTask,
  type SceneConditions,
} from '@/api/scripts'
import { formatLocalDateTime, formatLocalNowTime } from '@/utils/datetime'
import { useProjectContextStore } from '@/stores/projectContext'
import { useActivityCenterStore, type ActivityStatus } from '@/stores/activityCenter'

// 组件名用于 AppShell 的 KeepAlive include 精准缓存脚本工作台。
defineOptions({ name: 'ScriptWorkspaceView' })

type TimelineLevel = 'primary' | 'success' | 'warning' | 'danger' | 'info'

type ProgressEvent = {
  id: number
  title: string
  content: string
  timestamp: string
  type: TimelineLevel
}

type ScriptRunContext = {
  readonly projectId: number
  readonly outlineVersionId: number | null
  readonly totalPages: number
  taskId: number | null
  status: ActivityStatus
  completedPageIds: Set<number>
  events: ProgressEvent[]
}

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()
const projectContext = useProjectContextStore()
const activityCenter = useActivityCenterStore()
const { selectedProjectId, projects, loadingProjects } = storeToRefs(projectContext)

const outlineVersions = ref<OutlineVersion[]>([])
const scriptTasks = ref<ScriptTask[]>([])
const sections = ref<ScriptSection[]>([])
const scenes = ref<ScriptScene[]>([])
const visualCharacters = ref<ScriptCharacter[]>([])
const pages = ref<ScriptPage[]>([])
const selectedOutlineVersionId = ref<number | null>(null)
const selectedTaskId = ref<number | null>(null)
const unavailableTaskId = ref<number | null>(null)
const selectedSectionNo = ref<number | null>(null)
// 运行上下文不跟随浏览选择变化，避免切换项目后旧 SSE 写入当前工作台或暂停错误任务。
const runContext = shallowRef<ScriptRunContext | null>(null)
const workspaceActive = ref(true)
const showGenerationConfiguration = ref(false)
const totalPages = ref(12)
const userRequirement = ref('')
const progressEvents = ref<ProgressEvent[]>([])
const selectedPage = ref<ScriptPage | null>(null)
const detailVisible = ref(false)
const scriptDialogVisible = ref(false)
const scriptDialogMode = ref<'create' | 'edit'>('create')
const scriptFormPageNo = ref(1)
const scriptForm = reactive({
  scene_id: null as number | null,
  character_ids: [] as number[],
  scene_conditions: { time_of_day: '', weather: '', lighting: '', atmosphere: '' } as SceneConditions,
  summary: '',
  characters: '',
  clothing: '',
  scene: '',
  composition: '',
  character_action: '',
  dialogue: '无',
})
const savingScript = ref(false)

const loadingOutlineVersions = ref(false)
const loadingTasks = ref(false)
const loadingSections = ref(false)
const loadingVisualSettings = ref(false)
const loadingPages = ref(false)
const generatingBatch = ref(false)
const suspendingBatch = ref(false)
const continuingBatch = ref(false)
const reviewingPages = ref(false)
const needsOutline = ref(false)
const eventSequence = ref(1)
const activeScriptTab = ref<'pages' | 'visual'>(
  (localStorage.getItem('comaic-script-workspace-tab') as 'pages' | 'visual') || 'pages',
)
const pageSearch = ref(localStorage.getItem('comaic-script-page-search') ?? '')
const pageStatusFilter = ref<'all' | 'passed' | 'pending' | 'failed'>('all')
const pageTablePage = ref(1)
const pageTablePageSize = ref(20)

const selectedProject = computed(() =>
  projects.value.find((project) => project.id === selectedProjectId.value),
)

const sortedPages = computed(() =>
  [...pages.value].sort((left, right) => left.page_no - right.page_no),
)

const currentTask = computed(() =>
  scriptTasks.value.find((task) => task.id === selectedTaskId.value) ?? null,
)
const selectedOutlineVersion = computed(
  () => outlineVersions.value.find((version) => version.version_id === selectedOutlineVersionId.value) ?? null,
)
const isSelectedOutlineConfirmed = computed(() =>
  Boolean(selectedOutlineVersion.value?.confirmed_at),
)

const displayedPages = computed(() => {
  if (selectedSectionNo.value === null) {
    return sortedPages.value
  }
  return sortedPages.value.filter((page) => page.section_no === selectedSectionNo.value)
})
const filteredPages = computed(() => {
  const query = pageSearch.value.trim().toLowerCase()
  return displayedPages.value.filter((page) => {
    const statusMatches =
      pageStatusFilter.value === 'all' ||
      (pageStatusFilter.value === 'passed' && page.script_review_status === 'passed') ||
      (pageStatusFilter.value === 'pending' &&
        page.summary !== null &&
        !['passed', 'failed'].includes(page.script_review_status)) ||
      (pageStatusFilter.value === 'failed' && page.script_review_status === 'failed')
    if (!statusMatches) return false
    if (!query) return true
    return [page.page_no, page.summary, page.scene, page.characters, page.dialogue]
      .filter((value) => value !== null)
      .some((value) => String(value).toLowerCase().includes(query))
  })
})
const paginatedPages = computed(() => {
  const start = (pageTablePage.value - 1) * pageTablePageSize.value
  return filteredPages.value.slice(start, start + pageTablePageSize.value)
})

const taskTotalPages = computed(() => currentTask.value?.total_pages ?? totalPages.value)
const completedPageCount = computed(
  () => pages.value.filter((page) => page.script_review_status === 'passed').length,
)
const completionPercentage = computed(() => {
  if (currentTask.value === null || taskTotalPages.value <= 0) {
    return 0
  }
  return Math.min(100, Math.round((completedPageCount.value / taskTotalPages.value) * 100))
})
const expandedCharacterGroups = ref<string[]>([])
const groupedVisualCharacters = computed(() => {
  const groups = new Map<
    string,
    {
      character_key: string
      name: string
      items: ScriptCharacter[]
    }
  >()

  const sortedCharacters = [...visualCharacters.value].sort((left, right) => {
    const keyOrder = left.character_key.localeCompare(right.character_key)
    if (keyOrder !== 0) {
      return keyOrder
    }
    return (left.section_no ?? 0) - (right.section_no ?? 0)
  })

  for (const character of sortedCharacters) {
    const group = groups.get(character.character_key) ?? {
      character_key: character.character_key,
      name: character.name,
      items: [],
    }
    if (!group.name && character.name) {
      group.name = character.name
    }
    group.items.push(character)
    groups.set(character.character_key, group)
  }

  return [...groups.values()]
})

const canGenerate = computed(
  () =>
    selectedProjectId.value !== null &&
    selectedOutlineVersionId.value !== null &&
    isSelectedOutlineConfirmed.value &&
    !needsOutline.value &&
    !loadingOutlineVersions.value &&
    !loadingTasks.value &&
    !generatingBatch.value &&
    !continuingBatch.value &&
    !reviewingPages.value,
)

const generationDisabled = computed(() => !canGenerate.value)
const streamRunning = computed(() => generatingBatch.value || continuingBatch.value || reviewingPages.value)
const completedTask = computed(() => currentTask.value?.status === 'succeeded')
const configurationExpanded = computed(() => !completedTask.value || showGenerationConfiguration.value)
const runIsVisible = (context: ScriptRunContext) =>
  selectedProjectId.value === context.projectId &&
  selectedOutlineVersionId.value === context.outlineVersionId &&
  selectedTaskId.value === context.taskId
const runningElsewhere = computed(() => streamRunning.value && runContext.value !== null && !runIsVisible(runContext.value))
const canEditScripts = computed(
  () =>
    selectedProjectId.value !== null &&
    selectedTaskId.value !== null &&
    !generatingBatch.value &&
    !continuingBatch.value &&
    !reviewingPages.value,
)
const canDeleteAllScripts = computed(() => canEditScripts.value && pages.value.length > 0)
const pendingReviewCount = computed(
  () =>
    pages.value.filter(
      (page) => page.summary !== null && page.script_review_status !== 'passed',
    ).length,
)
const canReviewPages = computed(
  () =>
    currentTask.value?.status === 'succeeded' &&
    pendingReviewCount.value > 0 &&
    !generatingBatch.value &&
    !continuingBatch.value &&
    !reviewingPages.value,
)
const canContinueBatch = computed(
  () =>
    currentTask.value !== null &&
    currentTask.value.mode === 'batch' &&
    ['suspended', 'failed'].includes(currentTask.value.status) &&
    !generatingBatch.value &&
    !continuingBatch.value &&
    !reviewingPages.value,
)

const normalizeTaskActivityStatus = (status: string): ActivityStatus => {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'suspended') return 'suspended'
  if (status === 'running') return 'running'
  return 'pending'
}

const formatDateTime = (value: string) => {
  return formatLocalDateTime(value, locale.value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

const nowLabel = () => formatLocalNowTime(locale.value)

// 脚本表格只展示摘要，完整结构化脚本通过详情弹窗查看，避免表格被长文本撑开。
const scriptSummary = (summary: string | null) => {
  if (!summary) {
    return t('scripts.pages.noScript')
  }

  const compact = summary.replace(/\s+/g, ' ').trim()
  return compact.length > 86 ? `${compact.slice(0, 86)}...` : compact
}

const resetScriptForm = () => {
  scriptForm.scene_id = null
  scriptForm.character_ids = []
  scriptForm.scene_conditions = { time_of_day: '', weather: '', lighting: '', atmosphere: '' }
  scriptForm.summary = ''
  scriptForm.characters = ''
  scriptForm.clothing = ''
  scriptForm.scene = ''
  scriptForm.composition = ''
  scriptForm.character_action = ''
  scriptForm.dialogue = '无'
}

const fillScriptForm = (page: ScriptPage) => {
  scriptForm.scene_id = page.scene_id ?? null
  scriptForm.character_ids = pageCharacterBindings(page).map(character => character.id)
  scriptForm.scene_conditions = { ...pageConditions(page) }
  scriptForm.summary = page.summary ?? ''
  scriptForm.characters = page.characters ?? ''
  scriptForm.clothing = page.clothing ?? ''
  scriptForm.scene = page.scene ?? ''
  scriptForm.composition = page.composition ?? ''
  scriptForm.character_action = page.character_action ?? ''
  scriptForm.dialogue = page.dialogue ?? '无'
}

const buildScriptPayload = () => ({
  ...(scriptForm.scene_id !== null ? { scene_id: scriptForm.scene_id } : {}),
  character_ids: [...scriptForm.character_ids],
  scene_conditions: { ...scriptForm.scene_conditions },
  summary: scriptForm.summary.trim(),
  characters: scriptForm.characters.trim(),
  clothing: scriptForm.clothing.trim(),
  scene: scriptForm.scene.trim(),
  composition: scriptForm.composition.trim(),
  character_action: scriptForm.character_action.trim(),
  dialogue: scriptForm.dialogue.trim() || '无',
})

const requiredScriptFieldsFilled = () =>
  Boolean(
    scriptForm.summary.trim() &&
      scriptForm.characters.trim() &&
      scriptForm.clothing.trim() &&
      scriptForm.scene.trim() &&
      scriptForm.composition.trim() &&
      scriptForm.character_action.trim(),
  )

// ID 决定关联，名称只用于阅读；历史响应缺少摘要时从当前批次的锁定设定回填。
const pageCharacterBindings = (page: ScriptPage) => page.character_bindings ?? visualCharacters.value
  .filter(character => character.section_id === page.section_id && (page.character_keys ?? []).includes(character.character_key))
const pageSceneName = (page: ScriptPage) => page.reference_subject_name || page.scene_name ||
  scenes.value.find(scene => scene.id === page.scene_id)?.name || t('scripts.bindings.unbound')
const pageConditions = (page: ScriptPage): SceneConditions => {
  const scene = scenes.value.find(item => item.id === page.scene_id)
  return page.scene_conditions ?? { time_of_day: scene?.time_of_day || '', weather: scene?.weather || '', lighting: scene?.lighting || '', atmosphere: '' }
}
const pageCharacterDetails = (page: ScriptPage) => pageCharacterBindings(page)
  .map(binding => visualCharacters.value.find(character => character.id === binding.id))
  .filter((character): character is ScriptCharacter => Boolean(character))
const pageSceneDetails = (page: ScriptPage) => scenes.value.find(scene => scene.id === page.scene_id)
// 直接展示已保存字段，不把自由描述推断成新的设定；基准与分段变化分组阅读。
const baselineFields = ['name', 'role', 'background', 'appearance', 'default_hairstyle', 'default_clothing', 'default_accessories', 'default_color_palette', 'negative_constraints'] as const
const sectionCharacterFields = ['section_role', 'current_hairstyle', 'current_clothing', 'current_accessories', 'current_state', 'emotion', 'temporary_changes', 'negative_constraints'] as const
const fixedSceneFields = ['location_type', 'environment_details', 'color_palette', 'negative_constraints'] as const
const detailFieldValue = (value: unknown) => typeof value === 'string' && value.trim() ? value : t('scripts.bindings.unspecified')
const editorSection = computed(() => scriptDialogMode.value === 'edit'
  ? sections.value.find(section => section.id === pages.value.find(page => page.page_no === scriptFormPageNo.value)?.section_id)
  : sections.value.find(section => section.page_start <= scriptFormPageNo.value && section.page_end >= scriptFormPageNo.value))
const editorCharacters = computed(() => visualCharacters.value.filter(character => character.section_id === editorSection.value?.id))
watch(scriptFormPageNo, () => {
  if (scriptDialogMode.value !== 'create') return
  const allowed = new Set(editorCharacters.value.map(character => character.id))
  scriptForm.character_ids = scriptForm.character_ids.filter(id => allowed.has(id))
})
const conditionFields: Array<keyof SceneConditions> = ['time_of_day', 'weather', 'lighting', 'atmosphere']

const reviewStatusLabel = (status: string) => {
  const key = `scripts.reviewStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

const reviewStatusTagType = (status: string) => {
  if (status === 'passed') {
    return 'success'
  }
  if (status === 'failed') {
    return 'danger'
  }
  if (status === 'reviewing') {
    return 'warning'
  }
  return 'info'
}

const sectionStatusLabel = (status: string) => {
  const key = `scripts.sectionStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

const sectionStatusTagType = (status: string) => {
  if (status === 'completed') {
    return 'success'
  }
  if (status === 'failed') {
    return 'danger'
  }
  return 'warning'
}

const outlineStatusLabel = (status: string) => {
  const key = `outline.versionStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

const outlineVersionLabel = (version: OutlineVersion) =>
  `v${version.version_no} · ${outlineStatusLabel(version.status)} · ${
    version.confirmed_at ? t('scripts.config.outlineConfirmed') : t('scripts.config.outlineUnconfirmed')
  } · ${formatDateTime(version.created_at)}`

const taskStatusLabel = (status: string) => {
  const key = `scripts.taskStatus.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

const taskModeLabel = (mode: string) => {
  const key = `scripts.taskMode.${mode}`
  const translated = t(key)
  return translated === key ? mode : translated
}

const scriptTaskLabel = (task: ScriptTask) =>
  `#${task.id} · ${taskModeLabel(task.mode)} · ${taskStatusLabel(task.status)} · ${task.total_pages} ${t('scripts.config.pagesUnit')} · ${formatDateTime(task.updated_at)}`

const sectionPageRange = (section: ScriptSection) =>
  `${t('scripts.pages.pageNoPrefix')}${section.page_start}-${section.page_end}${t('scripts.pages.pageNoSuffix')}`

const firstMissingPageNo = () => {
  const total = currentTask.value?.total_pages ?? totalPages.value
  const completed = new Set(pages.value.filter((page) => page.summary).map((page) => page.page_no))
  for (let pageNo = 1; pageNo <= total; pageNo += 1) {
    if (!completed.has(pageNo)) {
      return pageNo
    }
  }
  return Math.min(total + 1, 300)
}

// SSE 事件数据来源不完全一致，这里统一提取最有用的信息写入时间线。
const describePayload = (event: string, payload: Record<string, unknown>) => {
  if (typeof payload.code === 'string') {
    const key = `backendEvents.${payload.code}`
    const translated = t(key, {
      attempt: String(payload.attempt ?? '-'),
      sectionNo: String(payload.section_no ?? '-'),
      pageNo: String(payload.page_no ?? '-'),
      pageStart: String(payload.page_start ?? '-'),
      pageEnd: String(payload.page_end ?? '-'),
      count: String(payload.count ?? '-'),
      outfitCount: String(payload.outfit_count ?? '-'),
      sceneCount: String(payload.scene_count ?? '-'),
    })
    if (translated !== key) {
      return translated
    }
    const errorKey = `backendErrors.${payload.code}`
    const errorText = t(errorKey)
    if (errorText !== errorKey) {
      return errorText
    }
  }
  if (event === 'task') {
    return `#${String(payload.task_id ?? '-')}: ${String(payload.status ?? '-')}`
  }
  if (event === 'page') {
    const page = payload.page as ScriptPage | undefined
    const pageNo = String(page?.page_no ?? payload.page_no ?? '-')
    if (payload.action === 'created') {
      return t('scripts.events.pageCreated', { pageNo })
    }
    if (payload.action === 'updated') {
      const revisionNote = String(payload.revision_note ?? '')
      return revisionNote
        ? t('scripts.events.pageUpdatedWithNote', { pageNo, revisionNote })
        : t('scripts.events.pageUpdated', { pageNo })
    }
    return `${t('scripts.pages.pageNoPrefix')}${pageNo}${t('scripts.pages.pageNoSuffix')}`
  }
  if (event === 'section_pages') {
    const section = payload.section as Record<string, unknown> | undefined
    const pageCount = Array.isArray(payload.pages) ? payload.pages.length : 0
    return t('scripts.events.sectionPagesSaved', {
      sectionNo: String(section?.section_no ?? '-'),
      pageStart: String(section?.page_start ?? '-'),
      pageEnd: String(section?.page_end ?? '-'),
      count: String(pageCount),
    })
  }
  if (event === 'section') {
    const sectionNo = payload.section_no
    const pageStart = payload.page_start
    const pageEnd = payload.page_end
    if (sectionNo !== undefined && pageStart !== undefined && pageEnd !== undefined) {
      return t('scripts.events.sectionRange', {
        sectionNo: String(sectionNo),
        pageStart: String(pageStart),
        pageEnd: String(pageEnd),
        title: String(payload.title ?? ''),
        description: String(payload.description ?? ''),
      })
    }
  }
  if (event === 'review') {
    const pageNo = payload.page_no
    const suggestions = Array.isArray(payload.revision_suggestions)
      ? payload.revision_suggestions.map((item) => String(item)).filter(Boolean).join('；')
      : ''
    if (pageNo !== undefined && suggestions) {
      return `${t('scripts.pages.pageNoPrefix')}${String(pageNo)}${t('scripts.pages.pageNoSuffix')}：${suggestions}`
    }
    if (pageNo !== undefined) {
      return `${t('scripts.pages.pageNoPrefix')}${String(pageNo)}${t('scripts.pages.pageNoSuffix')}：${String(payload.summary ?? t('scripts.events.reviewDone'))}`
    }
    return String(payload.message ?? payload.result ?? payload.comment ?? payload.summary ?? t('scripts.events.reviewDone'))
  }
  if (event === 'error') {
    return String(payload.message ?? t('scripts.errors.batchFailed'))
  }
  if (event === 'suspended') {
    return `#${String(payload.task_id ?? '-')}: ${String(payload.status ?? 'suspended')}`
  }

  return String(payload.message ?? payload.description ?? payload.section ?? payload.status ?? '')
}

const eventType = (event: string): TimelineLevel => {
  if (event === 'done' || event === 'page' || event === 'section_pages') {
    return 'success'
  }
  if (event === 'review' || event === 'suspended') {
    return 'warning'
  }
  if (event === 'error') {
    return 'danger'
  }
  return 'primary'
}

const eventTitle = (event: string) => {
  const titleKey = `scripts.events.${event}`
  return t(titleKey) === titleKey ? event : t(titleKey)
}

const addProgressEvent = (event: string, payload: Record<string, unknown> = {}) => {

  progressEvents.value.unshift({
    id: eventSequence.value,
    title: eventTitle(event),
    content: describePayload(event, payload),
    timestamp: nowLabel(),
    type: eventType(event),
  })
  eventSequence.value += 1
}

const upsertPageInList = (page: ScriptPage) => {
  if (page.project_id !== selectedProjectId.value || page.task_id !== selectedTaskId.value) return
  pagesRequest += 1
  loadingPages.value = false
  // 同一项目的不同脚本任务可以拥有相同页码，前端合并时必须以页面主键为准。
  const index = pages.value.findIndex((item) => item.id === page.id)
  if (index === -1) {
    pages.value = [...pages.value, page]
  } else {
    pages.value.splice(index, 1, page)
  }

  if (selectedPage.value?.id === page.id || selectedPage.value?.page_no === page.page_no) {
    selectedPage.value = page
  }
}

const upsertSectionInList = (section: ScriptSection) => {
  if (section.task_id !== selectedTaskId.value) return
  sectionsRequest += 1
  loadingSections.value = false
  const index = sections.value.findIndex((item) => item.id === section.id)
  if (index === -1) {
    sections.value = [...sections.value, section].sort((left, right) => left.section_no - right.section_no)
  } else {
    sections.value.splice(index, 1, section)
  }
}

const loadProjects = async () => {
  try {
    // KeepAlive 中的工作台直接共享项目列表，新建或重命名后无需重建组件。
    await projectContext.refreshProjects()

    const queryProjectId = route.path === '/scripts' ? Number(route.query.project_id) : NaN
    if (Number.isFinite(queryProjectId) && projects.value.some((project) => project.id === queryProjectId)) {
      selectedProjectId.value = queryProjectId
      return
    }

    if (!projects.value.some((project) => project.id === selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? null
    }
  } catch {
    ElMessage.error(t('scripts.errors.loadProjects'))
  }
}

let pagesRequest = 0
let sectionsRequest = 0
let visualRequest = 0
let tasksRequest = 0
let outlineRequest = 0
let routeSelectionRequest = 0
let applyingRouteSelection = false

const clearTaskView = () => {
  pages.value = []
  sections.value = []
  scenes.value = []
  visualCharacters.value = []
  selectedSectionNo.value = null
  selectedPage.value = null
  detailVisible.value = false
  scriptDialogVisible.value = false
  progressEvents.value = runContext.value && runIsVisible(runContext.value) ? [...runContext.value.events] : []
}

const loadPages = async () => {
  const request = ++pagesRequest
  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  if (taskId === null) {
    pages.value = []
    loadingPages.value = false
    return
  }

  loadingPages.value = true
  try {
    const items = await listScriptTaskPages(taskId)
    if (request === pagesRequest && projectId === selectedProjectId.value && taskId === selectedTaskId.value) pages.value = items
  } catch {
    if (request === pagesRequest && taskId === selectedTaskId.value) ElMessage.error(t('scripts.errors.loadPages'))
  } finally {
    if (request === pagesRequest) loadingPages.value = false
  }
}

const loadSections = async () => {
  const request = ++sectionsRequest
  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  if (taskId === null) {
    sections.value = []
    loadingSections.value = false
    return
  }

  loadingSections.value = true
  try {
    const items = await listScriptTaskSections(taskId)
    if (request === sectionsRequest && projectId === selectedProjectId.value && taskId === selectedTaskId.value) sections.value = items
  } catch {
    if (request === sectionsRequest && taskId === selectedTaskId.value) ElMessage.error(t('scripts.errors.loadSections'))
  } finally {
    if (request === sectionsRequest) loadingSections.value = false
  }
}

const loadVisualSettings = async () => {
  const request = ++visualRequest
  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  if (taskId === null) {
    scenes.value = []
    visualCharacters.value = []
    loadingVisualSettings.value = false
    return
  }

  loadingVisualSettings.value = true
  try {
    const [sceneItems, characterItems] = await Promise.all([
      listScriptTaskScenes(taskId),
      listScriptTaskCharacters(taskId),
    ])
    if (request === visualRequest && projectId === selectedProjectId.value && taskId === selectedTaskId.value) {
      scenes.value = sceneItems
      visualCharacters.value = characterItems
    }
  } catch {
    if (request === visualRequest && taskId === selectedTaskId.value) ElMessage.error(t('scripts.errors.loadVisualSettings'))
  } finally {
    if (request === visualRequest) loadingVisualSettings.value = false
  }
}

let refreshingTaskStructure = false
let pendingTaskStructureRefresh = false

const refreshTaskStructure = () => {
  if (selectedTaskId.value === null) {
    return
  }
  if (refreshingTaskStructure) {
    pendingTaskStructureRefresh = true
    return
  }

  refreshingTaskStructure = true
  void Promise.all([loadSections(), loadVisualSettings()]).finally(() => {
    refreshingTaskStructure = false
    if (pendingTaskStructureRefresh) {
      pendingTaskStructureRefresh = false
      refreshTaskStructure()
    }
  })
}

const loadScriptTasks = async (preferredTaskId?: number | null) => {
  const request = ++tasksRequest
  const projectId = selectedProjectId.value
  const outlineId = selectedOutlineVersionId.value
  if (projectId === null || outlineId === null) {
    scriptTasks.value = []
    selectedTaskId.value = null
    loadingTasks.value = false
    return
  }

  loadingTasks.value = true
  try {
    const items = await listProjectScriptTasks(projectId, {
      outlineVersionId: outlineId,
    })
    if (request !== tasksRequest || projectId !== selectedProjectId.value || outlineId !== selectedOutlineVersionId.value) return
    scriptTasks.value = items
    const routeTaskId = route.path === '/scripts' && Number(route.query.project_id) === projectId ? Number(route.query.script_task_id) : NaN
    const requestedTaskId = preferredTaskId ?? (Number.isSafeInteger(routeTaskId) && routeTaskId > 0 ? routeTaskId : null)
    unavailableTaskId.value = requestedTaskId !== null && !items.some((task) => task.id === requestedTaskId) ? requestedTaskId : null
    const candidates = [
      preferredTaskId,
      Number.isFinite(routeTaskId) ? routeTaskId : null,
      selectedTaskId.value,
      scriptTasks.value[0]?.id ?? null,
    ]
    selectedTaskId.value =
      unavailableTaskId.value !== null || route.query.activity_legacy === '1' && preferredTaskId == null ? null : candidates.find(
        (taskId) => taskId !== null && scriptTasks.value.some((task) => task.id === taskId),
      ) ?? null
  } catch {
    if (request !== tasksRequest || projectId !== selectedProjectId.value || outlineId !== selectedOutlineVersionId.value) return
    ElMessage.error(t('scripts.errors.loadTasks'))
    scriptTasks.value = []
    selectedTaskId.value = null
  } finally {
    if (request === tasksRequest) loadingTasks.value = false
  }
}

const syncProjectQuery = () => {
  // KeepAlive 在离页后仍响应共享项目变化，不能因此把用户导航回脚本页。
  if (!workspaceActive.value || route.path !== '/scripts' || applyingRouteSelection || selectedProjectId.value === null) {
    return
  }

  const query = {
      project_id: String(selectedProjectId.value),
      ...(selectedOutlineVersionId.value !== null
        ? { outline_version_id: String(selectedOutlineVersionId.value) }
        : {}),
      ...(selectedTaskId.value !== null || unavailableTaskId.value !== null ? { script_task_id: String(selectedTaskId.value ?? unavailableTaskId.value) } : {}),
      ...(route.query.activity_legacy === '1' && selectedTaskId.value === null ? { activity_legacy: '1' } : {}),
  }
  if (Object.keys(route.query).length === Object.keys(query).length && Object.entries(query).every(([key, value]) => route.query[key] === value)) return
  void router.replace({ path: '/scripts', query })
}

const loadOutlineVersions = async (projectId: number) => {
  const request = ++outlineRequest
  loadingOutlineVersions.value = true
  try {
    const session = await resolveOutlineSession(projectId)
    if (request !== outlineRequest || projectId !== selectedProjectId.value) return
    outlineVersions.value = session.outline_versions
    const queryOutlineVersionId = Number(route.query.outline_version_id)
    const queryVersion = outlineVersions.value.find(
      (version) => version.version_id === queryOutlineVersionId,
    )

    if (queryVersion !== undefined) {
      selectedOutlineVersionId.value = queryVersion.version_id
    } else {
      selectedOutlineVersionId.value = outlineVersions.value[0]?.version_id ?? null
    }

    needsOutline.value = outlineVersions.value.length === 0
  } catch {
    if (request !== outlineRequest || projectId !== selectedProjectId.value) return
    outlineVersions.value = []
    selectedOutlineVersionId.value = null
    needsOutline.value = true
    ElMessage.error(t('scripts.errors.loadOutlineVersions'))
  } finally {
    if (request === outlineRequest) loadingOutlineVersions.value = false
  }
}

const isOutlineMissingError = (error: unknown) =>
  error instanceof ApiError &&
  (error.code === 'outline.required' ||
    error.code === 'outline.version_not_found')

const handleGenerationError = (error: unknown, fallback: string) => {
  if (isOutlineMissingError(error)) {
    needsOutline.value = true
    addProgressEvent('missing_outline', { message: t('scripts.needsOutline.description') })
    ElMessage.warning(t('scripts.needsOutline.title'))
    return
  }

  const message = apiErrorMessage(error, t, fallback)
  addProgressEvent('error', {
    code: error instanceof ApiError ? error.code : undefined,
    message,
  })
  ElMessage.error(fallback)
}

const validateBatchGenerationInput = () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return false
  }

  if (selectedOutlineVersionId.value === null) {
    ElMessage.warning(t('scripts.errors.selectOutlineVersion'))
    return false
  }

  if (!isSelectedOutlineConfirmed.value) {
    ElMessage.warning(t('backendErrors.outline.version_not_confirmed'))
    return false
  }

  return true
}

const updateRunActivity = (context: ScriptRunContext) => {
  if (context.taskId === null) return
  activityCenter.upsertActivity({
    id: `script-${context.taskId}`,
    kind: 'script',
    label: `#${context.taskId} · ${context.completedPageIds.size}/${context.totalPages}`,
    status: context.status,
    progress: Math.min(100, context.completedPageIds.size / Math.max(1, context.totalPages) * 100),
    route: `/scripts?project_id=${context.projectId}&script_task_id=${context.taskId}`,
    projectId: context.projectId,
    scriptTaskId: context.taskId,
  })
}

const startRun = (taskId: number | null): ScriptRunContext => {
  const context: ScriptRunContext = {
    projectId: selectedProjectId.value!,
    outlineVersionId: selectedOutlineVersionId.value,
    totalPages: taskId === null ? totalPages.value : taskTotalPages.value,
    taskId,
    status: 'running',
    completedPageIds: new Set(taskId === null ? [] : pages.value.filter((page) => page.script_review_status === 'passed').map((page) => page.id)),
    events: [],
  }
  runContext.value = context
  progressEvents.value = []
  updateRunActivity(context)
  return context
}

/** 先更新运行任务本身，再判断是否能更新当前浏览中的批次。 */
const acceptRunEvent = (context: ScriptRunContext, event: string, payload: Record<string, unknown>) => {
  if (runContext.value !== context) return false
  if (event === 'task') {
    const wasVisible = runIsVisible(context)
    const taskId = Number(payload.task_id)
    if (Number.isInteger(taskId) && taskId > 0) {
      context.taskId = taskId
      if (wasVisible) {
        selectedTaskId.value = taskId
        void loadScriptTasks(taskId)
      }
    }
  }
  const page = payload.page as ScriptPage | undefined
  const receivedPages = Array.isArray(payload.pages) ? payload.pages as ScriptPage[] : page ? [page] : []
  for (const item of receivedPages) {
    if (item.project_id === context.projectId && item.task_id === context.taskId && item.script_review_status === 'passed') context.completedPageIds.add(item.id)
  }
  if (event === 'done') context.status = 'succeeded'
  if (event === 'suspended') context.status = 'suspended'
  const entry: ProgressEvent = {
    id: eventSequence.value++,
    title: eventTitle(event),
    content: describePayload(event, payload),
    timestamp: nowLabel(),
    type: eventType(event),
  }
  context.events.unshift(entry)
  updateRunActivity(context)
  if (!runIsVisible(context)) return false
  progressEvents.value = [...context.events]
  return true
}

const runFailed = (context: ScriptRunContext, error: unknown, fallback: string) => {
  if (runContext.value !== context) return
  context.status = 'failed'
  updateRunActivity(context)
  if (runIsVisible(context)) handleGenerationError(error, fallback)
}

const refreshFinishedRun = async (context: ScriptRunContext) => {
  if (context.taskId !== null) {
    // 即使用户正在别的项目中浏览，也按捕获的项目读取真实终态并刷新任务中心。
    const items = await listProjectScriptTasks(context.projectId).catch(() => [])
    const task = items.find((item) => item.id === context.taskId)
    if (task) context.status = normalizeTaskActivityStatus(task.status)
    updateRunActivity(context)
  }
  if (!runIsVisible(context)) return
  await loadScriptTasks(context.taskId)
  if (runIsVisible(context)) await Promise.all([loadPages(), loadSections(), loadVisualSettings()])
}

const generateBatch = async () => {
  if (
    !validateBatchGenerationInput() ||
    selectedProjectId.value === null ||
    selectedOutlineVersionId.value === null
  ) {
    return
  }

  generatingBatch.value = true
  needsOutline.value = false
  // 批量生成永远创建新任务；先清空旧任务视图，避免已有任务的页面/分段被误认为本轮结果。
  selectedTaskId.value = null
  selectedSectionNo.value = null
  pages.value = []
  sections.value = []
  scenes.value = []
  visualCharacters.value = []
  selectedPage.value = null
  detailVisible.value = false
  const context = startRun(null)
  acceptRunEvent(context, 'phase', { message: t('scripts.events.batchStarted') })
  const requirement = userRequirement.value.trim() || undefined

  try {
    await streamBatchScriptGeneration(
      {
        project_id: context.projectId,
        total_pages: context.totalPages,
        outline_version_id: context.outlineVersionId ?? undefined,
        user_requirement: requirement,
      },
      {
        onEvent: (event, payload) => {
          if (!acceptRunEvent(context, event, payload)) return
          if (event === 'page') {
            const page = payload.page as ScriptPage | undefined
            if (page !== undefined) {
              upsertPageInList(page)
            }
          }
          if (event === 'section_plan') {
            if (Array.isArray(payload.sections)) {
              sectionsRequest += 1
              sections.value = (payload.sections as ScriptSection[]).filter((section) => section.task_id === context.taskId)
            }
            refreshTaskStructure()
          }
          if (event === 'section') {
            upsertSectionInList(payload as ScriptSection)
            if (sections.value.length === 0 || scenes.value.length === 0) {
              refreshTaskStructure()
            }
          }
          if (event === 'section_pages' && Array.isArray(payload.pages)) {
            if (payload.section !== undefined) {
              upsertSectionInList(payload.section as ScriptSection)
            }
            for (const page of payload.pages as ScriptPage[]) {
              upsertPageInList(page)
            }
            refreshTaskStructure()
          }
          if (event === 'done') {
            ElMessage.success(t('scripts.messages.batchSuccess'))
          }
          if (event === 'suspended') {
            ElMessage.warning(t('scripts.messages.batchSuspended'))
          }
        },
        onError: (error) => {
          runFailed(context, error, t('scripts.errors.batchFailed'))
        },
      },
    )
  } catch (error) {
    runFailed(context, error, t('scripts.errors.batchFailed'))
  } finally {
    generatingBatch.value = false
    suspendingBatch.value = false
    await refreshFinishedRun(context)
  }
}

const continueBatch = async () => {
  if (selectedTaskId.value === null || !canContinueBatch.value) {
    ElMessage.warning(t('scripts.errors.selectTask'))
    return
  }

  continuingBatch.value = true
  const context = startRun(selectedTaskId.value)
  acceptRunEvent(context, 'phase', { code: 'script.continue.started', task_id: context.taskId })
  const requirement = userRequirement.value.trim() || undefined

  try {
    await streamContinueScriptGeneration(
      context.taskId!,
      {
        user_requirement: requirement,
      },
      {
        onEvent: (event, payload) => {
          if (!acceptRunEvent(context, event, payload)) return
          if (event === 'section_plan') {
            if (Array.isArray(payload.sections)) {
              sectionsRequest += 1
              sections.value = (payload.sections as ScriptSection[]).filter((section) => section.task_id === context.taskId)
            }
            refreshTaskStructure()
          }
          if (event === 'section') {
            upsertSectionInList(payload as ScriptSection)
            if (sections.value.length === 0 || scenes.value.length === 0) {
              refreshTaskStructure()
            }
          }
          if (event === 'section_pages' && Array.isArray(payload.pages)) {
            if (payload.section !== undefined) {
              upsertSectionInList(payload.section as ScriptSection)
            }
            for (const page of payload.pages as ScriptPage[]) {
              upsertPageInList(page)
            }
            refreshTaskStructure()
          }
          if (event === 'done') {
            ElMessage.success(t('scripts.messages.continueSuccess'))
          }
          if (event === 'suspended') {
            ElMessage.warning(t('scripts.messages.batchSuspended'))
          }
        },
        onError: (error) => {
          runFailed(context, error, t('scripts.errors.continueFailed'))
        },
      },
    )
  } catch (error) {
    runFailed(context, error, t('scripts.errors.continueFailed'))
  } finally {
    continuingBatch.value = false
    suspendingBatch.value = false
    await refreshFinishedRun(context)
  }
}

const reviewPendingPages = async () => {
  if (selectedTaskId.value === null || !canReviewPages.value) {
    ElMessage.warning(t('scripts.errors.noPagesToReview'))
    return
  }
  const taskId = selectedTaskId.value
  const projectId = selectedProjectId.value

  try {
    await ElMessageBox.confirm(
      t('scripts.messages.reviewConfirm', { count: pendingReviewCount.value }),
      t('scripts.actions.reviewPending'),
      {
        type: 'warning',
        confirmButtonText: t('scripts.actions.reviewPending'),
        cancelButtonText: t('projects.cancel'),
      },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    throw error
  }

  if (taskId !== selectedTaskId.value || projectId !== selectedProjectId.value || !canReviewPages.value) return
  reviewingPages.value = true
  const context = startRun(taskId)
  try {
    await streamReviewScriptPages(
      taskId,
      {},
      {
        onEvent: (event, payload) => {
          if (!acceptRunEvent(context, event, payload)) return
          if (event === 'page') {
            const page = payload.page as ScriptPage | undefined
            if (page !== undefined) {
              upsertPageInList(page)
            }
          }
          if (event === 'done') {
            const failed = Number(payload.failed ?? 0)
            void loadPages()
            void loadSections()
            if (failed > 0) {
              ElMessage.warning(
                t('scripts.messages.reviewPartial', {
                  passed: Number(payload.passed ?? 0),
                  failed,
                }),
              )
            } else {
              ElMessage.success(
                t('scripts.messages.reviewSuccess', {
                  count: Number(payload.passed ?? 0),
                }),
              )
            }
          }
        },
        onError: (error) => {
          runFailed(context, error, t('scripts.errors.reviewFailed'))
        },
      },
    )
  } catch (error) {
    runFailed(context, error, t('scripts.errors.reviewFailed'))
  } finally {
    reviewingPages.value = false
    await refreshFinishedRun(context)
  }
}

const suspendBatch = async () => {
  const taskId = streamRunning.value ? runContext.value?.taskId ?? null : currentTask.value?.status === 'running' ? currentTask.value.id : null
  if (taskId === null) {
    ElMessage.warning(t('scripts.errors.noCurrentBatchTask'))
    return
  }

  suspendingBatch.value = true
  try {
    await suspendScriptTask(taskId)
    ElMessage.info(t('scripts.messages.suspendRequested'))
  } catch {
    suspendingBatch.value = false
    ElMessage.error(t('scripts.errors.suspendFailed'))
  }
}

const returnToRunningTask = () => {
  const context = runContext.value
  if (!context) return
  void router.push({
    path: '/scripts',
    query: {
      project_id: String(context.projectId),
      ...(context.outlineVersionId !== null ? { outline_version_id: String(context.outlineVersionId) } : {}),
      ...(context.taskId !== null ? { script_task_id: String(context.taskId) } : {}),
    },
  })
}

const openDetail = (page: ScriptPage) => {
  selectedPage.value = page
  detailVisible.value = true
}

const openCreateScript = () => {
  if (selectedTaskId.value === null) {
    ElMessage.warning(t('scripts.errors.selectTask'))
    return
  }
  scriptDialogMode.value = 'create'
  scriptFormPageNo.value = firstMissingPageNo()
  resetScriptForm()
  scriptDialogVisible.value = true
}

const openEditScript = (page: ScriptPage) => {
  scriptDialogMode.value = 'edit'
  scriptFormPageNo.value = page.page_no
  fillScriptForm(page)
  scriptDialogVisible.value = true
}

const saveManualScript = async () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return
  }
  if (selectedTaskId.value === null) {
    ElMessage.warning(t('scripts.errors.selectTask'))
    return
  }
  if (!requiredScriptFieldsFilled()) {
    ElMessage.warning(t('scripts.errors.emptyScript'))
    return
  }
  if (scriptForm.scene_id === null) {
    ElMessage.warning(t('scripts.bindings.sceneRequired'))
    return
  }

  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  const pageNo = scriptFormPageNo.value
  const mode = scriptDialogMode.value
  const payload = buildScriptPayload()
  savingScript.value = true
  try {
    const page =
      mode === 'create'
        ? await createPageScript(projectId, {
            page_no: pageNo,
            task_id: taskId,
            ...payload,
          })
        : await updatePageScript(projectId, pageNo, {
            task_id: taskId,
            ...payload,
          })
    upsertPageInList(page)
    if (projectId === selectedProjectId.value && taskId === selectedTaskId.value) {
      await loadSections()
      scriptDialogVisible.value = false
      ElMessage.success(t('scripts.messages.scriptSaved'))
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('scripts.errors.saveScriptFailed')))
  } finally {
    savingScript.value = false
  }
}

const clearManualScript = async (page: ScriptPage) => {
  if (selectedProjectId.value === null) {
    return
  }
  const projectId = page.project_id
  const taskId = page.task_id

  try {
    await ElMessageBox.confirm(
      t('scripts.messages.clearConfirm', { pageNo: page.page_no }),
      t('scripts.actions.clearScript'),
      {
        type: 'warning',
        confirmButtonText: t('scripts.actions.clearScript'),
        cancelButtonText: t('projects.cancel'),
      },
    )
    const nextPage = await clearPageScript(projectId, page.page_no, taskId ?? undefined)
    upsertPageInList(nextPage)
    if (projectId === selectedProjectId.value && taskId === selectedTaskId.value) {
      await loadSections()
      ElMessage.success(t('scripts.messages.scriptCleared'))
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('scripts.errors.clearScriptFailed'))
    }
  }
}

const deleteAllScripts = async () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return
  }
  const projectId = selectedProjectId.value

  try {
    await ElMessageBox.confirm(
      t('scripts.messages.deleteAllConfirm'),
      t('scripts.actions.deleteAllScripts'),
      {
        type: 'warning',
        confirmButtonText: t('scripts.actions.deleteAllScripts'),
        cancelButtonText: t('projects.cancel'),
      },
    )
    await deleteAllProjectPages(projectId)
    if (projectId === selectedProjectId.value) {
      pages.value = []
      await loadSections()
      selectedPage.value = null
      detailVisible.value = false
      ElMessage.success(t('scripts.messages.allScriptsDeleted'))
    }
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('scripts.errors.deleteAllScriptsFailed'))
    }
  }
}

const deleteCurrentTaskSections = async () => {
  if (selectedTaskId.value === null) {
    ElMessage.warning(t('scripts.errors.noCurrentTask'))
    return
  }

  const taskId = selectedTaskId.value
  try {
    await ElMessageBox.confirm(
      t('scripts.messages.deleteTaskSectionsConfirm', { taskId }),
      t('scripts.actions.deleteAllSections'),
      {
        type: 'warning',
        confirmButtonText: t('scripts.actions.deleteAllSections'),
        cancelButtonText: t('projects.cancel'),
      },
    )
    await deleteScriptTaskSections(taskId)
    if (taskId !== selectedTaskId.value) return
    pages.value = []
    sections.value = []
    scenes.value = []
    visualCharacters.value = []
    selectedPage.value = selectedPage.value?.task_id === taskId ? null : selectedPage.value
    if (selectedPage.value === null) {
      detailVisible.value = false
    }
    await loadScriptTasks(taskId)
    await loadSections()
    await loadVisualSettings()
    ElMessage.success(t('scripts.messages.taskSectionsDeleted'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('scripts.errors.deleteTaskSectionsFailed'))
    }
  }
}

const goOutline = () => {
  if (selectedProjectId.value === null) {
    return
  }

  router.push({
    path: '/outline',
    query: {
      project_id: String(selectedProjectId.value),
    },
  })
}

const loadTaskView = () => Promise.all([loadSections(), loadVisualSettings(), loadPages()])

/** 深链接先解析所属大纲，再选择批次；同路由导航与历史返回采用同一入口。 */
const applyRouteSelection = async () => {
  if (route.path !== '/scripts') return
  const projectId = Number(route.query.project_id) || selectedProjectId.value
  if (projectId === null || !projects.value.some((project) => project.id === projectId)) return
  const taskId = Number(route.query.script_task_id) || null
  const outlineId = Number(route.query.outline_version_id) || null
  const legacy = route.query.activity_legacy === '1'
  if (projectId === selectedProjectId.value && (!legacy || selectedTaskId.value === null) && (!taskId || taskId === selectedTaskId.value) && (!outlineId || outlineId === selectedOutlineVersionId.value) && outlineVersions.value.length > 0) return
  const request = ++routeSelectionRequest
  applyingRouteSelection = true
  try {
    selectedProjectId.value = projectId
    selectedOutlineVersionId.value = null
    selectedTaskId.value = null
    scriptTasks.value = []
    clearTaskView()
    await loadOutlineVersions(projectId)
    if (request !== routeSelectionRequest || selectedProjectId.value !== projectId) return
    if (taskId !== null) {
      const projectTasks = await listProjectScriptTasks(projectId)
      if (request !== routeSelectionRequest || selectedProjectId.value !== projectId) return
      const target = projectTasks.find((task) => task.id === taskId)
      if (target?.outline_version_id !== null && target?.outline_version_id !== undefined) selectedOutlineVersionId.value = target.outline_version_id
    }
    await loadScriptTasks(taskId)
    if (request !== routeSelectionRequest || selectedProjectId.value !== projectId) return
    const context = runContext.value
    if (streamRunning.value && context?.taskId === null && context.projectId === projectId && context.outlineVersionId === selectedOutlineVersionId.value) selectedTaskId.value = null
    await nextTick()
    if (request !== routeSelectionRequest) return
    clearTaskView()
    await loadTaskView()
  } catch (error) {
    if (request === routeSelectionRequest) ElMessage.error(apiErrorMessage(error, t, t('scripts.errors.loadTasks')))
  } finally {
    if (request === routeSelectionRequest) {
      applyingRouteSelection = false
      syncProjectQuery()
    }
  }
}

watch(selectedProjectId, async (projectId) => {
  if (applyingRouteSelection) return
  const request = ++routeSelectionRequest
  needsOutline.value = false
  selectedOutlineVersionId.value = null
  selectedTaskId.value = null
  unavailableTaskId.value = null
  scriptTasks.value = []
  outlineVersions.value = []
  clearTaskView()
  if (projectId === null) return
  await loadOutlineVersions(projectId)
  if (request !== routeSelectionRequest || projectId !== selectedProjectId.value) return
  await loadScriptTasks()
  if (request === routeSelectionRequest) syncProjectQuery()
})

watch(selectedOutlineVersionId, async () => {
  if (applyingRouteSelection) return
  const projectId = selectedProjectId.value
  const outlineId = selectedOutlineVersionId.value
  selectedTaskId.value = null
  clearTaskView()
  await loadScriptTasks()
  if (projectId === selectedProjectId.value && outlineId === selectedOutlineVersionId.value) syncProjectQuery()
})

watch(selectedTaskId, async () => {
  if (applyingRouteSelection) return
  const taskId = selectedTaskId.value
  if (taskId !== null) unavailableTaskId.value = null
  const projectId = selectedProjectId.value
  clearTaskView()
  showGenerationConfiguration.value = false
  if (currentTask.value !== null) totalPages.value = currentTask.value.total_pages
  await loadTaskView()
  if (projectId === selectedProjectId.value && taskId === selectedTaskId.value) syncProjectQuery()
})

watch(() => [route.path, route.query.project_id, route.query.script_task_id, route.query.outline_version_id, route.query.activity_legacy], () => {
  if (route.path === '/scripts') void applyRouteSelection()
})

watch(groupedVisualCharacters, (groups) => {
  const validKeys = new Set(groups.map((group) => group.character_key))
  expandedCharacterGroups.value = expandedCharacterGroups.value.filter((key) => validKeys.has(key))
  if (expandedCharacterGroups.value.length === 0 && groups[0] !== undefined) {
    expandedCharacterGroups.value = [groups[0].character_key]
  }
})

watch(progressEvents, async () => {
  await nextTick()
})

watch([pageSearch, pageStatusFilter, selectedSectionNo], () => {
  pageTablePage.value = 1
  localStorage.setItem('comaic-script-page-search', pageSearch.value)
})

watch(activeScriptTab, (value) => localStorage.setItem('comaic-script-workspace-tab', value))

watch(
  [currentTask, completionPercentage],
  ([task]) => {
    if (!task) return
    if (streamRunning.value && runContext.value?.taskId === task.id) {
      updateRunActivity(runContext.value)
      return
    }
    activityCenter.upsertActivity({
      id: `script-${task.id}`,
      kind: 'script',
      label: `#${task.id} · ${completedPageCount.value}/${taskTotalPages.value}`,
      status: normalizeTaskActivityStatus(task.status),
      progress: completionPercentage.value,
      route: `/scripts?project_id=${task.project_id}&script_task_id=${task.id}`,
      projectId: task.project_id,
      scriptTaskId: task.id,
      updatedAt: task.updated_at,
    })
  },
  { immediate: true },
)

onMounted(async () => {
  await loadProjects()
  await applyRouteSelection()
})

onActivated(async () => {
  workspaceActive.value = true
  await applyRouteSelection()
  // 返回时从数据库补齐隐藏期间的页面，运行连接和任务上下文仍由 KeepAlive 保存。
  if (selectedTaskId.value !== null) await loadTaskView()
})

onDeactivated(() => {
  workspaceActive.value = false
})
</script>

<template>
  <section class="script-page">
    <el-alert v-if="unavailableTaskId !== null" :title="t('activityCenter.targetUnavailable')" type="warning" show-icon :closable="false" />
    <el-alert
      v-if="needsOutline"
      class="script-page__alert"
      :title="t('scripts.needsOutline.title')"
      :description="t('scripts.needsOutline.description')"
      type="warning"
      show-icon
      :closable="false"
    >
      <template #default>
        <el-button type="warning" plain @click="goOutline">
          {{ t('scripts.needsOutline.action') }}
        </el-button>
      </template>
    </el-alert>

    <section class="panel script-context">
      <el-form label-position="top" class="script-context__form">
            <el-form-item :label="t('scripts.config.outlineVersion')">
              <el-select
                v-model="selectedOutlineVersionId"
                :loading="loadingOutlineVersions"
                :placeholder="t('scripts.config.outlineVersionPlaceholder')"
                :disabled="selectedProjectId === null || outlineVersions.length === 0"
                filterable
                class="script-config__control"
              >
                <el-option
                  v-for="version in outlineVersions"
                  :key="version.version_id"
                  :label="outlineVersionLabel(version)"
                  :value="version.version_id"
                />
              </el-select>
              <p
                v-if="selectedProjectId !== null && outlineVersions.length === 0 && !loadingOutlineVersions"
                class="script-config__hint"
              >
                {{ t('scripts.config.emptyOutlineVersions') }}
              </p>
            </el-form-item>

            <el-form-item :label="t('scripts.config.scriptTask')">
              <el-select
                v-model="selectedTaskId"
                :loading="loadingTasks"
                :placeholder="t('scripts.config.scriptTaskPlaceholder')"
                :disabled="selectedOutlineVersionId === null || scriptTasks.length === 0"
                filterable
                class="script-config__control"
              >
                <el-option
                  v-for="task in scriptTasks"
                  :key="task.id"
                  :label="scriptTaskLabel(task)"
                  :value="task.id"
                />
              </el-select>
              <p
                v-if="selectedOutlineVersionId !== null && scriptTasks.length === 0 && !loadingTasks"
                class="script-config__hint"
              >
                {{ t('scripts.config.emptyTasks') }}
              </p>
            </el-form-item>

      </el-form>
      <div v-if="currentTask" class="script-context__actions">
        <span>{{ t('ux.currentBatch') }} #{{ currentTask.id }}</span>
        <el-tag effect="light">{{ taskStatusLabel(currentTask.status) }}</el-tag>
      </div>
    </section>

    <section v-if="currentTask !== null" class="panel script-task-progress">
      <div class="script-task-progress__meta">
        <div>
          <strong>{{ t('scripts.taskProgress.title') }}</strong>
          <span>
            {{
              t('scripts.taskProgress.completed', {
                completed: String(completedPageCount),
                total: String(taskTotalPages),
              })
            }}
          </span>
        </div>
        <el-tag effect="light">{{ taskStatusLabel(currentTask.status) }}</el-tag>
      </div>
      <el-progress :percentage="completionPercentage" :stroke-width="10" />
    </section>

    <el-alert v-if="runningElsewhere" type="info" :closable="false" show-icon>
      <template #title>{{ t('scripts.taskStatus.running') }} · {{ t('ux.currentBatch') }} #{{ runContext?.taskId ?? '…' }}</template>
      <el-button link type="primary" @click="returnToRunningTask">{{ t('scripts.actions.viewDetail') }}</el-button>
      <el-button v-if="!reviewingPages" link type="warning" :loading="suspendingBatch" :disabled="runContext?.taskId == null || suspendingBatch" @click="suspendBatch">{{ t('scripts.actions.suspendBatch') }}</el-button>
    </el-alert>

    <div class="script-workspace" :class="{ 'script-workspace--completed': completedTask }">
      <div class="script-sidebar">
        <section class="panel script-config">
          <div class="panel__heading">
            <el-icon><EditPen /></el-icon>
            <div>
              <div class="title-with-info"><h2>{{ t('scripts.config.title') }}</h2><InfoTip :content="t('scripts.config.description')" :label="t('scripts.config.title')" /></div>
            </div>
          </div>

          <div v-if="!configurationExpanded" class="script-config__summary">
            <strong>{{ t('ux.currentBatch') }} #{{ currentTask?.id }}</strong>
            <span>{{ t('scripts.taskProgress.completed', { completed: String(completedPageCount), total: String(taskTotalPages) }) }}</span>
            <el-button link type="primary" @click="showGenerationConfiguration = true">{{ t('ux.showConfiguration') }}</el-button>
          </div>
          <el-form v-show="configurationExpanded" label-position="top" class="script-config__form">
            <el-form-item :label="t('scripts.config.totalPages')">
              <el-input-number v-model="totalPages" :min="1" :max="300" />
            </el-form-item>

            <el-form-item :label="t('scripts.config.requirement')">
              <el-input
                v-model="userRequirement"
                type="textarea"
                :rows="4"
                :placeholder="t('scripts.config.requirementPlaceholder')"
              />
            </el-form-item>
          </el-form>

          <div v-if="configurationExpanded || pendingReviewCount > 0" class="script-config__actions">
            <el-button
              v-if="configurationExpanded"
              class="ai-gradient-button"
              type="success"
              :icon="Tickets"
              :loading="generatingBatch"
              :disabled="generationDisabled"
              @click="generateBatch"
            >
              {{ t('scripts.actions.generateBatch') }}
            </el-button>
            <el-button
              v-if="canContinueBatch"
              type="primary"
              :icon="Refresh"
              :loading="continuingBatch"
              @click="continueBatch"
            >
              {{ t('scripts.actions.continueBatch') }}
            </el-button>
            <el-button
              v-if="pendingReviewCount > 0"
              type="primary"
              plain
              :icon="Refresh"
              :loading="reviewingPages"
              :disabled="!canReviewPages"
              @click="reviewPendingPages"
            >
              {{ t('scripts.actions.reviewPending', { count: pendingReviewCount }) }}
            </el-button>
            <el-button
              v-if="(generatingBatch || continuingBatch) && !runningElsewhere || currentTask?.status === 'running' && !streamRunning"
              type="warning"
              :icon="VideoPause"
              :loading="suspendingBatch"
              :disabled="(streamRunning && runContext?.taskId == null) || suspendingBatch"
              @click="suspendBatch"
            >
              {{ t('scripts.actions.suspendBatch') }}
            </el-button>
          </div>

          <el-empty
            v-if="projects.length === 0 && !loadingProjects"
            :description="t('scripts.config.emptyProjects')"
            :image-size="90"
          />
        </section>

        <section class="panel script-progress">
          <div class="panel__heading">
            <el-icon><Tickets /></el-icon>
            <div>
              <div class="title-with-info"><h2>{{ t('scripts.progress.title') }}</h2><InfoTip :content="t('scripts.progress.description')" :label="t('scripts.progress.title')" /></div>
            </div>
          </div>

          <el-scrollbar class="script-progress__scroll">
            <el-empty
              v-if="progressEvents.length === 0"
              :description="t('scripts.progress.empty')"
              :image-size="96"
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
      </div>

      <div class="script-main">
        <el-tabs v-model="activeScriptTab" class="workspace-tabs script-content-tabs">
          <el-tab-pane name="pages">
            <template #label>
              <el-icon><Document /></el-icon>{{ t('scripts.tabs.pages') }}
              <el-badge :value="filteredPages.length" :max="999" />
            </template>
        <section class="panel script-sections">
          <div class="panel__heading script-sections__heading">
            <div class="panel__heading-main">
              <el-icon><Tickets /></el-icon>
              <div>
                <div class="title-with-info"><h2>{{ t('scripts.sections.title') }}</h2><InfoTip :content="t('scripts.sections.description')" :label="t('scripts.sections.title')" /></div>
              </div>
            </div>
            <el-dropdown trigger="click">
              <el-button :icon="MoreFilled" :aria-label="t('scripts.actions.more')" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item
                    :icon="Delete"
                    :disabled="selectedTaskId === null || sections.length === 0 || generatingBatch || continuingBatch"
                    @click="deleteCurrentTaskSections"
                  >{{ t('scripts.actions.deleteAllSections') }}</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div v-loading="loadingSections" class="script-sections__scroll">
            <el-empty
              v-if="sections.length === 0"
              class="script-sections__empty"
              :description="t('scripts.sections.empty')"
              :image-size="72"
            />
            <div v-else class="script-sections__track">
              <button
                v-for="section in sections"
                :key="section.id"
                class="script-section-item"
                :class="{ 'script-section-item--active': selectedSectionNo === section.section_no }"
                type="button"
                @click="
                  selectedSectionNo =
                    selectedSectionNo === section.section_no ? null : section.section_no
                "
              >
                <span class="script-section-item__title">
                  {{ t('scripts.sections.sectionNo', { sectionNo: section.section_no }) }}
                  · {{ sectionPageRange(section) }}
                </span>
                <span>{{ section.title }}</span>
                <small>{{ section.description }}</small>
                <el-tag :type="sectionStatusTagType(section.status)" effect="light">
                  {{ sectionStatusLabel(section.status) }}
                </el-tag>
                <small v-if="section.error_message" class="script-section-item__error">
                  {{ section.error_message }}
                </small>
              </button>
            </div>
          </div>
        </section>

        <section v-loading="loadingPages" class="panel script-results">
          <div class="panel__heading script-results__heading">
            <div class="panel__heading-main">
              <el-icon><Document /></el-icon>
              <div>
                <h2>{{ t('scripts.pages.title') }}</h2>
                <p>
                  {{
                    selectedProject
                      ? t('scripts.filters.projectContext', { project: selectedProject.title })
                      : t('scripts.pages.noProject')
                  }}
                </p>
              </div>
            </div>
            <div class="script-results__actions">
              <el-button type="primary" :icon="Plus" :disabled="!canEditScripts" @click="openCreateScript">
                {{ t('scripts.actions.addScript') }}
              </el-button>
              <el-dropdown trigger="click">
                <el-button :icon="MoreFilled" :aria-label="t('scripts.actions.more')" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item :icon="Delete" :disabled="!canDeleteAllScripts" @click="deleteAllScripts">
                      {{ t('scripts.actions.deleteAllScripts') }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>

          <div class="script-results__toolbar workspace-toolbar">
            <el-input
              v-model="pageSearch"
              clearable
              :prefix-icon="Search"
              :placeholder="t('scripts.filters.search')"
              :aria-label="t('scripts.filters.search')"
            />
            <el-select
              v-model="pageStatusFilter"
              :aria-label="t('scripts.filters.status')"
            >
              <el-option :label="t('scripts.filters.all')" value="all" />
              <el-option :label="t('scripts.reviewStatus.passed')" value="passed" />
              <el-option :label="t('scripts.filters.pending')" value="pending" />
              <el-option :label="t('scripts.reviewStatus.failed')" value="failed" />
            </el-select>
            <el-tag v-if="selectedSectionNo !== null" closable @close="selectedSectionNo = null">
              {{ t('scripts.sections.sectionNo', { sectionNo: selectedSectionNo }) }}
            </el-tag>
            <span class="workspace-toolbar__spacer" />
            <span class="script-results__count">
              {{ t('scripts.filters.resultCount', { count: filteredPages.length }) }}
            </span>
          </div>

          <el-table
            v-if="paginatedPages.length > 0"
            :data="paginatedPages"
            class="script-results__table"
            max-height="520"
            :aria-label="t('scripts.pages.title')"
          >
            <el-table-column prop="page_no" :label="t('scripts.pages.columns.pageNo')" width="88" />
            <el-table-column :label="t('scripts.pages.columns.status')" width="130">
              <template #default="{ row }">
                <el-tooltip
                  :disabled="!row.script_review_error"
                  :content="row.script_review_error"
                  placement="top"
                >
                  <el-tag :type="reviewStatusTagType(row.script_review_status)" effect="light">
                    {{ reviewStatusLabel(row.script_review_status) }}
                  </el-tag>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column :label="t('scripts.pages.columns.updatedAt')" width="136">
              <template #default="{ row }">
                {{ formatDateTime(row.updated_at) }}
              </template>
            </el-table-column>
            <el-table-column :label="t('scripts.pages.columns.summary')" min-width="260">
              <template #default="{ row }">
                <span class="script-results__summary">{{ scriptSummary(row.summary) }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('scripts.bindings.characters')" min-width="150">
              <template #default="{ row }">
                <span>{{ pageCharacterBindings(row).map(character => character.name).join('、') || t('scripts.bindings.noCharacters') }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('scripts.bindings.scene')" min-width="170">
              <template #default="{ row }">{{ pageSceneName(row) }}</template>
            </el-table-column>
            <el-table-column :label="t('scripts.pages.columns.actions')" width="200" fixed="right">
              <template #default="{ row }">
                <div class="table-actions">
                <el-button link type="primary" :icon="View" @click="openDetail(row)">
                  {{ t('scripts.actions.viewDetail') }}
                </el-button>
                <el-button link type="primary" :icon="EditPen" :disabled="!canEditScripts" @click="openEditScript(row)">
                  {{ t('projects.edit') }}
                </el-button>
                <el-dropdown trigger="click">
                  <el-button link :icon="MoreFilled" :aria-label="t('ux.moreActions')" />
                  <template #dropdown><el-dropdown-menu>
                    <el-dropdown-item :icon="Delete" :disabled="!canEditScripts" @click="clearManualScript(row)">{{ t('scripts.actions.clearScript') }}</el-dropdown-item>
                  </el-dropdown-menu></template>
                </el-dropdown>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-else
            class="script-results__empty"
            :description="t('scripts.pages.empty')"
            :image-size="108"
          />
          <div v-if="filteredPages.length > pageTablePageSize" class="script-results__pagination">
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
          </el-tab-pane>

          <el-tab-pane name="visual">
            <template #label>
              <el-icon><View /></el-icon>{{ t('scripts.tabs.visual') }}
              <el-badge :value="visualCharacters.length + scenes.length" :max="999" />
            </template>
      <section class="panel visual-settings">
        <div class="panel__heading">
          <div class="panel__heading-main">
            <el-icon><View /></el-icon>
            <div>
              <div class="title-with-info"><h2>{{ t('scripts.visual.title') }}</h2><InfoTip :content="t('scripts.visual.description')" :label="t('scripts.visual.title')" /></div>
            </div>
          </div>
        </div>
        <div v-loading="loadingVisualSettings" class="visual-settings__grid">
          <div class="visual-settings__column">
            <h3>{{ t('scripts.visual.characters') }}</h3>
            <el-empty
              v-if="groupedVisualCharacters.length === 0"
              :description="t('scripts.visual.emptyCharacters')"
              :image-size="72"
            />
            <el-collapse v-else v-model="expandedCharacterGroups" class="visual-character-groups">
              <el-collapse-item
                v-for="group in groupedVisualCharacters"
                :key="group.character_key"
                :name="group.character_key"
              >
                <template #title>
                  <span class="visual-character-group__title">
                    <span>{{ group.name || t('imageGeneration.emptyText') }}</span>
                    <el-tag size="small" effect="plain">
                      {{ group.items.length }}
                    </el-tag>
                  </span>
                </template>
                <details class="script-technical-details">
                  <summary>{{ t('visualBible.review.technicalDetails') }}</summary>
                  <p>{{ t('scripts.visual.characterKeys') }} · {{ group.character_key }}</p>
                </details>
                <article
                  v-for="character in group.items"
                  :key="character.id"
                  class="visual-card visual-card--compact"
                >
                  <strong>
                    <span v-if="character.section_no">S{{ character.section_no }} · </span>
                    {{ character.section_role || character.current_state || t('imageGeneration.emptyText') }}
                  </strong>
                  <p>{{ character.current_clothing || character.current_state || character.section_role }}</p>
                </article>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div class="visual-settings__column">
            <h3>{{ t('scripts.visual.scenes') }}</h3>
            <el-empty v-if="scenes.length === 0" :description="t('scripts.visual.emptyScenes')" :image-size="72" />
            <template v-else>
              <article v-for="scene in scenes" :key="scene.id" class="visual-card">
                <strong>{{ scene.name }}</strong>
                <p>{{ scene.environment_details }}</p>
                <details class="script-technical-details">
                  <summary>{{ t('visualBible.review.technicalDetails') }}</summary>
                  <p>{{ t('scripts.visual.sceneKey') }} · {{ scene.scene_key }}</p>
                </details>
              </article>
            </template>
          </div>
        </div>
      </section>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="`${t('scripts.detail.title')} ${selectedPage?.page_no ?? ''}`"
      width="720px"
    >
      <div v-if="selectedPage?.summary" class="script-detail">
        <section class="script-detail__block">
          <strong>{{ t('scripts.bindings.characters') }}</strong>
          <p>{{ pageCharacterBindings(selectedPage).map(character => character.name).join('、') || t('scripts.bindings.noCharacters') }}</p>
          <details v-for="binding in pageCharacterBindings(selectedPage)" :key="`${selectedPage.id}-${binding.id}`" class="script-detail__entry">
            <summary>{{ binding.name }}</summary>
            <template v-for="character in pageCharacterDetails(selectedPage).filter(item => item.id === binding.id)" :key="character.id">
              <h4>{{ t('scripts.bindings.identity') }}</h4>
              <dl v-if="character.outline_character" class="script-detail__fields">
                <div v-for="field in baselineFields" :key="field">
                  <dt>{{ t(`scripts.bindings.attributes.${field}`) }}</dt>
                  <dd>{{ detailFieldValue(character.outline_character[field]) }}</dd>
                </div>
              </dl>
              <p v-else>{{ t('scripts.bindings.unbound') }}</p>
              <h4>{{ t('scripts.bindings.sectionSettings') }}</h4>
              <dl class="script-detail__fields">
                <div v-for="field in sectionCharacterFields" :key="field">
                  <dt>{{ t(`scripts.bindings.attributes.${field}`) }}</dt>
                  <dd>{{ detailFieldValue(character[field]) }}</dd>
                </div>
              </dl>
            </template>
            <p v-if="!pageCharacterDetails(selectedPage).some(item => item.id === binding.id)">{{ t('scripts.bindings.detailsUnavailable') }}</p>
          </details>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.bindings.scene') }}</strong>
          <details v-if="selectedPage.scene_id" :key="`${selectedPage.id}-${selectedPage.scene_id}`" class="script-detail__entry">
            <summary>{{ pageSceneName(selectedPage) }}</summary>
            <dl v-if="pageSceneDetails(selectedPage)" class="script-detail__fields">
              <div v-for="field in fixedSceneFields" :key="field">
                <dt>{{ t(`scripts.bindings.attributes.${field}`) }}</dt>
                <dd>{{ detailFieldValue(pageSceneDetails(selectedPage)?.[field]) }}</dd>
              </div>
            </dl>
            <p v-else>{{ t('scripts.bindings.detailsUnavailable') }}</p>
          </details>
          <p v-else>{{ t('scripts.bindings.unbound') }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.bindings.conditions') }}</strong>
          <dl class="script-detail__fields">
            <div v-for="field in conditionFields" :key="field">
              <dt>{{ t(`scripts.bindings.${field}`) }}</dt>
              <dd>{{ detailFieldValue(pageConditions(selectedPage)[field]) }}</dd>
            </div>
          </dl>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.summary') }}</strong>
          <p>{{ selectedPage.summary }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.characters') }}</strong>
          <p>{{ selectedPage.characters }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.clothing') }}</strong>
          <p>{{ selectedPage.clothing }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.scene') }}</strong>
          <p>{{ selectedPage.scene }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.composition') }}</strong>
          <p>{{ selectedPage.composition }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.characterAction') }}</strong>
          <p>{{ selectedPage.character_action }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.fields.dialogue') }}</strong>
          <p>{{ selectedPage.dialogue }}</p>
        </section>
        <details :key="selectedPage.id" class="script-technical-details">
          <summary>{{ t('visualBible.review.technicalDetails') }}</summary>
          <section class="script-detail__block">
            <strong>{{ t('scripts.visual.sceneKey') }}</strong>
            <p>{{ selectedPage.scene_key || '-' }}</p>
          </section>
          <section class="script-detail__block">
            <strong>{{ t('scripts.visual.characterKeys') }}</strong>
            <p>{{ selectedPage.character_keys.join(', ') || '-' }}</p>
          </section>
        </details>
      </div>
      <el-empty v-else :description="t('scripts.pages.noScript')" :image-size="96" />
      <template #footer>
        <el-button @click="detailVisible = false">{{ t('scripts.actions.close') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="scriptDialogVisible"
      :title="
        scriptDialogMode === 'create'
          ? t('scripts.editor.createTitle')
          : t('scripts.editor.editTitle', { pageNo: scriptFormPageNo })
      "
      width="720px"
    >
      <el-form label-position="top">
        <el-form-item :label="t('scripts.bindings.scene')" required>
          <el-select v-model="scriptForm.scene_id" filterable :loading="loadingVisualSettings" :placeholder="t('scripts.bindings.selectScene')" style="width:100%">
            <el-option v-for="scene in scenes" :key="scene.id" :value="scene.id" :label="scene.name" />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('scripts.bindings.characters')">
          <el-select v-model="scriptForm.character_ids" multiple filterable :loading="loadingVisualSettings" :placeholder="t('scripts.bindings.selectCharacters')" style="width:100%">
            <el-option v-for="character in editorCharacters" :key="character.id" :value="character.id" :label="character.name" />
          </el-select>
        </el-form-item>
        <el-form-item v-for="field in conditionFields" :key="field" :label="t(`scripts.bindings.${field}`)">
          <el-input v-model="scriptForm.scene_conditions[field]" :placeholder="t('scripts.bindings.unspecified')" />
        </el-form-item>
        <p>{{ t('scripts.bindings.editHelp') }}</p>
        <el-form-item :label="t('scripts.pages.columns.pageNo')">
          <el-input-number
            v-model="scriptFormPageNo"
            :min="1"
            :max="taskTotalPages"
            :disabled="scriptDialogMode === 'edit'"
          />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.summary')">
          <el-input
            v-model="scriptForm.summary"
            type="textarea"
            :rows="2"
            :placeholder="t('scripts.editor.summaryPlaceholder')"
          />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.characters')">
          <el-input v-model="scriptForm.characters" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.clothing')">
          <el-input v-model="scriptForm.clothing" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.scene')">
          <el-input v-model="scriptForm.scene" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.composition')">
          <el-input v-model="scriptForm.composition" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.characterAction')">
          <el-input v-model="scriptForm.character_action" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item :label="t('scripts.fields.dialogue')">
          <el-input
            v-model="scriptForm.dialogue"
            type="textarea"
            :rows="3"
            :placeholder="t('scripts.editor.dialoguePlaceholder')"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scriptDialogVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" :loading="savingScript" @click="saveManualScript">
          {{ t('projects.save') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.table-actions { display: flex; align-items: center; gap: 12px; white-space: nowrap; }
.table-actions :deep(.el-button) { margin-left: 0; }
.script-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.script-page__alert {
  border-radius: 8px;
}

.script-context {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 18px;
}

.script-context__form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
  flex: 1;
  min-width: 0;
  gap: 14px;
}

.script-context__form .el-form-item {
  min-width: 0;
  margin-bottom: 0;
}

.script-context__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.script-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.85fr) minmax(280px, 0.65fr);
  gap: 18px;
  align-items: start;
}

.script-sidebar {
  display: grid;
  gap: 18px;
  order: 2;
}

.script-main {
  display: grid;
  min-width: 0;
  gap: 18px;
  order: 1;
}

.script-workspace--completed {
  grid-template-columns: 1fr;
}

.script-workspace--completed .script-sidebar {
  grid-template-columns: minmax(280px, 1fr) minmax(0, 1.6fr);
}

.script-workspace--completed .script-results {
  order: 1;
}

.script-workspace--completed .script-sections {
  order: 2;
}

.script-config__summary {
  display: grid;
  gap: 10px;
  padding: 18px 22px;
}

.script-config__summary .el-button {
  justify-self: start;
}

.script-config__summary span {
  color: var(--color-muted);
}

.script-content-tabs {
  min-width: 0;
}

.script-content-tabs :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.script-content-tabs :deep(.el-badge__content) {
  transform: translateY(-5px) translateX(6px) scale(0.82);
}

.script-content-tabs :deep(.el-tab-pane) {
  display: grid;
  gap: 18px;
}

.panel {
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--shadow-soft);
}

.panel__heading {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 20px 22px 16px;
  border-bottom: 1px solid var(--color-border);
}

.panel__heading h2 {
  margin: 0;
  font-size: 18px;
}

.panel__heading p {
  margin: 6px 0 0;
  color: var(--color-muted);
  line-height: 1.5;
}

.panel__heading-main {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.script-config__form {
  padding: 18px 22px 0;
}

.script-config__control {
  width: 100%;
}

.script-config__hint {
  margin: 8px 0 0;
  color: var(--color-muted);
  font-size: 13px;
  line-height: 1.5;
}

.script-config__numbers {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.script-config__actions {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
  padding: 4px 22px 22px;
}

.script-config__actions .el-button {
  width: 100%;
  margin-left: 0;
}

.visual-settings__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  /* 两列内容独立靠顶，场景列表的高度不能撑开人物列和收起的卡片。 */
  align-items: start;
  gap: 16px;
  padding: 18px 22px 22px;
}

.visual-settings__column {
  display: grid;
  align-content: start;
  gap: 10px;
  min-width: 0;
}

.visual-settings__column h3 {
  margin: 0;
  font-size: 15px;
}

.visual-card {
  display: grid;
  gap: 6px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #f8fafc;
}

.visual-card p,
.visual-card small {
  margin: 0;
  color: var(--color-muted);
  line-height: 1.45;
}

.visual-card--compact {
  margin-bottom: 8px;
}

.visual-card--compact:last-child {
  margin-bottom: 0;
}

.visual-character-groups {
  display: grid;
  align-content: start;
  gap: 10px;
  border: 0;
}

.visual-character-groups :deep(.el-collapse-item) {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #ffffff;
}

.visual-character-groups :deep(.el-collapse-item__header) {
  height: 44px;
  min-height: 44px;
  padding: 0 12px;
  border-bottom: 0;
  font-weight: 700;
}

.visual-character-groups :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.visual-character-groups :deep(.el-collapse-item__content) {
  display: grid;
  gap: 8px;
  padding: 0 12px 12px;
}

.visual-character-group__title {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.visual-character-group__title > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-task-progress {
  padding: 16px 18px;
}

.script-task-progress__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.script-task-progress__meta div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.script-task-progress__meta span {
  color: var(--color-muted);
  font-size: 13px;
}

.script-sections__heading {
  align-items: flex-start;
  justify-content: space-between;
}

.script-sections {
  overflow: hidden;
}

.script-sections__scroll {
  width: 100%;
  max-width: 100%;
  overflow: auto;
}

.script-sections__empty {
  padding: 14px 16px;
}

.script-sections__track {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  width: 100%;
  max-height: 390px;
  gap: 12px;
  padding: 14px 16px 18px;
}

.script-section-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 100%;
  min-height: 148px;
  margin: 0 0 10px;
  padding: 12px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #ffffff;
  color: #1f2937;
  text-align: left;
  cursor: pointer;
}

.script-section-item:hover,
.script-section-item--active {
  border-color: #60a5fa;
  background: #eff6ff;
}

.script-section-item__title {
  font-weight: 700;
  color: #0f172a;
}

.script-section-item small {
  display: -webkit-box;
  overflow: hidden;
  color: var(--color-muted);
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.script-section-item__error {
  color: #dc2626 !important;
  -webkit-line-clamp: 2 !important;
}

.script-progress__scroll {
  height: 360px;
  padding: 14px 18px 8px;
}

.script-progress :deep(.el-timeline) {
  padding-left: 2px;
}

.script-progress :deep(.el-timeline-item__content strong) {
  display: block;
  margin-bottom: 6px;
}

.script-progress :deep(.el-timeline-item__content p) {
  margin: 0;
  color: var(--color-muted);
  line-height: 1.55;
  word-break: break-word;
}

.script-results {
  overflow: hidden;
}

.script-results__heading {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}

/* 主操作与更多菜单作为同一组靠右，避免三个元素被均分到标题栏中间。 */
.script-results__actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 12px;
  margin-left: auto;
}

.script-results__table {
  width: 100%;
}

.script-results__toolbar {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  background: #fbfcff;
}

.script-results__toolbar :deep(.el-input) {
  width: min(100%, 320px);
}

.script-results__toolbar :deep(.el-select) {
  width: 160px;
}

.script-results__count {
  color: var(--text-soft);
  font-size: 13px;
}

.script-results__pagination {
  display: flex;
  justify-content: flex-end;
  padding: 14px 16px 18px;
  border-top: 1px solid var(--color-border);
}

.script-results__empty {
  min-height: 480px;
}

.script-results__summary {
  color: #334155;
  line-height: 1.55;
}

.script-detail__entry {
  margin-top: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px;
}

.script-detail__entry summary {
  cursor: pointer;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.script-detail__entry h4 {
  margin: 16px 0 8px;
}

.script-detail__fields {
  margin: 8px 0 0;
}

.script-detail__fields > div {
  display: grid;
  grid-template-columns: minmax(90px, 25%) minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.script-detail__fields dt {
  color: var(--el-text-color-secondary);
  overflow-wrap: anywhere;
}

.script-detail__fields dd {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.6;
}

.script-detail {
  display: grid;
  gap: 12px;
  max-height: 58vh;
  margin: 0;
  padding: 16px;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #f8fafc;
  color: #1f2937;
  line-height: 1.7;
  word-break: break-word;
}

.script-detail__block {
  display: grid;
  gap: 6px;
}

.script-detail__block strong {
  color: #0f172a;
}

.script-detail__block p {
  margin: 0;
  white-space: pre-wrap;
}

.script-technical-details {
  color: var(--color-muted);
  font-size: 13px;
}

.script-technical-details summary {
  cursor: pointer;
}

.script-technical-details .script-detail__block {
  margin-top: 10px;
}

@media (max-width: 1320px) {
  .script-workspace:not(.script-workspace--completed) {
    grid-template-columns: minmax(420px, 1.28fr) minmax(280px, 0.72fr);
  }
}

@media (max-width: 980px) {
  .script-context {
    flex-direction: column;
    align-items: stretch;
  }

  .script-context__form {
    grid-template-columns: 1fr;
  }

  .script-workspace,
  .script-workspace:not(.script-workspace--completed),
  .script-workspace--completed .script-sidebar {
    grid-template-columns: 1fr;
  }

  .script-config__numbers {
    grid-template-columns: 1fr;
  }

  .script-section-item {
    width: 100%;
  }

  .script-progress__scroll {
    height: 420px;
  }

  .visual-settings__grid {
    grid-template-columns: 1fr;
  }
}
</style>

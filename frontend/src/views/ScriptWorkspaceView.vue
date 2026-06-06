<script setup lang="ts">
import { Delete, Document, EditPen, Plus, Refresh, Tickets, VideoPause, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { listProjects, type Project } from '@/api/projects'
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
  updatePageScript,
  type ScriptPage,
  type ScriptCharacter,
  type ScriptScene,
  type ScriptSection,
  type ScriptTask,
} from '@/api/scripts'
import { formatLocalDateTime, formatLocalNowTime } from '@/utils/datetime'

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

const route = useRoute()
const router = useRouter()
const { locale, t } = useI18n()

const projects = ref<Project[]>([])
const outlineVersions = ref<OutlineVersion[]>([])
const scriptTasks = ref<ScriptTask[]>([])
const sections = ref<ScriptSection[]>([])
const scenes = ref<ScriptScene[]>([])
const visualCharacters = ref<ScriptCharacter[]>([])
const pages = ref<ScriptPage[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedOutlineVersionId = ref<number | null>(null)
const selectedTaskId = ref<number | null>(null)
const selectedSectionNo = ref<number | null>(null)
const currentTaskId = ref<number | null>(null)
const totalPages = ref(12)
const userRequirement = ref('')
const progressEvents = ref<ProgressEvent[]>([])
const selectedPage = ref<ScriptPage | null>(null)
const detailVisible = ref(false)
const scriptDialogVisible = ref(false)
const scriptDialogMode = ref<'create' | 'edit'>('create')
const scriptFormPageNo = ref(1)
const scriptForm = reactive({
  summary: '',
  characters: '',
  clothing: '',
  scene: '',
  composition: '',
  character_action: '',
  dialogue: '无',
})
const savingScript = ref(false)

const loadingProjects = ref(false)
const loadingOutlineVersions = ref(false)
const loadingTasks = ref(false)
const loadingSections = ref(false)
const loadingVisualSettings = ref(false)
const loadingPages = ref(false)
const generatingBatch = ref(false)
const suspendingBatch = ref(false)
const continuingBatch = ref(false)
const needsOutline = ref(false)
const eventSequence = ref(1)

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

const taskTotalPages = computed(() => currentTask.value?.total_pages ?? totalPages.value)
const completedPageCount = computed(() => pages.value.filter((page) => Boolean(page.summary)).length)
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
    !generatingBatch.value &&
    !continuingBatch.value,
)

const generationDisabled = computed(() => !canGenerate.value)
const canEditScripts = computed(
  () =>
    selectedProjectId.value !== null &&
    selectedTaskId.value !== null &&
    !generatingBatch.value &&
    !continuingBatch.value,
)
const canDeleteAllScripts = computed(() => canEditScripts.value && pages.value.length > 0)
const canContinueBatch = computed(
  () =>
    currentTask.value !== null &&
    currentTask.value.mode === 'batch' &&
    ['suspended', 'failed'].includes(currentTask.value.status) &&
    !generatingBatch.value &&
    !continuingBatch.value,
)

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
  scriptForm.summary = ''
  scriptForm.characters = ''
  scriptForm.clothing = ''
  scriptForm.scene = ''
  scriptForm.composition = ''
  scriptForm.character_action = ''
  scriptForm.dialogue = '无'
}

const fillScriptForm = (page: ScriptPage) => {
  scriptForm.summary = page.summary ?? ''
  scriptForm.characters = page.characters ?? ''
  scriptForm.clothing = page.clothing ?? ''
  scriptForm.scene = page.scene ?? ''
  scriptForm.composition = page.composition ?? ''
  scriptForm.character_action = page.character_action ?? ''
  scriptForm.dialogue = page.dialogue ?? '无'
}

const buildScriptPayload = () => ({
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

const statusLabel = (status: string) => {
  const key = `scripts.status.${status}`
  const translated = t(key)
  return translated === key ? status : translated
}

const statusTagType = (status: string) => {
  if (status === 'script_ready') {
    return 'success'
  }
  if (status === 'draft') {
    return 'info'
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

const sectionCompleted = (section: ScriptSection) => {
  const completed = new Set(
    pages.value
      .filter((page) => page.section_id === section.id && Boolean(page.summary))
      .map((page) => page.page_no),
  )
  for (let pageNo = section.page_start; pageNo <= section.page_end; pageNo += 1) {
    if (!completed.has(pageNo)) {
      return false
    }
  }
  return true
}

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

const addProgressEvent = (event: string, payload: Record<string, unknown> = {}) => {
  const titleKey = `scripts.events.${event}`
  const title = t(titleKey) === titleKey ? event : t(titleKey)

  progressEvents.value.unshift({
    id: eventSequence.value,
    title,
    content: describePayload(event, payload),
    timestamp: nowLabel(),
    type: eventType(event),
  })
  eventSequence.value += 1
}

const upsertPageInList = (page: ScriptPage) => {
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

const loadProjects = async () => {
  loadingProjects.value = true
  try {
    projects.value = await listProjects()

    const queryProjectId = Number(route.query.project_id)
    if (Number.isFinite(queryProjectId) && projects.value.some((project) => project.id === queryProjectId)) {
      selectedProjectId.value = queryProjectId
      return
    }

    const firstProject = projects.value[0]
    if (selectedProjectId.value === null && firstProject !== undefined) {
      selectedProjectId.value = firstProject.id
    }
  } catch {
    ElMessage.error(t('scripts.errors.loadProjects'))
  } finally {
    loadingProjects.value = false
  }
}

const loadPages = async () => {
  if (selectedTaskId.value === null) {
    pages.value = []
    return
  }

  loadingPages.value = true
  try {
    pages.value = await listScriptTaskPages(selectedTaskId.value)
  } catch {
    ElMessage.error(t('scripts.errors.loadPages'))
  } finally {
    loadingPages.value = false
  }
}

const loadSections = async () => {
  if (selectedTaskId.value === null) {
    sections.value = []
    return
  }

  loadingSections.value = true
  try {
    sections.value = await listScriptTaskSections(selectedTaskId.value)
  } catch {
    ElMessage.error(t('scripts.errors.loadSections'))
  } finally {
    loadingSections.value = false
  }
}

const loadVisualSettings = async () => {
  if (selectedTaskId.value === null) {
    scenes.value = []
    visualCharacters.value = []
    return
  }

  loadingVisualSettings.value = true
  try {
    const [sceneItems, characterItems] = await Promise.all([
      listScriptTaskScenes(selectedTaskId.value),
      listScriptTaskCharacters(selectedTaskId.value),
    ])
    scenes.value = sceneItems
    visualCharacters.value = characterItems
  } catch {
    ElMessage.error(t('scripts.errors.loadVisualSettings'))
  } finally {
    loadingVisualSettings.value = false
  }
}

const loadScriptTasks = async (preferredTaskId?: number | null) => {
  if (selectedProjectId.value === null || selectedOutlineVersionId.value === null) {
    scriptTasks.value = []
    selectedTaskId.value = null
    return
  }

  loadingTasks.value = true
  try {
    scriptTasks.value = await listProjectScriptTasks(selectedProjectId.value, {
      outlineVersionId: selectedOutlineVersionId.value,
    })
    const routeTaskId = Number(route.query.script_task_id)
    const candidates = [
      preferredTaskId,
      Number.isFinite(routeTaskId) ? routeTaskId : null,
      selectedTaskId.value,
      scriptTasks.value[0]?.id ?? null,
    ]
    selectedTaskId.value =
      candidates.find(
        (taskId) => taskId !== null && scriptTasks.value.some((task) => task.id === taskId),
      ) ?? null
  } catch {
    ElMessage.error(t('scripts.errors.loadTasks'))
    scriptTasks.value = []
    selectedTaskId.value = null
  } finally {
    loadingTasks.value = false
  }
}

const syncProjectQuery = () => {
  if (selectedProjectId.value === null) {
    return
  }

  router.replace({
    path: '/scripts',
    query: {
      project_id: String(selectedProjectId.value),
      ...(selectedOutlineVersionId.value !== null
        ? { outline_version_id: String(selectedOutlineVersionId.value) }
        : {}),
      ...(selectedTaskId.value !== null ? { script_task_id: String(selectedTaskId.value) } : {}),
    },
  })
}

const loadOutlineVersions = async (projectId: number) => {
  loadingOutlineVersions.value = true
  try {
    const session = await resolveOutlineSession(projectId)
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
    outlineVersions.value = []
    selectedOutlineVersionId.value = null
    needsOutline.value = true
    ElMessage.error(t('scripts.errors.loadOutlineVersions'))
  } finally {
    loadingOutlineVersions.value = false
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
  currentTaskId.value = null
  selectedTaskId.value = null
  selectedSectionNo.value = null
  pages.value = []
  sections.value = []
  scenes.value = []
  visualCharacters.value = []
  selectedPage.value = null
  detailVisible.value = false
  addProgressEvent('phase', { message: t('scripts.events.batchStarted') })

  try {
    await streamBatchScriptGeneration(
      {
        project_id: selectedProjectId.value,
        total_pages: totalPages.value,
        outline_version_id: selectedOutlineVersionId.value,
        user_requirement: userRequirement.value.trim() || undefined,
      },
      {
        onEvent: (event, payload) => {
          addProgressEvent(event, payload)
          if (event === 'task') {
            const taskId = Number(payload.task_id)
            currentTaskId.value = Number.isFinite(taskId) ? taskId : null
            if (currentTaskId.value !== null) {
              selectedTaskId.value = currentTaskId.value
              void loadScriptTasks(currentTaskId.value)
            }
          }
          if (event === 'page') {
            const page = payload.page as ScriptPage | undefined
            if (page !== undefined) {
              upsertPageInList(page)
            }
          }
          if (event === 'section_pages' && Array.isArray(payload.pages)) {
            for (const page of payload.pages as ScriptPage[]) {
              upsertPageInList(page)
            }
            void loadSections()
            void loadVisualSettings()
          }
          if (event === 'done') {
            void loadScriptTasks(currentTaskId.value)
            void loadPages()
            void loadSections()
            void loadVisualSettings()
            ElMessage.success(t('scripts.messages.batchSuccess'))
          }
          if (event === 'suspended') {
            generatingBatch.value = false
            suspendingBatch.value = false
            ElMessage.warning(t('scripts.messages.batchSuspended'))
          }
        },
        onError: (error) => {
          handleGenerationError(error, t('scripts.errors.batchFailed'))
        },
      },
    )
  } catch (error) {
    handleGenerationError(error, t('scripts.errors.batchFailed'))
  } finally {
    generatingBatch.value = false
    suspendingBatch.value = false
    void loadScriptTasks(currentTaskId.value ?? selectedTaskId.value)
  }
}

const continueBatch = async () => {
  if (selectedTaskId.value === null || !canContinueBatch.value) {
    ElMessage.warning(t('scripts.errors.selectTask'))
    return
  }

  continuingBatch.value = true
  currentTaskId.value = selectedTaskId.value
  addProgressEvent('phase', { code: 'script.continue.started', task_id: selectedTaskId.value })

  try {
    await streamContinueScriptGeneration(
      selectedTaskId.value,
      {
        user_requirement: userRequirement.value.trim() || undefined,
      },
      {
        onEvent: (event, payload) => {
          addProgressEvent(event, payload)
          if (event === 'section_pages' && Array.isArray(payload.pages)) {
            for (const page of payload.pages as ScriptPage[]) {
              upsertPageInList(page)
            }
            void loadSections()
            void loadVisualSettings()
          }
          if (event === 'done') {
            void loadScriptTasks(selectedTaskId.value)
            void loadPages()
            void loadSections()
            void loadVisualSettings()
            ElMessage.success(t('scripts.messages.continueSuccess'))
          }
          if (event === 'suspended') {
            continuingBatch.value = false
            suspendingBatch.value = false
            void loadScriptTasks(selectedTaskId.value)
            ElMessage.warning(t('scripts.messages.batchSuspended'))
          }
        },
        onError: (error) => {
          handleGenerationError(error, t('scripts.errors.continueFailed'))
        },
      },
    )
  } catch (error) {
    handleGenerationError(error, t('scripts.errors.continueFailed'))
  } finally {
    continuingBatch.value = false
    suspendingBatch.value = false
    void loadScriptTasks(selectedTaskId.value)
  }
}

const suspendBatch = async () => {
  const taskId = currentTaskId.value ?? selectedTaskId.value
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

  savingScript.value = true
  try {
    const page =
      scriptDialogMode.value === 'create'
        ? await createPageScript(selectedProjectId.value, {
            page_no: scriptFormPageNo.value,
            task_id: selectedTaskId.value,
            ...buildScriptPayload(),
          })
        : await updatePageScript(selectedProjectId.value, scriptFormPageNo.value, {
            task_id: selectedTaskId.value,
            ...buildScriptPayload(),
          })
    upsertPageInList(page)
    await loadSections()
    scriptDialogVisible.value = false
    ElMessage.success(t('scripts.messages.scriptSaved'))
  } catch {
    ElMessage.error(t('scripts.errors.saveScriptFailed'))
  } finally {
    savingScript.value = false
  }
}

const clearManualScript = async (page: ScriptPage) => {
  if (selectedProjectId.value === null) {
    return
  }

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
    const nextPage = await clearPageScript(selectedProjectId.value, page.page_no, selectedTaskId.value ?? undefined)
    upsertPageInList(nextPage)
    await loadSections()
    ElMessage.success(t('scripts.messages.scriptCleared'))
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
    await deleteAllProjectPages(selectedProjectId.value)
    pages.value = []
    await loadSections()
    selectedPage.value = null
    detailVisible.value = false
    ElMessage.success(t('scripts.messages.allScriptsDeleted'))
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

watch(selectedProjectId, async (projectId) => {
  needsOutline.value = false
  if (projectId === null) {
    pages.value = []
    sections.value = []
    scenes.value = []
    visualCharacters.value = []
    scriptTasks.value = []
    outlineVersions.value = []
    selectedOutlineVersionId.value = null
    selectedTaskId.value = null
    currentTaskId.value = null
    return
  }

  selectedOutlineVersionId.value = null
  selectedTaskId.value = null
  currentTaskId.value = null
  await loadOutlineVersions(projectId)
  await loadScriptTasks()
  syncProjectQuery()
})

watch(selectedOutlineVersionId, async () => {
  selectedTaskId.value = null
  selectedSectionNo.value = null
  pages.value = []
  sections.value = []
  scenes.value = []
  visualCharacters.value = []
  await loadScriptTasks()
  syncProjectQuery()
})

watch(selectedTaskId, async (taskId) => {
  currentTaskId.value = taskId
  selectedSectionNo.value = null
  if (currentTask.value !== null) {
    totalPages.value = currentTask.value.total_pages
  }
  await loadSections()
  await loadVisualSettings()
  await loadPages()
  syncProjectQuery()
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

onMounted(async () => {
  await loadProjects()
})

onActivated(async () => {
  // 从其它页面切回脚本页时，SSE 内存状态仍在；这里额外刷新页面列表，兜底补齐隐藏期间已落库的脚本。
  if (selectedTaskId.value !== null) {
    await loadSections()
    await loadPages()
  }
})
</script>

<template>
  <section class="script-page">
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

    <div class="script-workspace">
      <div class="script-sidebar">
        <section class="panel script-config">
          <div class="panel__heading">
            <el-icon><EditPen /></el-icon>
            <div>
              <h2>{{ t('scripts.config.title') }}</h2>
              <p>{{ t('scripts.config.description') }}</p>
            </div>
          </div>

          <el-form label-position="top" class="script-config__form">
            <el-form-item :label="t('scripts.config.project')">
              <el-select
                v-model="selectedProjectId"
                :loading="loadingProjects"
                :placeholder="t('scripts.config.projectPlaceholder')"
                filterable
                class="script-config__control"
              >
                <el-option
                  v-for="project in projects"
                  :key="project.id"
                  :label="project.title"
                  :value="project.id"
                />
              </el-select>
            </el-form-item>

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

          <div class="script-config__actions">
            <el-button
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
              v-if="generatingBatch || continuingBatch"
              type="warning"
              :icon="VideoPause"
              :loading="suspendingBatch"
              :disabled="(currentTaskId === null && selectedTaskId === null) || suspendingBatch"
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
              <h2>{{ t('scripts.progress.title') }}</h2>
              <p>{{ t('scripts.progress.description') }}</p>
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
        <section class="panel script-sections">
          <div class="panel__heading script-sections__heading">
            <div class="panel__heading-main">
              <el-icon><Tickets /></el-icon>
              <div>
                <h2>{{ t('scripts.sections.title') }}</h2>
                <p>{{ t('scripts.sections.description') }}</p>
              </div>
            </div>
            <el-button
              type="danger"
              plain
              :icon="Delete"
              :disabled="generatingBatch || continuingBatch"
              @click="deleteCurrentTaskSections"
            >
              {{ t('scripts.actions.deleteAllSections') }}
            </el-button>
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
                <el-tag :type="sectionCompleted(section) ? 'success' : 'info'" effect="light">
                  {{
                    sectionCompleted(section)
                      ? t('scripts.sections.completed')
                      : t('scripts.sections.pending')
                  }}
                </el-tag>
              </button>
            </div>
          </div>
        </section>

        <section class="panel script-results">
          <div class="panel__heading script-results__heading">
            <div class="panel__heading-main">
              <el-icon><Document /></el-icon>
              <div>
                <h2>{{ t('scripts.pages.title') }}</h2>
                <p>
                  {{ selectedProject?.title || t('scripts.pages.noProject') }}
                </p>
              </div>
            </div>
            <el-button type="primary" :icon="Plus" :disabled="!canEditScripts" @click="openCreateScript">
              {{ t('scripts.actions.addScript') }}
            </el-button>
            <el-button type="danger" plain :icon="Delete" :disabled="!canDeleteAllScripts" @click="deleteAllScripts">
              {{ t('scripts.actions.deleteAllScripts') }}
            </el-button>
          </div>

          <el-table
            v-loading="loadingPages"
            :data="displayedPages"
            class="script-results__table"
            height="520"
            empty-text=""
          >
            <el-table-column prop="page_no" :label="t('scripts.pages.columns.pageNo')" width="88" />
            <el-table-column :label="t('scripts.pages.columns.status')" width="130">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" effect="light">
                  {{ statusLabel(row.status) }}
                </el-tag>
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
            <el-table-column :label="t('scripts.pages.columns.actions')" width="210" fixed="right">
              <template #default="{ row }">
                <el-button text type="primary" :icon="View" @click="openDetail(row)">
                  {{ t('scripts.actions.viewDetail') }}
                </el-button>
                <el-button text type="primary" :icon="EditPen" :disabled="!canEditScripts" @click="openEditScript(row)">
                  {{ t('projects.edit') }}
                </el-button>
                <el-button text type="danger" :icon="Delete" :disabled="!canEditScripts" @click="clearManualScript(row)">
                  {{ t('scripts.actions.clearScript') }}
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty :description="t('scripts.pages.empty')" :image-size="108" />
            </template>
          </el-table>
        </section>
      </div>

      <section class="panel visual-settings">
        <div class="panel__heading">
          <div class="panel__heading-main">
            <el-icon><View /></el-icon>
            <div>
              <h2>{{ t('scripts.visual.title') }}</h2>
              <p>{{ t('scripts.visual.description') }}</p>
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
                    <span>{{ group.character_key }} · {{ group.name || t('imageGeneration.emptyText') }}</span>
                    <el-tag size="small" effect="plain">
                      {{ group.items.length }}
                    </el-tag>
                  </span>
                </template>
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
                  <small>{{ character.visual_anchors }}</small>
                </article>
              </el-collapse-item>
            </el-collapse>
          </div>
          <div class="visual-settings__column">
            <h3>{{ t('scripts.visual.scenes') }}</h3>
            <el-empty v-if="scenes.length === 0" :description="t('scripts.visual.emptyScenes')" :image-size="72" />
            <template v-else>
              <article v-for="scene in scenes" :key="scene.id" class="visual-card">
                <strong>{{ scene.scene_key }} · {{ scene.name }}</strong>
                <p>{{ scene.environment_details }}</p>
                <small>{{ scene.visual_anchors }}</small>
              </article>
            </template>
          </div>
        </div>
      </section>
    </div>

    <el-dialog
      v-model="detailVisible"
      :title="`${t('scripts.detail.title')} ${selectedPage?.page_no ?? ''}`"
      width="720px"
    >
      <div v-if="selectedPage?.summary" class="script-detail">
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
          <strong>{{ t('scripts.visual.sceneKey') }}</strong>
          <p>{{ selectedPage.scene_key || '-' }}</p>
        </section>
        <section class="script-detail__block">
          <strong>{{ t('scripts.visual.characterKeys') }}</strong>
          <p>{{ selectedPage.character_keys.join(', ') || '-' }}</p>
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
.script-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.script-page__alert {
  border-radius: 8px;
}

.script-workspace {
  display: grid;
  grid-template-columns: minmax(280px, 0.72fr) minmax(520px, 1.55fr) minmax(300px, 0.72fr);
  gap: 18px;
  align-items: start;
}

.script-sidebar {
  display: grid;
  gap: 18px;
  order: 1;
}

.script-main {
  display: grid;
  min-width: 0;
  gap: 18px;
  order: 2;
}

.visual-settings {
  order: 3;
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
  grid-template-columns: 1fr;
  gap: 16px;
  padding: 18px 22px 22px;
}

.visual-settings__column {
  display: grid;
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
  overflow-x: auto;
  overflow-y: hidden;
}

.script-sections__empty {
  padding: 14px 16px;
}

.script-sections__track {
  display: flex;
  width: max-content;
  max-width: none;
  gap: 12px;
  padding: 14px 16px 18px;
}

.script-section-item {
  display: flex;
  flex: 0 0 280px;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  width: 280px;
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
  gap: 16px;
}

.script-results__table {
  width: 100%;
}

.script-results__summary {
  color: #334155;
  line-height: 1.55;
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

@media (max-width: 1320px) {
  .script-workspace {
    grid-template-columns: minmax(300px, 0.8fr) minmax(420px, 1.2fr);
  }

  .visual-settings {
    grid-column: 1 / -1;
  }

  .visual-settings__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .script-workspace {
    grid-template-columns: 1fr;
  }

  .script-config__numbers {
    grid-template-columns: 1fr;
  }

  .script-section-item {
    flex-basis: 260px;
    width: 260px;
  }

  .script-progress__scroll {
    height: 420px;
  }

  .visual-settings__grid {
    grid-template-columns: 1fr;
  }
}
</style>

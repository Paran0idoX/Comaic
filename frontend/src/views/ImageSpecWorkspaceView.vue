<script setup lang="ts">
import { Delete, EditPen, MagicStick, MoreFilled, Plus, Refresh, Search, Setting, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { apiErrorMessage } from '@/api/errors'
import {
  createImageSpecPreset,
  deleteImageSpecPreset,
  listContinuityCompilations,
  listImageSpecCompilations,
  listImageSpecPresets,
  listImageSpecs,
  replaceContinuityEvents,
  streamCompileImageSpecs,
  updateImageSpecPreset,
  type ContinuityCompilation,
  type ContinuityEvent,
  type ImagePromptType,
  type ImageSpec,
  type ImageSpecCompilation,
  type ImageSpecPreset,
  type ImageSpecPresetKind,
} from '@/api/imageSpecs'
import { listProjectScriptTasks, type ScriptTask } from '@/api/scripts'
import ReferenceImagePlan from '@/components/workspace/ReferenceImagePlan.vue'
import { useProjectContextStore } from '@/stores/projectContext'
import { useActivityCenterStore, type ActivityStatus } from '@/stores/activityCenter'
import WorkflowReadiness, {
  type ReadinessItem,
} from '@/components/workspace/WorkflowReadiness.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const projectContext = useProjectContextStore()
const activityCenter = useActivityCenterStore()
const { selectedProjectId, projects } = storeToRefs(projectContext)

const tasks = ref<ScriptTask[]>([])
const presets = ref<ImageSpecPreset[]>([])
const specs = ref<ImageSpec[]>([])
const compilations = ref<ContinuityCompilation[]>([])
const specCompilations = ref<ImageSpecCompilation[]>([])
const selectedTaskId = ref<number | null>(null)
const shotPresetId = ref<number | null>(null)
const negativePresetId = ref<number | null>(null)
const generationMode = ref<'preview' | 'final'>('preview')
const concurrency = ref(8)
const regenerateContinuity = ref(false)
const compiling = ref(false)
const selectedCompilationId = ref<number | null>(null)
const configurationOpen = ref(true)
const taskLocationUnavailable = ref(false)
const compilationLocationUnavailable = ref(false)
const targetUnavailable = computed(() => taskLocationUnavailable.value || compilationLocationUnavailable.value)
let projectLoadToken = 0
let taskLoadToken = 0
let viewMounted = true
const runningCompilation = ref<{ projectId: number; scriptTaskId: number; compilationId: number | null } | null>(null)
const queryId = (value: unknown) => {
  const id = Number(value)
  return Number.isInteger(id) && id > 0 ? id : null
}
const progressEvents = ref<Array<{ event: string; payload: Record<string, unknown> }>>([])
const legacyActivityLocation = computed(() => route.query.activity_legacy === '1')
const activeSpecTab = ref<'compile' | 'presets' | 'results'>(
  (['compile', 'presets', 'results'].includes(String(route.query.tab)) ? String(route.query.tab) as 'compile' | 'presets' | 'results' : null) ||
  (localStorage.getItem('comaic-image-spec-tab') as 'compile' | 'presets' | 'results') ||
    'compile',
)
const specPageSearch = ref('')
const specListPage = ref(1)
const specListPageSize = ref(10)

const detailSpec = ref<ImageSpec | null>(null)
const detailVisible = ref(false)
const eventEditorVisible = ref(false)
const eventEditorText = ref('[]')
const presetDialogVisible = ref(false)
const presetSaving = ref(false)
const editingPresetId = ref<number | null>(null)
const presetForm = reactive({
  name: '',
  kind: 'shot_planner_system_prompt' as ImageSpecPresetKind,
  description: '',
  content: '',
  tag_content: '',
  natural_language_content: '',
  is_default: false,
})

const promptTypeOrder: ImagePromptType[] = ['tag', 'natural_language', 'hybrid']
const latestCompilation = computed(() => compilations.value[0] ?? null)
const latestSpecCompilation = computed(() =>
  compilationLocationUnavailable.value ? null : specCompilations.value.find((item) => item.id === selectedCompilationId.value) ?? specCompilations.value[0] ?? null,
)
const shotPresets = computed(() =>
  presets.value.filter((item) => item.kind === 'shot_planner_system_prompt'),
)
const negativePresets = computed(() =>
  presets.value.filter((item) => item.kind === 'negative_prompt'),
)
const presetsReady = computed(() =>
  shotPresets.value.some((item) => item.id === shotPresetId.value) &&
  negativePresets.value.some((item) => item.id === negativePresetId.value),
)
const canCompile = computed(() => selectedTask.value !== null && presetsReady.value && !compiling.value)
const selectedTask = computed(
  () => tasks.value.find((item) => item.id === selectedTaskId.value) ?? null,
)
const expectedSpecCount = computed(() => (selectedTask.value?.total_pages ?? 0) * 3)
const canSavePreset = computed(() => {
  if (!presetForm.name.trim()) return false
  if (presetForm.kind === 'shot_planner_system_prompt') return Boolean(presetForm.content.trim())
  return Boolean(
    presetForm.tag_content.trim() && presetForm.natural_language_content.trim(),
  )
})
const specsByPage = computed(() => {
  const result = new Map<number, ImageSpec[]>()
  for (const spec of specs.value) {
    const values = result.get(spec.page_no) ?? []
    values.push(spec)
    result.set(spec.page_no, values)
  }
  return [...result.entries()]
    .sort(([left], [right]) => left - right)
    .map(([pageNo, values]) => [
      pageNo,
      [...values].sort(
        (left, right) =>
          promptTypeOrder.indexOf(left.prompt_type) - promptTypeOrder.indexOf(right.prompt_type),
      ),
    ] as const)
})
const filteredSpecsByPage = computed(() => {
  const query = specPageSearch.value.trim().toLowerCase()
  if (!query) return specsByPage.value
  return specsByPage.value.filter(([pageNo, values]) =>
    [pageNo, ...values.flatMap((item) => [item.positive_prompt, item.negative_prompt])]
      .filter((value) => value !== null)
      .some((value) => String(value).toLowerCase().includes(query)),
  )
})
const paginatedSpecsByPage = computed(() => {
  const start = (specListPage.value - 1) * specListPageSize.value
  return filteredSpecsByPage.value.slice(start, start + specListPageSize.value)
})
const imageSpecReadinessItems = computed<ReadinessItem[]>(() => [
  {
    key: 'task',
    label: t('imageSpecs.readiness.task'),
    detail: selectedTask.value
      ? `#${selectedTask.value.id} · ${selectedTask.value.total_pages}p`
      : t('imageSpecs.readiness.taskMissing'),
    status: selectedTask.value ? 'ready' : 'blocked',
    to: selectedTask.value ? undefined : { path: '/scripts', query: { project_id: selectedProjectId.value ?? undefined } },
    actionLabel: selectedTask.value ? undefined : t('imageSpecs.readiness.openScripts'),
  },
  {
    key: 'presets',
    label: t('imageSpecs.readiness.presets'),
    detail: t('imageSpecs.readiness.presetCount', {
      shot: shotPresets.value.length,
      negative: negativePresets.value.length,
    }),
    status: presetsReady.value ? 'ready' : 'blocked',
    to: presetsReady.value ? undefined : { path: '/image-specs', query: { ...route.query, tab: 'presets' } },
    actionLabel: presetsReady.value ? undefined : t('imageSpecs.presets.manage'),
  },
  {
    key: 'scope',
    label: t('imageSpecs.readiness.scope'),
    detail: t('imageSpecs.readiness.scopeDetail', {
      pages: selectedTask.value?.total_pages ?? 0,
      specs: expectedSpecCount.value,
    }),
    status: selectedTask.value ? 'info' : 'pending',
  },
  {
    key: 'result',
    label: t('imageSpecs.readiness.result'),
    detail: t('imageSpecs.readiness.resultDetail', {
      pages: latestSpecCompilation.value?.completed_pages ?? specsByPage.value.length,
    }),
    status:
      latestSpecCompilation.value?.status === 'succeeded'
        ? 'ready'
        : latestSpecCompilation.value?.status === 'failed'
          ? 'blocked'
          : 'pending',
  },
])

const selectPresetDefaults = () => {
  if (!shotPresets.value.some((item) => item.id === shotPresetId.value)) {
    shotPresetId.value =
      (shotPresets.value.find((item) => item.is_default) ?? shotPresets.value[0])?.id ?? null
  }
  if (!negativePresets.value.some((item) => item.id === negativePresetId.value)) {
    negativePresetId.value =
      (negativePresets.value.find((item) => item.is_default) ?? negativePresets.value[0])?.id ??
      null
  }
}

const loadPresets = async () => {
  presets.value = await listImageSpecPresets()
  selectPresetDefaults()
}

const loadProject = async () => {
  const projectId = selectedProjectId.value
  const token = ++projectLoadToken
  ++taskLoadToken
  tasks.value = []
  specs.value = []
  compilations.value = []
  specCompilations.value = []
  if (projectId === null) {
    selectedTaskId.value = null
    return
  }
  try {
    const taskItems = await listProjectScriptTasks(projectId, { status: 'succeeded' })
    if (token !== projectLoadToken || projectId !== selectedProjectId.value) return
    tasks.value = taskItems
    const requestedTaskId = queryId(route.query.project_id) === projectId ? queryId(route.query.script_task_id) : null
    taskLocationUnavailable.value = !legacyActivityLocation.value && requestedTaskId !== null && !tasks.value.some((item) => item.id === requestedTaskId)
    if (legacyActivityLocation.value || taskLocationUnavailable.value) {
      selectedTaskId.value = null
    } else if (requestedTaskId !== null && tasks.value.some((item) => item.id === requestedTaskId)) {
      selectedTaskId.value = requestedTaskId
    }
    if (!legacyActivityLocation.value && !taskLocationUnavailable.value && !tasks.value.some((item) => item.id === selectedTaskId.value)) {
      selectedTaskId.value = tasks.value[0]?.id ?? null
    }
    await loadTask()
  } catch (error) {
    if (token === projectLoadToken) ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const loadTask = async () => {
  const taskId = selectedTaskId.value
  const projectId = selectedProjectId.value
  const token = ++taskLoadToken
  if (taskId === null) {
    specs.value = []
    compilations.value = []
    specCompilations.value = []
    return
  }
  try {
    const [specItems, continuityItems, compilationItems] = await Promise.all([
      listImageSpecs(taskId),
      listContinuityCompilations(taskId),
      listImageSpecCompilations(taskId),
    ])
    if (token !== taskLoadToken || taskId !== selectedTaskId.value || projectId !== selectedProjectId.value) return
    specs.value = specItems
    compilations.value = continuityItems
    specCompilations.value = compilationItems
    const requested = queryId(route.query.compilation_id)
    compilationLocationUnavailable.value = requested !== null && !compilationItems.some((item) => item.id === requested)
    selectedCompilationId.value = compilationLocationUnavailable.value ? null : compilationItems.some((item) => item.id === requested) ? requested : compilationItems[0]?.id ?? null
    if (compilationLocationUnavailable.value) specs.value = []
    configurationOpen.value = latestSpecCompilation.value?.status !== 'succeeded'
    syncContextQuery()
    for (const compilation of compilationItems) syncCompilationActivity(compilation, projectId)
  } catch (error) {
    if (token === taskLoadToken) ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const compile = async () => {
  if (!canCompile.value || selectedTaskId.value === null || selectedProjectId.value === null) return
  // 流式回调始终属于提交时的项目和脚本，浏览器切换项目不会改变任务归属。
  const context = { projectId: selectedProjectId.value, scriptTaskId: selectedTaskId.value, compilationId: null as number | null }
  runningCompilation.value = context
  const visible = () => viewMounted && selectedProjectId.value === context.projectId && selectedTaskId.value === context.scriptTaskId
  compiling.value = true
  progressEvents.value = []
  let failed = false
  try {
    await streamCompileImageSpecs(
      context.scriptTaskId,
      {
        style_profile_id: null,
        shot_planner_preset_id: shotPresetId.value,
        negative_prompt_preset_id: negativePresetId.value,
        generation_mode: generationMode.value,
        concurrency: concurrency.value,
        regenerate_continuity: regenerateContinuity.value,
        resume_existing: true,
      },
      {
        onEvent: (event, payload) => {
          const id = queryId(payload.image_spec_compilation_id ?? (event === 'compilation' ? payload.id : payload.compilation_id))
          if (id !== null) context.compilationId = id
          if (event === 'compilation' && visible() && id !== null) {
            compilationLocationUnavailable.value = false
            selectedCompilationId.value = id
            syncContextQuery()
          }
          if (visible()) progressEvents.value.unshift({ event, payload })
          if (context.compilationId !== null) {
            activityCenter.upsertActivity({
              id: `image-spec-${context.compilationId}`, kind: 'imageSpec', label: `#${context.compilationId}`,
              status: event === 'done' ? 'succeeded' : event === 'error' || event === 'failed' ? 'failed' : 'running', progress: event === 'done' ? 100 : null,
              route: `/image-specs?project_id=${context.projectId}&script_task_id=${context.scriptTaskId}&compilation_id=${context.compilationId}&tab=results`,
              projectId: context.projectId, scriptTaskId: context.scriptTaskId, compilationId: context.compilationId, updatedAt: new Date().toISOString(),
            })
          }
        },
        onError: (error) => {
          failed = true
          if (visible()) ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.compile')))
        },
      },
    )
    const completed = await listImageSpecCompilations(context.scriptTaskId)
    for (const item of completed) syncCompilationActivity(item, context.projectId)
    if (visible()) {
      await loadTask()
      if (!failed) {
        activeSpecTab.value = 'results'
        configurationOpen.value = false
        ElMessage.success(t('imageSpecs.messages.compiled'))
      }
    }
  } catch (error) {
    if (visible()) ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.compile')))
  } finally {
    compiling.value = false
    runningCompilation.value = null
  }
}

const openDetail = (spec: ImageSpec) => {
  detailSpec.value = spec
  detailVisible.value = true
}

const resetPresetForm = (kind: ImageSpecPresetKind) => {
  editingPresetId.value = null
  presetForm.name = ''
  presetForm.kind = kind
  presetForm.description = ''
  presetForm.content = ''
  presetForm.tag_content = ''
  presetForm.natural_language_content = ''
  presetForm.is_default = false
}

const openCreatePreset = (kind: ImageSpecPresetKind = 'shot_planner_system_prompt') => {
  resetPresetForm(kind)
  presetDialogVisible.value = true
}

const openEditPreset = (preset: ImageSpecPreset) => {
  editingPresetId.value = preset.id
  presetForm.name = preset.name
  presetForm.kind = preset.kind
  presetForm.description = preset.description ?? ''
  presetForm.content = preset.content
  presetForm.tag_content = preset.tag_content
  presetForm.natural_language_content = preset.natural_language_content
  presetForm.is_default = preset.is_default
  presetDialogVisible.value = true
}

const savePreset = async () => {
  if (!canSavePreset.value) return
  presetSaving.value = true
  const payload = {
    name: presetForm.name,
    kind: presetForm.kind,
    description: presetForm.description || null,
    content: presetForm.content,
    tag_content: presetForm.tag_content,
    natural_language_content: presetForm.natural_language_content,
    is_default: presetForm.is_default,
  }
  try {
    if (editingPresetId.value === null) await createImageSpecPreset(payload)
    else await updateImageSpecPreset(editingPresetId.value, payload)
    presetDialogVisible.value = false
    await loadPresets()
    ElMessage.success(t('imageSpecs.presets.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.presets.saveFailed')))
  } finally {
    presetSaving.value = false
  }
}

const removePreset = async (preset: ImageSpecPreset) => {
  try {
    await ElMessageBox.confirm(
      t('imageSpecs.presets.deleteConfirm', { name: preset.name }),
      t('imageSpecs.presets.deleteTitle'),
      { type: 'warning' },
    )
    await deleteImageSpecPreset(preset.id)
    await loadPresets()
    ElMessage.success(t('imageSpecs.presets.deleted'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.presets.deleteFailed')))
    }
  }
}

const openEventEditor = () => {
  if (latestCompilation.value === null) return
  eventEditorText.value = JSON.stringify(
    latestCompilation.value.events
      .filter((item) => item.source !== 'system')
      .map(({ page_no, sequence_no, event_type, target_type, target_key, timing, payload }) => ({
        page_no,
        sequence_no,
        event_type,
        target_type,
        target_key,
        timing,
        payload,
      })),
    null,
    2,
  )
  eventEditorVisible.value = true
}

const saveEvents = async () => {
  if (latestCompilation.value === null) return
  try {
    const parsed = JSON.parse(eventEditorText.value) as unknown
    if (!Array.isArray(parsed)) throw new Error('events must be an array')
    await replaceContinuityEvents(
      latestCompilation.value.id,
      parsed as Array<Omit<ContinuityEvent, 'id' | 'page_id' | 'source'>>,
    )
    eventEditorVisible.value = false
    await loadTask()
    ElMessage.success(t('imageSpecs.messages.eventsSaved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.events')))
  }
}

const normalizeCompilationStatus = (status: string): ActivityStatus => {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'suspended') return 'suspended'
  if (status === 'running') return 'running'
  return 'pending'
}

const syncCompilationActivity = (compilation: ImageSpecCompilation, projectId: number | null) => {
  if (projectId === null) return
  const total = Math.max(1, compilation.total_specs)
  activityCenter.upsertActivity({
    id: `image-spec-${compilation.id}`,
    kind: 'imageSpec',
    label: `#${compilation.id} · ${compilation.completed_specs}/${compilation.total_specs}`,
    status: normalizeCompilationStatus(compilation.status),
    progress: (compilation.completed_specs / total) * 100,
    route: `/image-specs?project_id=${projectId}&script_task_id=${compilation.task_id}&compilation_id=${compilation.id}&tab=results`,
    projectId,
    scriptTaskId: compilation.task_id,
    compilationId: compilation.id,
    updatedAt: compilation.updated_at,
  })
}

const syncContextQuery = () => {
  if (route.path !== '/image-specs') return
  const query = { ...route.query, project_id: selectedProjectId.value?.toString(), script_task_id: taskLocationUnavailable.value ? route.query.script_task_id : selectedTaskId.value?.toString(), compilation_id: targetUnavailable.value && selectedCompilationId.value === null ? route.query.compilation_id : selectedCompilationId.value?.toString(), tab: activeSpecTab.value, activity_legacy: selectedTaskId.value === null ? route.query.activity_legacy : undefined }
  if (Object.entries(query).some(([key, value]) => route.query[key] !== value)) void router.replace({ query })
}

const applyRouteContext = async () => {
  if (route.path !== '/image-specs') return
  const projectId = queryId(route.query.project_id)
  if (projectId !== null && projectId !== selectedProjectId.value) {
    selectedProjectId.value = projectId
    return
  }
  const taskId = queryId(route.query.script_task_id)
  if (legacyActivityLocation.value) {
    taskLocationUnavailable.value = false
    compilationLocationUnavailable.value = false
    selectedTaskId.value = null
    selectedCompilationId.value = null
    specs.value = []
    compilations.value = []
    specCompilations.value = []
    if (['compile', 'presets', 'results'].includes(String(route.query.tab))) activeSpecTab.value = String(route.query.tab) as typeof activeSpecTab.value
    return
  }
  if (taskId !== null && !tasks.value.some((item) => item.id === taskId)) {
    taskLocationUnavailable.value = true
    selectedTaskId.value = null
    specs.value = []
    return
  }
  if (taskId !== null && tasks.value.some((item) => item.id === taskId) && taskId !== selectedTaskId.value) {
    taskLocationUnavailable.value = false
    selectedTaskId.value = taskId
  }
  const compilationId = queryId(route.query.compilation_id)
  if (compilationId !== null && selectedTaskId.value !== null && !specCompilations.value.some((item) => item.id === compilationId) && runningCompilation.value?.compilationId !== compilationId) {
    compilationLocationUnavailable.value = true
    selectedCompilationId.value = null
    specs.value = []
    return
  }
  if (compilationId !== null) {
    const previouslyUnavailable = compilationLocationUnavailable.value
    compilationLocationUnavailable.value = false
    selectedCompilationId.value = compilationId
    if (previouslyUnavailable) void loadTask()
  }
  if (['compile', 'presets', 'results'].includes(String(route.query.tab))) activeSpecTab.value = String(route.query.tab) as typeof activeSpecTab.value
}

watch(selectedProjectId, () => {
  taskLocationUnavailable.value = false
  compilationLocationUnavailable.value = false
  selectedCompilationId.value = null
  progressEvents.value = []
  if (queryId(route.query.project_id) !== selectedProjectId.value) {
    void router.replace({ query: { ...route.query, project_id: selectedProjectId.value?.toString(), script_task_id: undefined, compilation_id: undefined, style_profile_id: undefined } })
  }
  void loadProject()
})
watch(selectedTaskId, () => {
  if (selectedTaskId.value !== null && queryId(route.query.script_task_id) !== selectedTaskId.value) taskLocationUnavailable.value = false
  compilationLocationUnavailable.value = false
  selectedCompilationId.value = queryId(route.query.script_task_id) === selectedTaskId.value ? queryId(route.query.compilation_id) : null
  specs.value = []
  compilations.value = []
  specCompilations.value = []
  syncContextQuery()
  void loadTask()
})
watch(presets, selectPresetDefaults)
watch(activeSpecTab, (value) => { localStorage.setItem('comaic-image-spec-tab', value); syncContextQuery() })
watch(specPageSearch, () => {
  specListPage.value = 1
})
watch(() => route.query, applyRouteContext, { deep: true })

onMounted(async () => {
  try {
    const previousProjectId = selectedProjectId.value
    await Promise.all([projectContext.refreshProjects(), loadPresets()])
    const requestedProject = queryId(route.query.project_id)
    if (projects.value.some((item) => item.id === requestedProject)) selectedProjectId.value = requestedProject
    if (selectedProjectId.value !== null && selectedProjectId.value === previousProjectId) {
      await loadProject()
    }
    await applyRouteContext()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
})

onBeforeUnmount(() => {
  viewMounted = false
  ++projectLoadToken
  ++taskLoadToken
})
</script>

<template>
  <div class="image-spec-page">
    <el-alert v-if="legacyActivityLocation" type="info" :closable="false" :title="t('activityCenter.legacyLocation')" />
    <el-alert v-if="targetUnavailable" type="warning" :closable="false" :title="t('activityCenter.targetUnavailable')" />
    <div class="page-header">
      <div class="workspace-context">
        <strong>{{ t('ux.currentProject') }} · {{ projects.find((item) => item.id === selectedProjectId)?.title || '—' }}</strong>
        <span>{{ t('ux.currentBatch') }} · {{ selectedTask ? `#${selectedTask.id} · ${selectedTask.total_pages}p` : t('ux.notStarted') }}</span>
      </div>
      <el-select v-model="selectedTaskId" class="context-task-select" :placeholder="t('imageSpecs.task')" :aria-label="t('imageSpecs.task')" filterable>
        <el-option v-for="item in tasks" :key="item.id" :label="`#${item.id} · ${item.total_pages}p`" :value="item.id" />
      </el-select>
      <el-button :icon="Refresh" @click="loadTask">{{ t('imageSpecs.refresh') }}</el-button>
      <el-button :icon="Setting" @click="openCreatePreset()">
        {{ t('imageSpecs.presets.manage') }}
      </el-button>
      <el-button v-if="activeSpecTab === 'compile'" class="ai-gradient-button" type="primary" :icon="MagicStick" :loading="compiling" :disabled="!canCompile" @click="compile">
        {{ t('imageSpecs.compileAllTypes') }}
      </el-button>
      <el-button v-if="specs.length" type="primary" @click="router.push({ path: '/image-generation', query: { project_id: selectedProjectId ?? undefined, script_task_id: selectedTaskId ?? undefined } })">
        {{ t('ux.nextStep') }} · {{ t('nav.imageGeneration') }}
      </el-button>
    </div>

    <WorkflowReadiness
      :title="t('imageSpecs.readiness.title')"
      :description="t('imageSpecs.readiness.description')"
      :items="imageSpecReadinessItems"
    />

    <el-tabs v-model="activeSpecTab" class="workspace-tabs image-spec-tabs">
      <el-tab-pane :label="t('imageSpecs.tabs.compile')" name="compile" />
      <el-tab-pane name="presets">
        <template #label>{{ t('imageSpecs.tabs.presets') }}<el-badge :value="presets.length" /></template>
      </el-tab-pane>
      <el-tab-pane name="results">
        <template #label>{{ t('imageSpecs.tabs.results') }}<el-badge :value="specsByPage.length" :hidden="specsByPage.length === 0" /></template>
      </el-tab-pane>
    </el-tabs>

    <section v-show="activeSpecTab === 'compile'" class="panel controls">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.configTitle') }}</h2>
          <p>{{ t('imageSpecs.promptTypeHint') }}</p>
        </div>
        <el-button link type="primary" @click="configurationOpen = !configurationOpen">{{ t('ux.showConfiguration') }}</el-button>
      </header>
      <div v-show="configurationOpen" class="panel-body controls-body">
        <el-form label-position="top">
          <div class="control-grid">
            <el-form-item :label="t('ux.referenceCheck')">
              <el-segmented
                v-model="generationMode"
                :options="[
                  { label: t('ux.relaxed'), value: 'preview' },
                  { label: t('ux.strict'), value: 'final' },
                ]"
              />
            </el-form-item>
          </div>
          <p class="reference-help">{{ t('ux.referenceCheckHelp') }}</p>
          <el-collapse class="advanced-settings">
            <el-collapse-item :title="t('ux.advancedSettings')" name="advanced">
          <div class="control-grid secondary">
            <el-form-item :label="t('imageSpecs.shotPlanner')">
              <el-select v-model="shotPresetId">
                <el-option v-for="item in shotPresets" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageSpecs.negativePrompt')">
              <el-select v-model="negativePresetId">
                <el-option v-for="item in negativePresets" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageSpecs.concurrency')">
              <el-input-number v-model="concurrency" :min="1" :max="20" />
            </el-form-item>
            <el-form-item label=" ">
              <el-checkbox v-model="regenerateContinuity">{{ t('imageSpecs.regenerate') }}</el-checkbox>
            </el-form-item>
          </div>
          <div class="prompt-type-strip">
            <div v-for="type in promptTypeOrder" :key="type" class="prompt-type-card">
              <strong>{{ t(`imageSpecs.promptTypes.${type}`) }}</strong>
              <span>{{ t(`imageSpecs.promptTypes.${type}Hint`) }}</span>
            </div>
          </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <el-alert
          v-if="generationMode === 'final'"
          type="warning"
          :closable="false"
          :title="t('imageSpecs.finalHint')"
        />
        <div class="controls-actions">
          <span class="compile-scope">
            {{
              t('imageSpecs.readiness.scopeDetail', {
                pages: selectedTask?.total_pages ?? 0,
                specs: expectedSpecCount,
              })
            }}
          </span>
          <el-button
            class="ai-gradient-button"
            type="primary"
            :icon="MagicStick"
            :loading="compiling"
            :disabled="!canCompile"
            @click="compile"
          >
            {{ t('imageSpecs.compileAllTypes') }}
          </el-button>
        </div>
      </div>
    </section>

    <section v-show="activeSpecTab === 'compile'" v-if="latestSpecCompilation" class="panel compilation-status">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.compilationStatus.title') }}</h2>
          <p>#{{ latestSpecCompilation.id }} · {{ latestSpecCompilation.source_hash.slice(0, 12) }}</p>
        </div>
        <el-tag
          :type="latestSpecCompilation.status === 'succeeded' ? 'success' : latestSpecCompilation.status === 'failed' ? 'danger' : 'warning'"
        >
          {{ t(`imageSpecs.compilationStatus.statuses.${latestSpecCompilation.status}`) }}
        </el-tag>
      </header>
      <div class="compilation-status__body">
        <p>
          {{
            t('imageSpecs.compilationStatus.summary', {
              pages: latestSpecCompilation.completed_pages,
              totalPages: latestSpecCompilation.total_pages,
              specs: latestSpecCompilation.completed_specs,
              totalSpecs: latestSpecCompilation.total_specs,
            })
          }}
        </p>
        <el-progress
          :percentage="latestSpecCompilation.total_specs ? Math.round(latestSpecCompilation.completed_specs * 100 / latestSpecCompilation.total_specs) : 0"
        />
        <el-alert
          v-if="latestSpecCompilation.failed_pages.length"
          type="error"
          :closable="false"
          :title="t('imageSpecs.compilationStatus.failedPages', {
            pages: latestSpecCompilation.failed_pages.map((item) => item.page_no).join(', '),
          })"
        />
      </div>
    </section>

    <section v-show="activeSpecTab === 'presets'" class="panel preset-panel">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.presets.title') }}</h2>
          <p>{{ t('imageSpecs.presets.hint') }}</p>
        </div>
        <el-button :icon="Plus" @click="openCreatePreset()">{{ t('imageSpecs.presets.create') }}</el-button>
      </header>
      <div class="preset-grid">
        <article v-for="preset in presets" :key="preset.id" class="preset-card">
          <div>
            <el-tag size="small">{{ t(`imageSpecs.presets.kinds.${preset.kind}`) }}</el-tag>
            <el-tag v-if="preset.is_default" size="small" type="success">{{ t('imageSpecs.presets.default') }}</el-tag>
          </div>
          <strong>{{ preset.name }}</strong>
          <p>{{ preset.description || t('imageSpecs.presets.noDescription') }}</p>
          <div class="preset-actions">
            <el-button link type="primary" :icon="EditPen" @click="openEditPreset(preset)">
              {{ t('projects.edit') }}
            </el-button>
            <el-dropdown trigger="click">
              <el-button link :icon="MoreFilled" :aria-label="t('imageSpecs.presets.more')" />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item :icon="Delete" @click="removePreset(preset)">
                    {{ t('projects.delete') }}
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </article>
      </div>
    </section>

    <section v-show="activeSpecTab === 'results'" v-if="latestCompilation" class="panel continuity">
      <el-collapse>
        <el-collapse-item :title="`${t('ux.advancedSettings')} · ${t('imageSpecs.continuity.title')}`" name="continuity">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.continuity.title') }}</h2>
          <p>#{{ latestCompilation.id }} · {{ latestCompilation.source_hash.slice(0, 12) }}</p>
        </div>
        <el-button :icon="EditPen" @click="openEventEditor">{{ t('imageSpecs.continuity.edit') }}</el-button>
      </header>
      <el-table :data="latestCompilation.events" max-height="280">
        <el-table-column prop="page_no" :label="t('imageSpecs.table.page')" width="80" />
        <el-table-column prop="timing" :label="t('imageSpecs.table.timing')" width="120" />
        <el-table-column prop="event_type" :label="t('imageSpecs.table.event')" width="190" />
        <el-table-column prop="target_key" :label="t('imageSpecs.table.target')" width="150" />
        <el-table-column prop="source" :label="t('imageSpecs.table.source')" width="90" />
        <el-table-column :label="t('imageSpecs.table.payload')">
          <template #default="scope"><code class="payload-code">{{ JSON.stringify(scope.row.payload) }}</code></template>
        </el-table-column>
      </el-table>
        </el-collapse-item>
      </el-collapse>
    </section>

    <div v-show="activeSpecTab === 'results'" class="spec-result-toolbar panel workspace-toolbar">
      <el-input
        v-model="specPageSearch"
        clearable
        :prefix-icon="Search"
        :placeholder="t('imageSpecs.search')"
        :aria-label="t('imageSpecs.search')"
      />
      <span class="workspace-toolbar__spacer" />
      <span>{{ t('imageSpecs.resultCount', { count: filteredSpecsByPage.length }) }}</span>
    </div>

    <section v-show="activeSpecTab === 'results'" class="spec-list">
      <article v-for="[pageNo, pageSpecs] in paginatedSpecsByPage" :key="pageNo" class="panel spec-card">
        <header class="panel-heading">
          <h2>{{ t('imageSpecs.page', { page: pageNo }) }}</h2>
          <span>{{ t('imageSpecs.threeTypesReady') }}</span>
        </header>
        <ReferenceImagePlan :plan="pageSpecs[0]?.spec.reference_plan" />
        <el-tabs class="spec-tabs">
          <el-tab-pane
            v-for="spec in pageSpecs"
            :key="spec.id"
            :label="t(`imageSpecs.promptTypes.${spec.prompt_type}`)"
          >
            <div class="spec-content">
              <div class="tags">
                <el-tag>{{ t(`imageSpecs.promptTypes.${spec.prompt_type}`) }}</el-tag>
                <el-tag :type="spec.generation_mode === 'final' ? 'success' : 'info'">{{ t(spec.generation_mode === 'final' ? 'ux.strict' : 'ux.relaxed') }}</el-tag>
                <el-tag v-if="spec.warnings.length" type="warning">
                  {{ t('imageSpecs.warningCount', { count: spec.warnings.length }) }}
                </el-tag>
              </div>
              <p>{{ spec.positive_prompt }}</p>
              <div class="spec-footer">
                <el-button link type="primary" :icon="View" @click="openDetail(spec)">{{ t('imageSpecs.detail') }}</el-button>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </article>
      <el-empty v-if="filteredSpecsByPage.length === 0" class="panel spec-list__empty" :description="t('imageSpecs.empty')" />
    </section>

    <div
      v-show="activeSpecTab === 'results'"
      v-if="filteredSpecsByPage.length > specListPageSize"
      class="spec-pagination panel"
    >
      <el-pagination
        v-model:current-page="specListPage"
        v-model:page-size="specListPageSize"
        :total="filteredSpecsByPage.length"
        :page-sizes="[5, 10, 20]"
        layout="total, sizes, prev, pager, next, jumper"
        background
      />
    </div>

    <section v-show="activeSpecTab === 'compile'" v-if="progressEvents.length" class="panel">
      <el-collapse><el-collapse-item :title="`${t('ux.advancedSettings')} · ${t('imageSpecs.progress')}`" name="events">
      <div class="event-log">
        <div v-for="(item, index) in progressEvents.slice(0, 30)" :key="index">
          <el-tag size="small">{{ item.event }}</el-tag><code>{{ JSON.stringify(item.payload) }}</code>
        </div>
      </div>
      </el-collapse-item></el-collapse>
    </section>

    <el-drawer v-model="detailVisible" size="min(860px, 94vw)" :title="t('imageSpecs.detail')">
      <template v-if="detailSpec">
        <ReferenceImagePlan :plan="detailSpec.spec.reference_plan" />
        <el-alert
          v-for="warning in detailSpec.warnings"
          :key="warning.code"
          type="warning"
          :closable="false"
          :title="warning.message"
        />
        <h3>{{ t('imageSpecs.positivePrompt') }}</h3><pre>{{ detailSpec.positive_prompt }}</pre>
        <h3>{{ t('imageSpecs.negativePromptTitle') }}</h3><pre>{{ detailSpec.negative_prompt }}</pre>
        <el-collapse><el-collapse-item :title="`${t('ux.advancedSettings')} · JSON`" name="json"><pre>{{ JSON.stringify(detailSpec.spec, null, 2) }}</pre></el-collapse-item></el-collapse>
      </template>
    </el-drawer>

    <el-dialog v-model="presetDialogVisible" destroy-on-close :title="t('imageSpecs.presets.editorTitle')" width="min(760px, 94vw)">
      <el-form label-position="top">
        <div class="dialog-grid">
          <el-form-item :label="t('imageSpecs.presets.name')" required><el-input v-model="presetForm.name" /></el-form-item>
          <el-form-item :label="t('imageSpecs.presets.kind')" required>
            <el-select v-model="presetForm.kind">
              <el-option :label="t('imageSpecs.presets.kinds.shot_planner_system_prompt')" value="shot_planner_system_prompt" />
              <el-option :label="t('imageSpecs.presets.kinds.negative_prompt')" value="negative_prompt" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item :label="t('imageSpecs.presets.description')"><el-input v-model="presetForm.description" /></el-form-item>
        <el-form-item v-if="presetForm.kind === 'shot_planner_system_prompt'" :label="t('imageSpecs.presets.shotContent')" required>
          <el-input v-model="presetForm.content" type="textarea" :rows="14" />
        </el-form-item>
        <template v-else>
          <el-form-item :label="t('imageSpecs.presets.tagNegative')" required>
            <el-input v-model="presetForm.tag_content" type="textarea" :rows="6" />
          </el-form-item>
          <el-form-item :label="t('imageSpecs.presets.naturalNegative')" required>
            <el-input v-model="presetForm.natural_language_content" type="textarea" :rows="6" />
          </el-form-item>
        </template>
        <el-checkbox v-model="presetForm.is_default">{{ t('imageSpecs.presets.setDefault') }}</el-checkbox>
      </el-form>
      <template #footer>
        <el-button @click="presetDialogVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" :loading="presetSaving" :disabled="!canSavePreset" @click="savePreset">{{ t('projects.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="eventEditorVisible" :title="t('imageSpecs.continuity.edit')" width="min(820px, 94vw)">
      <el-alert type="info" :closable="false" :title="t('imageSpecs.continuity.editHint')" />
      <el-input v-model="eventEditorText" type="textarea" :rows="22" class="json-editor" />
      <template #footer>
        <el-button @click="eventEditorVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" @click="saveEvents">{{ t('projects.save') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.image-spec-page { display: grid; grid-template-columns: minmax(0, 1fr); min-width: 0; gap: 18px; }
.page-header { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.workspace-context { display: grid; gap: 5px; margin-right: auto; min-width: 0; }
.workspace-context span, .reference-help { color: var(--text-secondary); font-size: 13px; }
.context-task-select { width: min(230px, 100%); }
.advanced-settings { margin-top: 12px; }
.image-spec-tabs { margin-bottom: -2px; }
.panel { min-width: 0; overflow: hidden; border: 1px solid var(--panel-border); border-radius: 8px; background: #fff; box-shadow: var(--panel-shadow); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px 22px 16px; border-bottom: 1px solid var(--panel-border); }
.panel-heading h2, .panel-heading p { margin: 0; }
.panel-heading p { margin-top: 6px; color: var(--text-secondary); }
.panel-body { padding: 20px 22px; }
.compilation-status__body { display: grid; gap: 12px; padding: 18px 22px 22px; }
.compilation-status__body p { margin: 0; color: var(--text-secondary); }
.control-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.secondary { margin-top: 2px; }
.controls-actions { display: flex; align-items: center; justify-content: flex-end; gap: 16px; margin-top: 18px; }
.compile-scope { color: var(--text-secondary); font-size: 13px; }
.prompt-type-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.prompt-type-card { display: grid; gap: 6px; padding: 14px; border: 1px solid #dce8f8; border-radius: 8px; background: #f7fbff; }
.prompt-type-card span { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.preset-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; padding: 18px 22px 22px; }
.preset-card { display: grid; gap: 10px; padding: 14px; border: 1px solid #e2eaf4; border-radius: 8px; }
.preset-card p { min-height: 38px; margin: 0; color: var(--text-secondary); font-size: 13px; }
.preset-actions { display: flex; justify-content: flex-end; }
.spec-result-toolbar { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.spec-result-toolbar :deep(.el-input) { width: min(320px, 100%); }
.spec-list { display: grid; gap: 16px; }
.spec-list__empty { padding: 36px 20px; }
.spec-pagination { display: flex; justify-content: flex-end; padding: 14px 18px; }
.spec-tabs { padding: 0 22px 18px; }
.spec-content { display: grid; gap: 12px; }
.spec-content p { max-height: 110px; overflow: auto; margin: 0; color: var(--text-secondary); white-space: pre-wrap; }
.spec-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.tags { display: flex; flex-wrap: wrap; gap: 8px; }
.payload-code { white-space: normal; overflow-wrap: anywhere; }
.event-log { display: grid; gap: 8px; max-height: 300px; overflow: auto; padding: 18px 22px; }
.event-log div { display: flex; align-items: flex-start; gap: 8px; }
.event-log code { overflow-wrap: anywhere; }
pre { overflow: auto; padding: 14px; border-radius: 8px; background: #071426; color: #d8e7ff; white-space: pre-wrap; }
.json-editor { margin-top: 14px; }
.dialog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1100px) { .control-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) {
  .control-grid, .prompt-type-strip, .dialog-grid { grid-template-columns: 1fr; }
  .page-header { align-items: stretch; }
  .page-header :deep(.el-button) { width: 100%; margin-left: 0; }
  .controls-actions, .spec-result-toolbar { align-items: stretch; flex-direction: column; }
  .spec-result-toolbar :deep(.el-input) { width: 100%; }
  .spec-pagination { overflow-x: auto; justify-content: flex-start; }
}
</style>

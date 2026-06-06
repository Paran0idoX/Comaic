<script setup lang="ts">
import { Delete, EditPen, Picture, Plus, Search, Select, UploadFilled, VideoPause, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  createComfyWorkflow,
  deleteComfyWorkflow,
  listComfyWorkflows,
  listImageGenerationPages,
  selectGeneratedImage,
  streamGenerateImagesForPage,
  streamGenerateImagesForTask,
  suspendImageGenerationTask,
  updateComfyWorkflow,
  type ComfyWorkflowPreset,
  type GeneratedImage,
  type ImageGenerationPage,
} from '@/api/imageGeneration'
import { apiErrorMessage } from '@/api/errors'
import { listCompletedScriptTasks } from '@/api/imagePrompts'
import { listProjects, type Project } from '@/api/projects'
import type { ScriptTask } from '@/api/scripts'
import { formatLocalNowTime } from '@/utils/datetime'

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

const { locale, t } = useI18n()

const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const workflows = ref<ComfyWorkflowPreset[]>([])
const pages = ref<ImageGenerationPage[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedTaskId = ref<number | null>(null)
const selectedWorkflowId = ref<number | null>(null)
const currentGenerationTaskId = ref<number | null>(null)
const loading = ref(false)
const loadingTasks = ref(false)
const loadingPages = ref(false)
const generating = ref(false)
const suspending = ref(false)
const workflowDialogVisible = ref(false)
const workflowDialogMode = ref<'create' | 'edit'>('create')
const editingWorkflowId = ref<number | null>(null)
const detailImage = ref<GeneratedImage | null>(null)
const detailVisible = ref(false)
const progressEvents = ref<ProgressEvent[]>([])
const eventSequence = ref(1)

const generationForm = reactive({
  poll_interval_seconds: 2,
  candidates_per_page: 1,
  negative_prompt: '',
})

const workflowForm = reactive({
  name: '',
  description: '',
  workflow_json: '',
  is_default: false,
  positive_node_id: '',
  positive_input_name: 'text',
  negative_node_id: '',
  negative_input_name: '',
  seed_node_id: '',
  seed_input_name: '',
})

const selectedProject = computed(
  () => projects.value.find((project) => project.id === selectedProjectId.value) ?? null,
)
const sortedPages = computed(() => [...pages.value].sort((left, right) => left.page_no - right.page_no))
const canGenerate = computed(
  () => selectedTaskId.value !== null && selectedWorkflowId.value !== null && !generating.value,
)

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
  workflowForm.description = ''
  workflowForm.workflow_json = ''
  workflowForm.is_default = false
  workflowForm.positive_node_id = ''
  workflowForm.positive_input_name = 'text'
  workflowForm.negative_node_id = ''
  workflowForm.negative_input_name = ''
  workflowForm.seed_node_id = ''
  workflowForm.seed_input_name = ''
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

const parsePositiveNodeFromTextarea = () => {
  const workflow = parseWorkflowJson(workflowForm.workflow_json)
  if (workflow !== null) {
    applyPositivePromptCandidate(workflow)
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
    applyPositivePromptCandidate(workflow)
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

const workflowPayload = () => ({
  name: workflowForm.name.trim(),
  description: workflowForm.description.trim() || null,
  workflow_json: workflowForm.workflow_json.trim(),
  is_default: workflowForm.is_default,
  positive_node_id: workflowForm.positive_node_id.trim(),
  positive_input_name: workflowForm.positive_input_name.trim(),
  negative_node_id: workflowForm.negative_node_id.trim() || null,
  negative_input_name: workflowForm.negative_input_name.trim() || null,
  seed_node_id: workflowForm.seed_node_id.trim() || null,
  seed_input_name: workflowForm.seed_input_name.trim() || null,
})

const streamPayload = () => ({
  workflow_preset_id: selectedWorkflowId.value ?? 0,
  poll_interval_seconds: generationForm.poll_interval_seconds,
  candidates_per_page: generationForm.candidates_per_page,
  negative_prompt: generationForm.negative_prompt.trim() || null,
})

const loadProjects = async () => {
  projects.value = await listProjects()
  if (selectedProjectId.value === null) {
    selectedProjectId.value = projects.value[0]?.id ?? null
  }
}

const loadWorkflows = async () => {
  workflows.value = await listComfyWorkflows()
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
    tasks.value = await listCompletedScriptTasks(selectedProjectId.value)
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
    pages.value = await listImageGenerationPages(selectedTaskId.value)
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
  workflowDialogVisible.value = true
}

const openEditWorkflow = (workflow: ComfyWorkflowPreset) => {
  workflowDialogMode.value = 'edit'
  editingWorkflowId.value = workflow.id
  workflowForm.name = workflow.name
  workflowForm.description = workflow.description ?? ''
  workflowForm.workflow_json = workflow.workflow_json
  workflowForm.is_default = workflow.is_default
  workflowForm.positive_node_id = workflow.positive_node_id
  workflowForm.positive_input_name = workflow.positive_input_name
  workflowForm.negative_node_id = workflow.negative_node_id ?? ''
  workflowForm.negative_input_name = workflow.negative_input_name ?? ''
  workflowForm.seed_node_id = workflow.seed_node_id ?? ''
  workflowForm.seed_input_name = workflow.seed_input_name ?? ''
  workflowDialogVisible.value = true
}

const saveWorkflow = async () => {
  const payload = workflowPayload()
  if (!payload.name || !payload.workflow_json || !payload.positive_node_id || !payload.positive_input_name) {
    ElMessage.warning(t('imageGeneration.errors.emptyWorkflow'))
    return
  }
  try {
    if (workflowDialogMode.value === 'create' || editingWorkflowId.value === null) {
      await createComfyWorkflow(payload)
    } else {
      await updateComfyWorkflow(editingWorkflowId.value, payload)
    }
    workflowDialogVisible.value = false
    await loadWorkflows()
    ElMessage.success(t('imageGeneration.messages.workflowSaved'))
  } catch {
    ElMessage.error(t('imageGeneration.errors.saveWorkflowFailed'))
  }
}

const removeWorkflow = async (workflow: ComfyWorkflowPreset) => {
  try {
    await ElMessageBox.confirm(
      t('imageGeneration.messages.deleteWorkflowConfirm', { name: workflow.name }),
      t('imageGeneration.actions.deleteWorkflow'),
      { type: 'warning' },
    )
    await deleteComfyWorkflow(workflow.id)
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

const generatePage = async (page: ImageGenerationPage) => {
  if (selectedWorkflowId.value === null) {
    ElMessage.warning(t('imageGeneration.errors.selectWorkflow'))
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

watch(selectedProjectId, () => {
  pages.value = []
  void loadTasks()
})

watch(selectedTaskId, () => {
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
              <el-option v-for="workflow in workflows" :key="workflow.id" :label="workflow.name" :value="workflow.id" />
            </el-select>
          </el-form-item>
          <div class="generation-config__numbers">
            <el-form-item :label="t('imageGeneration.generation.pollInterval')">
              <el-input-number v-model="generationForm.poll_interval_seconds" :min="0.5" :max="20" :step="0.5" />
            </el-form-item>
            <el-form-item :label="t('imageGeneration.generation.candidates')">
              <el-input-number v-model="generationForm.candidates_per_page" :min="1" :max="4" />
            </el-form-item>
          </div>
          <el-form-item :label="t('imageGeneration.generation.negativePrompt')">
            <el-input v-model="generationForm.negative_prompt" type="textarea" :rows="4" />
          </el-form-item>
        </el-form>

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
            v-if="generating"
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
              <strong>{{ workflow.name }}</strong>
              <el-tag v-if="workflow.is_default" type="success" effect="plain">
                {{ t('imageGeneration.workflows.default') }}
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
              {{ shortText(row.image_prompt) }}
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
              <el-button link type="primary" :disabled="generating || !row.image_prompt" @click="generatePage(row)">
                {{ t('imageGeneration.actions.generatePage') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <el-dialog v-model="workflowDialogVisible" :title="t('imageGeneration.workflows.editorTitle')" width="920px">
      <el-form label-position="top">
        <el-form-item :label="t('imageGeneration.workflows.name')">
          <el-input v-model="workflowForm.name" />
        </el-form-item>
        <el-form-item :label="t('imageGeneration.workflows.descriptionLabel')">
          <el-input v-model="workflowForm.description" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="workflowForm.is_default">
            {{ t('imageGeneration.workflows.default') }}
          </el-checkbox>
        </el-form-item>
        <div class="workflow-node-grid">
          <el-form-item :label="t('imageGeneration.workflows.positiveNode')">
            <el-input v-model="workflowForm.positive_node_id" />
          </el-form-item>
          <el-form-item :label="t('imageGeneration.workflows.positiveInput')">
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
        <el-form-item :label="t('imageGeneration.workflows.workflowJson')">
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
              <div class="workflow-upload__text">{{ t('imageGeneration.workflows.uploadHint') }}</div>
            </el-upload>
            <el-button :icon="Search" @click="parsePositiveNodeFromTextarea">
              {{ t('imageGeneration.actions.parsePositiveNode') }}
            </el-button>
          </div>
          <el-input v-model="workflowForm.workflow_json" type="textarea" :rows="18" resize="none" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="workflowDialogVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" @click="saveWorkflow">{{ t('projects.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="t('imageGeneration.detail.title')" width="760px">
      <el-image v-if="detailImage?.image_url" :src="detailImage.image_url" fit="contain" class="detail-image" />
      <pre class="image-meta">{{ detailImage }}</pre>
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
.workflow-node-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.workflow-json-tools {
  display: grid;
  gap: 12px;
  width: 100%;
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
  width: 100%;
  max-height: 520px;
}

.image-meta {
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1180px) {
  .image-generation-grid,
  .generation-config__numbers,
  .workflow-node-grid {
    grid-template-columns: 1fr;
  }
}
</style>

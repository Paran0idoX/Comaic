<script setup lang="ts">
import { Delete, Document, EditPen, Plus, Refresh, Tickets, VideoPause, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { listProjects, type Project } from '@/api/projects'
import { resolveOutlineSession, type OutlineVersion } from '@/api/outline'
import {
  clearPageScript,
  createPageScript,
  deleteAllProjectPages,
  deleteScriptTaskSections,
  generateSinglePageScript,
  listProjectPages,
  suspendScriptTask,
  streamBatchScriptGeneration,
  updatePageScript,
  type ScriptPage,
} from '@/api/scripts'

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
const pages = ref<ScriptPage[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedOutlineVersionId = ref<number | null>(null)
const currentTaskId = ref<number | null>(null)
const totalPages = ref(12)
const singlePageNo = ref(1)
const userRequirement = ref('')
const progressEvents = ref<ProgressEvent[]>([])
const selectedPage = ref<ScriptPage | null>(null)
const detailVisible = ref(false)
const scriptDialogVisible = ref(false)
const scriptDialogMode = ref<'create' | 'edit'>('create')
const scriptFormPageNo = ref(1)
const scriptFormContent = ref('')
const savingScript = ref(false)

const loadingProjects = ref(false)
const loadingOutlineVersions = ref(false)
const loadingPages = ref(false)
const generatingSingle = ref(false)
const generatingBatch = ref(false)
const suspendingBatch = ref(false)
const needsOutline = ref(false)
const eventSequence = ref(1)

const selectedProject = computed(() =>
  projects.value.find((project) => project.id === selectedProjectId.value),
)

const sortedPages = computed(() =>
  [...pages.value].sort((left, right) => left.page_no - right.page_no),
)

const canGenerate = computed(
  () =>
    selectedProjectId.value !== null &&
    selectedOutlineVersionId.value !== null &&
    !needsOutline.value &&
    !generatingSingle.value &&
    !generatingBatch.value,
)

const generationDisabled = computed(() => !canGenerate.value)
const canEditScripts = computed(
  () => selectedProjectId.value !== null && !generatingSingle.value && !generatingBatch.value,
)
const canDeleteAllScripts = computed(() => canEditScripts.value && pages.value.length > 0)

const formatDateTime = (value: string) => {
  if (!value) {
    return '-'
  }

  return new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

const nowLabel = () =>
  new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date())

// 脚本表格只展示摘要，完整脚本通过详情弹窗查看，避免表格被长文本撑开。
const scriptSummary = (script: string | null) => {
  if (!script) {
    return t('scripts.pages.noScript')
  }

  const compact = script.replace(/\s+/g, ' ').trim()
  return compact.length > 86 ? `${compact.slice(0, 86)}...` : compact
}

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
  `v${version.version_no} · ${outlineStatusLabel(version.status)} · ${formatDateTime(version.created_at)}`

// SSE 事件数据来源不完全一致，这里统一提取最有用的信息写入时间线。
const describePayload = (event: string, payload: Record<string, unknown>) => {
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
    return String(payload.message ?? payload.result ?? payload.comment ?? t('scripts.events.reviewDone'))
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
  const index = pages.value.findIndex((item) => item.id === page.id || item.page_no === page.page_no)
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
  if (selectedProjectId.value === null) {
    pages.value = []
    return
  }

  loadingPages.value = true
  try {
    pages.value = await listProjectPages(selectedProjectId.value)
  } catch {
    ElMessage.error(t('scripts.errors.loadPages'))
  } finally {
    loadingPages.value = false
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

const isOutlineMissingError = (message: string) => {
  const normalized = message.toLowerCase()
  return normalized.includes('outline') && (normalized.includes('active') || normalized.includes('not found'))
}

const handleGenerationError = (message: string, fallback: string) => {
  if (isOutlineMissingError(message)) {
    needsOutline.value = true
    addProgressEvent('missing_outline', { message: t('scripts.needsOutline.description') })
    ElMessage.warning(t('scripts.needsOutline.title'))
    return
  }

  addProgressEvent('error', { message: message || fallback })
  ElMessage.error(fallback)
}

const validateGenerationInput = () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return false
  }

  if (selectedOutlineVersionId.value === null) {
    ElMessage.warning(t('scripts.errors.selectOutlineVersion'))
    return false
  }

  if (singlePageNo.value < 1 || singlePageNo.value > totalPages.value) {
    ElMessage.warning(t('scripts.errors.invalidPageRange'))
    return false
  }

  return true
}

const generateSingle = async () => {
  if (
    !validateGenerationInput() ||
    selectedProjectId.value === null ||
    selectedOutlineVersionId.value === null
  ) {
    return
  }

  generatingSingle.value = true
  needsOutline.value = false
  try {
    const result = await generateSinglePageScript({
      project_id: selectedProjectId.value,
      page_no: singlePageNo.value,
      total_pages: totalPages.value,
      outline_version_id: selectedOutlineVersionId.value,
      user_requirement: userRequirement.value.trim() || undefined,
    })

    addProgressEvent('single_done', {
      page_no: result.page_no,
      task_id: result.task_id,
      status: result.status,
    })
    currentTaskId.value = result.task_id
    ElMessage.success(t('scripts.messages.singleSuccess'))
    await loadPages()
  } catch (error) {
    handleGenerationError(error instanceof Error ? error.message : '', t('scripts.errors.singleFailed'))
  } finally {
    generatingSingle.value = false
  }
}

const generateBatch = async () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return
  }
  if (selectedOutlineVersionId.value === null) {
    ElMessage.warning(t('scripts.errors.selectOutlineVersion'))
    return
  }

  generatingBatch.value = true
  needsOutline.value = false
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
          }
          if (event === 'done') {
            void loadPages()
          }
          if (event === 'done') {
            ElMessage.success(t('scripts.messages.batchSuccess'))
          }
          if (event === 'suspended') {
            generatingBatch.value = false
            suspendingBatch.value = false
            ElMessage.warning(t('scripts.messages.batchSuspended'))
          }
        },
        onError: (message) => {
          handleGenerationError(message, t('scripts.errors.batchFailed'))
        },
      },
    )
  } catch (error) {
    handleGenerationError(error instanceof Error ? error.message : '', t('scripts.errors.batchFailed'))
  } finally {
    generatingBatch.value = false
    suspendingBatch.value = false
  }
}

const suspendBatch = async () => {
  if (currentTaskId.value === null) {
    ElMessage.warning(t('scripts.errors.noCurrentBatchTask'))
    return
  }

  suspendingBatch.value = true
  try {
    await suspendScriptTask(currentTaskId.value)
    ElMessage.info(t('scripts.messages.suspendRequested'))
  } catch {
    suspendingBatch.value = false
    ElMessage.error(t('scripts.errors.suspendFailed'))
  }
}

const refreshCurrentProject = async () => {
  await loadPages()
  addProgressEvent('refreshed', { message: t('scripts.events.refreshed') })
}

const openDetail = (page: ScriptPage) => {
  selectedPage.value = page
  detailVisible.value = true
}

const openCreateScript = () => {
  scriptDialogMode.value = 'create'
  scriptFormPageNo.value = singlePageNo.value
  scriptFormContent.value = ''
  scriptDialogVisible.value = true
}

const openEditScript = (page: ScriptPage) => {
  scriptDialogMode.value = 'edit'
  scriptFormPageNo.value = page.page_no
  scriptFormContent.value = page.script ?? ''
  scriptDialogVisible.value = true
}

const saveManualScript = async () => {
  if (selectedProjectId.value === null) {
    ElMessage.warning(t('scripts.errors.selectProject'))
    return
  }
  const content = scriptFormContent.value.trim()
  if (!content) {
    ElMessage.warning(t('scripts.errors.emptyScript'))
    return
  }

  savingScript.value = true
  try {
    const page =
      scriptDialogMode.value === 'create'
        ? await createPageScript(selectedProjectId.value, {
            page_no: scriptFormPageNo.value,
            script: content,
          })
        : await updatePageScript(selectedProjectId.value, scriptFormPageNo.value, {
            script: content,
          })
    upsertPageInList(page)
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
    const nextPage = await clearPageScript(selectedProjectId.value, page.page_no)
    upsertPageInList(nextPage)
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
    pages.value = await deleteAllProjectPages(selectedProjectId.value)
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
  if (currentTaskId.value === null) {
    ElMessage.warning(t('scripts.errors.noCurrentTask'))
    return
  }

  const taskId = currentTaskId.value
  try {
    await ElMessageBox.confirm(
      t('scripts.messages.deleteTaskSectionsConfirm', { taskId }),
      t('scripts.actions.deleteTaskSections'),
      {
        type: 'warning',
        confirmButtonText: t('scripts.actions.deleteTaskSections'),
        cancelButtonText: t('projects.cancel'),
      },
    )
    await deleteScriptTaskSections(taskId)
    pages.value = pages.value.filter((page) => page.task_id !== taskId)
    selectedPage.value = selectedPage.value?.task_id === taskId ? null : selectedPage.value
    if (selectedPage.value === null) {
      detailVisible.value = false
    }
    currentTaskId.value = null
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
    outlineVersions.value = []
    selectedOutlineVersionId.value = null
    currentTaskId.value = null
    return
  }

  selectedOutlineVersionId.value = null
  currentTaskId.value = null
  await loadOutlineVersions(projectId)
  await loadPages()
  syncProjectQuery()
})

watch(selectedOutlineVersionId, () => {
  syncProjectQuery()
})

watch(progressEvents, async () => {
  await nextTick()
})

onMounted(async () => {
  await loadProjects()
})
</script>

<template>
  <section class="script-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ t('scripts.title') }}</h1>
        <p class="page-subtitle">{{ t('scripts.subtitle') }}</p>
      </div>
      <el-button :icon="Refresh" :loading="loadingPages" @click="refreshCurrentProject">
        {{ t('scripts.refresh') }}
      </el-button>
    </div>

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
        <el-button size="small" type="warning" plain @click="goOutline">
          {{ t('scripts.needsOutline.action') }}
        </el-button>
      </template>
    </el-alert>

    <div class="script-workspace">
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

          <div class="script-config__numbers">
            <el-form-item :label="t('scripts.config.totalPages')">
              <el-input-number v-model="totalPages" :min="1" :max="300" />
            </el-form-item>
            <el-form-item :label="t('scripts.config.singlePageNo')">
              <el-input-number v-model="singlePageNo" :min="1" :max="totalPages" />
            </el-form-item>
          </div>

          <el-form-item :label="t('scripts.config.requirement')">
            <el-input
              v-model="userRequirement"
              type="textarea"
              :rows="5"
              :placeholder="t('scripts.config.requirementPlaceholder')"
            />
          </el-form-item>
        </el-form>

        <div class="script-config__actions">
          <el-button
            type="primary"
            :icon="Document"
            :loading="generatingSingle"
            :disabled="generationDisabled || generatingBatch"
            @click="generateSingle"
          >
            {{ t('scripts.actions.generateSingle') }}
          </el-button>
          <el-button
            type="success"
            :icon="Tickets"
            :loading="generatingBatch"
            :disabled="!canGenerate"
            @click="generateBatch"
          >
            {{ t('scripts.actions.generateBatch') }}
          </el-button>
          <el-button
            v-if="generatingBatch"
            type="warning"
            :icon="VideoPause"
            :loading="suspendingBatch"
            :disabled="currentTaskId === null || suspendingBatch"
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
          <el-button text :icon="Refresh" :loading="loadingPages" @click="loadPages">
            {{ t('scripts.refresh') }}
          </el-button>
          <el-button type="primary" :icon="Plus" :disabled="!canEditScripts" @click="openCreateScript">
            {{ t('scripts.actions.addScript') }}
          </el-button>
          <el-button
            type="danger"
            plain
            :icon="Delete"
            @click="deleteCurrentTaskSections"
          >
            {{ t('scripts.actions.deleteTaskSections') }}
          </el-button>
          <el-button type="danger" plain :icon="Delete" :disabled="!canDeleteAllScripts" @click="deleteAllScripts">
            {{ t('scripts.actions.deleteAllScripts') }}
          </el-button>
        </div>

        <el-table
          v-loading="loadingPages"
          :data="sortedPages"
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
              <span class="script-results__summary">{{ scriptSummary(row.script) }}</span>
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

    <el-dialog
      v-model="detailVisible"
      :title="`${t('scripts.detail.title')} ${selectedPage?.page_no ?? ''}`"
      width="720px"
    >
      <pre class="script-detail">{{ selectedPage?.script || t('scripts.pages.noScript') }}</pre>
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
        <el-form-item :label="t('scripts.config.singlePageNo')">
          <el-input-number
            v-model="scriptFormPageNo"
            :min="1"
            :max="totalPages"
            :disabled="scriptDialogMode === 'edit'"
          />
        </el-form-item>
        <el-form-item :label="t('scripts.editor.scriptContent')">
          <el-input
            v-model="scriptFormContent"
            type="textarea"
            :rows="12"
            :placeholder="t('scripts.editor.scriptPlaceholder')"
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
  grid-template-columns: minmax(280px, 0.82fr) minmax(300px, 0.9fr) minmax(430px, 1.35fr);
  gap: 18px;
  align-items: start;
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

.script-progress__scroll {
  height: 560px;
  padding: 18px 22px 8px;
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
  max-height: 58vh;
  margin: 0;
  padding: 16px;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #f8fafc;
  color: #1f2937;
  font-family:
    ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 1320px) {
  .script-workspace {
    grid-template-columns: minmax(300px, 0.8fr) minmax(420px, 1.2fr);
  }

  .script-results {
    grid-column: 1 / -1;
  }
}

@media (max-width: 860px) {
  .script-workspace {
    grid-template-columns: 1fr;
  }

  .script-config__numbers {
    grid-template-columns: 1fr;
  }

  .script-progress__scroll {
    height: 420px;
  }
}
</style>

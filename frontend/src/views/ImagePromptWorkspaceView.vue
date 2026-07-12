<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CopyDocument, Delete, EditPen, MagicStick, Plus, Refresh, View } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import {
  IMAGE_PROMPT_PRESET_KINDS,
  createImagePromptPreset,
  deleteImagePromptPreset,
  generateImagePromptForPage,
  listCompletedScriptTasks,
  listImagePromptPresets,
  listScriptTaskImagePrompts,
  streamGenerateImagePromptsForTask,
  updateImagePromptPreset,
  type GenerateImagePromptsResponse,
  type ImagePromptGenerationItem,
  type ImagePromptPreset,
  type ImagePromptPresetKind,
} from '@/api/imagePrompts'
import { apiErrorMessage } from '@/api/errors'
import { listProjects, type Project } from '@/api/projects'
import type { ScriptTask } from '@/api/scripts'
import { formatLocalDateTime } from '@/utils/datetime'

const { locale, t } = useI18n()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const presets = ref<ImagePromptPreset[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedTaskId = ref<number | null>(null)
const selectedSystemPresetId = ref<number | null>(null)
const activePresetKind = ref<ImagePromptPresetKind>(IMAGE_PROMPT_PRESET_KINDS.system)
const loading = ref(false)
const loadingTasks = ref(false)
const loadingPrompts = ref(false)
const generating = ref(false)
const concurrency = ref(20)
const generationResult = ref<GenerateImagePromptsResponse | null>(null)
const detailItem = ref<ImagePromptGenerationItem | null>(null)
const detailVisible = ref(false)
const editorVisible = ref(false)
const editingPresetId = ref<number | null>(null)
const historyLoadedAt = ref<string | null>(null)
const retryingPageIds = ref<Set<number>>(new Set())

const presetForm = reactive({
  name: '',
  description: '',
  content: '',
  is_default: false,
})

const systemPresets = computed(() =>
  presets.value.filter((preset) => preset.kind === IMAGE_PROMPT_PRESET_KINDS.system),
)
const currentKindPresets = computed(() =>
  presets.value.filter((preset) => preset.kind === activePresetKind.value),
)
const selectedProject = computed(
  () => projects.value.find((project) => project.id === selectedProjectId.value) ?? null,
)
const renderedPresetContent = computed(() => markdown.render(presetForm.content || ''))
const sortedGenerationItems = computed(() =>
  [...(generationResult.value?.items ?? [])].sort((left, right) => left.page_no - right.page_no),
)
const completedCount = computed(() =>
  generationResult.value === null ? 0 : generationResult.value.succeeded + generationResult.value.failed,
)
const progressPercentage = computed(() => {
  if (generationResult.value === null || generationResult.value.total <= 0) {
    return 0
  }
  return Math.round((completedCount.value / generationResult.value.total) * 100)
})

const formatDate = (value: string) => {
  return formatLocalDateTime(value, locale.value)
}

const taskLabel = (task: ScriptTask) =>
  `#${task.id} · ${task.mode} · ${task.total_pages} ${t('prompts.generation.pagesUnit')} · ${formatDate(task.updated_at)}`

const shortText = (value: string | null, maxLength = 120) => {
  if (!value) {
    return t('prompts.emptyText')
  }
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value
}

const itemErrorText = (item: ImagePromptGenerationItem | null) => {
  if (item?.error_code) {
    const key = `backendErrors.${item.error_code}`
    const translated = t(key)
    if (translated !== key) {
      return translated
    }
  }
  return item?.error ?? ''
}

const ensureSelectedPresets = () => {
  const defaultSystem = systemPresets.value.find((preset) => preset.is_default) ?? systemPresets.value[0]
  if (selectedSystemPresetId.value === null && defaultSystem !== undefined) {
    selectedSystemPresetId.value = defaultSystem.id
  }
}

const loadProjects = async () => {
  projects.value = await listProjects()
  const firstProject = projects.value[0]
  if (selectedProjectId.value === null && firstProject !== undefined) {
    selectedProjectId.value = firstProject.id
  }
}

const loadPresets = async () => {
  presets.value = await listImagePromptPresets()
  ensureSelectedPresets()
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
    const nextTaskId = tasks.value[0]?.id ?? null
    if (selectedTaskId.value === nextTaskId) {
      await loadTaskPrompts()
    } else {
      selectedTaskId.value = nextTaskId
    }
  } finally {
    loadingTasks.value = false
  }
}

const loadTaskPrompts = async () => {
  if (selectedTaskId.value === null) {
    generationResult.value = null
    historyLoadedAt.value = null
    return
  }
  loadingPrompts.value = true
  try {
    generationResult.value = await listScriptTaskImagePrompts(selectedTaskId.value)
    historyLoadedAt.value = formatDate(new Date().toISOString())
  } catch {
    generationResult.value = null
    historyLoadedAt.value = null
    ElMessage.error(t('prompts.errors.loadTaskPromptsFailed'))
  } finally {
    loadingPrompts.value = false
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([loadProjects(), loadPresets()])
    await loadTasks()
  } catch {
    ElMessage.error(t('prompts.errors.loadFailed'))
  } finally {
    loading.value = false
  }
}

watch(selectedProjectId, () => {
  generationResult.value = null
  void loadTasks()
})

watch(selectedTaskId, () => {
  void loadTaskPrompts()
})

watch(presets, ensureSelectedPresets)

const openCreatePreset = () => {
  editingPresetId.value = null
  presetForm.name = ''
  presetForm.description = ''
  presetForm.content = ''
  presetForm.is_default = false
  editorVisible.value = true
}

const openEditPreset = (preset: ImagePromptPreset) => {
  editingPresetId.value = preset.id
  activePresetKind.value = preset.kind
  presetForm.name = preset.name
  presetForm.description = preset.description ?? ''
  presetForm.content = preset.content
  presetForm.is_default = preset.is_default
  editorVisible.value = true
}

const savePreset = async () => {
  if (!presetForm.name.trim() || !presetForm.content.trim()) {
    ElMessage.warning(t('prompts.errors.emptyPreset'))
    return
  }
  const payload = {
    name: presetForm.name.trim(),
    description: presetForm.description.trim() || null,
    kind: activePresetKind.value,
    content: presetForm.content.trim(),
    is_default: presetForm.is_default,
  }
  try {
    if (editingPresetId.value === null) {
      await createImagePromptPreset(payload)
    } else {
      await updateImagePromptPreset(editingPresetId.value, payload)
    }
    editorVisible.value = false
    await loadPresets()
    ElMessage.success(t('prompts.messages.presetSaved'))
  } catch {
    ElMessage.error(t('prompts.errors.savePresetFailed'))
  }
}

const removePreset = async (preset: ImagePromptPreset) => {
  try {
    await ElMessageBox.confirm(
      t('prompts.messages.deletePresetConfirm', { name: preset.name }),
      t('prompts.actions.deletePreset'),
      { type: 'warning' },
    )
    await deleteImagePromptPreset(preset.id)
    if (selectedSystemPresetId.value === preset.id) {
      selectedSystemPresetId.value = null
    }
    await loadPresets()
    ElMessage.success(t('prompts.messages.presetDeleted'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(t('prompts.errors.deletePresetFailed'))
    }
  }
}

const numberFromPayload = (payload: Record<string, unknown>, key: string, fallback = 0) => {
  const value = payload[key]
  return typeof value === 'number' ? value : fallback
}

const stringFromPayload = (payload: Record<string, unknown>, key: string) => {
  const value = payload[key]
  return typeof value === 'string' ? value : null
}

const refreshGenerationCounters = () => {
  if (generationResult.value === null) {
    return
  }
  generationResult.value.succeeded = generationResult.value.items.filter((item) => item.image_prompt).length
  generationResult.value.failed = generationResult.value.items.filter((item) => item.error).length
}

const upsertGenerationItem = (item: ImagePromptGenerationItem) => {
  if (generationResult.value === null) {
    return
  }
  const items = generationResult.value.items
  const index = items.findIndex((current) => current.page_id === item.page_id)
  if (index >= 0) {
    items[index] = item
  } else {
    items.push(item)
  }
  items.sort((left, right) => left.page_no - right.page_no)
  refreshGenerationCounters()
}

const isRetryingPage = (pageId: number) => retryingPageIds.value.has(pageId)

const setRetryingPage = (pageId: number, value: boolean) => {
  const next = new Set(retryingPageIds.value)
  if (value) {
    next.add(pageId)
  } else {
    next.delete(pageId)
  }
  retryingPageIds.value = next
}

const retryPagePrompt = async (item: ImagePromptGenerationItem) => {
  if (selectedSystemPresetId.value === null) {
    ElMessage.warning(t('prompts.errors.selectSystemPreset'))
    return
  }
  setRetryingPage(item.page_id, true)
  try {
    const updated = await generateImagePromptForPage(item.page_id, {
      system_prompt_preset_id: selectedSystemPresetId.value,
      concurrency: 1,
    })
    upsertGenerationItem(updated)
    ElMessage.success(t('prompts.messages.pageRetrySucceeded'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('prompts.errors.pageRetryFailed')))
  } finally {
    setRetryingPage(item.page_id, false)
  }
}

const generatePrompts = async () => {
  if (selectedTaskId.value === null) {
    ElMessage.warning(t('prompts.errors.selectTask'))
    return
  }
  if (selectedSystemPresetId.value === null) {
    ElMessage.warning(t('prompts.errors.selectSystemPreset'))
    return
  }
  const hasExistingPrompts = generationResult.value?.items.some((item) => item.image_prompt) ?? false
  if (hasExistingPrompts) {
    try {
      await ElMessageBox.confirm(
        t('prompts.messages.regenerateConfirm'),
        t('prompts.actions.generate'),
        { type: 'warning' },
      )
    } catch (error) {
      if (error === 'cancel' || error === 'close') {
        return
      }
      throw error
    }
  }
  generating.value = true
  let streamFailed = false
  try {
    await streamGenerateImagePromptsForTask(
      selectedTaskId.value,
      {
        system_prompt_preset_id: selectedSystemPresetId.value,
        concurrency: concurrency.value,
      },
      {
        onEvent: (event, payload) => {
          if (event === 'start') {
            historyLoadedAt.value = null
            generationResult.value = {
              task_id: numberFromPayload(payload, 'task_id', selectedTaskId.value ?? 0),
              total: numberFromPayload(payload, 'total'),
              succeeded: 0,
              failed: 0,
              items: [],
            }
            return
          }
          if (event === 'page_prompt') {
            upsertGenerationItem({
              page_id: numberFromPayload(payload, 'page_id'),
              page_no: numberFromPayload(payload, 'page_no'),
              image_prompt: stringFromPayload(payload, 'image_prompt'),
              status: stringFromPayload(payload, 'status') ?? '',
              scene_key: stringFromPayload(payload, 'scene_key'),
              character_keys: Array.isArray(payload.character_keys)
                ? (payload.character_keys as string[])
                : [],
              error: stringFromPayload(payload, 'error'),
              error_code: stringFromPayload(payload, 'error_code'),
            })
            return
          }
          if (event === 'progress' && generationResult.value !== null) {
            generationResult.value.succeeded = numberFromPayload(payload, 'succeeded')
            generationResult.value.failed = numberFromPayload(payload, 'failed')
            generationResult.value.total = numberFromPayload(payload, 'total')
            return
          }
          if (event === 'done' && generationResult.value !== null) {
            generationResult.value.succeeded = numberFromPayload(payload, 'succeeded')
            generationResult.value.failed = numberFromPayload(payload, 'failed')
            generationResult.value.total = numberFromPayload(payload, 'total')
          }
        },
        onError: (error) => {
          streamFailed = true
          ElMessage.error(apiErrorMessage(error, t, t('prompts.errors.generateFailed')))
        },
      },
    )
    if (!streamFailed) {
      ElMessage.success(t('prompts.messages.generated'))
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('prompts.errors.generateFailed')))
  } finally {
    generating.value = false
  }
}

const openDetail = (item: ImagePromptGenerationItem) => {
  detailItem.value = item
  detailVisible.value = true
}

const copyDetailPrompt = async () => {
  const text = itemErrorText(detailItem.value) || detailItem.value?.image_prompt || ''
  if (!text) {
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(t('prompts.messages.copied'))
  } catch {
    ElMessage.error(t('prompts.errors.copyFailed'))
  }
}

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <section v-loading="loading" class="prompt-page">
    <div class="prompt-grid">
      <section class="panel generation-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('prompts.generation.title') }}</h2>
            <p>{{ t('prompts.generation.description') }}</p>
          </div>
          <el-button
            class="ai-gradient-button"
            type="primary"
            :icon="MagicStick"
            :loading="generating"
            :disabled="generating || loadingPrompts || selectedTaskId === null || selectedSystemPresetId === null"
            @click="generatePrompts"
          >
            {{ t('prompts.actions.generate') }}
          </el-button>
        </header>

        <div class="generation-form">
          <el-form label-position="top">
            <el-form-item :label="t('prompts.generation.project')">
              <el-select v-model="selectedProjectId" :disabled="generating" filterable>
                <el-option
                  v-for="project in projects"
                  :key="project.id"
                  :label="project.title"
                  :value="project.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('prompts.generation.scriptTask')">
              <el-select v-model="selectedTaskId" :loading="loadingTasks" :disabled="generating" filterable>
                <el-option
                  v-for="task in tasks"
                  :key="task.id"
                  :label="taskLabel(task)"
                  :value="task.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('prompts.generation.systemPreset')">
              <el-select v-model="selectedSystemPresetId" :disabled="generating" filterable>
                <el-option
                  v-for="preset in systemPresets"
                  :key="preset.id"
                  :label="preset.name"
                  :value="preset.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('prompts.generation.concurrency')">
              <el-input-number v-model="concurrency" :min="1" :max="50" :disabled="generating" />
            </el-form-item>
          </el-form>

          <el-alert
            v-if="tasks.length === 0 && selectedProject !== null"
            type="info"
            :closable="false"
            :title="t('prompts.generation.emptyTasks')"
          />
        </div>

        <el-divider />

        <div v-if="generationResult !== null" class="generation-progress">
          <div class="generation-progress__header">
            <strong>
              {{
                t('prompts.messages.generatingProgress', {
                  completed: completedCount,
                  total: generationResult.total,
                })
              }}
            </strong>
            <span v-if="historyLoadedAt && !generating">
              {{ t('prompts.messages.historyLoadedAt', { time: historyLoadedAt }) }}
            </span>
          </div>
          <el-progress :percentage="progressPercentage" :status="generationResult.failed > 0 ? 'exception' : undefined" />
        </div>

        <div class="result-summary">
          <el-statistic
            :title="t('prompts.result.total')"
            :value="generationResult?.total ?? 0"
          />
          <el-statistic
            :title="t('prompts.result.succeeded')"
            :value="generationResult?.succeeded ?? 0"
          />
          <el-statistic
            :title="t('prompts.result.failed')"
            :value="generationResult?.failed ?? 0"
          />
        </div>
        <el-table
          v-loading="loadingPrompts"
          :data="sortedGenerationItems"
          class="result-table"
          height="360"
        >
          <el-table-column prop="page_no" :label="t('prompts.result.pageNo')" width="86" />
          <el-table-column :label="t('prompts.result.status')" width="110">
            <template #default="{ row }">
              <el-tag :type="row.error ? 'danger' : row.image_prompt ? 'success' : 'info'" effect="plain">
                {{
                  row.error
                    ? t('prompts.result.failed')
                    : row.image_prompt
                      ? t('prompts.result.succeeded')
                      : t('prompts.result.notGenerated')
                }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column :label="t('prompts.result.scene')" width="140">
            <template #default="{ row }">
              {{ row.scene_key || '-' }}
            </template>
          </el-table-column>
          <el-table-column :label="t('prompts.result.characters')" width="180">
            <template #default="{ row }">
              {{ row.character_keys?.join(', ') || '-' }}
            </template>
          </el-table-column>
          <el-table-column :label="t('prompts.result.prompt')" min-width="260">
            <template #default="{ row }">
              {{ shortText(row.image_prompt) }}
            </template>
          </el-table-column>
          <el-table-column :label="t('prompts.result.actions')" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :icon="View" @click="openDetail(row)">
                {{ t('prompts.actions.view') }}
              </el-button>
              <el-button
                v-if="row.error"
                link
                type="warning"
                :icon="Refresh"
                :loading="isRetryingPage(row.page_id)"
                :disabled="generating || selectedSystemPresetId === null"
                @click="retryPagePrompt(row)"
              >
                {{ t('prompts.actions.retryPage') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>

      <section class="panel preset-panel">
        <header class="panel-header">
          <div>
            <h2>{{ t('prompts.presets.title') }}</h2>
            <p>{{ t('prompts.presets.description') }}</p>
          </div>
          <el-button type="primary" plain :icon="Plus" @click="openCreatePreset">
            {{ t('prompts.actions.addPreset') }}
          </el-button>
        </header>

        <el-tabs v-model="activePresetKind">
          <el-tab-pane
            :label="t('prompts.presets.systemPrompt')"
            :name="IMAGE_PROMPT_PRESET_KINDS.system"
          />
          <el-tab-pane
            :label="t('prompts.presets.shotPlannerPrompt')"
            :name="IMAGE_PROMPT_PRESET_KINDS.shot"
          />
          <el-tab-pane
            :label="t('prompts.presets.negativePrompt')"
            :name="IMAGE_PROMPT_PRESET_KINDS.negative"
          />
        </el-tabs>

        <div class="preset-list">
          <article v-for="preset in currentKindPresets" :key="preset.id" class="preset-item">
            <div>
              <strong>{{ preset.name }}</strong>
              <el-tag v-if="preset.is_default" type="success" effect="plain">
                {{ t('prompts.presets.default') }}
              </el-tag>
              <p>{{ preset.description || t('prompts.emptyText') }}</p>
            </div>
            <div class="preset-actions">
              <el-button link type="primary" :icon="EditPen" @click="openEditPreset(preset)">
                {{ t('prompts.actions.editPreset') }}
              </el-button>
              <el-button link type="danger" :icon="Delete" @click="removePreset(preset)">
                {{ t('prompts.actions.deletePreset') }}
              </el-button>
            </div>
          </article>
          <el-empty
            v-if="currentKindPresets.length === 0"
            :description="t('prompts.presets.empty')"
          />
        </div>
      </section>
    </div>

    <el-dialog v-model="editorVisible" :title="t('prompts.editor.title')" width="960px">
      <el-form label-position="top">
        <el-form-item :label="t('prompts.editor.name')">
          <el-input v-model="presetForm.name" />
        </el-form-item>
        <el-form-item :label="t('prompts.editor.description')">
          <el-input v-model="presetForm.description" />
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="presetForm.is_default">
            {{ t('prompts.editor.default') }}
          </el-checkbox>
        </el-form-item>
        <div class="editor-grid">
          <el-form-item :label="t('prompts.editor.content')">
            <el-input
              v-model="presetForm.content"
              type="textarea"
              :rows="18"
              resize="none"
            />
          </el-form-item>
          <div class="preview-pane">
            <strong>{{ t('prompts.editor.preview') }}</strong>
            <el-scrollbar height="430px">
              <article class="markdown-body" v-html="renderedPresetContent" />
            </el-scrollbar>
          </div>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" @click="savePreset">{{ t('projects.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="t('prompts.detail.title')" width="760px">
      <div v-if="detailItem" class="prompt-detail-meta">
        <span>{{ t('prompts.result.scene') }}: {{ detailItem.scene_key || '-' }}</span>
        <span>
          {{ t('prompts.result.characters') }}:
          {{ detailItem.character_keys?.join(', ') || '-' }}
        </span>
      </div>
      <pre class="prompt-detail">{{ itemErrorText(detailItem) || detailItem?.image_prompt }}</pre>
      <template #footer>
        <el-button :icon="CopyDocument" @click="copyDetailPrompt">
          {{ t('prompts.actions.copy') }}
        </el-button>
        <el-button type="primary" @click="detailVisible = false">
          {{ t('prompts.actions.close') }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.prompt-page {
  display: grid;
  gap: 28px;
}

.page-header {
  display: flex;
  justify-content: flex-end;
  gap: 16px;
}

.panel-header h2,
.panel-header p {
  margin: 0;
}

.prompt-grid {
  display: grid;
  grid-template-columns: minmax(520px, 1.2fr) minmax(420px, 0.8fr);
  gap: 18px;
  align-items: start;
}

.panel {
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #ffffff;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 24px;
  border-bottom: 1px solid var(--panel-border);
}

.panel-header p {
  margin-top: 6px;
  color: var(--text-soft);
}

.generation-form,
.preset-list {
  padding: 20px 24px;
}

.result-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  padding: 0 24px 16px;
}

.result-table {
  width: 100%;
}

.generation-progress {
  padding: 0 24px 16px;
}

.generation-progress__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: var(--text-soft);
  font-size: 13px;
}

.generation-progress__header strong {
  color: var(--text-main);
}

.preset-list {
  display: grid;
  gap: 12px;
}

.preset-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
}

.preset-item strong {
  margin-right: 8px;
}

.preset-item p {
  margin: 8px 0 0;
  color: var(--text-soft);
}

.preset-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.editor-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.preview-pane {
  min-width: 0;
}

.markdown-body {
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  line-height: 1.7;
  overflow-wrap: anywhere;
}

.prompt-detail,
.detail :deep(pre) {
  white-space: pre-wrap;
  word-break: break-word;
}

.prompt-detail {
  margin: 0;
  line-height: 1.7;
}

.prompt-detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-bottom: 12px;
  color: var(--text-soft);
  font-size: 13px;
}

@media (max-width: 1180px) {
  .prompt-grid,
  .editor-grid {
    grid-template-columns: 1fr;
  }
}
</style>

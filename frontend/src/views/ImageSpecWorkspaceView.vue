<script setup lang="ts">
import { Delete, EditPen, MagicStick, Plus, Refresh, Setting, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

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
import { listProjects, type Project } from '@/api/projects'
import { listProjectScriptTasks, type ScriptTask } from '@/api/scripts'
import { listStyles, type StyleProfile } from '@/api/visualBible'
import { useProjectContextStore } from '@/stores/projectContext'

const { t } = useI18n()
const projectContext = useProjectContextStore()
const { selectedProjectId } = storeToRefs(projectContext)

const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const styles = ref<StyleProfile[]>([])
const presets = ref<ImageSpecPreset[]>([])
const specs = ref<ImageSpec[]>([])
const compilations = ref<ContinuityCompilation[]>([])
const specCompilations = ref<ImageSpecCompilation[]>([])
const selectedTaskId = ref<number | null>(null)
const selectedStyleId = ref<number | null>(null)
const shotPresetId = ref<number | null>(null)
const negativePresetId = ref<number | null>(null)
const generationMode = ref<'preview' | 'final'>('preview')
const concurrency = ref(8)
const regenerateContinuity = ref(false)
const compiling = ref(false)
const progressEvents = ref<Array<{ event: string; payload: Record<string, unknown> }>>([])

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
const latestSpecCompilation = computed(() => specCompilations.value[0] ?? null)
const shotPresets = computed(() =>
  presets.value.filter((item) => item.kind === 'shot_planner_system_prompt'),
)
const negativePresets = computed(() =>
  presets.value.filter((item) => item.kind === 'negative_prompt'),
)
const canCompile = computed(() => selectedTaskId.value !== null && !compiling.value)
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
  if (selectedProjectId.value === null) return
  try {
    ;[tasks.value, styles.value] = await Promise.all([
      listProjectScriptTasks(selectedProjectId.value, { status: 'succeeded' }),
      listStyles(selectedProjectId.value),
    ])
    if (!tasks.value.some((item) => item.id === selectedTaskId.value)) {
      selectedTaskId.value = tasks.value[0]?.id ?? null
    }
    if (!styles.value.some((item) => item.id === selectedStyleId.value)) {
      selectedStyleId.value = styles.value.find((item) => item.status === 'approved')?.id ?? null
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const loadTask = async () => {
  if (selectedTaskId.value === null) {
    specs.value = []
    compilations.value = []
    specCompilations.value = []
    return
  }
  try {
    ;[specs.value, compilations.value, specCompilations.value] = await Promise.all([
      listImageSpecs(selectedTaskId.value),
      listContinuityCompilations(selectedTaskId.value),
      listImageSpecCompilations(selectedTaskId.value),
    ])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const compile = async () => {
  if (selectedTaskId.value === null) return
  compiling.value = true
  progressEvents.value = []
  let failed = false
  try {
    await streamCompileImageSpecs(
      selectedTaskId.value,
      {
        style_profile_id: selectedStyleId.value,
        shot_planner_preset_id: shotPresetId.value,
        negative_prompt_preset_id: negativePresetId.value,
        generation_mode: generationMode.value,
        concurrency: concurrency.value,
        regenerate_continuity: regenerateContinuity.value,
        resume_existing: true,
      },
      {
        onEvent: (event, payload) => progressEvents.value.unshift({ event, payload }),
        onError: (error) => {
          failed = true
          ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.compile')))
        },
      },
    )
    await loadTask()
    if (!failed) ElMessage.success(t('imageSpecs.messages.compiled'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.compile')))
  } finally {
    compiling.value = false
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

watch(selectedProjectId, loadProject)
watch(selectedTaskId, loadTask)
watch(presets, selectPresetDefaults)

onMounted(async () => {
  try {
    const previousProjectId = selectedProjectId.value
    ;[projects.value] = await Promise.all([listProjects(), loadPresets()])
    if (!projects.value.some((project) => project.id === selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? null
    }
    if (selectedProjectId.value !== null && selectedProjectId.value === previousProjectId) {
      await loadProject()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
})
</script>

<template>
  <div class="image-spec-page">
    <div class="page-header">
      <el-button :icon="Refresh" @click="loadTask">{{ t('imageSpecs.refresh') }}</el-button>
      <el-button :icon="Setting" @click="openCreatePreset()">
        {{ t('imageSpecs.presets.manage') }}
      </el-button>
    </div>

    <section class="panel controls">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.configTitle') }}</h2>
          <p>{{ t('imageSpecs.promptTypeHint') }}</p>
        </div>
      </header>
      <div class="panel-body controls-body">
        <el-form label-position="top">
          <div class="control-grid">
            <el-form-item :label="t('imageSpecs.project')">
              <el-select v-model="selectedProjectId" filterable>
                <el-option v-for="item in projects" :key="item.id" :label="item.title" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageSpecs.task')">
              <el-select v-model="selectedTaskId">
                <el-option
                  v-for="item in tasks"
                  :key="item.id"
                  :label="`#${item.id} · ${item.total_pages}p`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageSpecs.style')">
              <el-select v-model="selectedStyleId" clearable>
                <el-option
                  v-for="item in styles.filter((style) => style.status === 'approved')"
                  :key="item.id"
                  :label="`${item.name} v${item.version}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item :label="t('imageSpecs.mode')">
              <el-segmented
                v-model="generationMode"
                :options="[
                  { label: t('imageSpecs.preview'), value: 'preview' },
                  { label: t('imageSpecs.final'), value: 'final' },
                ]"
              />
            </el-form-item>
          </div>
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
        </el-form>
        <el-alert
          v-if="generationMode === 'final'"
          type="warning"
          :closable="false"
          :title="t('imageSpecs.finalHint')"
        />
        <div class="prompt-type-strip">
          <div v-for="type in promptTypeOrder" :key="type" class="prompt-type-card">
            <strong>{{ t(`imageSpecs.promptTypes.${type}`) }}</strong>
            <span>{{ t(`imageSpecs.promptTypes.${type}Hint`) }}</span>
          </div>
        </div>
        <div class="controls-actions">
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

    <section v-if="latestSpecCompilation" class="panel compilation-status">
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

    <section class="panel preset-panel">
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
            <el-button link type="danger" :icon="Delete" @click="removePreset(preset)">
              {{ t('projects.delete') }}
            </el-button>
          </div>
        </article>
      </div>
    </section>

    <section v-if="latestCompilation" class="panel continuity">
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
    </section>

    <section class="spec-list">
      <article v-for="[pageNo, pageSpecs] in specsByPage" :key="pageNo" class="panel spec-card">
        <header class="panel-heading">
          <h2>{{ t('imageSpecs.page', { page: pageNo }) }}</h2>
          <span>{{ t('imageSpecs.threeTypesReady') }}</span>
        </header>
        <el-tabs class="spec-tabs">
          <el-tab-pane
            v-for="spec in pageSpecs"
            :key="spec.id"
            :label="t(`imageSpecs.promptTypes.${spec.prompt_type}`)"
          >
            <div class="spec-content">
              <div class="tags">
                <el-tag>{{ spec.prompt_type }}</el-tag>
                <el-tag :type="spec.generation_mode === 'final' ? 'success' : 'info'">{{ spec.generation_mode }}</el-tag>
                <el-tag v-if="spec.warnings.length" type="warning">
                  {{ t('imageSpecs.warningCount', { count: spec.warnings.length }) }}
                </el-tag>
              </div>
              <p>{{ spec.positive_prompt }}</p>
              <div class="spec-footer">
                <small>{{ spec.spec_hash.slice(0, 16) }} · {{ spec.compiler_key }}</small>
                <el-button link type="primary" :icon="View" @click="openDetail(spec)">{{ t('imageSpecs.detail') }}</el-button>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </article>
      <el-empty v-if="specsByPage.length === 0" class="panel spec-list__empty" :description="t('imageSpecs.empty')" />
    </section>

    <section v-if="progressEvents.length" class="panel">
      <header class="panel-heading"><h2>{{ t('imageSpecs.progress') }}</h2></header>
      <div class="event-log">
        <div v-for="(item, index) in progressEvents.slice(0, 30)" :key="index">
          <el-tag size="small">{{ item.event }}</el-tag><code>{{ JSON.stringify(item.payload) }}</code>
        </div>
      </div>
    </section>

    <el-drawer v-model="detailVisible" size="55%" :title="detailSpec ? `ImageSpec #${detailSpec.id}` : ''">
      <template v-if="detailSpec">
        <el-alert
          v-for="warning in detailSpec.warnings"
          :key="warning.code"
          type="warning"
          :closable="false"
          :title="warning.message"
        />
        <h3>{{ t('imageSpecs.positivePrompt') }}</h3><pre>{{ detailSpec.positive_prompt }}</pre>
        <h3>{{ t('imageSpecs.negativePromptTitle') }}</h3><pre>{{ detailSpec.negative_prompt }}</pre>
        <h3>{{ t('imageSpecs.specJson') }}</h3><pre>{{ JSON.stringify(detailSpec.spec, null, 2) }}</pre>
      </template>
    </el-drawer>

    <el-dialog v-model="presetDialogVisible" destroy-on-close :title="t('imageSpecs.presets.editorTitle')" width="760px">
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

    <el-dialog v-model="eventEditorVisible" :title="t('imageSpecs.continuity.edit')" width="820px">
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
.image-spec-page { display: grid; gap: 18px; }
.page-header { display: flex; justify-content: flex-end; gap: 10px; }
.panel { min-width: 0; overflow: hidden; border: 1px solid var(--panel-border); border-radius: 8px; background: #fff; box-shadow: var(--panel-shadow); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; padding: 20px 22px 16px; border-bottom: 1px solid var(--panel-border); }
.panel-heading h2, .panel-heading p { margin: 0; }
.panel-heading p { margin-top: 6px; color: var(--text-secondary); }
.panel-body { padding: 20px 22px; }
.compilation-status__body { display: grid; gap: 12px; padding: 18px 22px 22px; }
.compilation-status__body p { margin: 0; color: var(--text-secondary); }
.control-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.secondary { margin-top: 2px; }
.controls-actions { display: flex; justify-content: flex-end; margin-top: 18px; }
.prompt-type-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.prompt-type-card { display: grid; gap: 6px; padding: 14px; border: 1px solid #dce8f8; border-radius: 8px; background: #f7fbff; }
.prompt-type-card span { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }
.preset-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; padding: 18px 22px 22px; }
.preset-card { display: grid; gap: 10px; padding: 14px; border: 1px solid #e2eaf4; border-radius: 8px; }
.preset-card p { min-height: 38px; margin: 0; color: var(--text-secondary); font-size: 13px; }
.preset-actions { display: flex; justify-content: flex-end; }
.spec-list { display: grid; gap: 16px; }
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
@media (max-width: 720px) { .control-grid, .prompt-type-strip, .dialog-grid { grid-template-columns: 1fr; } }
</style>

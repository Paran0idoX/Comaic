<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { EditPen, MagicStick, Refresh, View } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

import { apiErrorMessage } from '@/api/errors'
import { listCompletedScriptTasks } from '@/api/imagePrompts'
import {
  IMAGE_PROMPT_PRESET_KINDS,
  listImagePromptPresets,
  type ImagePromptPreset,
} from '@/api/imagePrompts'
import {
  listContinuityCompilations,
  listImageSpecs,
  replaceContinuityEvents,
  streamCompileImageSpecs,
  type ContinuityCompilation,
  type ContinuityEvent,
  type ImageSpec,
} from '@/api/imageSpecs'
import { listProjects, type Project } from '@/api/projects'
import type { ScriptTask } from '@/api/scripts'
import {
  listModelProfiles,
  listStyles,
  type ModelProfile,
  type StyleProfile,
} from '@/api/visualBible'

const { t } = useI18n()
const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const profiles = ref<ModelProfile[]>([])
const styles = ref<StyleProfile[]>([])
const presets = ref<ImagePromptPreset[]>([])
const specs = ref<ImageSpec[]>([])
const compilations = ref<ContinuityCompilation[]>([])
const selectedProjectId = ref<number | null>(null)
const selectedTaskId = ref<number | null>(null)
const selectedProfileIds = ref<number[]>([])
const primaryProfileId = ref<number | null>(null)
const selectedStyleId = ref<number | null>(null)
const shotPresetId = ref<number | null>(null)
const negativePresetId = ref<number | null>(null)
const generationMode = ref<'preview' | 'final'>('preview')
const concurrency = ref(8)
const regenerateContinuity = ref(false)
const compiling = ref(false)
const events = ref<Array<{ event: string; payload: Record<string, unknown> }>>([])
const detailSpec = ref<ImageSpec | null>(null)
const detailVisible = ref(false)
const eventEditorVisible = ref(false)
const eventEditorText = ref('[]')

const enabledProfiles = computed(() => profiles.value.filter((item) => item.is_enabled))
const latestCompilation = computed(() => compilations.value[0] ?? null)
const specsByPage = computed(() => {
  const result = new Map<number, ImageSpec[]>()
  for (const spec of specs.value) {
    const values = result.get(spec.page_no) ?? []
    values.push(spec)
    result.set(spec.page_no, values)
  }
  return [...result.entries()].sort(([a], [b]) => a - b)
})
const shotPresets = computed(() =>
  presets.value.filter((item) => item.kind === IMAGE_PROMPT_PRESET_KINDS.shot),
)
const negativePresets = computed(() =>
  presets.value.filter((item) => item.kind === IMAGE_PROMPT_PRESET_KINDS.negative),
)

const selectDefaults = () => {
  if (selectedProfileIds.value.length === 0) {
    selectedProfileIds.value = enabledProfiles.value.map((item) => item.id)
  }
  if (!selectedProfileIds.value.includes(primaryProfileId.value ?? -1)) {
    primaryProfileId.value = selectedProfileIds.value[0] ?? null
  }
  if (shotPresetId.value === null) {
    shotPresetId.value =
      (shotPresets.value.find((item) => item.is_default) ?? shotPresets.value[0])?.id ?? null
  }
  if (negativePresetId.value === null) {
    negativePresetId.value =
      (negativePresets.value.find((item) => item.is_default) ?? negativePresets.value[0])?.id ??
      null
  }
}

const loadProject = async () => {
  if (selectedProjectId.value === null) return
  try {
    ;[tasks.value, styles.value] = await Promise.all([
      listCompletedScriptTasks(selectedProjectId.value),
      listStyles(selectedProjectId.value),
    ])
    selectedTaskId.value = tasks.value.some((item) => item.id === selectedTaskId.value)
      ? selectedTaskId.value
      : (tasks.value[0]?.id ?? null)
    selectedStyleId.value = styles.value.find((item) => item.status === 'approved')?.id ?? null
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const loadTask = async () => {
  if (selectedTaskId.value === null) {
    specs.value = []
    compilations.value = []
    return
  }
  try {
    ;[specs.value, compilations.value] = await Promise.all([
      listImageSpecs(selectedTaskId.value),
      listContinuityCompilations(selectedTaskId.value),
    ])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
}

const compile = async () => {
  if (
    selectedTaskId.value === null ||
    primaryProfileId.value === null ||
    selectedProfileIds.value.length === 0
  ) {
    ElMessage.warning(t('imageSpecs.errors.selectRequired'))
    return
  }
  compiling.value = true
  events.value = []
  let failed = false
  try {
    await streamCompileImageSpecs(
      selectedTaskId.value,
      {
        model_profile_ids: selectedProfileIds.value,
        primary_model_profile_id: primaryProfileId.value,
        style_profile_id: selectedStyleId.value,
        shot_planner_preset_id: shotPresetId.value,
        negative_prompt_preset_id: negativePresetId.value,
        generation_mode: generationMode.value,
        concurrency: concurrency.value,
        regenerate_continuity: regenerateContinuity.value,
      },
      {
        onEvent: (event, payload) => {
          events.value.unshift({ event, payload })
        },
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
watch(selectedProfileIds, selectDefaults)

onMounted(async () => {
  try {
    ;[projects.value, profiles.value, presets.value] = await Promise.all([
      listProjects(),
      listModelProfiles(),
      listImagePromptPresets(),
    ])
    selectDefaults()
    selectedProjectId.value = projects.value[0]?.id ?? null
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('imageSpecs.errors.load')))
  }
})
</script>

<template>
  <main class="image-spec-page">
    <div class="page-header">
      <el-button :icon="Refresh" @click="loadTask">{{ t('imageSpecs.refresh') }}</el-button>
    </div>

    <section class="panel controls">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.configTitle') }}</h2>
          <p>{{ t('imageSpecs.subtitle') }}</p>
        </div>
      </header>
      <div class="panel-body controls-body">
        <el-form label-position="top">
          <div class="control-grid">
            <el-form-item :label="t('imageSpecs.project')"
              ><el-select v-model="selectedProjectId"
                ><el-option
                  v-for="item in projects"
                  :key="item.id"
                  :label="item.title"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.task')"
              ><el-select v-model="selectedTaskId"
                ><el-option
                  v-for="item in tasks"
                  :key="item.id"
                  :label="`#${item.id} · ${item.total_pages}p`"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.models')"
              ><el-select v-model="selectedProfileIds" multiple collapse-tags
                ><el-option
                  v-for="item in enabledProfiles"
                  :key="item.id"
                  :label="`${item.name} · ${item.family}`"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.primaryModel')"
              ><el-select v-model="primaryProfileId"
                ><el-option
                  v-for="id in selectedProfileIds"
                  :key="id"
                  :label="profiles.find((p) => p.id === id)?.name"
                  :value="id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.style')"
              ><el-select v-model="selectedStyleId" clearable
                ><el-option
                  v-for="item in styles.filter((s) => s.status === 'approved')"
                  :key="item.id"
                  :label="`${item.name} v${item.version}`"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.mode')"
              ><el-segmented
                v-model="generationMode"
                :options="[
                  { label: t('imageSpecs.preview'), value: 'preview' },
                  { label: t('imageSpecs.final'), value: 'final' },
                ]"
            /></el-form-item>
          </div>
          <div class="control-grid secondary">
            <el-form-item :label="t('imageSpecs.shotPlanner')"
              ><el-select v-model="shotPresetId"
                ><el-option
                  v-for="item in shotPresets"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.negativePrompt')"
              ><el-select v-model="negativePresetId"
                ><el-option
                  v-for="item in negativePresets"
                  :key="item.id"
                  :label="item.name"
                  :value="item.id" /></el-select
            ></el-form-item>
            <el-form-item :label="t('imageSpecs.concurrency')"
              ><el-input-number v-model="concurrency" :min="1" :max="20"
            /></el-form-item>
            <el-form-item label=" "
              ><el-checkbox v-model="regenerateContinuity">{{
                t('imageSpecs.regenerate')
              }}</el-checkbox></el-form-item
            >
          </div>
        </el-form>
        <el-alert
          v-if="generationMode === 'final'"
          type="warning"
          :closable="false"
          :title="t('imageSpecs.finalHint')"
        />
        <div class="controls-actions">
          <el-button
            class="ai-gradient-button"
            type="primary"
            :icon="MagicStick"
            :loading="compiling"
            @click="compile"
            >{{ t('imageSpecs.compile') }}</el-button
          >
        </div>
      </div>
    </section>

    <section v-if="latestCompilation" class="panel continuity">
      <header class="panel-heading">
        <div>
          <h2>{{ t('imageSpecs.continuity.title') }}</h2>
          <p>
            #{{ latestCompilation.id }} · {{ latestCompilation.source_hash.slice(0, 12) }} ·
            {{ t('imageSpecs.eventCount', { count: latestCompilation.events.length }) }}
          </p>
        </div>
        <el-button :icon="EditPen" @click="openEventEditor">{{
          t('imageSpecs.continuity.edit')
        }}</el-button>
      </header>
      <el-table :data="latestCompilation.events" max-height="280"
        ><el-table-column
          prop="page_no"
          :label="t('imageSpecs.table.page')"
          width="80"
        /><el-table-column
          prop="timing"
          :label="t('imageSpecs.table.timing')"
          width="120"
        /><el-table-column
          prop="event_type"
          :label="t('imageSpecs.table.event')"
          width="190"
        /><el-table-column
          prop="target_key"
          :label="t('imageSpecs.table.target')"
          width="150"
        /><el-table-column
          prop="source"
          :label="t('imageSpecs.table.source')"
          width="90"
        /><el-table-column :label="t('imageSpecs.table.payload')"
          ><template #default="scope"
            ><code class="payload-code">{{ JSON.stringify(scope.row.payload) }}</code></template
          ></el-table-column
        ></el-table
      >
    </section>

    <section class="spec-list">
      <article v-for="[pageNo, pageSpecs] in specsByPage" :key="pageNo" class="panel spec-card">
        <header class="panel-heading">
          <h2>{{ t('imageSpecs.page', { page: pageNo }) }}</h2>
          <span>{{ t('imageSpecs.specCount', { count: pageSpecs.length }) }}</span>
        </header>
        <div class="spec-card__body">
          <div v-for="spec in pageSpecs" :key="spec.id" class="spec-row">
            <div>
              <div class="tags">
                <el-tag>{{ spec.model_family }}</el-tag
                ><el-tag :type="spec.generation_mode === 'final' ? 'success' : 'info'">{{
                  spec.generation_mode
                }}</el-tag
                ><el-tag v-if="spec.warnings.length" type="warning">{{
                  t('imageSpecs.warningCount', { count: spec.warnings.length })
                }}</el-tag>
              </div>
              <p>{{ spec.positive_prompt }}</p>
              <small>{{ spec.spec_hash.slice(0, 16) }} · {{ spec.compiler_key }}</small>
            </div>
            <el-button link type="primary" :icon="View" @click="openDetail(spec)">{{
              t('imageSpecs.detail')
            }}</el-button>
          </div>
        </div>
      </article>
      <el-empty
        v-if="specsByPage.length === 0"
        class="panel spec-list__empty"
        :description="t('imageSpecs.empty')"
      />
    </section>

    <section v-if="events.length" class="panel">
      <header class="panel-heading">
        <h2>{{ t('imageSpecs.progress') }}</h2>
      </header>
      <div class="event-log">
        <div v-for="(item, index) in events.slice(0, 30)" :key="index">
          <el-tag size="small">{{ item.event }}</el-tag
          ><code>{{ JSON.stringify(item.payload) }}</code>
        </div>
      </div>
    </section>

    <el-drawer
      v-model="detailVisible"
      size="55%"
      :title="detailSpec ? `ImageSpec #${detailSpec.id}` : ''"
      ><template v-if="detailSpec"
        ><el-alert
          v-for="warning in detailSpec.warnings"
          :key="warning.code"
          type="warning"
          :closable="false"
          :title="warning.message"
        />
        <h3>{{ t('imageSpecs.positivePrompt') }}</h3>
        <pre>{{ detailSpec.positive_prompt }}</pre>
        <h3>{{ t('imageSpecs.negativePromptTitle') }}</h3>
        <pre>{{ detailSpec.negative_prompt }}</pre>
        <h3>{{ t('imageSpecs.specJson') }}</h3>
        <pre>{{ JSON.stringify(detailSpec.spec, null, 2) }}</pre>
      </template></el-drawer
    >
    <el-dialog v-model="eventEditorVisible" :title="t('imageSpecs.continuity.edit')" width="820px"
      ><el-alert
        type="info"
        :closable="false"
        :title="t('imageSpecs.continuity.editHint')"
      /><el-input
        v-model="eventEditorText"
        type="textarea"
        :rows="22"
        class="json-editor"
      /><template #footer
        ><el-button @click="eventEditorVisible = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" @click="saveEvents">{{
          t('projects.save')
        }}</el-button></template
      ></el-dialog
    >
  </main>
</template>

<style scoped>
.image-spec-page {
  display: grid;
  gap: 18px;
}

.page-header {
  margin-bottom: 6px;
}

.panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--panel-shadow);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 20px 22px 16px;
  border-bottom: 1px solid var(--panel-border);
}

.panel-heading h2,
.panel-heading p {
  margin: 0;
}

.panel-heading h2 {
  font-size: 18px;
}

.panel-heading p {
  margin-top: 6px;
  color: var(--text-soft);
  line-height: 1.5;
}

.panel-heading > span {
  color: var(--text-soft);
  font-size: 13px;
}

.panel-body {
  padding: 18px 22px 22px;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.control-grid.secondary {
  grid-template-columns: 2fr 2fr 1fr 2fr;
}

.control-grid :deep(.el-select),
.control-grid :deep(.el-input-number) {
  width: 100%;
}

.controls-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.controls-actions .el-button {
  min-width: 180px;
}

.spec-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  align-items: start;
}

.spec-list__empty {
  grid-column: 1 / -1;
  padding: 36px 18px;
}

.spec-card__body {
  padding: 2px 22px;
}

.spec-row {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid var(--panel-border);
}

.spec-row:last-child {
  border-bottom: 0;
}

.spec-row > div {
  min-width: 0;
}

.spec-row p {
  display: -webkit-box;
  margin: 10px 0 8px;
  overflow: hidden;
  color: var(--text-regular);
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.spec-row small {
  color: var(--text-soft);
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.event-log {
  display: grid;
  gap: 8px;
  max-height: 280px;
  padding: 18px 22px 22px;
  overflow: auto;
}

.event-log > div {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.event-log code,
.payload-code {
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-regular);
  font-size: 12px;
}

.event-log code {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid var(--panel-border);
  border-radius: 6px;
  background: #f8fafc;
}

pre {
  margin: 0 0 18px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fafc;
  color: var(--text-regular);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.json-editor {
  margin-top: 14px;
}

@media (max-width: 1180px) {
  .control-grid.secondary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .spec-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 820px) {
  .control-grid,
  .control-grid.secondary {
    grid-template-columns: 1fr;
  }

  .panel-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .spec-row {
    flex-direction: column;
  }
}
</style>

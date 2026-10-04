<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { ApiError, apiErrorMessage } from '@/api/errors'
import type { ImageGenerationTool } from '@/api/imageGeneration'
import type { OutfitVariant, SceneVisualVersion, VisualAsset } from '@/api/visualBible'
import { createReferenceImageBatch, previewReferencePrompts, previewReferencePromptBatch,
  type ReferenceCategory, type ReferenceCategoryDefinition, type ReferenceImageTask,
  type ReferenceRequest, type ReferenceRole, type ReferenceSize, type ReferenceSubject,
  type ReferenceTaskRequest, type ReferencePromptPreview, type VisualProfile, visualProfileRefs } from '@/api/referenceImages'
import { defaultReferenceSize, type ReferenceOwner } from './referenceLibrary'
import VisualProfileEditor from './VisualProfileEditor.vue'

const props = defineProps<{
  projectId: number; characters: Array<{ id: number; label: string }>; subjects: ReferenceSubject[]
  catalog: ReferenceCategoryDefinition[]; tools: ImageGenerationTool[]; assets: VisualAsset[]
  outfits: OutfitVariant[]; currentCharacters: Array<{ outline_character_id: number | null; outfit_variant_id: number | null }>
  scenes: Array<{ id: number; name: string; reference_subject_id?: number | null }>; sceneVersions: SceneVisualVersion[]
  taskUpdates?: ReferenceImageTask[]
}>()
const emit = defineEmits<{ close: []; submitted: [tasks: ReferenceImageTask[]] }>()
const { t } = useI18n()
const supportsSize = (tool: ImageGenerationTool) => tool.provider === 'openai_images_compatible' ||
  ['render.width', 'render.height'].every(source => tool.bindings?.bindings?.some(binding => binding.source === source))
const form = reactive({
  toolId: props.tools.find(tool => tool.is_default)?.id ?? props.tools[0]?.id ?? null as number | null,
  candidateCount: 2, sourceMode: 'auto' as 'auto' | 'none',
  keys: { character: [], scene: [], prop: [] } as Record<ReferenceCategory, string[]>,
  roles: Object.fromEntries(props.catalog.map(item => [item.entity_type,
    item.roles.filter(item => !['identity_side', 'identity_back'].includes(item.role)).map(item => item.role)])) as Record<ReferenceCategory, ReferenceRole[]>,
  sizes: Object.fromEntries(props.catalog.flatMap(item => item.roles.map(({ role }) => [role, defaultReferenceSize(role)]))) as Record<ReferenceRole, ReferenceSize>,
})
const categories = props.catalog.map(item => item.entity_type)
const owners: ReferenceOwner[] = [
  ...props.characters.map(character => ({ key: `character:${character.id}`, category: 'character' as const,
    name: character.label, characterId: character.id, subjectId: null, description: '', negativeConstraints: '' })),
  ...props.subjects.map(subject => ({ key: `${subject.entity_type}:${subject.id}`, category: subject.entity_type,
    name: subject.name, characterId: null, subjectId: subject.id, description: subject.description, negativeConstraints: subject.negative_constraints,
    sceneDefinitionVersion: subject.scene_definition_version ?? 1 })),
]
const selections = reactive<Record<string, { outfitId: number | null; sceneId: number | null; canvasId: number | null }>>({})
// 每个主体单独保存服装/场景版本及画布，不把同一人物或场景的输入套到其它对象。
for (const owner of owners) {
  const currentIds = [...new Set(props.currentCharacters.filter(character => character.outline_character_id === owner.characterId)
    .map(character => character.outfit_variant_id).filter((id): id is number => id !== null && props.outfits.some(outfit => outfit.id === id && outfit.status !== 'archived')))]
  selections[owner.key] = { outfitId: owner.category === 'character' && currentIds.length === 1 ? currentIds[0]! : null, sceneId: 0, canvasId: null }
}
const selectedOwners = computed(() => owners.filter(owner => form.keys[owner.category]?.includes(owner.key)))
const selectedTool = computed(() => props.tools.find(tool => tool.id === form.toolId))
const customSizes = computed(() => Boolean(selectedTool.value && supportsSize(selectedTool.value)))
const needsCanvas = computed(() => Boolean(selectedTool.value?.capabilities.reference_images?.requires_canvas))
const canvasOptions = computed(() => props.assets.filter(asset => asset.project_id === props.projectId && asset.status === 'approved' &&
  asset.role !== 'identity_half_body' && ['character', 'scene', 'prop'].includes(asset.entity_type) &&
  (Boolean(asset.local_path) || selectedTool.value?.provider === 'comfyui' && Boolean(asset.renderer_locator))))
const outfitOptions = (owner: ReferenceOwner) => props.outfits.filter(outfit => outfit.outline_character_id === owner.characterId && outfit.status !== 'archived')
const ambiguousOutfit = (owner: ReferenceOwner) => owner.category === 'character' &&
  new Set(props.currentCharacters.filter(character => character.outline_character_id === owner.characterId)
    .map(character => character.outfit_variant_id).filter(id => outfitOptions(owner).some(outfit => outfit.id === id))).size > 1
const sceneOptions = (owner: ReferenceOwner) => (owner.sceneDefinitionVersion ?? 1) >= 2 ? [] : props.sceneVersions.filter(version => version.status !== 'archived' &&
  props.scenes.some(scene => scene.id === version.script_scene_id && scene.reference_subject_id === owner.subjectId))
const roleLabel = (role: ReferenceRole) => t(props.catalog.flatMap(item => item.roles).find(item => item.role === role)?.label_key || `visualBible.roleLabels.${role}`)
const selectedRoles = computed(() => [...new Set(selectedOwners.value.flatMap(owner => form.roles[owner.category] || []))])
const requestCount = computed(() => selectedOwners.value.reduce((count, owner) => count + (form.roles[owner.category]?.length || 0) * form.candidateCount, 0))
const selectionValid = computed(() => selectedOwners.value.length > 0 && selectedOwners.value.length <= 100 &&
  Boolean(selectedTool.value) &&
  selectedOwners.value.every(owner => (form.roles[owner.category]?.length || 0) > 0 &&
    (!needsCanvas.value || canvasOptions.value.some(asset => asset.id === selections[owner.key]!.canvasId)) &&
    (!ambiguousOutfit(owner) || !form.roles.character.some(role => role !== 'identity_face') || selections[owner.key]!.outfitId !== null)) &&
  (!customSizes.value || selectedRoles.value.every(role => [form.sizes[role]?.width, form.sizes[role]?.height]
    .every(value => Number.isInteger(value) && value >= 256 && value <= 2048 && value % 32 === 0))))
type PromptStatus = 'pending' | 'preparing' | 'ready' | 'failed'
type PromptState = { status: PromptStatus; error: string }
type PreparedRow = { owner: ReferenceOwner; request: ReferenceTaskRequest; error: string; baseline: string; profiles: VisualProfile[]; dirty: boolean; busy: boolean; ready: boolean; rebuilt: boolean; running: boolean; activeTab: string; states: Partial<Record<ReferenceRole, PromptState>> }
const rows = ref<PreparedRow[]>([])
// 按完整准备输入缓存方案，返回阶段和重新勾选对象都不丢失人工编辑。
const rowCache = new Map<string, PreparedRow>()
const stage = ref(0)
const preparing = ref(false)
const submitting = ref(false)
const reviewing = computed(() => stage.value === 1)
const createdTasks = ref<ReferenceImageTask[]>([])
const submittedInput = ref('')
const currentInput = computed(() => JSON.stringify(rows.value.map(row => row.request)))
const draftChanged = computed(() => currentInput.value !== submittedInput.value)
const selectionLocked = computed(() => preparing.value || submitting.value || rows.value.some(row => row.running || row.busy || row.dirty))
// 复用素材库已有的任务订阅，弹窗只展示本次创建的任务，不重复提交或建立订阅。
const generationTasks = computed(() => createdTasks.value.map(task => props.taskUpdates?.find(update =>
  update.id === task.id && update.project_id === props.projectId) || task))
const generationComplete = computed(() => generationTasks.value.length > 0 && generationTasks.value.every(task => task.status === 'succeeded'))
const generationAttention = computed(() => generationTasks.value.some(task => ['failed', 'suspended'].includes(task.status)))
const taskProgress = (task: ReferenceImageTask) => {
  const total = task.progress?.total ?? task.selected_roles.length * task.candidate_count
  const completed = task.progress?.completed ?? 0, failed = task.progress?.failed ?? 0
  return { total, completed, failed, percentage: total ? Math.min(100, Math.round((completed + failed) / total * 100)) : 0 }
}
const generationProgress = computed(() => {
  const totals = generationTasks.value.reduce((sum, task) => {
    const progress = taskProgress(task)
    return { total: sum.total + progress.total, completed: sum.completed + progress.completed, failed: sum.failed + progress.failed }
  }, { total: 0, completed: 0, failed: 0 })
  return { ...totals, percentage: totals.total ? Math.min(100, Math.round((totals.completed + totals.failed) / totals.total * 100)) : 0 }
})
const taskStatusType = (task: ReferenceImageTask) => task.status === 'succeeded' ? 'success' : task.status === 'failed' ? 'danger' : task.status === 'suspended' ? 'warning' : 'info'
let sequence = 0
let disposed = false
let batchController: AbortController | null = null
const statusType = (status: PromptStatus) => ({ pending: 'info', preparing: 'primary', ready: 'success', failed: 'danger' } as const)[status]
const progress = computed(() => {
  const states = rows.value.flatMap(row => row.request.roles.map(role => row.states[role]!))
  const completed = states.filter(state => state.status === 'ready').length
  const failed = states.filter(state => state.status === 'failed').length
  return { total: states.length, completed, failed, pending: states.filter(state => state.status === 'pending').length,
    percentage: states.length ? Math.round((completed + failed) / states.length * 100) : 0 }
})
const currentPrompts = computed(() => rows.value.filter(row => row.running).map(row =>
  `${row.owner.name} · ${row.request.roles.filter(role => row.states[role]?.status === 'preparing').map(roleLabel).join('、')}`).join('；'))
const syncRow = (row: PreparedRow) => {
  row.error = row.request.roles.map(role => row.states[role]?.error).find(Boolean) || ''
  row.ready = row.profiles.length > 0 && row.request.roles.every(role => row.states[role]?.status === 'ready')
}
const requests = (): Array<{ owner: ReferenceOwner; request: ReferenceRequest }> => selectedOwners.value.map(owner => {
  const selection = selections[owner.key]!
  const roles = [...form.roles[owner.category]]
  return { owner, request: { entity_type: owner.category,
    entity_id: owner.category === 'scene' ? (owner.sceneDefinitionVersion ?? 1) >= 2 ? null : selection.sceneId || null : owner.characterId, reference_subject_id: owner.subjectId,
    outfit_variant_id: owner.category === 'character' && roles.some(role => role !== 'identity_face') ? selection.outfitId : null,
    tool_preset_id: form.toolId!, roles, source_mode: form.sourceMode,
    canvas_asset_id: needsCanvas.value ? selection.canvasId : null,
    // 固定尺寸工作流不接收宽高覆盖；支持尺寸输入的工具才冻结各用途的自定义尺寸。
    sizes: customSizes.value ? Object.fromEntries(roles.map(role => [role, { ...form.sizes[role] }])) : {},
  } }
})
const requestKey = (owner: ReferenceOwner, request: ReferenceRequest) => JSON.stringify([
  owner.key, request.tool_preset_id, props.tools.find(tool => tool.id === request.tool_preset_id)?.prompt_type,
  request.entity_id, request.reference_subject_id, request.outfit_variant_id, request.source_mode, request.canvas_asset_id,
  [...request.roles].sort(),
])
const selectionMatches = computed(() => selectionValid.value && requests().length === rows.value.length && requests().every((item, index) => {
  const row = rows.value[index]!
  return requestKey(item.owner, item.request) === requestKey(row.owner, row.request) && row.request.candidate_count === form.candidateCount &&
    item.request.roles.every(role => item.request.sizes?.[role]?.width === row.request.sizes?.[role]?.width && item.request.sizes?.[role]?.height === row.request.sizes?.[role]?.height)
}))
const applyPreview = (row: PreparedRow, preview: ReferencePromptPreview, roles = row.request.roles) => {
  const profiles = preview.visual_profiles || []
  const refs = visualProfileRefs(profiles)
  // 局部重生成遇到来源更新时，旧用途不能冒用新修订号提交；保留文字供用户检查。
  if (row.profiles.length && JSON.stringify(row.request.visual_profile_refs) !== JSON.stringify(refs)) {
    for (const role of row.request.roles.filter(role => !roles.includes(role))) {
      row.states[role] = { status: 'failed', error: t('referenceLibrary.batch.profileChanged') }
    }
  }
  const baseline = row.baseline ? JSON.parse(row.baseline) : {}
  for (const role of roles) {
    const prompt = preview.prompts[role]
    if (profiles.length && prompt?.positive.trim()) {
      row.request.prompts[role] = { ...prompt }; baseline[role] = { ...prompt }
      row.states[role] = { status: 'ready', error: '' }
    } else row.states[role] = { status: 'failed', error: t('referenceLibrary.errors.prompt') }
  }
  row.baseline = JSON.stringify(baseline)
  row.profiles = profiles; row.request.visual_profile_refs = refs
  row.rebuilt = preview.warnings?.includes('reference.profile_rebuilt') || false
}
const prepareRow = async (row: PreparedRow, token: number, force = false, roles = row.request.roles) => {
  row.ready = false; row.running = true
  for (const role of roles) row.states[role] = { status: 'preparing', error: '' }
  try {
    const { candidate_count: _count, prompts: _prompts, visual_profile_refs: _refs, ...selection } = row.request
    const preview = await previewReferencePrompts(props.projectId, { ...selection, roles,
      sizes: Object.fromEntries(roles.filter(role => selection.sizes?.[role]).map(role => [role, selection.sizes![role]])),
      refresh_visual_profiles: force })
    if (token !== sequence) return
    applyPreview(row, preview, roles)
  } catch (error) {
    if (token === sequence) for (const role of roles) row.states[role] = {
      status: 'failed', error: apiErrorMessage(error, t, t('referenceLibrary.errors.prompt')) }
  } finally {
    if (token === sequence) { row.running = false; syncRow(row) }
  }
}
const prepare = async () => {
  if (disposed || !selectionValid.value || selectionLocked.value) return
  const missing: PreparedRow[] = []
  rows.value = requests().map(({ owner, request }) => {
    const key = requestKey(owner, request)
    let row = rowCache.get(key)
    if (!row) {
      row = reactive<PreparedRow>({ owner,
        request: { ...request, candidate_count: form.candidateCount, prompts: {} }, error: '', baseline: '', profiles: [], dirty: false, busy: false, ready: false, rebuilt: false, running: false, activeTab: `${owner.key}:${request.roles[0]}`,
        states: Object.fromEntries(request.roles.map(role => [role, { status: 'pending' as PromptStatus, error: '' }])) })
      rowCache.set(key, row); missing.push(row)
    } else {
      row.request.candidate_count = form.candidateCount
      row.request.sizes = request.sizes
    }
    return row
  })
  stage.value = 1
  if (!missing.length) return
  const token = ++sequence
  preparing.value = true
  const batchRows = missing, finished = new Set<number>()
  try {
    batchController = new AbortController()
    await previewReferencePromptBatch(props.projectId, batchRows.map(row => {
      const { candidate_count: _count, prompts: _prompts, visual_profile_refs: _refs, ...selection } = row.request
      return selection
    }), event => {
      if (token !== sequence || event.project_id !== props.projectId || !Number.isInteger(event.index) || finished.has(event.index)) return
      const row = batchRows[event.index]
      if (!row) return
      if (event.status === 'running') {
        row.running = true
        for (const role of row.request.roles) row.states[role] = { status: 'preparing', error: '' }
      } else {
        finished.add(event.index)
        if (event.status === 'succeeded' && event.preview) applyPreview(row, event.preview)
        else for (const role of row.request.roles) row.states[role] = { status: 'failed', error:
          apiErrorMessage(new ApiError(event.error?.message || t('referenceLibrary.errors.prompt'), { code: event.error?.code }), t, t('referenceLibrary.errors.prompt')) }
        row.running = false; syncRow(row)
      }
    }, batchController.signal)
    // 流正常结束也必须收到全部对象结果；缺项保持未就绪，允许单项重试。
    if (token === sequence) for (const [index, row] of batchRows.entries()) {
      if (!finished.has(index)) {
        for (const role of row.request.roles) row.states[role] = { status: 'failed', error: t('referenceLibrary.errors.prompt') }
        row.running = false; syncRow(row)
      }
    }
  } catch (error) {
    if (token === sequence) for (const [index, row] of batchRows.entries()) {
      if (finished.has(index)) continue
      for (const role of row.request.roles) row.states[role] = { status: 'failed', error: apiErrorMessage(error, t, t('referenceLibrary.errors.prompt')) }
      row.running = false; syncRow(row)
    }
  } finally { if (token === sequence) { preparing.value = false; batchController = null } }
}
const confirmRowReplacement = async (row: PreparedRow, roles = row.request.roles) => {
  const baseline = row.baseline ? JSON.parse(row.baseline) : {}
  if (roles.some(role => baseline[role] && JSON.stringify(baseline[role]) !== JSON.stringify(row.request.prompts[role]))) {
    try { await ElMessageBox.confirm(t('referenceLibrary.replacePrompts'), t('referenceLibrary.refreshPrompts'), { type: 'warning' }) }
    catch { return false }
  }
  return true
}
const retryRow = async (row: PreparedRow, force = false, confirmed = false) => {
  if (disposed || row.running || row.dirty || row.busy && !confirmed || submitting.value || preparing.value && row.request.roles.every(role => row.states[role]?.status === 'pending')) return
  const token = sequence
  if (!confirmed && !await confirmRowReplacement(row)) return
  if (force) {
    try { await ElMessageBox.confirm(t('referenceLibrary.visual.reextractConfirm'), t('referenceLibrary.visual.reextract'), { type: 'warning' }) }
    catch { return }
  }
  if (token !== sequence || row.running || submitting.value) return
  await prepareRow(row, token, force)
}
const retryPrompt = async (row: PreparedRow, role: ReferenceRole) => {
  if (disposed || row.running || row.dirty || row.busy || submitting.value || !['ready', 'failed'].includes(row.states[role]?.status || 'pending')) return
  const token = sequence
  if (!await confirmRowReplacement(row, [role])) return
  if (token !== sequence || row.running || submitting.value) return
  await prepareRow(row, token, false, [role])
}
const profileUpdated = async (row: PreparedRow, profiles: VisualProfile[]) => {
  if (disposed) return
  row.profiles = profiles; row.dirty = false; row.ready = false
  await retryRow(row, false, true)
}
const ready = computed(() => selectionMatches.value && draftChanged.value && reviewing.value && rows.value.length > 0 && !preparing.value && rows.value.every(row =>
  row.ready && !row.running && !row.error && !row.dirty && !row.busy && row.request.roles.every(role => Boolean(row.request.prompts[role]?.positive.trim()))))
const canVisit = (index: number) => !submitting.value && (index === 0 || index === 1 && (rows.value.length > 0 || selectionValid.value) || index === 2 && createdTasks.value.length > 0)
const goToStage = async (index: number) => {
  if (disposed || !canVisit(index)) return
  if (index === 1 && stage.value === 0 && !selectionLocked.value && selectionValid.value) await prepare()
  else stage.value = index
}
const back = () => goToStage(0)
const submit = async () => {
  if (disposed || !ready.value || submitting.value) return
  submitting.value = true
  try {
    // 冻结本次输入，后来返回修改不会写入正在生成或已完成的任务。
    const items: ReferenceTaskRequest[] = JSON.parse(currentInput.value)
    const tasks = await createReferenceImageBatch(props.projectId, items)
    submittedInput.value = JSON.stringify(items)
    createdTasks.value.push(...tasks)
    stage.value = 2
    emit('submitted', tasks)
    ElMessage.success(t('referenceLibrary.batch.submitted', { count: tasks.length }))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.generate'))) }
  finally { submitting.value = false }
}
const close = () => { if (!submitting.value && !disposed) { disposed = true; sequence += 1; batchController?.abort(); emit('close') } }
onBeforeUnmount(() => { disposed = true; sequence += 1; batchController?.abort() })
</script>

<template>
  <el-dialog class="reference-batch-dialog" :model-value="true" :title="t('referenceLibrary.batch.title')" width="min(980px, calc(100vw - 28px))" top="24px"
    :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @close="close">
    <template #header><div class="batch-dialog-heading title-with-info">{{ t('referenceLibrary.batch.title') }}<InfoTip :content="t('referenceLibrary.batch.help')" :label="t('referenceLibrary.batch.title')" /></div>
      <ol class="batch-stages" :aria-label="t('referenceLibrary.batch.stagesLabel')">
        <li v-for="(name, index) in ['select', 'prompts', 'images']" :key="name" :class="{ 'is-current': index === stage, 'is-complete': index === 0 && rows.length || index === 1 && createdTasks.length || index === 2 && generationComplete }">
          <button type="button" :disabled="!canVisit(index)" :aria-current="index === stage ? 'step' : undefined" @click="goToStage(index)">
            <span class="batch-stage-number">{{ String(index + 1).padStart(2, '0') }}</span><span>{{ t(`referenceLibrary.batch.stages.${name}`) }}</span>
          </button>
        </li>
      </ol></template>
    <section v-show="stage === 2">
      <div class="batch-prompt-progress" role="status" aria-live="polite">
        <div class="batch-progress-heading"><strong>{{ t('referenceLibrary.batch.imageProgress', generationProgress) }}</strong>
          <span>{{ t('referenceLibrary.batch.imageFailures', generationProgress) }}</span></div>
        <el-progress :percentage="generationProgress.percentage" :status="generationAttention ? 'warning' : generationComplete ? 'success' : undefined" />
      </div>
      <p class="batch-help">{{ t('referenceLibrary.batch.generationHelp') }}</p>
      <article v-for="task in generationTasks" :key="task.id" class="batch-generation-task">
        <div class="batch-progress-heading"><strong>{{ task.subject_name || task.character_name }}</strong>
          <el-tag :type="taskStatusType(task)">{{ t(`activityCenter.status.${task.status}`) }}</el-tag></div>
        <p class="batch-help">{{ task.selected_roles.map(role => roleLabel(role as ReferenceRole)).join('、') }}</p>
        <el-progress :percentage="taskProgress(task).percentage" :status="task.status === 'failed' || task.status === 'suspended' ? 'warning' : task.status === 'succeeded' ? 'success' : undefined" />
        <p class="batch-help">{{ t('referenceLibrary.batch.imageProgress', taskProgress(task)) }}</p>
      </article>
      <el-alert v-if="generationAttention" type="warning" :closable="false" :title="t('referenceLibrary.batch.generationAttention')" />
    </section>
    <div v-show="stage !== 2">
    <el-form v-show="stage === 0" label-position="top" :disabled="selectionLocked">
      <div class="batch-grid">
        <el-form-item :label="t('visualBible.references.tool')" required><el-select v-model="form.toolId">
          <el-option v-for="tool in tools" :key="tool.id" :value="tool.id" :label="tool.name" />
        </el-select></el-form-item>
        <el-form-item :label="t('referenceLibrary.candidateCount')"><el-input-number v-model="form.candidateCount" :min="1" :max="4" /></el-form-item>
      </div>
      <section v-for="kind in categories" :key="kind" class="batch-category">
        <div class="batch-category-heading"><strong>{{ t(`referenceLibrary.categories.${kind}`) }}</strong>
          <el-button link type="primary" :disabled="selectionLocked" @click="form.keys[kind] = owners.filter(owner => owner.category === kind).map(owner => owner.key)">{{ t('referenceLibrary.batch.selectAll') }}</el-button>
        </div>
        <el-select v-model="form.keys[kind]" :aria-label="t(`referenceLibrary.categories.${kind}`)" multiple filterable collapse-tags collapse-tags-tooltip :max-collapse-tags="3" :placeholder="t('referenceLibrary.batch.selectSubjects')">
          <el-option v-for="owner in owners.filter(owner => owner.category === kind)" :key="owner.key" :value="owner.key" :label="owner.name" />
        </el-select>
        <el-checkbox-group v-if="form.keys[kind].length" v-model="form.roles[kind]" class="batch-role-options">
          <el-checkbox v-for="entry in catalog.find(item => item.entity_type === kind)?.roles" :key="entry.role" :value="entry.role">{{ roleLabel(entry.role) }}</el-checkbox>
        </el-checkbox-group>
      </section>
      <el-form-item :label="t('referenceLibrary.inputImages')"><template #label><span class="field-with-info">{{ t('referenceLibrary.inputImages') }}<InfoTip :content="t('referenceLibrary.batch.sourcesHelp')" :label="t('referenceLibrary.inputImages')" /></span></template><el-segmented v-model="form.sourceMode" :options="['auto', 'none'].map(value => ({ value, label: t(`referenceLibrary.sourceModes.${value}`) }))" />
      </el-form-item>
      <el-collapse v-if="selectedRoles.length && customSizes"><el-collapse-item name="sizes"><template #title><span class="field-with-info">{{ t('referenceLibrary.batch.sizes') }}<InfoTip :content="t('referenceLibrary.sizeHelp')" :label="t('referenceLibrary.batch.sizes')" /></span></template>
        <div v-for="role in selectedRoles" :key="role" class="batch-size-row"><strong>{{ roleLabel(role) }}</strong>
          <el-input-number v-model="form.sizes[role].width" :min="256" :max="2048" :step="32" step-strictly :aria-label="`${roleLabel(role)} · ${t('referenceLibrary.width')}`" />
          <span>×</span><el-input-number v-model="form.sizes[role].height" :min="256" :max="2048" :step="32" step-strictly :aria-label="`${roleLabel(role)} · ${t('referenceLibrary.height')}`" />
        </div>
      </el-collapse-item></el-collapse>
      <p v-if="selectedTool && !customSizes" class="batch-help">{{ t('referenceLibrary.batch.fixedSizes') }}</p>
      <div v-for="owner in selectedOwners.filter(owner => owner.category === 'scene' || needsCanvas || owner.category === 'character' && form.roles.character.some(role => role !== 'identity_face'))" :key="owner.key" class="batch-owner-options">
        <strong>{{ owner.name }}</strong>
        <el-form-item v-if="owner.category === 'character' && form.roles.character.some(role => role !== 'identity_face')" :label="t('referenceLibrary.applicability')"><template #label><span class="field-with-info">{{ t('referenceLibrary.applicability') }}<InfoTip :content="t('referenceLibrary.outfitHelp')" :label="t('referenceLibrary.applicability')" /></span></template>
          <el-select v-model="selections[owner.key]!.outfitId" clearable :placeholder="t(ambiguousOutfit(owner) ? 'referenceLibrary.chooseOutfit' : 'referenceLibrary.anyOutfit')">
            <el-option v-for="outfit in outfitOptions(owner)" :key="outfit.id" :value="outfit.id" :label="`${outfit.name} · v${outfit.version}`" />
          </el-select><p v-if="ambiguousOutfit(owner) && !selections[owner.key]!.outfitId" class="batch-help">{{ t('referenceLibrary.ambiguousOutfits') }}</p>
        </el-form-item>
        <el-form-item v-if="owner.category === 'scene' && (owner.sceneDefinitionVersion ?? 1) < 2" :label="t('referenceLibrary.sceneScope')"><template #label><span class="field-with-info">{{ t('referenceLibrary.sceneScope') }}<InfoTip :content="t('referenceLibrary.sceneScopeHelp')" :label="t('referenceLibrary.sceneScope')" /></span></template>
          <el-select v-model="selections[owner.key]!.sceneId"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" />
            <el-option v-for="version in sceneOptions(owner)" :key="version.id" :value="version.id" :label="t('referenceLibrary.sceneVersion', { name: scenes.find(scene => scene.id === version.script_scene_id)?.name || owner.name, version: version.version })" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="needsCanvas" :label="t('referenceInputs.canvas')" required>
          <el-select v-model="selections[owner.key]!.canvasId" clearable :placeholder="t('referenceLibrary.selectCanvas')"><el-option v-for="asset in canvasOptions" :key="asset.id" :value="asset.id" :label="`#${asset.id} · ${t(`visualBible.roleLabels.${asset.role}`)} · v${asset.version}`" /></el-select>
        </el-form-item>
      </div>
      <el-alert v-if="selectedOwners.length > 100" type="warning" :closable="false" :title="t('referenceLibrary.batch.limit')" />
    </el-form>
    <section v-show="stage === 1">
      <el-alert v-if="createdTasks.length" class="batch-summary" type="info" :closable="false" :title="t('referenceLibrary.batch.savedTasksHelp')" />
      <div class="batch-prompt-progress" role="status" aria-live="polite">
        <div class="batch-progress-heading"><strong>{{ t('referenceLibrary.batch.promptProgress', progress) }}</strong>
          <span>{{ t('referenceLibrary.batch.promptCounts', progress) }}</span></div>
        <el-progress :percentage="progress.percentage" :status="progress.failed ? 'warning' : progress.completed === progress.total ? 'success' : undefined" />
        <p v-if="currentPrompts" class="batch-help">{{ t('referenceLibrary.batch.currentPrompt', { name: currentPrompts }) }}</p>
      </div>
      <el-collapse><el-collapse-item v-for="row in rows" :key="row.owner.key" :name="row.owner.key">
        <template #title><div class="batch-row-title"><strong>{{ row.owner.name }}</strong>
          <span class="batch-role-status" v-for="role in row.request.roles" :key="role">
            <span>{{ roleLabel(role) }}</span><el-tag size="small" :type="statusType(row.states[role]!.status)">{{ t(`referenceLibrary.batch.promptStatuses.${row.states[role]!.status}`) }}</el-tag>
          </span></div></template>
        <el-button v-if="row.error && row.request.roles.length > 1" :disabled="row.running || submitting || row.dirty || row.busy" @click="retryRow(row)">{{ t('referenceLibrary.batch.retrySubject') }}</el-button>
        <el-alert v-if="row.rebuilt" type="info" :closable="false" :title="t('referenceLibrary.visual.rebuilt')" />
        <VisualProfileEditor :profiles="row.profiles" :disabled="row.running || submitting" :confirm-replacement="() => confirmRowReplacement(row)"
          @updated="profileUpdated(row, $event)" @dirty="row.dirty = $event" @busy="row.busy = $event" />
        <el-button v-if="row.profiles.length" :disabled="row.running || submitting || row.dirty || row.busy" @click="retryRow(row, true)">{{ t('referenceLibrary.visual.reextract') }}</el-button>
        <el-tabs v-model="row.activeTab"><el-tab-pane v-for="role in row.request.roles" :key="role" :name="`${row.owner.key}:${role}`" :label="roleLabel(role)">
          <div class="batch-prompt-toolbar"><el-tag :type="statusType(row.states[role]!.status)">{{ t(`referenceLibrary.batch.promptStatuses.${row.states[role]!.status}`) }}</el-tag>
            <el-button :loading="row.states[role]!.status === 'preparing'" :disabled="row.running || submitting || row.dirty || row.busy || row.states[role]!.status === 'pending'"
              :aria-label="t('referenceLibrary.batch.regenerateNamed', { name: row.owner.name, role: roleLabel(role) })" @click="retryPrompt(row, role)">{{ t('referenceLibrary.batch.regeneratePrompt') }}</el-button></div>
          <el-alert v-if="row.states[role]!.error" type="error" :closable="false" :title="row.states[role]!.error" />
          <p v-if="!row.request.prompts[role]" class="batch-help">{{ t(`referenceLibrary.batch.promptHints.${row.states[role]!.status}`) }}</p>
          <el-form v-else label-position="top"><el-form-item :label="t('imageSpecs.positivePrompt')"><el-input v-model="row.request.prompts[role]!.positive" type="textarea" :rows="4" :disabled="submitting || row.states[role]!.status === 'preparing'" /></el-form-item>
            <el-form-item :label="t('imageSpecs.negativePromptTitle')"><el-input v-model="row.request.prompts[role]!.negative" type="textarea" :rows="2" :disabled="submitting || row.states[role]!.status === 'preparing'" /></el-form-item>
          </el-form>
        </el-tab-pane></el-tabs>
      </el-collapse-item></el-collapse>
      <el-alert v-if="rows.some(row => row.error)" type="warning" :closable="false" :title="t('referenceLibrary.batch.previewFailed')" />
    </section>
    </div>
    <template #footer><div v-if="stage === 2" class="batch-footer">
      <el-button @click="back">{{ t('referenceLibrary.batch.back') }}</el-button>
      <el-button @click="goToStage(1)">{{ t('referenceLibrary.batch.backPrompts') }}</el-button>
      <el-button type="primary" @click="close">{{ t('referenceLibrary.batch.closeGeneration') }}</el-button></div>
      <template v-else><span class="batch-footer-summary">{{ t('referenceLibrary.batch.summary', { subjects: selectedOwners.length, count: requestCount }) }}</span><div class="batch-footer">
      <el-button :disabled="submitting" @click="close">{{ t('projects.cancel') }}</el-button>
      <el-button v-if="reviewing" :disabled="submitting" @click="back">{{ t('referenceLibrary.batch.back') }}</el-button>
      <el-button v-if="createdTasks.length" :disabled="submitting" :type="reviewing && !draftChanged ? 'primary' : 'default'" @click="goToStage(2)">{{ t('referenceLibrary.batch.viewGeneration') }}</el-button>
      <el-button v-if="stage === 0" type="primary" :disabled="!selectionValid || selectionLocked" :loading="preparing" @click="prepare">{{ t('referenceLibrary.batch.prepare') }}</el-button>
      <el-button v-else-if="!createdTasks.length || draftChanged" type="primary" :disabled="!ready" :loading="submitting" @click="submit">{{ t(createdTasks.length ? 'referenceLibrary.batch.submitNew' : 'referenceLibrary.batch.submit') }}</el-button>
    </div></template></template>
  </el-dialog>
</template>

<style scoped>
:global(.reference-batch-dialog) { display: flex; flex-direction: column; max-height: calc(100vh - 48px); margin-bottom: 24px; }
:global(.reference-batch-dialog .el-dialog__body) { overflow-y: auto; min-height: 0; }
:global(.reference-batch-dialog .el-dialog__header), :global(.reference-batch-dialog .el-dialog__footer) { flex-shrink: 0; }
.batch-help { margin: 0 0 14px; font-size: 13px; color: var(--text-soft); line-height: 1.6; }
.batch-dialog-heading { font-size: 18px; line-height: 24px; padding-right: 30px; }
.batch-stages { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; list-style: none; padding: 0; margin: 18px 0 0; }
.batch-stages li { border-bottom: 2px solid var(--el-border-color-lighter); color: var(--el-text-color-placeholder); font-size: 14px; line-height: 20px; }
.batch-stages button { display: flex; align-items: center; gap: 8px; width: 100%; padding: 0 0 10px; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.batch-stages button:disabled { cursor: default; }
.batch-stages button:not(:disabled):hover { color: var(--el-color-primary); }
.batch-stages button:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 3px; border-radius: 3px; }
.batch-stage-number { font-size: 11px; font-variant-numeric: tabular-nums; opacity: 0.75; }
.batch-stages .is-complete { color: var(--el-text-color-regular); }
.batch-stages .is-current { border-bottom-color: var(--el-color-primary); color: var(--el-color-primary); font-weight: 600; }
.batch-generation-task { padding: 14px; margin-bottom: 12px; border: 1px solid var(--panel-border); border-radius: 8px; }
.batch-generation-task .batch-help:last-child { margin: 6px 0 0; }
.batch-prompt-progress { position: sticky; top: 0; z-index: 3; padding: 12px; margin-bottom: 14px; border: 1px solid var(--panel-border); border-radius: 8px; background: var(--el-bg-color); }
.batch-progress-heading, .batch-prompt-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.batch-progress-heading span { font-size: 13px; color: var(--text-soft); }
.batch-prompt-progress .batch-help { margin: 6px 0 0; }
.batch-row-title { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; min-width: 0; padding: 12px 0; line-height: 1.5; }
.batch-row-title strong { overflow-wrap: anywhere; }
.batch-role-status { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 13px; font-weight: normal; }
:deep(.el-collapse-item__header) { height: auto; min-height: 48px; }
.batch-grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 16px; }
.batch-category { margin-bottom: 16px; padding: 14px; border: 1px solid var(--panel-border); border-radius: 8px; }
.batch-category-heading, .batch-size-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 10px; }
.batch-category-heading { justify-content: space-between; }
.batch-role-options { margin-top: 10px; }
.batch-size-row strong { min-width: 95px; }
.batch-owner-options { margin-top: 16px; padding: 14px; border: 1px solid var(--panel-border); border-radius: 8px; }
.batch-owner-options > strong { display: block; margin-bottom: 12px; overflow-wrap: anywhere; }
.batch-owner-options .el-form-item:last-child { margin-bottom: 0; }
.batch-summary { margin-bottom: 14px; text-align: left; }
.batch-footer-summary { margin-right: auto; color: var(--text-soft); font-size: 13px; line-height: 1.6; text-align: left; }
.batch-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.batch-footer .el-button + .el-button { margin-left: 0; }
@media (max-width: 640px) {
  .batch-grid { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .batch-stages { gap: 12px; }
  .batch-stages button { flex-direction: column; align-items: flex-start; gap: 2px; }
}
</style>

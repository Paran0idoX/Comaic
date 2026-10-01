<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, MagicStick, Plus, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '@/api/errors'
import type { ImageGenerationTool } from '@/api/imageGeneration'
import type { OutfitVariant, SceneVisualVersion, VisualAsset } from '@/api/visualBible'
import { setVisualAssetStatus, uploadVisualAsset } from '@/api/visualBible'
import {
  approveReferenceImage, bindSceneReferenceSubject, continueReferenceImageTask,
  createReferenceImageTask, createReferenceSubject, listReferenceCategories, listReferenceImageTasks,
  listReferenceSubjects, previewReferencePrompts, suspendReferenceImageTask,
  updateReferenceSubject, watchReferenceImageTask,
  type ReferenceCategory, type ReferenceCategoryDefinition, type ReferenceImageTask, type ReferenceRequest,
  type ReferenceRole, type ReferenceSubject,
} from '@/api/referenceImages'
import { assetImageUrl, autoFaceAsset, ownerAssets, type ReferenceOwner } from './referenceLibrary'

const props = defineProps<{
  projectId: number | null; scriptTaskId: number | null
  characters: Array<{ id: number; label: string }>; outfits: OutfitVariant[]
  currentCharacters?: Array<{ outline_character_id: number | null; outfit_variant_id: number | null }>
  scenes: Array<{ id: number; name: string; reference_subject_id?: number | null }>
  sceneVersions?: SceneVisualVersion[]
  assets: VisualAsset[]; tools: ImageGenerationTool[]
}>()
const emit = defineEmits<{
  changed: []; task: [task: ReferenceImageTask, scriptTaskId: number | null]
  bound: [sceneId: number, subjectId: number | null]
}>()
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const catalog = ref<ReferenceCategoryDefinition[]>([])
const categories = computed(() => catalog.value.map(item => item.entity_type))
const catalogFailed = ref(false)
const subjects = ref<ReferenceSubject[]>([])
const tasks = ref<ReferenceImageTask[]>([])
const category = ref<ReferenceCategory>('character')
const selectedOwnerKey = ref<string | null>(null)
const statusFilter = ref<'all' | 'draft' | 'approved'>('all')
const loading = ref(false)
const busyIds = ref<string[]>([])
const selectedTaskId = ref<number | null>(null)
const selectedSceneScope = ref(0)
const uploadDialog = ref(false)
const generateDialog = ref(false)
const subjectDialog = ref(false)
const saving = ref(false)
const promptLoading = ref(false)
const submitting = ref(false)
const editorProjectId = ref<number | null>(null)
const editorOwner = ref<ReferenceOwner | null>(null)
const editorAssets = ref<VisualAsset[]>([])
const editorOutfits = ref<OutfitVariant[]>([])
const editorTools = ref<ImageGenerationTool[]>([])
const editorCurrentOutfitIds = ref<number[]>([])
const editorSceneScopeOptions = ref<Array<{ id: number; label: string; status: string }>>([])
const fileInputKey = ref(0)
const selectedFiles = ref<File[]>([])
const promptBaseline = ref('')
const editedSubjectId = ref<number | null>(null)
const bindSceneId = ref<number | null>(null)
const inputContextScriptTaskId = ref<number | null>(null)
let loadSequence = 0
let promptSequence = 0
const stops = new Map<number, () => void>()
const taskScriptContexts = new Map<number, number | null>()
const subjectForm = reactive({ entity_type: 'scene' as 'scene' | 'prop', name: '', description: '', negative_constraints: '' })
const uploadForm = reactive({ role: 'identity_face' as ReferenceRole, outfit_variant_id: null as number | null, scene_scope: 0 })
const generateForm = reactive({ tool_preset_id: null as number | null, roles: ['identity_face'] as ReferenceRole[],
  candidate_count: 2, outfit_variant_id: null as number | null,
  canvas_asset_id: null as number | null,
  scene_scope: 0,
  source_mode: 'auto' as 'auto' | 'none' | 'manual', source_asset_ids: [] as number[],
  prompts: {} as Partial<Record<ReferenceRole, { positive: string; negative: string }>> })

const owners = computed<ReferenceOwner[]>(() => category.value === 'character'
  ? props.characters.map(character => ({ key: `character:${character.id}`, category: 'character', name: character.label,
    characterId: character.id, subjectId: null, description: '', negativeConstraints: '' }))
  : subjects.value.filter(subject => subject.entity_type === category.value).map(subject => ({
    key: `${subject.entity_type}:${subject.id}`, category: subject.entity_type, name: subject.name,
    characterId: null, subjectId: subject.id, description: subject.description, negativeConstraints: subject.negative_constraints,
  })))
const selectedOwner = computed(() => owners.value.find(owner => owner.key === selectedOwnerKey.value) ?? null)
const sceneScopeOptions = computed(() => {
  const subjectId = selectedOwner.value?.subjectId
  const sceneIds = props.scenes.filter(scene => scene.reference_subject_id === subjectId).map(scene => scene.id)
  const historicalVersionIds = tasks.value.filter(task => task.entity_type === 'scene' && task.reference_subject_id === subjectId).map(task => task.entity_id)
  return (props.sceneVersions || []).filter(version => version.project_id === props.projectId &&
    (sceneIds.includes(version.script_scene_id) || historicalVersionIds.includes(version.id))).map(version => ({
      id: version.id, status: version.status, label: t('referenceLibrary.sceneVersion', {
        name: props.scenes.find(scene => scene.id === version.script_scene_id)?.name || selectedOwner.value?.name || '', version: version.version,
      }) + ` · ${t(`visualBible.status.${version.status}`)}`,
    }))
})
const sceneScopeAvailable = computed(() => selectedSceneScope.value === 0 || sceneScopeOptions.value.some(option => option.id === selectedSceneScope.value))
const sceneScopeEditable = computed(() => sceneScopeAvailable.value && !sceneScopeOptions.value.some(option => option.id === selectedSceneScope.value && option.status === 'archived'))
const currentAssets = computed(() => selectedOwner.value && props.projectId !== null
  ? ownerAssets(props.assets, { ...selectedOwner.value, ...(category.value === 'scene' ? { sceneVersionId: selectedSceneScope.value || null } : {}) }, props.projectId) : [])
const filteredAssets = computed(() => currentAssets.value.filter(asset => statusFilter.value === 'all' || asset.status === statusFilter.value))
const currentTasks = computed(() => selectedOwner.value ? tasks.value.filter(task => task.entity_type === selectedOwner.value!.category &&
  (selectedOwner.value!.category === 'character' ? task.entity_id === selectedOwner.value!.characterId : task.reference_subject_id === selectedOwner.value!.subjectId &&
    (selectedOwner.value!.category !== 'scene' || (task.entity_id ?? null) === (selectedSceneScope.value || null)))) : [])
const displayedTask = computed(() => currentTasks.value.find(task => task.id === selectedTaskId.value) ?? null)
const categoryRoles = (value: ReferenceCategory): ReferenceRole[] => catalog.value.find(item => item.entity_type === value)?.roles.map(item => item.role) ?? []
const roleOptions = computed(() => categoryRoles(editorOwner.value?.category ?? category.value))
const outfitOptions = computed(() => editorOutfits.value.filter(outfit => outfit.outline_character_id === editorOwner.value?.characterId && outfit.status !== 'archived'))
const ambiguousOutfits = computed(() => editorCurrentOutfitIds.value.length > 1)
const sourceOptions = computed(() => editorAssets.value.filter(asset => asset.project_id === editorProjectId.value &&
  asset.status === 'approved' && ['character', 'scene', 'prop'].includes(asset.entity_type)))
const autoSource = computed(() => editorOwner.value?.category === 'character' && editorProjectId.value !== null &&
  generateForm.roles.some(role => role !== 'identity_face')
  ? autoFaceAsset(editorAssets.value, editorOwner.value, editorProjectId.value) : null)
const selectedTool = computed(() => editorTools.value.find(tool => tool.id === generateForm.tool_preset_id))
const requiresCanvas = computed(() => Boolean(selectedTool.value?.capabilities.reference_images?.requires_canvas))
const imageCapacity = computed(() => {
  const tool = selectedTool.value; const config = tool?.capabilities.reference_images
  const max = config?.max_images ?? 0
  return tool?.provider === 'comfyui' ? Math.min(max, tool.bindings.reference_slots?.length ?? 0)
    : config?.transport && config.transport !== 'none' ? max : 0
})
const toolSupportsImages = computed(() => imageCapacity.value > 0 && Boolean(selectedTool.value?.capabilities.features?.some(feature => feature === 'reference_image' || feature === 'img2img')))
const effectiveSourceIds = computed(() => generateForm.source_mode === 'none' ? []
  : generateForm.source_mode === 'manual' ? generateForm.source_asset_ids : autoSource.value && toolSupportsImages.value ? [autoSource.value.id] : [])
const sourceSupported = computed(() => generateForm.source_mode !== 'manual' || effectiveSourceIds.value.length === 0 || toolSupportsImages.value)
const withinCapacity = computed(() => new Set([
  ...effectiveSourceIds.value, ...(generateForm.canvas_asset_id ? [generateForm.canvas_asset_id] : []),
]).size <= imageCapacity.value)
const promptsReady = computed(() => generateForm.roles.length > 0 && generateForm.roles.every(role => Boolean(generateForm.prompts[role]?.positive.trim())))
const canSubmit = computed(() => editorOwner.value !== null && generateForm.tool_preset_id !== null && promptsReady.value && sourceSupported.value &&
  (generateForm.source_mode !== 'manual' || generateForm.source_asset_ids.length > 0) && !promptLoading.value)
const canCreate = computed(() => canSubmit.value && (!requiresCanvas.value || generateForm.canvas_asset_id !== null) && withinCapacity.value &&
  (editorOwner.value?.category !== 'scene' || generateForm.scene_scope === 0 || editorSceneScopeOptions.value.some(option => option.id === generateForm.scene_scope && option.status !== 'archived')) &&
  (!ambiguousOutfits.value || generateForm.roles.every(role => role === 'identity_face') || generateForm.outfit_variant_id !== null))
const requestCount = computed(() => generateForm.roles.length * generateForm.candidate_count)
const boundScenes = computed(() => props.scenes.filter(scene => scene.reference_subject_id === selectedOwner.value?.subjectId))
const historicalAssets = computed(() => props.assets.filter(asset => ['style', 'control'].includes(asset.entity_type) ||
  asset.entity_type === 'scene' && !asset.reference_subject_id))
const locationUnavailable = computed(() => !loading.value && (
  (Number(route.query.character_id) > 0 || Number(route.query.reference_subject_id) > 0) && !selectedOwner.value ||
  Number(route.query.reference_task_id) > 0 && !displayedTask.value || category.value === 'scene' && !sceneScopeAvailable.value))
const approvedCount = (owner: ReferenceOwner) => props.projectId === null ? 0 : ownerAssets(props.assets, owner, props.projectId).filter(asset => asset.status === 'approved').length
const taskRoles = (task: ReferenceImageTask) => task.selected_roles?.length ? task.selected_roles :
  Object.keys(task.prompts || {}) as ReferenceRole[]
const roleLabel = (role: string) => t(catalog.value.flatMap(item => item.roles).find(item => item.role === role)?.label_key || `visualBible.roleLabels.${role}`)
const statusType = (status: string) => status === 'succeeded' || status === 'approved' ? 'success' : status === 'failed' ? 'danger' : 'info'
const taskProgress = (task: ReferenceImageTask) => task.progress.total ? Math.min(100, Math.round(((task.progress.completed || 0) + (task.progress.failed || 0)) / task.progress.total * 100)) : 0
const assetLabel = (asset: VisualAsset) => {
  const ownerName = asset.entity_type === 'character' ? props.characters.find(item => item.id === asset.entity_id)?.label
    : subjects.value.find(item => item.id === asset.reference_subject_id)?.name
  return `${ownerName || t(`referenceLibrary.categories.${asset.entity_type}`)} · ${roleLabel(asset.role)} · v${asset.version}`
}
const applicabilityLabel = (asset: VisualAsset) => asset.outfit_variant_id
  ? props.outfits.find(outfit => outfit.id === asset.outfit_variant_id)?.name || t('referenceLibrary.selectedOutfit')
  : t('referenceLibrary.anyOutfit')

const syncLocation = (owner: ReferenceOwner | null, taskId: number | null = null) => {
  if (props.projectId === null || route.path !== '/visual-bible') return
  const query = { ...route.query, tab: 'references', reference_category: category.value,
    script_task_id: props.scriptTaskId ? String(props.scriptTaskId) : undefined,
    character_id: owner?.characterId ? String(owner.characterId) : undefined,
    reference_subject_id: owner?.subjectId ? String(owner.subjectId) : undefined,
    scene_visual_version_id: owner?.category === 'scene' && selectedSceneScope.value > 0 ? String(selectedSceneScope.value) : undefined,
    reference_task_id: taskId ? String(taskId) : undefined,
    reference_task_kind: taskId ? 'referenceImage' : undefined }
  void router.replace({ query })
}
const applyLocation = () => {
  const requestedCategory = String(route.query.reference_category || '')
  if (categories.value.includes(requestedCategory as ReferenceCategory)) category.value = requestedCategory as ReferenceCategory
  const characterId = Number(route.query.character_id)
  const subjectId = Number(route.query.reference_subject_id)
  const requestedTaskId = Number(route.query.reference_task_id)
  const requestedSceneVersionId = Number(route.query.scene_visual_version_id)
  if (subjectId > 0) {
    const subject = subjects.value.find(item => item.id === subjectId)
    if (subject) { category.value = subject.entity_type; selectedOwnerKey.value = `${subject.entity_type}:${subject.id}` }
    else selectedOwnerKey.value = null
  } else if (characterId > 0) { category.value = 'character'; selectedOwnerKey.value = `character:${characterId}` }
  else if (requestedTaskId > 0) {
    const exactTask = tasks.value.find(task => task.id === requestedTaskId && task.project_id === props.projectId)
    if (exactTask) {
      category.value = exactTask.entity_type
      selectedOwnerKey.value = exactTask.entity_type === 'character' ? `character:${exactTask.entity_id}` : `${exactTask.entity_type}:${exactTask.reference_subject_id}`
    } else selectedOwnerKey.value = null
  }
  else if (!owners.value.some(owner => owner.key === selectedOwnerKey.value)) selectedOwnerKey.value = owners.value[0]?.key ?? null
  const exactTask = tasks.value.find(task => task.id === requestedTaskId && task.project_id === props.projectId &&
    task.entity_type === selectedOwner.value?.category && task.reference_subject_id === selectedOwner.value?.subjectId)
  selectedSceneScope.value = category.value === 'scene' ? requestedSceneVersionId > 0 ? requestedSceneVersionId : exactTask?.entity_id ?? 0 : 0
  selectedTaskId.value = requestedTaskId > 0 ? currentTasks.value.some(task => task.id === requestedTaskId) ? requestedTaskId : null
    : currentTasks.value[0]?.id ?? null
}
const receiveTask = (task: ReferenceImageTask, scriptTaskId: number | null, terminal = false) => {
  taskScriptContexts.set(task.id, scriptTaskId)
  emit('task', task, scriptTaskId)
  if (task.project_id === props.projectId) {
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)].sort((a, b) => b.id - a.id)
    if (terminal) emit('changed')
  }
  if (terminal) stops.delete(task.id)
}
const watchTask = (task: ReferenceImageTask, scriptTaskId = props.scriptTaskId) => {
  taskScriptContexts.set(task.id, scriptTaskId)
  if (stops.has(task.id)) return
  stops.set(task.id, watchReferenceImageTask(task.id, {
    onTask: (updated, terminal) => receiveTask(updated, taskScriptContexts.get(task.id) ?? null, terminal),
    onError: error => { stops.delete(task.id); ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.stream'))) },
  }))
}
const refresh = async () => {
  const projectId = props.projectId
  const scriptTaskId = props.scriptTaskId
  const requestedTaskId = Number(route.query.reference_task_id)
  const requestedScriptTaskId = Number(route.query.script_task_id)
  const token = ++loadSequence
  if (projectId === null) return
  loading.value = true
  try {
    const [nextCatalog, nextSubjects, nextTasks] = await Promise.all([listReferenceCategories(), listReferenceSubjects(projectId), listReferenceImageTasks(projectId)])
    nextTasks.forEach(task => {
      // 项目级历史列表没有原脚本信息，不能把浏览中的批次写成每项任务的原归属。
      const requestedContext = requestedTaskId === task.id && requestedScriptTaskId > 0 ? requestedScriptTaskId : null
      emit('task', task, taskScriptContexts.has(task.id) ? taskScriptContexts.get(task.id)! : requestedContext)
    })
    if (token !== loadSequence || projectId !== props.projectId) return
    catalog.value = nextCatalog; catalogFailed.value = false; subjects.value = nextSubjects; tasks.value = nextTasks
    applyLocation()
    nextTasks.filter(task => ['pending', 'running'].includes(task.status)).forEach(task => watchTask(task,
      taskScriptContexts.has(task.id) ? taskScriptContexts.get(task.id)! : requestedTaskId === task.id ? scriptTaskId : null))
  } catch (error) {
    if (token === loadSequence && projectId === props.projectId) { catalogFailed.value = true; catalog.value = []; ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.load'))) }
  } finally { if (token === loadSequence) loading.value = false }
}
const selectCategory = (value: ReferenceCategory) => {
  category.value = value; selectedSceneScope.value = 0; selectedOwnerKey.value = owners.value[0]?.key ?? null; selectedTaskId.value = currentTasks.value[0]?.id ?? null
  syncLocation(selectedOwner.value)
}
const selectOwner = (key: string) => {
  selectedOwnerKey.value = key; selectedSceneScope.value = 0; selectedTaskId.value = currentTasks.value[0]?.id ?? null; bindSceneId.value = null
  syncLocation(selectedOwner.value)
}
const selectSceneScope = (scope: number) => {
  selectedSceneScope.value = scope; selectedTaskId.value = currentTasks.value[0]?.id ?? null
  syncLocation(selectedOwner.value)
}
const openSubjectEditor = (edit = false) => {
  editorProjectId.value = props.projectId
  const subject = edit ? subjects.value.find(item => item.id === selectedOwner.value?.subjectId) : null
  editedSubjectId.value = subject?.id ?? null
  Object.assign(subjectForm, { entity_type: subject?.entity_type ?? (category.value === 'prop' ? 'prop' : 'scene'),
    name: subject?.name ?? '', description: subject?.description ?? '', negative_constraints: subject?.negative_constraints ?? '' })
  subjectDialog.value = true
}
const saveSubject = async () => {
  const projectId = editorProjectId.value
  if (projectId === null || !subjectForm.name.trim() || saving.value) return
  saving.value = true
  try {
    const result = editedSubjectId.value === null ? await createReferenceSubject(projectId, { ...subjectForm, name: subjectForm.name.trim() })
      : await updateReferenceSubject(editedSubjectId.value, { name: subjectForm.name.trim(), description: subjectForm.description, negative_constraints: subjectForm.negative_constraints })
    subjectDialog.value = false
    if (projectId === props.projectId) { await refresh(); category.value = result.entity_type; selectOwner(`${result.entity_type}:${result.id}`) }
    ElMessage.success(t('referenceLibrary.saved'))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.save'))) }
  finally { saving.value = false }
}
const openUpload = (role: ReferenceRole) => {
  if (!selectedOwner.value) return
  editorProjectId.value = props.projectId; editorOwner.value = { ...selectedOwner.value }
  editorAssets.value = [...props.assets]; editorOutfits.value = [...props.outfits]; editorTools.value = [...props.tools]
  editorSceneScopeOptions.value = [...sceneScopeOptions.value]; uploadForm.scene_scope = selectedSceneScope.value
  const outfitId = defaultOutfitId(editorOwner.value)
  uploadForm.role = role; uploadForm.outfit_variant_id = role === 'identity_face' ? null : outfitId; selectedFiles.value = []; fileInputKey.value += 1; uploadDialog.value = true
}
/** 只有当前任务能唯一确定造型时才预填；多个分段造型交给用户选择。 */
const defaultOutfitId = (owner: ReferenceOwner) => {
  if (owner.category !== 'character') { editorCurrentOutfitIds.value = []; return null }
  editorCurrentOutfitIds.value = [...new Set((props.currentCharacters || []).filter(character => character.outline_character_id === owner.characterId)
    .map(character => character.outfit_variant_id).filter((value): value is number => value !== null && editorOutfits.value.some(outfit =>
      outfit.id === value && outfit.outline_character_id === owner.characterId && outfit.status !== 'archived')))]
  const requested = Number(route.query.outfit_variant_id)
  if (requested > 0 && editorOutfits.value.some(outfit => outfit.id === requested && outfit.outline_character_id === owner.characterId && outfit.status !== 'archived')) return requested
  return editorCurrentOutfitIds.value.length === 1 ? editorCurrentOutfitIds.value[0]! : null
}
const saveUpload = async () => {
  const projectId = editorProjectId.value; const owner = editorOwner.value
  if (projectId === null || !owner || selectedFiles.value.length === 0 || saving.value ||
    owner.category === 'scene' && uploadForm.scene_scope > 0 && !editorSceneScopeOptions.value.some(option => option.id === uploadForm.scene_scope && option.status !== 'archived')) return
  saving.value = true
  try {
    for (const file of selectedFiles.value) {
      const form = new FormData()
      form.append('file', file); form.append('entity_type', owner.category); form.append('role', uploadForm.role); form.append('approve', 'false')
      if (owner.characterId) form.append('entity_id', String(owner.characterId))
      if (owner.category === 'scene' && uploadForm.scene_scope > 0) form.append('entity_id', String(uploadForm.scene_scope))
      if (owner.subjectId) form.append('reference_subject_id', String(owner.subjectId))
      if (uploadForm.outfit_variant_id && uploadForm.role !== 'identity_face') form.append('outfit_variant_id', String(uploadForm.outfit_variant_id))
      await uploadVisualAsset(projectId, form)
    }
    uploadDialog.value = false
    if (projectId === props.projectId) {
      if (owner.category === 'scene' && selectedOwner.value?.key === owner.key) {
        selectedSceneScope.value = uploadForm.scene_scope; syncLocation(selectedOwner.value)
      }
      emit('changed')
    }
    ElMessage.success(t('referenceLibrary.uploadedDraft'))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.save'))) }
  finally { saving.value = false }
}
const requestPayload = (): ReferenceRequest | null => {
  if (!editorOwner.value || generateForm.tool_preset_id === null) return null
  return { entity_type: editorOwner.value.category, entity_id: editorOwner.value.category === 'scene' ? generateForm.scene_scope || null : editorOwner.value.characterId,
    reference_subject_id: editorOwner.value.subjectId, outfit_variant_id: generateForm.outfit_variant_id,
    tool_preset_id: generateForm.tool_preset_id, roles: [...generateForm.roles],
    canvas_asset_id: generateForm.canvas_asset_id,
    source_mode: generateForm.source_mode === 'auto' && !toolSupportsImages.value ? 'none' : generateForm.source_mode,
    source_asset_ids: generateForm.source_mode === 'manual' ? [...generateForm.source_asset_ids] : [] }
}
const refreshPrompts = async (confirmReplacement = true) => {
  const payload = requestPayload(); const projectId = editorProjectId.value
  if (!payload || projectId === null || payload.roles.length === 0) return
  if (confirmReplacement && promptBaseline.value && JSON.stringify(generateForm.prompts) !== promptBaseline.value) {
    try { await ElMessageBox.confirm(t('referenceLibrary.replacePrompts'), t('referenceLibrary.refreshPrompts'), { type: 'warning' }) }
    catch { return }
  }
  const token = ++promptSequence; promptLoading.value = true
  try {
    const result = await previewReferencePrompts(projectId, payload)
    if (token !== promptSequence || !generateDialog.value || projectId !== editorProjectId.value) return
    generateForm.prompts = result.prompts; promptBaseline.value = JSON.stringify(result.prompts)
  } catch (error) { if (token === promptSequence) ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.prompt'))) }
  finally { if (token === promptSequence) promptLoading.value = false }
}
const openGenerator = (role: ReferenceRole) => {
  if (!selectedOwner.value) return
  editorProjectId.value = props.projectId; editorOwner.value = { ...selectedOwner.value }; inputContextScriptTaskId.value = props.scriptTaskId
  editorAssets.value = [...props.assets]; editorOutfits.value = [...props.outfits]; editorTools.value = [...props.tools]
  editorSceneScopeOptions.value = [...sceneScopeOptions.value]; generateForm.scene_scope = selectedSceneScope.value
  Object.assign(generateForm, { tool_preset_id: props.tools.find(tool => tool.is_default)?.id ?? props.tools[0]?.id ?? null,
    roles: [role], candidate_count: 2, outfit_variant_id: null, source_mode: 'auto', source_asset_ids: [], prompts: {} })
  generateForm.canvas_asset_id = null
  const outfitId = defaultOutfitId(editorOwner.value)
  generateForm.outfit_variant_id = role === 'identity_face' ? null : outfitId
  promptBaseline.value = ''; generateDialog.value = true; void refreshPrompts(false)
}
const configurationChanged = () => {
  promptSequence += 1; promptLoading.value = false
  if (!promptBaseline.value || JSON.stringify(generateForm.prompts) === promptBaseline.value) void refreshPrompts(false)
}
const rolesChanged = () => {
  generateForm.roles = categoryRoles(editorOwner.value?.category ?? category.value).filter(role => generateForm.roles.includes(role))
  // 保留用户手改提示词，新用途由用户主动刷新补齐，避免选择用途时静默覆盖。
  configurationChanged()
}
const submitGeneration = async () => {
  const payload = requestPayload(); const projectId = editorProjectId.value
  if (!payload || projectId === null || !canCreate.value || submitting.value) return
  const submittedOwner = editorOwner.value ? { ...editorOwner.value } : null
  submitting.value = true
  try {
    const task = await createReferenceImageTask(projectId, { ...payload, candidate_count: generateForm.candidate_count,
      prompts: Object.fromEntries(generateForm.roles.map(role => [role, { ...generateForm.prompts[role]! }])) })
    receiveTask(task, inputContextScriptTaskId.value)
    if (projectId === props.projectId && selectedOwner.value?.key === submittedOwner?.key) {
      if (task.entity_type === 'scene') selectedSceneScope.value = task.entity_id ?? 0
      selectedTaskId.value = task.id; syncLocation(selectedOwner.value, task.id)
    }
    if (['pending', 'running'].includes(task.status)) watchTask(task, inputContextScriptTaskId.value)
    generateDialog.value = false
    ElMessage.success(t('referenceLibrary.taskSubmitted'))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.generate'))) }
  finally { submitting.value = false }
}
const runAction = async (key: string, action: () => Promise<unknown>) => {
  if (busyIds.value.includes(key)) return
  busyIds.value.push(key)
  try { await action() }
  catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.save'))) }
  finally { busyIds.value = busyIds.value.filter(item => item !== key) }
}
const approveAsset = (asset: VisualAsset) => runAction(`asset-${asset.id}`, async () => {
  await setVisualAssetStatus(asset.id, 'approved'); if (asset.project_id === props.projectId) emit('changed')
})
const approveImage = (imageId: number, task: ReferenceImageTask) => runAction(`image-${imageId}`, async () => {
  await approveReferenceImage(imageId)
  if (task.project_id === props.projectId) { emit('changed'); await refresh() }
})
const taskAction = (task: ReferenceImageTask, resume: boolean) => runAction(`task-${task.id}`, async () => {
  const scriptTaskId = taskScriptContexts.get(task.id) ?? props.scriptTaskId
  const result = await (resume ? continueReferenceImageTask(task.id) : suspendReferenceImageTask(task.id))
  receiveTask(result, scriptTaskId)
  if (resume) watchTask(result, scriptTaskId)
})
const bindScene = () => {
  const subjectId = selectedOwner.value?.subjectId; const sceneId = bindSceneId.value
  if (!subjectId || !sceneId) return
  return runAction(`bind-${sceneId}`, async () => { await bindSceneReferenceSubject(sceneId, subjectId); emit('bound', sceneId, subjectId); ElMessage.success(t('referenceLibrary.bound')) })
}
watch(() => props.projectId, () => {
  loadSequence += 1; stops.forEach(stop => stop()); stops.clear(); subjects.value = []; tasks.value = []
  selectedOwnerKey.value = null; selectedTaskId.value = null; void refresh()
}, { immediate: true })
watch(() => props.characters, applyLocation)
watch(() => props.scenes, applyLocation)
watch(() => route.query, () => { if (!loading.value) applyLocation() })
watch(generateDialog, value => { if (!value) { promptSequence += 1; promptLoading.value = false } })
onMounted(() => window.addEventListener('focus', refresh))
onBeforeUnmount(() => { loadSequence += 1; promptSequence += 1; stops.forEach(stop => stop()); window.removeEventListener('focus', refresh) })
</script>

<template>
  <section class="reference-library" v-loading="loading">
    <div class="library-heading">
      <p>{{ t('referenceLibrary.description') }}</p>
      <el-button :icon="Refresh" @click="refresh">{{ t('referenceLibrary.refresh') }}</el-button>
    </div>
    <div class="library-toolbar">
      <el-segmented :model-value="category" :options="categories.map(value => ({ value, label: t(`referenceLibrary.categories.${value}`) }))" @change="selectCategory($event as ReferenceCategory)" />
      <el-button v-if="category !== 'character'" :disabled="projectId === null" :icon="Plus" @click="openSubjectEditor()">{{ t('referenceLibrary.addSubject', { category: t(`referenceLibrary.categories.${category}`) }) }}</el-button>
    </div>
    <el-alert v-if="catalogFailed" type="warning" :closable="false" :title="t('referenceLibrary.catalogFailed')" />
    <p v-if="category === 'character'" class="character-help">{{ t('referenceLibrary.characterHelp') }}</p>
    <el-alert v-if="locationUnavailable" type="warning" :closable="false" :title="t('visualBible.errors.targetUnavailable')" />
    <el-empty v-if="owners.length === 0" :description="t(category === 'character' ? 'referenceLibrary.noCharacters' : 'referenceLibrary.noSubjects')" />
    <template v-else>
      <el-select :model-value="selectedOwnerKey" class="owner-selector" :aria-label="t('referenceLibrary.owner')" @change="selectOwner">
        <el-option v-for="owner in owners" :key="owner.key" :value="owner.key" :label="`${owner.name} · ${t('referenceLibrary.confirmedCount', { count: approvedCount(owner) })}`" />
      </el-select>
      <template v-if="selectedOwner">
        <header v-if="category !== 'character'" class="owner-heading"><div><p v-if="selectedOwner.description">{{ selectedOwner.description }}</p><p v-if="selectedOwner.negativeConstraints">{{ t('referenceLibrary.constraints') }}：{{ selectedOwner.negativeConstraints }}</p></div>
          <el-button @click="openSubjectEditor(true)">{{ t('referenceLibrary.editSubject') }}</el-button>
        </header>
        <div v-if="category === 'scene' && scenes.length" class="scene-binding">
          <span>{{ t('referenceLibrary.boundScenes') }}：{{ boundScenes.map(scene => scene.name).join('、') || t('referenceLibrary.notBound') }}</span>
          <el-select v-model="bindSceneId" :placeholder="t('referenceLibrary.selectScriptScene')" :aria-label="t('referenceLibrary.selectScriptScene')"><el-option v-for="scene in scenes" :key="scene.id" :value="scene.id" :label="scene.name" /></el-select>
          <el-button :disabled="bindSceneId === null" @click="bindScene">{{ t('referenceLibrary.bind') }}</el-button>
        </div>
        <div v-if="category === 'scene'" class="scene-scope">
          <span>{{ t('referenceLibrary.sceneScope') }}</span>
          <el-select :model-value="selectedSceneScope" :aria-label="t('referenceLibrary.sceneScope')" @change="selectSceneScope"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in sceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" /></el-select>
          <p>{{ t('referenceLibrary.sceneScopeHelp') }}</p>
        </div>
        <div class="role-grid">
          <article v-for="role in categoryRoles(category)" :key="role" class="role-card">
            <strong>{{ roleLabel(role) }}</strong><span>{{ t('referenceLibrary.confirmedCount', { count: currentAssets.filter(asset => asset.role === role && asset.status === 'approved').length }) }}</span>
            <div><el-button size="small" :disabled="category === 'scene' && !sceneScopeEditable" @click="openUpload(role)">{{ t('referenceLibrary.upload') }}</el-button><el-button size="small" :disabled="tools.length === 0 || category === 'scene' && !sceneScopeEditable" @click="openGenerator(role)">{{ t('referenceLibrary.generate') }}</el-button></div>
          </article>
        </div>
        <div class="assets-heading"><h3>{{ t('referenceLibrary.images') }}</h3><el-segmented v-model="statusFilter" :options="['all', 'draft', 'approved'].map(value => ({ value, label: t(`visualBible.review.${value}`) }))" /></div>
        <div class="image-grid">
          <article v-for="asset in filteredAssets" :key="asset.id" class="asset-card">
            <el-image v-if="assetImageUrl(asset)" :src="assetImageUrl(asset)!" :preview-src-list="[assetImageUrl(asset)!]" :alt="assetLabel(asset)" fit="contain" preview-teleported />
            <div v-else class="image-placeholder">{{ t('visualBible.assets.noLocalPreview') }}</div>
            <strong>{{ roleLabel(asset.role) }} · v{{ asset.version }}</strong>
            <span v-if="category === 'character' && asset.role !== 'identity_face'">{{ applicabilityLabel(asset) }}</span>
            <el-button v-if="asset.status === 'draft'" type="success" plain :icon="Check" :loading="busyIds.includes(`asset-${asset.id}`)" @click="approveAsset(asset)">{{ t('visualBible.approve') }}</el-button>
            <el-tag v-else :type="statusType(asset.status)">{{ t(`visualBible.status.${asset.status}`) }}</el-tag>
          </article>
        </div>
        <el-empty v-if="filteredAssets.length === 0" :image-size="60" :description="t('referenceLibrary.noImages')" />
        <section v-if="currentTasks.length" class="task-history">
          <h3>{{ t('referenceLibrary.history') }}</h3>
          <el-select v-model="selectedTaskId" :aria-label="t('referenceLibrary.history')" @change="syncLocation(selectedOwner, $event)"><el-option v-for="task in currentTasks" :key="task.id" :value="task.id" :label="`#${task.id} · ${task.tool_name} · ${t(`visualBible.references.status.${task.status}`)}`" /></el-select>
          <template v-if="displayedTask">
            <div class="task-actions"><el-tag :type="statusType(displayedTask.status)">{{ t(`visualBible.references.status.${displayedTask.status}`) }}</el-tag><span>{{ t('referenceLibrary.updatedAt', { time: new Date(displayedTask.updated_at).toLocaleString() }) }}</span>
              <el-button v-if="['running', 'pending'].includes(displayedTask.status)" :loading="busyIds.includes(`task-${displayedTask.id}`)" @click="taskAction(displayedTask, false)">{{ t('visualBible.references.suspend') }}</el-button>
              <el-button v-if="['failed', 'suspended'].includes(displayedTask.status)" :loading="busyIds.includes(`task-${displayedTask.id}`)" @click="taskAction(displayedTask, true)">{{ t('visualBible.references.continue') }}</el-button>
            </div>
            <el-progress :percentage="taskProgress(displayedTask)" />
            <el-alert v-if="displayedTask.error_code" type="warning" :closable="false" :title="t('referenceLibrary.errors.generate')" />
            <div v-for="candidate in displayedTask.candidates" :key="candidate.candidate_index" class="candidate">
              <strong>{{ t('visualBible.references.candidate', { index: candidate.candidate_index }) }}</strong>
              <div class="image-grid">
                <template v-for="role in taskRoles(displayedTask)" :key="role">
                  <article v-for="image in candidate.roles[role]?.images || []" :key="image.id" class="asset-card">
                    <el-image :src="image.image_url" :preview-src-list="[image.image_url]" :alt="roleLabel(role)" fit="contain" preview-teleported /><strong>{{ roleLabel(role) }}</strong>
                    <el-tag v-if="image.promoted_asset_id" type="success">{{ t('visualBible.status.approved') }}</el-tag>
                    <el-button v-else type="success" plain :loading="busyIds.includes(`image-${image.id}`)" @click="approveImage(image.id, displayedTask)">{{ t('visualBible.approve') }}</el-button>
                  </article>
                  <span v-if="!candidate.roles[role]?.images.length" class="candidate-placeholder">{{ roleLabel(role) }} · {{ t(`visualBible.references.status.${candidate.roles[role]?.status || 'pending'}`) }}</span>
                </template>
              </div>
            </div>
          </template>
        </section>
      </template>
    </template>
    <el-collapse v-if="historicalAssets.length" class="historical-materials"><el-collapse-item :title="t('referenceLibrary.historical')" name="historical"><p>{{ t('referenceLibrary.historicalHelp') }}</p><div class="image-grid"><article v-for="asset in historicalAssets" :key="asset.id" class="asset-card"><el-image v-if="assetImageUrl(asset)" :src="assetImageUrl(asset)!" :preview-src-list="[assetImageUrl(asset)!]" fit="contain" /><strong>{{ roleLabel(asset.role) }} · v{{ asset.version }}</strong><el-tag>{{ t(`visualBible.status.${asset.status}`) }}</el-tag></article></div></el-collapse-item></el-collapse>

    <el-dialog v-model="subjectDialog" :title="t(editedSubjectId === null ? 'referenceLibrary.newSubject' : 'referenceLibrary.editSubject')" width="min(620px, 94vw)">
      <el-form label-position="top"><el-form-item :label="t('referenceLibrary.name')" required><el-input v-model="subjectForm.name" /></el-form-item><el-form-item :label="t('referenceLibrary.appearance')"><el-input v-model="subjectForm.description" type="textarea" :rows="4" /></el-form-item><el-form-item :label="t('referenceLibrary.constraints')"><el-input v-model="subjectForm.negative_constraints" type="textarea" :rows="3" /></el-form-item></el-form>
      <template #footer><el-button @click="subjectDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="saving" :disabled="!subjectForm.name.trim()" @click="saveSubject">{{ t('projects.save') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="uploadDialog" :title="t('referenceLibrary.uploadTitle', { name: editorOwner?.name || '' })" width="min(620px, 94vw)">
      <el-form label-position="top"><el-form-item :label="t('referenceLibrary.purpose')"><el-select v-model="uploadForm.role"><el-option v-for="role in roleOptions" :key="role" :value="role" :label="roleLabel(role)" /></el-select></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'scene'" :label="t('referenceLibrary.sceneScope')"><el-select v-model="uploadForm.scene_scope"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in editorSceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" :disabled="option.status === 'archived'" /></el-select><p class="help">{{ t('referenceLibrary.sceneScopeHelp') }}</p></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'character' && uploadForm.role !== 'identity_face'" :label="t('referenceLibrary.applicability')"><el-select v-model="uploadForm.outfit_variant_id" clearable :placeholder="t('referenceLibrary.anyOutfit')"><el-option v-for="outfit in outfitOptions" :key="outfit.id" :value="outfit.id" :label="`${outfit.name} · v${outfit.version}`" /></el-select><p class="help">{{ t('referenceLibrary.outfitHelp') }}</p></el-form-item>
        <el-form-item :label="t('visualBible.image')"><input :key="fileInputKey" type="file" accept="image/png,image/jpeg,image/webp" multiple @change="selectedFiles = Array.from(($event.target as HTMLInputElement).files || [])" /></el-form-item>
        <el-alert type="info" :closable="false" :title="t('referenceLibrary.uploadHelp')" />
      </el-form><template #footer><el-button @click="uploadDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="saving" :disabled="selectedFiles.length === 0" @click="saveUpload">{{ t('projects.save') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="generateDialog" :title="t('referenceLibrary.generateTitle', { name: editorOwner?.name || '' })" width="min(980px, 96vw)" top="4vh" destroy-on-close>
      <el-form label-position="top">
        <div class="form-grid"><el-form-item :label="t('visualBible.references.tool')"><el-select v-model="generateForm.tool_preset_id" @change="configurationChanged"><el-option v-for="tool in editorTools" :key="tool.id" :value="tool.id" :label="tool.name" /></el-select></el-form-item><el-form-item :label="t('referenceLibrary.candidateCount')"><el-input-number v-model="generateForm.candidate_count" :min="1" :max="4" /></el-form-item></div>
        <el-form-item :label="t('referenceLibrary.selectedPurposes')"><el-checkbox-group v-model="generateForm.roles" @change="rolesChanged"><el-checkbox v-for="role in roleOptions" :key="role" :value="role">{{ roleLabel(role) }}</el-checkbox></el-checkbox-group><p class="help">{{ t('referenceLibrary.rolesHelp') }}</p></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'scene'" :label="t('referenceLibrary.sceneScope')"><el-select v-model="generateForm.scene_scope" @change="configurationChanged"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in editorSceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" :disabled="option.status === 'archived'" /></el-select><p class="help">{{ t('referenceLibrary.sceneScopeHelp') }}</p></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'character' && generateForm.roles.some(role => role !== 'identity_face')" :label="t('referenceLibrary.applicability')"><el-select v-model="generateForm.outfit_variant_id" clearable :placeholder="t(ambiguousOutfits ? 'referenceLibrary.chooseOutfit' : 'referenceLibrary.anyOutfit')" @change="configurationChanged"><el-option v-for="outfit in outfitOptions" :key="outfit.id" :value="outfit.id" :label="`${outfit.name} · v${outfit.version}`" /></el-select><p class="help">{{ t(ambiguousOutfits && generateForm.outfit_variant_id === null ? 'referenceLibrary.ambiguousOutfits' : 'referenceLibrary.outfitHelp') }}</p></el-form-item>
        <el-form-item :label="t('referenceLibrary.inputImages')"><el-segmented v-model="generateForm.source_mode" :options="['auto', 'none', 'manual'].map(value => ({ value, label: t(`referenceLibrary.sourceModes.${value}`) }))" @change="configurationChanged" />
          <p v-if="generateForm.source_mode === 'auto'" class="help">{{ t(editorOwner?.category !== 'character' ? 'referenceLibrary.autoSubjectHelp' : !toolSupportsImages && autoSource ? 'referenceLibrary.autoTextFallback' : autoSource ? 'referenceLibrary.autoFaceHelp' : 'referenceLibrary.noAutoFace', { name: editorOwner?.name || '' }) }}</p>
          <el-select v-if="generateForm.source_mode === 'manual'" v-model="generateForm.source_asset_ids" multiple :placeholder="t('referenceLibrary.selectSources')" @change="configurationChanged"><el-option v-for="asset in sourceOptions" :key="asset.id" :value="asset.id" :label="assetLabel(asset)" /></el-select>
          <div v-if="effectiveSourceIds.length" class="source-images"><el-image v-for="id in effectiveSourceIds" :key="id" :src="`/api/visual-bible/assets/${id}/file`" fit="contain" /></div>
        </el-form-item>
        <el-alert v-if="!sourceSupported" type="warning" :closable="false" :title="t('referenceLibrary.unsupportedSources')" />
        <el-form-item v-if="requiresCanvas" :label="t('referenceInputs.canvas')" required><el-select v-model="generateForm.canvas_asset_id" clearable :placeholder="t('referenceLibrary.selectCanvas')" @change="configurationChanged"><el-option v-for="asset in sourceOptions" :key="asset.id" :value="asset.id" :label="assetLabel(asset)" /></el-select><p class="help">{{ t('referenceLibrary.canvasHelp') }}</p></el-form-item>
        <el-alert v-if="requiresCanvas && generateForm.canvas_asset_id === null" type="warning" :closable="false" :title="t('referenceLibrary.canvasRequired')" />
        <el-alert v-if="!withinCapacity" type="warning" :closable="false" :title="t('referenceInputs.capacity', { count: imageCapacity })" />
        <div class="prompt-heading"><strong>{{ t('referenceLibrary.prompts') }}</strong><el-button :icon="Refresh" :loading="promptLoading" :disabled="generateForm.roles.length === 0 || generateForm.tool_preset_id === null" @click="refreshPrompts()">{{ t('referenceLibrary.refreshPrompts') }}</el-button></div>
        <div v-loading="promptLoading"><el-tabs><el-tab-pane v-for="role in generateForm.roles" :key="role" :label="roleLabel(role)"><el-form-item :label="t('imageSpecs.positivePrompt')"><el-input :model-value="generateForm.prompts[role]?.positive || ''" type="textarea" :rows="4" @update:model-value="generateForm.prompts[role] = { positive: $event, negative: generateForm.prompts[role]?.negative || '' }" /></el-form-item><el-collapse><el-collapse-item :title="t('imageSpecs.negativePromptTitle')" :name="role"><el-input :model-value="generateForm.prompts[role]?.negative || ''" type="textarea" :rows="2" @update:model-value="generateForm.prompts[role] = { positive: generateForm.prompts[role]?.positive || '', negative: $event }" /></el-collapse-item></el-collapse></el-tab-pane></el-tabs></div>
        <el-alert class="request-summary" type="info" :closable="false" :title="t('referenceLibrary.requestCount', { count: requestCount })" />
      </el-form><template #footer><el-button @click="generateDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="submitting" :disabled="!canCreate" @click="submitGeneration">{{ t('referenceLibrary.submit') }}</el-button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.reference-library { padding: 20px; background: white; border: 1px solid var(--panel-border); border-radius: 8px; min-width: 0; }
.library-heading, .library-toolbar, .owner-heading, .assets-heading, .prompt-heading, .task-actions, .scene-binding { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:16px; }
h2,h3,p { margin:0; } h2 { font-size:18px; } h3 { font-size:16px; } p,.help,.task-actions span { color:var(--text-secondary); font-size:13px; line-height:1.6; } .library-heading p,.owner-heading p { margin-top:7px; }
.owner-selector { max-width:520px; margin:16px 0; } .scene-binding { justify-content:flex-start; padding:12px; background:var(--bg-secondary); } .scene-binding .el-select { width:260px; }
.role-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(175px,1fr)); gap:12px; margin-bottom:24px; } .role-card { display:grid; gap:10px; padding:12px; border:1px solid var(--panel-border); border-radius:8px; } .role-card span { color:var(--text-secondary); font-size:13px; } .role-card > div { display:flex; flex-wrap:wrap; gap:8px; } .role-card :deep(.el-button) { margin-left:0; }
.image-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:14px; } .asset-card { display:flex; flex-direction:column; align-items:flex-start; gap:9px; min-width:0; border:1px solid var(--panel-border); border-radius:8px; padding:12px; font-size:13px; } .asset-card .el-image,.image-placeholder { width:100%; height:190px; background:#f4f6f9; } .image-placeholder { display:grid; place-items:center; color:var(--text-secondary); }
.task-history { margin-top:24px; border-top:1px solid var(--panel-border); padding-top:18px; } .task-history > .el-select { max-width:520px; margin:14px 0; } .task-actions { justify-content:flex-start; margin-top:8px; } .candidate { margin-top:20px; } .candidate > strong { display:block; margin-bottom:12px; } .candidate-placeholder { padding:14px; color:var(--text-secondary); }
.historical-materials { margin-top:20px; } .historical-materials p { margin-bottom:14px; } .form-grid { display:grid; grid-template-columns:2fr 1fr; gap:18px; } .help { width:100%; margin-top:8px; } .source-images { display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; } .source-images .el-image { width:80px; height:90px; } .request-summary { margin-top:16px; }
.character-help { margin:8px 0; } .library-heading { gap:8px; margin-bottom:10px; } .library-heading p { flex:1; margin:0; } .owner-selector { margin:10px 0 14px; }
.scene-scope { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px; } .scene-scope .el-select { width:min(520px,100%); } .scene-scope p { flex-basis:100%; }
@media(max-width:700px) { .reference-library { padding:14px; } .form-grid { grid-template-columns:1fr; gap:0; } .role-grid { grid-template-columns:1fr; } .image-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .asset-card .el-image { height:150px; } .scene-binding .el-select,.owner-selector { width:100%; } .library-heading { align-items:flex-start; } }
</style>

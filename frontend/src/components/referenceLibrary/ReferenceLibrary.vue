<script setup lang="ts">
import InfoTip from '@/components/workspace/InfoTip.vue'
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
  type ReferenceRole, type ReferenceSubject, type ReferenceSize, type VisualProfile, visualProfileRefs,
} from '@/api/referenceImages'
import type { CharacterReferenceImage } from '@/api/characterReference'
import { assetImageUrl, autoFaceAsset, defaultReferenceSize, ownerAssets, sameReferenceSlot, validReferenceRoles, type QuickReferenceImage, type ReferenceOwner } from './referenceLibrary'
import ReferenceBatchGenerator from './ReferenceBatchGenerator.vue'
import ReferenceQuickPicker from './ReferenceQuickPicker.vue'
import VisualProfileEditor from './VisualProfileEditor.vue'

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
const quickDialog = ref(false)
const quickSelectedImageKey = ref<string | null>(null)
const quickConfirming = ref(false)
const quickReachedEnd = ref(false)
const approvedAssets = ref<Record<number, VisualAsset>>({})
let quickSession = 0
let libraryDisposed = false
const uploadDialog = ref(false)
const generateDialog = ref(false)
const batchContext = ref<{
  projectId: number; scriptTaskId: number | null; characters: Array<{ id: number; label: string }>
  subjects: ReferenceSubject[]; catalog: ReferenceCategoryDefinition[]; tools: ImageGenerationTool[]; assets: VisualAsset[]
  outfits: OutfitVariant[]; currentCharacters: Array<{ outline_character_id: number | null; outfit_variant_id: number | null }>
  scenes: Array<{ id: number; name: string; reference_subject_id?: number | null }>; sceneVersions: SceneVisualVersion[]
  taskUpdates: ReferenceImageTask[]
} | null>(null)
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
const visualProfiles = ref<VisualProfile[]>([])
const previewReady = ref(false)
const visualDirty = ref(false)
const visualBusy = ref(false)
const profileRebuilt = ref(false)
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
  sizes: {} as Partial<Record<ReferenceRole, ReferenceSize>>,
  source_mode: 'auto' as 'auto' | 'none' | 'manual', source_asset_ids: [] as number[],
  prompts: {} as Partial<Record<ReferenceRole, { positive: string; negative: string }>> })

const owners = computed<ReferenceOwner[]>(() => category.value === 'character'
  ? props.characters.map(character => ({ key: `character:${character.id}`, category: 'character', name: character.label,
    characterId: character.id, subjectId: null, description: '', negativeConstraints: '' }))
  : subjects.value.filter(subject => subject.project_id === props.projectId && subject.entity_type === category.value).map(subject => ({
    key: `${subject.entity_type}:${subject.id}`, category: subject.entity_type, name: subject.name,
    characterId: null, subjectId: subject.id, description: subject.description, negativeConstraints: subject.negative_constraints,
    sceneDefinitionVersion: subject.scene_definition_version ?? 1,
  })))
const selectedOwner = computed(() => owners.value.find(owner => owner.key === selectedOwnerKey.value) ?? null)
const editingFixedScene = computed(() => subjectForm.entity_type === 'scene' && (editedSubjectId.value === null ||
  (subjects.value.find(subject => subject.id === editedSubjectId.value)?.scene_definition_version ?? 1) >= 2))
const sceneScopeOptions = computed(() => {
  if ((selectedOwner.value?.sceneDefinitionVersion ?? 1) >= 2) return []
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
// 确认接口返回的素材立即用于展示，父页面刷新完成后再交回其素材列表。
const availableAssets = computed(() => [...new Map([...props.assets, ...Object.values(approvedAssets.value)].map(asset => [asset.id, asset])).values()])
const currentAssets = computed(() => selectedOwner.value && props.projectId !== null
  ? ownerAssets(availableAssets.value, { ...selectedOwner.value, ...(category.value === 'scene' ? { sceneVersionId: selectedSceneScope.value || null } : {}) }, props.projectId) : [])
const filteredAssets = computed(() => currentAssets.value.filter(asset => statusFilter.value === 'all' || asset.status === statusFilter.value))
const currentTasks = computed(() => selectedOwner.value ? tasks.value.filter(task => task.project_id === props.projectId && task.entity_type === selectedOwner.value!.category &&
  (selectedOwner.value!.category === 'character' ? task.entity_id === selectedOwner.value!.characterId : task.reference_subject_id === selectedOwner.value!.subjectId &&
    (selectedOwner.value!.category !== 'scene' || (task.entity_id ?? null) === (selectedSceneScope.value || null)))).sort((a, b) => b.id - a.id) : [])
const displayedTask = computed(() => currentTasks.value.find(task => task.id === selectedTaskId.value) ?? null)
const categoryRoles = (value: ReferenceCategory): ReferenceRole[] => validReferenceRoles(value, catalog.value.find(item => item.entity_type === value)?.roles.map(item => item.role) ?? [])
const roleOptions = computed(() => categoryRoles(editorOwner.value?.category ?? category.value))
const outfitOptions = computed(() => editorOutfits.value.filter(outfit => outfit.outline_character_id === editorOwner.value?.characterId && outfit.status !== 'archived'))
const ambiguousOutfits = computed(() => editorCurrentOutfitIds.value.length > 1)
const sourceOptions = computed(() => editorAssets.value.filter(asset => asset.role !== 'identity_half_body' && asset.project_id === editorProjectId.value &&
  asset.status === 'approved' && (Boolean(asset.local_path) || selectedTool.value?.provider === 'comfyui' && Boolean(asset.renderer_locator)) &&
  ['character', 'scene', 'prop'].includes(asset.entity_type)))
const autoSource = computed(() => editorOwner.value?.category === 'character' && editorProjectId.value !== null &&
  generateForm.roles.some(role => role !== 'identity_face')
  ? autoFaceAsset(editorAssets.value, editorOwner.value, editorProjectId.value) : null)
const selectedTool = computed(() => editorTools.value.find(tool => tool.id === generateForm.tool_preset_id))
const supportsSize = (tool: ImageGenerationTool) => tool.provider === 'openai_images_compatible' ||
  ['render.width', 'render.height'].every(source => tool.bindings?.bindings?.some(binding => binding.source === source))
const toolSupportsSize = computed(() => Boolean(selectedTool.value && supportsSize(selectedTool.value)))
const sizesValid = computed(() => generateForm.roles.every(role => {
  const size = generateForm.sizes[role]
  return size && [size.width, size.height].every(value => Number.isInteger(value) && value >= 256 && value <= 2048 && value % 32 === 0)
}))
const requiresCanvas = computed(() => Boolean(selectedTool.value?.capabilities.reference_images?.requires_canvas))
// 切换为不消费画布的工具后，隐藏字段不能继续参与容量检查或请求。
const effectiveCanvasId = computed(() => requiresCanvas.value ? generateForm.canvas_asset_id : null)
const imageCapacity = computed(() => {
  const tool = selectedTool.value; const config = tool?.capabilities.reference_images
  const max = config?.max_images ?? 0
  return tool?.provider === 'comfyui' ? Math.min(max, tool.bindings.reference_slots?.length ?? 0)
    : config?.transport && config.transport !== 'none' ? max : 0
})
const toolSupportsImages = computed(() => imageCapacity.value > 0 && Boolean(selectedTool.value?.capabilities.features?.some(feature => feature === 'reference_image' || feature === 'img2img')))
const effectiveSourceIds = computed(() => generateForm.source_mode === 'none' ? []
  : generateForm.source_mode === 'manual' ? generateForm.source_asset_ids : autoSource.value && toolSupportsImages.value ? [autoSource.value.id] : [])
const selectedSourcesAvailable = computed(() => [...effectiveSourceIds.value, ...(effectiveCanvasId.value ? [effectiveCanvasId.value] : [])]
  .every(id => sourceOptions.value.some(asset => asset.id === id)))
const sourcePreview = (id: number) => {
  const asset = editorAssets.value.find(item => item.id === id)
  return asset ? assetImageUrl(asset) : null
}
const sourceSupported = computed(() => generateForm.source_mode !== 'manual' || effectiveSourceIds.value.length === 0 || toolSupportsImages.value)
const withinCapacity = computed(() => new Set([
  ...effectiveSourceIds.value, ...(effectiveCanvasId.value ? [effectiveCanvasId.value] : []),
]).size <= imageCapacity.value)
const promptsReady = computed(() => generateForm.roles.length > 0 && generateForm.roles.every(role => Boolean(generateForm.prompts[role]?.positive.trim())))
const canSubmit = computed(() => previewReady.value && !visualDirty.value && !visualBusy.value && editorOwner.value !== null && generateForm.tool_preset_id !== null && promptsReady.value && sourceSupported.value && toolSupportsSize.value && sizesValid.value &&
  (generateForm.source_mode !== 'manual' || generateForm.source_asset_ids.length > 0) && !promptLoading.value)
const canCreate = computed(() => canSubmit.value && selectedSourcesAvailable.value && (!requiresCanvas.value || generateForm.canvas_asset_id !== null) && withinCapacity.value &&
  (editorOwner.value?.category !== 'scene' || generateForm.scene_scope === 0 || editorSceneScopeOptions.value.some(option => option.id === generateForm.scene_scope && option.status !== 'archived')) &&
  (!ambiguousOutfits.value || generateForm.roles.every(role => role === 'identity_face') || generateForm.outfit_variant_id !== null))
const requestCount = computed(() => generateForm.roles.length * generateForm.candidate_count)
const boundScenes = computed(() => props.scenes.filter(scene => scene.reference_subject_id === selectedOwner.value?.subjectId))
const historicalAssets = computed(() => props.assets.filter(asset => ['style', 'control'].includes(asset.entity_type) ||
  asset.entity_type === 'scene' && !asset.reference_subject_id))
const locationUnavailable = computed(() => !loading.value && (
  (Number(route.query.character_id) > 0 || Number(route.query.reference_subject_id) > 0) && !selectedOwner.value ||
  Number(route.query.reference_task_id) > 0 && !displayedTask.value || category.value === 'scene' && !sceneScopeAvailable.value))
const approvedCount = (owner: ReferenceOwner) => props.projectId === null ? 0 : ownerAssets(availableAssets.value, owner, props.projectId).filter(asset => asset.status === 'approved').length
const taskRoles = (task: ReferenceImageTask) => task.selected_roles?.length ? task.selected_roles :
  Object.keys(task.prompts || {}) as ReferenceRole[]
const taskHasRetiredRole = (task: ReferenceImageTask) => taskRoles(task).some(role => role === 'identity_half_body')
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

const quickOwners = computed(() => owners.value.map(owner => ({ ...owner, approvedCount: approvedCount(owner) })))
// 转存关联不会在撤回时删除；主页面和弹窗都以素材当前状态判断是否已确认。
const referenceImageStatus = (image: CharacterReferenceImage) => availableAssets.value.find(asset => asset.id === image.promoted_asset_id)?.status
  ?? image.promoted_asset_status ?? (image.promoted_asset_id ? 'approved' : 'draft')
const quickAssets = computed<QuickReferenceImage[]>(() => currentAssets.value
  .filter(asset => categoryRoles(category.value).includes(asset.role as ReferenceRole))
  .map(asset => ({
    key: `asset-${asset.id}`, imageUrl: assetImageUrl(asset), label: `${roleLabel(asset.role)} · v${asset.version}`,
    applicability: category.value === 'character' && asset.role !== 'identity_face' ? applicabilityLabel(asset) : null,
    approved: asset.status === 'approved', canApprove: asset.status === 'draft', target: { kind: 'asset', id: asset.id },
  })))
const quickCandidates = computed<QuickReferenceImage[]>(() => {
  const task = displayedTask.value
  if (!task) return []
  return task.candidates.flatMap(candidate => categoryRoles(category.value).flatMap(role => {
    const run = candidate.roles[role]
    return (run?.images || []).map(image => ({
      key: `image-${image.id}`, imageUrl: image.image_url,
      label: t('referenceLibrary.quick.candidate', { index: candidate.candidate_index, role: roleLabel(role) }),
      applicability: category.value === 'character' && role !== 'identity_face'
        ? task.outfit_variant_id ? props.outfits.find(outfit => outfit.id === task.outfit_variant_id)?.name || t('referenceLibrary.selectedOutfit') : t('referenceLibrary.anyOutfit') : null,
      approved: referenceImageStatus(image) === 'approved', canApprove: referenceImageStatus(image) === 'draft' && run?.status === 'succeeded',
      target: { kind: 'image' as const, id: image.id, taskId: task.id },
    }))
  }))
})

const syncLocation = (owner: ReferenceOwner | null, taskId: number | null = null) => {
  if (props.projectId === null || route.path !== '/visual-bible') return
  const query = { ...route.query, tab: 'references', reference_category: category.value,
    script_task_id: props.scriptTaskId ? String(props.scriptTaskId) : undefined,
    character_id: owner?.characterId ? String(owner.characterId) : undefined,
    reference_subject_id: owner?.subjectId ? String(owner.subjectId) : undefined,
    scene_visual_version_id: owner?.category === 'scene' && selectedSceneScope.value > 0 ? String(selectedSceneScope.value) : undefined,
    reference_task_id: taskId ? String(taskId) : undefined,
    reference_task_kind: taskId ? 'referenceImage' : undefined }
  return router.replace({ query })
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
  selectedSceneScope.value = category.value === 'scene' && (selectedOwner.value?.sceneDefinitionVersion ?? 1) < 2 ? requestedSceneVersionId > 0 ? requestedSceneVersionId : exactTask?.entity_id ?? 0 : 0
  selectedTaskId.value = requestedTaskId > 0 ? currentTasks.value.some(task => task.id === requestedTaskId) ? requestedTaskId : null
    : currentTasks.value[0]?.id ?? null
}
const receiveTask = (task: ReferenceImageTask, scriptTaskId: number | null, terminal = false) => {
  if (batchContext.value?.projectId === task.project_id && batchContext.value.taskUpdates.some(item => item.id === task.id)) {
    batchContext.value.taskUpdates = [task, ...batchContext.value.taskUpdates.filter(item => item.id !== task.id)]
  }
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
  return syncLocation(selectedOwner.value)
}
const selectOwner = (key: string) => {
  selectedOwnerKey.value = key; selectedSceneScope.value = 0; selectedTaskId.value = currentTasks.value[0]?.id ?? null; bindSceneId.value = null
  return syncLocation(selectedOwner.value)
}
const selectSceneScope = (scope: number) => {
  selectedSceneScope.value = (selectedOwner.value?.sceneDefinitionVersion ?? 1) >= 2 ? 0 : scope; selectedTaskId.value = currentTasks.value[0]?.id ?? null
  return syncLocation(selectedOwner.value)
}
const resetQuickPicker = () => {
  quickSession += 1; quickDialog.value = false; quickSelectedImageKey.value = null
  quickConfirming.value = false; quickReachedEnd.value = false
}
const openQuickPicker = () => {
  if (props.projectId === null || loading.value || catalogFailed.value || !selectedOwner.value || locationUnavailable.value) return
  quickSession += 1; quickSelectedImageKey.value = null; quickReachedEnd.value = false; quickDialog.value = true
  selectedTaskId.value = currentTasks.value[0]?.id ?? null
  void syncLocation(selectedOwner.value, selectedTaskId.value)
}
const closeQuickPicker = () => { if (!quickConfirming.value) resetQuickPicker() }
const quickChangeCategory = (value: ReferenceCategory) => { if (!quickConfirming.value && !loading.value && categories.value.includes(value)) return selectCategory(value) }
const quickChangeOwner = (key: string) => { if (!quickConfirming.value && !loading.value && owners.value.some(owner => owner.key === key)) return selectOwner(key) }
const quickChangeScope = (scope: number) => { if (!quickConfirming.value && !loading.value && (scope === 0 || sceneScopeOptions.value.some(option => option.id === scope))) return selectSceneScope(scope) }
const quickChangeTask = (id: number) => {
  if (quickConfirming.value || loading.value || !currentTasks.value.some(task => task.id === id)) return
  selectedTaskId.value = id
  return syncLocation(selectedOwner.value, id)
}
const quickSelectImage = (key: string) => {
  if (!quickConfirming.value && !loading.value && [...quickCandidates.value, ...quickAssets.value].some(image => image.key === key)) quickSelectedImageKey.value = key
}
const moveQuickOwner = (direction: -1 | 1) => {
  if (quickConfirming.value || loading.value) return
  const index = owners.value.findIndex(owner => owner.key === selectedOwnerKey.value)
  const next = index >= 0 ? owners.value[index + direction] : undefined
  if (next) return selectOwner(next.key)
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
  const selection = { ...uploadForm }
  const files = [...selectedFiles.value]
  let uploaded = 0
  saving.value = true
  try {
    for (const file of files) {
      const form = new FormData()
      form.append('file', file); form.append('entity_type', owner.category); form.append('role', selection.role); form.append('approve', 'false')
      if (owner.characterId) form.append('entity_id', String(owner.characterId))
      if (owner.category === 'scene' && (owner.sceneDefinitionVersion ?? 1) < 2 && selection.scene_scope > 0) form.append('entity_id', String(selection.scene_scope))
      if (owner.subjectId) form.append('reference_subject_id', String(owner.subjectId))
      if (selection.outfit_variant_id && selection.role !== 'identity_face') form.append('outfit_variant_id', String(selection.outfit_variant_id))
      await uploadVisualAsset(projectId, form)
      // 每张原图独立保存；保留失败和未处理文件，重试时不重复创建成功素材。
      uploaded += 1
      selectedFiles.value = selectedFiles.value.filter(item => item !== file)
    }
    uploadDialog.value = false
    ElMessage.success(t('referenceLibrary.uploadedDraft'))
  } catch (error) { ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.save'))) }
  finally {
    if (uploaded > 0) {
      fileInputKey.value += 1
      if (projectId === props.projectId) {
        if (owner.category === 'scene' && selectedOwner.value?.key === owner.key) {
          selectedSceneScope.value = selection.scene_scope; syncLocation(selectedOwner.value)
        }
        emit('changed')
      }
    }
    saving.value = false
  }
}
const requestPayload = (): ReferenceRequest | null => {
  if (!editorOwner.value || generateForm.tool_preset_id === null) return null
  return { entity_type: editorOwner.value.category, entity_id: editorOwner.value.category === 'scene' ? (editorOwner.value.sceneDefinitionVersion ?? 1) >= 2 ? null : generateForm.scene_scope || null : editorOwner.value.characterId,
    reference_subject_id: editorOwner.value.subjectId, outfit_variant_id: generateForm.outfit_variant_id,
    tool_preset_id: generateForm.tool_preset_id, roles: [...generateForm.roles],
    sizes: toolSupportsSize.value ? Object.fromEntries(generateForm.roles.map(role => [role, { ...generateForm.sizes[role]! }])) : {},
    canvas_asset_id: effectiveCanvasId.value,
    source_mode: generateForm.source_mode === 'auto' && !toolSupportsImages.value ? 'none' : generateForm.source_mode,
    source_asset_ids: generateForm.source_mode === 'manual' ? [...generateForm.source_asset_ids] : [] }
}
const confirmPromptReplacement = async () => {
  if (promptBaseline.value && JSON.stringify(generateForm.prompts) !== promptBaseline.value) {
    try { await ElMessageBox.confirm(t('referenceLibrary.replacePrompts'), t('referenceLibrary.refreshPrompts'), { type: 'warning' }) }
    catch { return false }
  }
  return true
}
const refreshPrompts = async (confirmReplacement = true, force = false) => {
  const payload = requestPayload(); const projectId = editorProjectId.value
  if (!payload || projectId === null || payload.roles.length === 0) return
  if (confirmReplacement && !await confirmPromptReplacement()) return
  const token = ++promptSequence; promptLoading.value = true; previewReady.value = false
  try {
    const result = await previewReferencePrompts(projectId, { ...payload, refresh_visual_profiles: force })
    if (token !== promptSequence || !generateDialog.value || projectId !== editorProjectId.value) return
    generateForm.prompts = result.prompts; promptBaseline.value = JSON.stringify(result.prompts)
    visualProfiles.value = result.visual_profiles || []; previewReady.value = visualProfiles.value.length > 0
    profileRebuilt.value = result.warnings?.includes('reference.profile_rebuilt') || false
  } catch (error) { if (token === promptSequence) ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.prompt'))) }
  finally { if (token === promptSequence) promptLoading.value = false }
}
const reextractProfiles = async () => {
  if (visualDirty.value || visualBusy.value || promptLoading.value) return
  try { await ElMessageBox.confirm(t('referenceLibrary.visual.reextractConfirm'), t('referenceLibrary.visual.reextract'), { type: 'warning' }) }
  catch { return }
  await refreshPrompts(true, true)
}
const profileUpdated = async (profiles: VisualProfile[]) => {
  visualProfiles.value = profiles; visualDirty.value = false; previewReady.value = false
  await refreshPrompts(false)
}
const openGenerator = (role: ReferenceRole) => {
  if (!selectedOwner.value) return
  editorProjectId.value = props.projectId; editorOwner.value = { ...selectedOwner.value }; inputContextScriptTaskId.value = props.scriptTaskId
  editorAssets.value = [...props.assets]; editorOutfits.value = [...props.outfits]; editorTools.value = [...props.tools]
  editorSceneScopeOptions.value = [...sceneScopeOptions.value]; generateForm.scene_scope = selectedSceneScope.value
  const sizedTools = props.tools.filter(supportsSize)
  Object.assign(generateForm, { tool_preset_id: sizedTools.find(tool => tool.is_default)?.id ?? sizedTools[0]?.id ?? props.tools[0]?.id ?? null,
    roles: [role], sizes: Object.fromEntries(roleOptions.value.map(item => [item, defaultReferenceSize(item)])),
    candidate_count: 2, outfit_variant_id: null, source_mode: 'auto', source_asset_ids: [], prompts: {} })
  generateForm.canvas_asset_id = null
  const outfitId = defaultOutfitId(editorOwner.value)
  generateForm.outfit_variant_id = role === 'identity_face' ? null : outfitId
  promptBaseline.value = ''; visualProfiles.value = []; previewReady.value = false; visualDirty.value = false; visualBusy.value = false
  generateDialog.value = true; void refreshPrompts(false)
}
const configurationChanged = () => {
  promptSequence += 1; promptLoading.value = false; previewReady.value = false
  if (visualDirty.value || visualBusy.value) return
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
      visual_profile_refs: visualProfileRefs(visualProfiles.value),
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
const openBatchGenerator = () => {
  if (props.projectId === null || catalogFailed.value || loading.value) return
  // 弹窗使用打开时的项目和设定快照，切换项目不能把已选主体提交到另一项目。
  batchContext.value = JSON.parse(JSON.stringify({ projectId: props.projectId, scriptTaskId: props.scriptTaskId,
    characters: props.characters, subjects: subjects.value, catalog: catalog.value, tools: props.tools,
    assets: props.assets, outfits: props.outfits, currentCharacters: props.currentCharacters || [],
    scenes: props.scenes, sceneVersions: props.sceneVersions || [], taskUpdates: [],
  }))
}
const batchSubmitted = (createdTasks: ReferenceImageTask[]) => {
  const scriptTaskId = batchContext.value?.scriptTaskId ?? null
  if (batchContext.value) batchContext.value.taskUpdates = [...batchContext.value.taskUpdates,
    ...createdTasks.filter(task => task.project_id === batchContext.value!.projectId && !batchContext.value!.taskUpdates.some(existing => existing.id === task.id))]
  for (const task of createdTasks) {
    receiveTask(task, scriptTaskId)
    if (['pending', 'running'].includes(task.status)) watchTask(task, scriptTaskId)
  }
  // 保持当前主体，不自动跳到整批最后一个对象。
  const current = createdTasks.find(task => task.entity_type === selectedOwner.value?.category &&
    (task.entity_type === 'character' ? task.entity_id === selectedOwner.value?.characterId : task.reference_subject_id === selectedOwner.value?.subjectId))
  if (current?.project_id === props.projectId) {
    if (current.entity_type === 'scene') selectedSceneScope.value = current.entity_id ?? 0
    selectedTaskId.value = current.id; syncLocation(selectedOwner.value, current.id)
  }
}
const runAction = async (key: string, action: () => Promise<unknown>, reportError = () => true) => {
  if (busyIds.value.includes(key)) return false
  busyIds.value.push(key)
  try { await action(); return true }
  catch (error) { if (reportError()) ElMessage.error(apiErrorMessage(error, t, t('referenceLibrary.errors.save'))); return false }
  finally { busyIds.value = busyIds.value.filter(item => item !== key) }
}
const syncAssetApproval = (approved: VisualAsset) => {
  if (libraryDisposed || approved.project_id !== props.projectId) return
  // 接口已原子撤回同槽旧图，立即同步两边状态，避免等待父页面刷新时仍显示多个确认入口。
  for (const asset of availableAssets.value) {
    if (asset.id !== approved.id && asset.status === 'approved' && sameReferenceSlot(asset, approved)) {
      approvedAssets.value[asset.id] = { ...asset, status: 'draft', approved_at: null }
    }
  }
  approvedAssets.value[approved.id] = approved
  for (const task of tasks.value.filter(item => item.project_id === approved.project_id)) {
    for (const candidate of task.candidates) for (const run of Object.values(candidate.roles)) {
      if (!run) continue
      for (const image of run.images) {
        const asset = image.promoted_asset_id ? approvedAssets.value[image.promoted_asset_id] : null
        if (asset) image.promoted_asset_status = asset.status
      }
      run.review_status = run.images.some(image => referenceImageStatus(image) === 'approved') ? 'approved' : 'draft'
    }
  }
}
const persistAssetApproval = async (asset: VisualAsset) => {
  const approved = await setVisualAssetStatus(asset.id, 'approved')
  syncAssetApproval(approved)
  return approved
}
const persistImageApproval = async (imageId: number, task: ReferenceImageTask) => {
  const approved = await approveReferenceImage(imageId)
  if (!libraryDisposed && approved.project_id === props.projectId) {
    const current = tasks.value.find(item => item.id === task.id && item.project_id === props.projectId)
    current?.candidates.forEach(candidate => Object.values(candidate.roles).forEach(run => {
      const image = run?.images.find(item => item.id === imageId)
      if (image && run) { image.promoted_asset_id = approved.id; image.promoted_asset_status = 'approved' }
    }))
    syncAssetApproval(approved)
  }
  return approved
}
const approveAsset = (asset: VisualAsset) => runAction(`asset-${asset.id}`, async () => {
  await persistAssetApproval(asset); if (asset.project_id === props.projectId) emit('changed')
})
const approveImage = (imageId: number, task: ReferenceImageTask) => runAction(`image-${imageId}`, async () => {
  await persistImageApproval(imageId, task)
  if (task.project_id === props.projectId) { emit('changed'); await refresh() }
})
/** 确认与定位按顺序执行；失败或上下文变化都不能触发下一对象的切换。 */
const confirmQuickImage = async (key: string | null = quickSelectedImageKey.value) => {
  const image = [...quickCandidates.value, ...quickAssets.value].find(item => item.key === key)
  const task = image?.target.kind === 'image' ? displayedTask.value : null
  const asset = image?.target.kind === 'asset' ? currentAssets.value.find(item => item.id === image.target.id) : null
  if (!quickDialog.value || quickConfirming.value || loading.value || locationUnavailable.value || !image?.canApprove || (!task && !asset)) return
  quickSelectedImageKey.value = image.key
  const context = { session: quickSession, projectId: props.projectId, scriptTaskId: props.scriptTaskId,
    category: category.value, ownerKey: selectedOwnerKey.value, scope: selectedSceneScope.value, taskId: selectedTaskId.value }
  const sessionActive = () => !libraryDisposed && quickDialog.value && quickSession === context.session &&
    props.projectId === context.projectId && props.scriptTaskId === context.scriptTaskId
  const selectionActive = () => sessionActive() && category.value === context.category && selectedOwnerKey.value === context.ownerKey &&
    selectedSceneScope.value === context.scope && selectedTaskId.value === context.taskId
  quickConfirming.value = true
  try {
    const succeeded = await runAction(image.key, () => asset ? persistAssetApproval(asset) : persistImageApproval(image.target.id, task!), selectionActive)
    if (!succeeded) return
    if (!selectionActive()) {
      if (!libraryDisposed && props.projectId === context.projectId) emit('changed')
      return
    }
    quickSelectedImageKey.value = null
    // 先完成路由定位，再触发父页面刷新，避免旧定位把自动切换退回上一对象。
    await syncLocation(selectedOwner.value, selectedTaskId.value)
    if (!selectionActive()) return
    const index = owners.value.findIndex(owner => owner.key === context.ownerKey)
    const next = index >= 0 ? owners.value[index + 1] : undefined
    if (context.category !== 'character' && next) await selectOwner(next.key)
    else if (index === owners.value.length - 1) quickReachedEnd.value = true
    if (!sessionActive()) return
    emit('changed')
    ElMessage.success(t('referenceLibrary.quick.confirmed'))
    await refresh()
  } finally { if (quickSession === context.session) quickConfirming.value = false }
}
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
  resetQuickPicker(); approvedAssets.value = {}
  loadSequence += 1
  // 已打开的批量弹窗仍属于原项目，只保留其生成订阅，其余列表订阅随项目切换释放。
  const batchIds = new Set(batchContext.value?.taskUpdates.map(task => task.id) || [])
  stops.forEach((stop, id) => { if (!batchIds.has(id)) { stop(); stops.delete(id) } })
  subjects.value = []; tasks.value = []
  selectedOwnerKey.value = null; selectedTaskId.value = null; void refresh()
}, { immediate: true })
watch(() => props.scriptTaskId, resetQuickPicker)
watch(() => props.assets, () => { approvedAssets.value = {} })
watch([category, selectedOwnerKey, selectedSceneScope, selectedTaskId], () => {
  quickSelectedImageKey.value = null; quickReachedEnd.value = false
}, { flush: 'sync' })
watch(() => props.characters, applyLocation)
watch(() => props.scenes, applyLocation)
watch(() => route.query, () => { if (!loading.value) applyLocation() })
watch(generateDialog, value => { if (!value) { promptSequence += 1; promptLoading.value = false } })
const refreshLibrary = async () => {
  // 素材归属与确认状态由父页面加载，用户刷新时同步更新图片列表。
  emit('changed')
  await refresh()
}
onMounted(() => window.addEventListener('focus', refreshLibrary))
onBeforeUnmount(() => { libraryDisposed = true; resetQuickPicker(); loadSequence += 1; promptSequence += 1; stops.forEach(stop => stop()); window.removeEventListener('focus', refreshLibrary) })
</script>

<template>
  <section class="reference-library" v-loading="loading">
    <div class="library-heading">
      <div class="title-with-info"><h2>{{ t('referenceLibrary.title') }}</h2><InfoTip :content="t('referenceLibrary.description')" :label="t('referenceLibrary.title')" /></div>
      <el-button type="primary" :icon="MagicStick" :disabled="projectId === null || loading || catalogFailed || catalog.length === 0 || tools.length === 0" @click="openBatchGenerator">{{ t('referenceLibrary.batch.title') }}</el-button>
      <el-button type="primary" plain :icon="Check" :disabled="projectId === null || loading || catalogFailed || !selectedOwner || locationUnavailable" @click="openQuickPicker">{{ t('referenceLibrary.quick.title') }}</el-button>
      <el-button :icon="Refresh" @click="refreshLibrary">{{ t('referenceLibrary.refresh') }}</el-button>
    </div>
    <div class="library-toolbar">
      <el-segmented :model-value="category" :options="categories.map(value => ({ value, label: t(`referenceLibrary.categories.${value}`) }))" @change="selectCategory($event as ReferenceCategory)" /><InfoTip v-if="category === 'character'" :content="t('referenceLibrary.characterHelp')" :label="t('referenceLibrary.categories.character')" />
      <el-button v-if="category !== 'character'" :disabled="projectId === null" :icon="Plus" @click="openSubjectEditor()">{{ t('referenceLibrary.addSubject', { category: t(`referenceLibrary.categories.${category}`) }) }}</el-button>
    </div>
    <el-alert v-if="catalogFailed" type="warning" :closable="false" :title="t('referenceLibrary.catalogFailed')" />
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
        <div v-if="category === 'scene' && (selectedOwner?.sceneDefinitionVersion ?? 1) < 2" class="scene-scope">
          <span class="field-with-info">{{ t('referenceLibrary.sceneScope') }}<InfoTip :content="t('referenceLibrary.sceneScopeHelp')" :label="t('referenceLibrary.sceneScope')" /></span>
          <el-select :model-value="selectedSceneScope" :aria-label="t('referenceLibrary.sceneScope')" @change="selectSceneScope"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in sceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" /></el-select>
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
            <el-image v-if="assetImageUrl(asset)" :src="assetImageUrl(asset)!" :preview-src-list="[assetImageUrl(asset)!]" :alt="assetLabel(asset)" fit="contain" lazy preview-teleported />
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
              <el-button v-if="['failed', 'suspended'].includes(displayedTask.status) && !taskHasRetiredRole(displayedTask)" :loading="busyIds.includes(`task-${displayedTask.id}`)" @click="taskAction(displayedTask, true)">{{ t('visualBible.references.continue') }}</el-button>
            </div>
            <el-progress :percentage="taskProgress(displayedTask)" />
            <el-alert v-if="displayedTask.error_code" type="warning" :closable="false" :title="t('referenceLibrary.errors.generate')" />
            <div v-for="candidate in displayedTask.candidates" :key="candidate.candidate_index" class="candidate">
              <strong>{{ t('visualBible.references.candidate', { index: candidate.candidate_index }) }}</strong>
              <div class="image-grid">
                <template v-for="role in taskRoles(displayedTask)" :key="role">
                  <article v-for="image in candidate.roles[role]?.images || []" :key="image.id" class="asset-card">
                    <el-image :src="image.image_url" :preview-src-list="[image.image_url]" :alt="roleLabel(role)" fit="contain" lazy preview-teleported /><strong>{{ roleLabel(role) }}</strong>
                    <el-tag v-if="referenceImageStatus(image) === 'approved'" type="success">{{ t('visualBible.status.approved') }}</el-tag>
                    <el-button v-else-if="role !== 'identity_half_body' && referenceImageStatus(image) === 'draft'" type="success" plain :loading="busyIds.includes(`image-${image.id}`)" @click="approveImage(image.id, displayedTask)">{{ t('visualBible.approve') }}</el-button>
                  </article>
                  <span v-if="!candidate.roles[role]?.images.length" class="candidate-placeholder">{{ roleLabel(role) }} · {{ t(`visualBible.references.status.${candidate.roles[role]?.status || 'pending'}`) }}</span>
                </template>
              </div>
            </div>
          </template>
        </section>
      </template>
    </template>
    <el-collapse v-if="historicalAssets.length" class="historical-materials"><el-collapse-item :title="t('referenceLibrary.historical')" name="historical"><p>{{ t('referenceLibrary.historicalHelp') }}</p><div class="image-grid"><article v-for="asset in historicalAssets" :key="asset.id" class="asset-card"><el-image v-if="assetImageUrl(asset)" :src="assetImageUrl(asset)!" :preview-src-list="[assetImageUrl(asset)!]" fit="contain" lazy preview-teleported /><strong>{{ roleLabel(asset.role) }} · v{{ asset.version }}</strong><el-tag>{{ t(`visualBible.status.${asset.status}`) }}</el-tag></article></div></el-collapse-item></el-collapse>

    <ReferenceQuickPicker
      v-if="quickDialog" :categories="categories" :category="category" :owners="quickOwners" :owner-key="selectedOwnerKey"
      :scene-scope="selectedSceneScope" :scene-scope-options="sceneScopeOptions" :tasks="currentTasks" :task-id="selectedTaskId"
      :show-scene-scope="(selectedOwner?.sceneDefinitionVersion ?? 1) < 2"
      :candidates="quickCandidates" :assets="quickAssets" :selected-image-key="quickSelectedImageKey"
      :busy="quickConfirming" :loading="loading" :unavailable="locationUnavailable" :reached-end="quickReachedEnd"
      @close="closeQuickPicker" @category="quickChangeCategory" @owner="quickChangeOwner" @scene-scope="quickChangeScope"
      @task="quickChangeTask" @select="quickSelectImage" @move="moveQuickOwner" @confirm="confirmQuickImage"
    />

    <el-dialog v-model="subjectDialog" :title="t(editedSubjectId === null ? 'referenceLibrary.newSubject' : 'referenceLibrary.editSubject')" width="min(620px, 94vw)">
      <el-form label-position="top">
        <el-form-item :label="t('referenceLibrary.name')" required><el-input v-model="subjectForm.name" /></el-form-item>
        <el-form-item :label="t(editingFixedScene ? 'referenceLibrary.fixedSceneDescription' : 'referenceLibrary.appearance')">
          <el-input v-model="subjectForm.description" type="textarea" :rows="4" />
          <p v-if="editingFixedScene" class="help">{{ t('referenceLibrary.fixedSceneHelp') }}</p>
        </el-form-item>
        <el-form-item :label="t('referenceLibrary.constraints')"><el-input v-model="subjectForm.negative_constraints" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="subjectDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="saving" :disabled="!subjectForm.name.trim()" @click="saveSubject">{{ t('projects.save') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="uploadDialog" :title="t('referenceLibrary.uploadTitle', { name: editorOwner?.name || '' })" width="min(620px, 94vw)">
      <el-form label-position="top"><el-form-item :label="t('referenceLibrary.purpose')"><el-select v-model="uploadForm.role"><el-option v-for="role in roleOptions" :key="role" :value="role" :label="roleLabel(role)" /></el-select></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'scene' && (editorOwner.sceneDefinitionVersion ?? 1) < 2" :label="t('referenceLibrary.sceneScope')"><template #label><span class="field-with-info">{{ t('referenceLibrary.sceneScope') }}<InfoTip :content="t('referenceLibrary.sceneScopeHelp')" :label="t('referenceLibrary.sceneScope')" /></span></template><el-select v-model="uploadForm.scene_scope"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in editorSceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" :disabled="option.status === 'archived'" /></el-select></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'character' && uploadForm.role !== 'identity_face'" :label="t('referenceLibrary.applicability')"><template #label><span class="field-with-info">{{ t('referenceLibrary.applicability') }}<InfoTip :content="t('referenceLibrary.outfitHelp')" :label="t('referenceLibrary.applicability')" /></span></template><el-select v-model="uploadForm.outfit_variant_id" clearable :placeholder="t('referenceLibrary.anyOutfit')"><el-option v-for="outfit in outfitOptions" :key="outfit.id" :value="outfit.id" :label="`${outfit.name} · v${outfit.version}`" /></el-select></el-form-item>
        <el-form-item :label="t('visualBible.image')"><template #label><span class="field-with-info">{{ t('visualBible.image') }}<InfoTip :content="t('referenceLibrary.uploadHelp')" :label="t('visualBible.image')" /></span></template><input :key="fileInputKey" type="file" accept="image/png,image/jpeg,image/webp" multiple :disabled="saving" @change="selectedFiles = Array.from(($event.target as HTMLInputElement).files || [])" /><p v-if="selectedFiles.length" class="help">{{ t('referenceLibrary.pendingUploads', { count: selectedFiles.length }) }}：{{ selectedFiles.map(file => file.name).join('、') }}</p></el-form-item>
      </el-form><template #footer><el-button @click="uploadDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="saving" :disabled="selectedFiles.length === 0" @click="saveUpload">{{ t('projects.save') }}</el-button></template>
    </el-dialog>
    <el-dialog class="reference-generate-dialog" v-model="generateDialog" :title="t('referenceLibrary.generateTitle', { name: editorOwner?.name || '' })" width="min(980px, calc(100vw - 28px))" top="24px" destroy-on-close>
      <el-form label-position="top">
        <div class="form-grid"><el-form-item :label="t('visualBible.references.tool')"><el-select v-model="generateForm.tool_preset_id" @change="configurationChanged"><el-option v-for="tool in editorTools" :key="tool.id" :value="tool.id" :label="tool.name" /></el-select></el-form-item><el-form-item :label="t('referenceLibrary.candidateCount')"><el-input-number v-model="generateForm.candidate_count" :min="1" :max="4" /></el-form-item></div>
        <el-form-item :label="t('referenceLibrary.selectedPurposes')"><el-checkbox-group v-model="generateForm.roles" @change="rolesChanged"><el-checkbox v-for="role in roleOptions" :key="role" :value="role">{{ roleLabel(role) }}</el-checkbox></el-checkbox-group></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'scene' && (editorOwner.sceneDefinitionVersion ?? 1) < 2" :label="t('referenceLibrary.sceneScope')"><template #label><span class="field-with-info">{{ t('referenceLibrary.sceneScope') }}<InfoTip :content="t('referenceLibrary.sceneScopeHelp')" :label="t('referenceLibrary.sceneScope')" /></span></template><el-select v-model="generateForm.scene_scope" @change="configurationChanged"><el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" /><el-option v-for="option in editorSceneScopeOptions" :key="option.id" :value="option.id" :label="option.label" :disabled="option.status === 'archived'" /></el-select></el-form-item>
        <el-form-item v-if="editorOwner?.category === 'character' && generateForm.roles.some(role => role !== 'identity_face')" :label="t('referenceLibrary.applicability')"><template #label><span class="field-with-info">{{ t('referenceLibrary.applicability') }}<InfoTip :content="t('referenceLibrary.outfitHelp')" :label="t('referenceLibrary.applicability')" /></span></template><el-select v-model="generateForm.outfit_variant_id" clearable :placeholder="t(ambiguousOutfits ? 'referenceLibrary.chooseOutfit' : 'referenceLibrary.anyOutfit')" @change="configurationChanged"><el-option v-for="outfit in outfitOptions" :key="outfit.id" :value="outfit.id" :label="`${outfit.name} · v${outfit.version}`" /></el-select><p v-if="ambiguousOutfits && generateForm.outfit_variant_id === null" class="help">{{ t('referenceLibrary.ambiguousOutfits') }}</p></el-form-item>
        <el-form-item :label="t('referenceLibrary.inputImages')"><el-segmented v-model="generateForm.source_mode" :options="['auto', 'none', 'manual'].map(value => ({ value, label: t(`referenceLibrary.sourceModes.${value}`) }))" @change="configurationChanged" />
          <p v-if="generateForm.source_mode === 'auto'" class="help">{{ t(editorOwner?.category !== 'character' ? 'referenceLibrary.autoSubjectHelp' : !toolSupportsImages && autoSource ? 'referenceLibrary.autoTextFallback' : autoSource ? 'referenceLibrary.autoFaceHelp' : 'referenceLibrary.noAutoFace', { name: editorOwner?.name || '' }) }}</p>
          <el-select v-if="generateForm.source_mode === 'manual'" v-model="generateForm.source_asset_ids" multiple :placeholder="t('referenceLibrary.selectSources')" @change="configurationChanged"><el-option v-for="asset in sourceOptions" :key="asset.id" :value="asset.id" :label="assetLabel(asset)" /></el-select>
          <div v-if="effectiveSourceIds.length" class="source-images"><template v-for="id in effectiveSourceIds" :key="id"><el-image v-if="sourcePreview(id)" :src="sourcePreview(id)!" fit="contain" /><span v-else class="help">#{{ id }} · {{ t('visualBible.assets.noLocalPreview') }}</span></template></div>
        </el-form-item>
        <el-alert v-if="!sourceSupported" type="warning" :closable="false" :title="t('referenceLibrary.unsupportedSources')" />
        <el-alert v-if="!selectedSourcesAvailable" type="warning" :closable="false" :title="t('referenceLibrary.unavailableSources')" />
        <el-form-item v-if="requiresCanvas" :label="t('referenceInputs.canvas')" required><template #label><span class="field-with-info">{{ t('referenceInputs.canvas') }}<InfoTip :content="t('referenceLibrary.canvasHelp')" :label="t('referenceInputs.canvas')" /></span></template><el-select v-model="generateForm.canvas_asset_id" clearable :placeholder="t('referenceLibrary.selectCanvas')" @change="configurationChanged"><el-option v-for="asset in sourceOptions" :key="asset.id" :value="asset.id" :label="assetLabel(asset)" /></el-select></el-form-item>
        <el-alert v-if="requiresCanvas && generateForm.canvas_asset_id === null" type="warning" :closable="false" :title="t('referenceLibrary.canvasRequired')" />
        <el-alert v-if="!withinCapacity" type="warning" :closable="false" :title="t('referenceInputs.capacity', { count: imageCapacity })" />
        <div class="prompt-heading"><strong>{{ t('referenceLibrary.prompts') }}</strong><el-button :icon="Refresh" :loading="promptLoading" :disabled="visualDirty || visualBusy || submitting || generateForm.roles.length === 0 || generateForm.tool_preset_id === null" @click="refreshPrompts()">{{ t('referenceLibrary.refreshPrompts') }}</el-button></div>
        <el-alert v-if="!previewReady && !promptLoading" type="warning" :closable="false" :title="t('referenceLibrary.visual.notReady')" />
        <el-alert v-if="profileRebuilt" type="info" :closable="false" :title="t('referenceLibrary.visual.rebuilt')" />
        <VisualProfileEditor :profiles="visualProfiles" :disabled="promptLoading || submitting" :confirm-replacement="confirmPromptReplacement"
          @updated="profileUpdated" @dirty="visualDirty = $event" @busy="visualBusy = $event" />
        <el-button :disabled="visualDirty || visualBusy || promptLoading || submitting || !visualProfiles.length" @click="reextractProfiles">{{ t('referenceLibrary.visual.reextract') }}</el-button>
        <el-alert v-if="!toolSupportsSize" type="warning" :closable="false" :title="t('referenceLibrary.sizeUnsupported')" />
        <div v-loading="promptLoading"><el-tabs><el-tab-pane v-for="role in generateForm.roles" :key="role" :label="roleLabel(role)">
          <div v-if="generateForm.sizes[role]" class="form-grid size-fields">
            <el-form-item :label="t('referenceLibrary.width')"><template #label><span class="field-with-info">{{ t('referenceLibrary.width') }}<InfoTip :content="t('referenceLibrary.sizeHelp')" :label="t('referenceLibrary.width')" /></span></template><el-input-number v-model="generateForm.sizes[role]!.width" :min="256" :max="2048" :step="32" step-strictly :disabled="!toolSupportsSize" /></el-form-item>
            <el-form-item :label="t('referenceLibrary.height')"><el-input-number v-model="generateForm.sizes[role]!.height" :min="256" :max="2048" :step="32" step-strictly :disabled="!toolSupportsSize" /></el-form-item>
          </div>
          <el-form-item :label="t('imageSpecs.positivePrompt')"><el-input :model-value="generateForm.prompts[role]?.positive || ''" type="textarea" :rows="4" @update:model-value="generateForm.prompts[role] = { positive: $event, negative: generateForm.prompts[role]?.negative || '' }" /></el-form-item><el-collapse><el-collapse-item :title="t('imageSpecs.negativePromptTitle')" :name="role"><el-input :model-value="generateForm.prompts[role]?.negative || ''" type="textarea" :rows="2" @update:model-value="generateForm.prompts[role] = { positive: generateForm.prompts[role]?.positive || '', negative: $event }" /></el-collapse-item></el-collapse></el-tab-pane></el-tabs></div>
        <el-alert class="request-summary" type="info" :closable="false" :title="t('referenceLibrary.requestCount', { count: requestCount })" />
      </el-form><template #footer><el-button @click="generateDialog = false">{{ t('projects.cancel') }}</el-button><el-button type="primary" :loading="submitting" :disabled="!canCreate" @click="submitGeneration">{{ t('referenceLibrary.submit') }}</el-button></template>
    </el-dialog>
    <ReferenceBatchGenerator v-if="batchContext" v-bind="batchContext" @close="batchContext = null" @submitted="batchSubmitted" />
  </section>
</template>

<style scoped>
:global(.reference-generate-dialog) { display: flex; flex-direction: column; max-height: calc(100vh - 48px); margin-bottom: 24px; }
:global(.reference-generate-dialog .el-dialog__body) { overflow-y: auto; min-height: 0; }
:global(.reference-generate-dialog .el-dialog__header), :global(.reference-generate-dialog .el-dialog__footer) { flex-shrink: 0; }
.reference-library { container-type: inline-size; padding: 20px; background: white; border: 1px solid var(--panel-border); border-radius: 8px; min-width: 0; }
.library-heading, .library-toolbar, .owner-heading, .assets-heading, .prompt-heading, .task-actions, .scene-binding { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; margin-bottom:16px; }
h2,h3,p { margin:0; } h2 { font-size:18px; } h3 { font-size:16px; } p,.help,.task-actions span { color:var(--text-soft); font-size:13px; line-height:1.6; overflow-wrap:anywhere; } .library-heading p,.owner-heading p { margin-top:7px; }
.owner-selector { max-width:520px; margin:16px 0; } .scene-binding { justify-content:flex-start; padding:14px; background:var(--el-fill-color-light); border-radius:8px; } .scene-binding .el-select { width:260px; }
.role-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,175px),1fr)); gap:12px; margin-bottom:24px; } .role-card { display:grid; gap:10px; padding:14px; border:1px solid var(--panel-border); border-radius:8px; background:#fbfcff; } .role-card span { color:var(--text-soft); font-size:13px; } .role-card > div { display:flex; flex-wrap:wrap; gap:8px; } .role-card :deep(.el-button) { margin-left:0; }
.image-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,180px),1fr)); gap:14px; } .asset-card { display:flex; flex-direction:column; align-items:flex-start; gap:10px; min-width:0; border:1px solid var(--panel-border); border-radius:10px; padding:12px; font-size:13px; } .asset-card .el-image,.image-placeholder { width:100%; height:210px; background:#f0f3f8; border-radius:6px; } .image-placeholder { display:grid; place-items:center; color:var(--text-soft); } .asset-card strong { line-height:1.5; overflow-wrap:anywhere; }
.task-history { margin-top:24px; border-top:1px solid var(--panel-border); padding-top:20px; } .task-history > .el-select { max-width:520px; margin:14px 0; } .task-actions { justify-content:flex-start; margin-top:8px; } .task-actions .el-button + .el-button { margin-left:0; } .candidate { margin-top:20px; } .candidate > strong { display:block; margin-bottom:12px; } .candidate-placeholder { padding:14px; color:var(--text-soft); }
.historical-materials { margin-top:20px; } .historical-materials p { margin-bottom:14px; } .form-grid { display:grid; grid-template-columns:2fr 1fr; gap:18px; } .help { width:100%; margin-top:8px; } .source-images { display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; } .source-images .el-image { width:80px; height:90px; } .request-summary { margin-top:16px; }
.character-help { margin:8px 0; } .library-heading { gap:8px; margin-bottom:10px; } .library-heading p { flex:1; margin:0; } .owner-selector { margin:10px 0 14px; }
.library-heading > .title-with-info { margin-right: auto; }
.library-heading .el-button + .el-button { margin-left: 0; }
.library-toolbar { justify-content: flex-start; }
.library-toolbar > .el-button { margin-left: auto; }
.scene-scope { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px; } .scene-scope .el-select { width:min(520px,100%); } .scene-scope p { flex-basis:100%; }
@container(max-width:580px) { .role-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .image-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .asset-card .el-image { height:170px; } .scene-binding .el-select,.owner-selector { width:100%; } .library-heading { align-items:flex-start; } .assets-heading { align-items:flex-start; } }
@container(max-width:340px) { .role-grid,.image-grid { grid-template-columns:1fr; } }
@media(max-width:700px) { .reference-library { padding:14px; } .form-grid { grid-template-columns:1fr; gap:0; } }
</style>

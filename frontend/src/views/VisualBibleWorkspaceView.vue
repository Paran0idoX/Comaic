<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Check,
  Collection,
  InfoFilled,
  MagicStick,
  Picture,
  Plus,
  RefreshRight,
  Setting,
  VideoPause,
  UploadFilled,
} from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { apiErrorMessage } from '@/api/errors'
import {
  approveCharacterReferenceSet,
  continueCharacterReferenceTask,
  createCharacterReferenceTask,
  listCharacterReferenceCharacters,
  listProjectCharacterReferenceCharacters,
  listCharacterReferenceTasks,
  previewCharacterReferencePrompts,
  suspendCharacterReferenceTask,
  watchCharacterReferenceTask,
  type CharacterReferenceCandidateSet,
  type CharacterReferenceCharacter,
  type CharacterReferenceRole,
  type CharacterReferenceRun,
  type CharacterReferenceTask,
} from '@/api/characterReference'
import { listImageGenerationTools, type ImageGenerationTool } from '@/api/imageGeneration'
import {
  listProjectScriptTasks,
  listScriptTaskCharacters,
  listScriptTaskScenes,
  type ScriptCharacter,
  type ScriptScene,
  type ScriptTask,
} from '@/api/scripts'
import {
  assignOutfitVariant,
  createOutfit,
  createSceneVersion,
  createStyle,
  listOutfits,
  listSceneVersions,
  listStyles,
  listVisualAssets,
  registerVisualAsset,
  selectSceneVisualVersion,
  setConfigurationStatus,
  setVisualAssetStatus,
  updateOutlineCharacterVisualType,
  uploadVisualAsset,
  type CharacterVisualType,
  type OutfitVariant,
  type SceneVisualVersion,
  type StyleProfile,
  type VisualAsset,
  type VisualAssetRole,
  type VisualEntityType,
} from '@/api/visualBible'
import { useProjectContextStore } from '@/stores/projectContext'
import { useActivityCenterStore, type ActivityStatus } from '@/stores/activityCenter'
import WorkflowReadiness, {
  type ReadinessItem,
} from '@/components/workspace/WorkflowReadiness.vue'
import VisualSettingDetails from '@/components/workspace/VisualSettingDetails.vue'
import ReferenceLibrary from '@/components/referenceLibrary/ReferenceLibrary.vue'
import type { ReferenceImageTask } from '@/api/referenceImages'
import { positiveId as queryId } from '@/utils/workspaceActivity'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const projectContext = useProjectContextStore()
const activityCenter = useActivityCenterStore()
const { selectedProjectId } = storeToRefs(projectContext)
const tasks = ref<ScriptTask[]>([])
const characters = ref<ScriptCharacter[]>([])
const scenes = ref<ScriptScene[]>([])
const outfits = ref<OutfitVariant[]>([])
const styles = ref<StyleProfile[]>([])
const sceneVersions = ref<SceneVisualVersion[]>([])
const assets = ref<VisualAsset[]>([])
const generationTools = ref<ImageGenerationTool[]>([])
const outlineCharacters = ref<CharacterReferenceCharacter[]>([])
const projectOutlineCharacters = ref<CharacterReferenceCharacter[]>([])
const referenceTasks = ref<Record<number, CharacterReferenceTask[]>>({})
const selectedReferenceTaskIds = reactive<Record<number, number | null>>({})
const selectedTaskId = ref<number | null>(null)
const loading = ref(false)
const taskVisualLoading = ref(false)
const savingConfiguration = ref<SettingKind | null>(null)
const savingAsset = ref(false)
const savingCharacterTypeIds = ref<number[]>([])
const activeBibleTab = ref<'assignments' | 'references' | 'library' | 'assets'>(
  ['assignments', 'references', 'library', 'assets'].includes(String(route.query.tab))
    ? (String(route.query.tab) === 'assets' ? 'references' : String(route.query.tab) as 'assignments' | 'references' | 'library' | 'assets')
    : 'references',
)
const activeAssignmentTab = ref<'characters' | 'scenes'>('characters')
const activeLibraryTab = ref<'outfits' | 'scenes' | 'styles'>('outfits')
const libraryStatusFilter = ref<'draft' | 'approved' | 'all'>('draft')
const assetStatusFilter = ref<'draft' | 'approved' | 'all'>('all')
const expandedReferenceCharacter = ref<number | null>(null)
const activeReferenceRole = ref<CharacterReferenceRole>('identity_face')
const batchApprovingKind = ref<'outfit' | 'scene' | 'style' | null>(null)

const outfitDialog = ref(false)
const styleDialog = ref(false)
const sceneDialog = ref(false)
const assetDialog = ref(false)
const referenceDialog = ref(false)
const referencePromptLoading = ref(false)
const referenceSubmitting = ref(false)
const referencePromptBaseline = ref('')
const referenceActionIds = ref<string[]>([])
const selectedReferenceCharacter = ref<{ id: number; label: string } | null>(null)
const referenceEditorScriptTaskId = ref<number | null>(null)
const selectedFile = ref<File | null>(null)
const assetInputKey = ref(0)
const assetEditorProjectId = ref<number | null>(null)
const outfitEditorProjectId = ref<number | null>(null)
const sceneEditorProjectId = ref<number | null>(null)
const styleEditorProjectId = ref<number | null>(null)
type SettingKind = 'outfit' | 'scene' | 'style'
type SettingVersion = OutfitVariant | SceneVisualVersion | StyleProfile
const detailsDialog = ref(false)
const detailKind = ref<SettingKind>('outfit')
const detailVersion = ref<SettingVersion | null>(null)
const bindingCharacterId = ref<number | null>(null)
let projectLoadSequence = 0
let taskLoadSequence = 0
let referenceLoadSequence = 0
let promptLoadSequence = 0
const referenceTaskScriptContexts = new Map<number, number | null>()

const referenceRoles: CharacterReferenceRole[] = [
  'identity_face',
  'identity_half_body',
  'identity_full_body',
]
const referenceStreamStops = new Map<number, () => void>()

const emptyReferencePrompts = () => ({
  identity_face: { positive: '', negative: '' },
  identity_half_body: { positive: '', negative: '' },
  identity_full_body: { positive: '', negative: '' },
})

const referenceForm = reactive({
  tool_preset_id: null as number | null,
  style_profile_id: null as number | null,
  candidate_count: 2,
  prompt_type: null as 'tag' | 'natural_language' | 'hybrid' | null,
  prompts: emptyReferencePrompts(),
})

const assetRolesByEntity: Record<VisualEntityType, VisualAssetRole[]> = {
  character: [
    'identity_face',
    'identity_half_body',
    'identity_full_body',
    'pose',
    'depth',
    'canny',
    'lineart',
    'segmentation',
    'mask',
  ],
  outfit: ['outfit_front', 'outfit_back', 'outfit_detail', 'mask'],
  scene: ['scene_master', 'prop_reference', 'depth', 'canny', 'lineart', 'segmentation', 'mask'],
  style: ['style_reference'],
  prop: ['prop_reference', 'mask'],
  control: ['pose', 'depth', 'canny', 'lineart', 'segmentation', 'mask'],
}

const outfitForm = reactive({
  outline_character_id: null as number | null,
  key: '',
  name: '',
  garments: '',
  colors: '',
  materials: '',
  accessories: '',
  negative_constraints: '',
  layer_order: '[]',
  patterns: '[]',
  trigger_tokens: '[]',
})
const copiedOutfit = ref<OutfitVariant | null>(null)
const styleForm = reactive({
  key: '',
  name: '',
  positive_tag: '',
  negative_tag: '',
  positive_natural_language: '',
  negative_natural_language: '',
  color_palette: '',
  lighting: '',
})
const sceneForm = reactive({
  script_scene_id: null as number | null,
  landmarks: '',
  object_states: '{}',
  spatial_relations: '{}',
  lighting_state: '{}',
  camera_presets: '[]',
  color_palette: '[]',
})
const copiedScene = ref<SceneVisualVersion | null>(null)
const copiedStyle = ref<StyleProfile | null>(null)
const assetForm = reactive({
  mode: 'upload' as 'upload' | 'locator',
  entity_type: 'character' as VisualEntityType,
  entity_id: null as number | null,
  entity_key: '',
  role: 'identity_face' as VisualAssetRole,
  renderer_locator: '',
  sha256: '',
  approve: false,
})
const splitValues = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

const arrayText = (values: unknown[]) =>
  values.map((value) => typeof value === 'string' ? value : JSON.stringify(value)).join(', ')
const copyData = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T

// 复制版本时保留未编辑的原始结构，避免把脚本生成的对象数组降为字符串。
const editedArray = (value: string, original?: unknown[]) =>
  original && value === arrayText(original) ? copyData(original) : splitValues(value)

const parseArray = (value: string) => {
  const parsed: unknown = JSON.parse(value || '[]')
  if (!Array.isArray(parsed)) throw new Error(t('visualBible.errors.save'))
  return parsed
}

const parseObject = (value: string, label: string) => {
  const parsed = JSON.parse(value || '{}') as unknown
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} must be a JSON object`)
  }
  return parsed as Record<string, unknown>
}

const ownerOptions = computed(() => {
  if (assetForm.entity_type === 'character') {
    return outlineCharacterOptions.value.map(({ id, label }) => ({ id, label }))
  }
  if (assetForm.entity_type === 'outfit') {
    return outfits.value.map((item) => ({
      id: item.id,
      label: `${item.name} · v${item.version}`,
    }))
  }
  if (assetForm.entity_type === 'scene') {
    return sceneVersions.value.map((item) => ({
      id: item.id,
      label: sceneVersionLabel(item),
    }))
  }
  if (assetForm.entity_type === 'style') {
    return styles.value.map((item) => ({
      id: item.id,
      label: `${item.name} · v${item.version}`,
    }))
  }
  return []
})
const assetRoleOptions = computed(() => assetRolesByEntity[assetForm.entity_type])

const outlineCharacterOptions = computed(() => {
  const values = new Map<
    number,
    { id: number; label: string; character_key: string; visual_type: CharacterVisualType }
  >()
  outlineCharacters.value.forEach((character) => {
    values.set(character.id, {
      id: character.id,
      label: character.name,
      character_key: character.character_key,
      visual_type: character.visual_type,
    })
  })
  characters.value.forEach((item) => {
    if (item.outline_character_id) {
      const rawType = item.outline_character?.visual_type
      const visualType: CharacterVisualType =
        rawType === 'realistic_human' || rawType === 'non_human' ? rawType : 'stylized_human'
      values.set(item.outline_character_id, {
        id: item.outline_character_id,
        label: item.name,
        character_key: item.character_key,
        visual_type: visualType,
      })
    }
  })
  return [...values.values()]
})

const txt2imgTools = computed(() =>
  generationTools.value.filter((tool) => tool.capabilities?.features?.includes('txt2img')),
)
const approvedStyles = computed(() => styles.value.filter((style) => style.status === 'approved'))
const referencePromptsReady = computed(() =>
  referenceRoles.every((role) => referenceForm.prompts[role].positive.trim().length > 0),
)
const referenceRequestCount = computed(() => referenceForm.candidate_count * referenceRoles.length)
const selectedReferenceTool = computed(() =>
  txt2imgTools.value.find((tool) => tool.id === referenceForm.tool_preset_id),
)
const approvedReferenceCharacterCount = computed(
  () =>
    outlineCharacterOptions.value.filter((character) =>
      assets.value.some(asset => asset.entity_type === 'character' && asset.entity_id === character.id && asset.status === 'approved' && asset.role.startsWith('identity_')),
    ).length,
)
const unresolvedOutfitCount = computed(
  () =>
    characters.value.filter((character) => {
      const selected = outfits.value.find((item) => item.id === character.outfit_variant_id)
      return selected?.status !== 'approved'
    }).length,
)
const unresolvedSceneCount = computed(
  () =>
    scenes.value.filter((scene) => {
      const selected = sceneVersions.value.find(
        (item) => item.id === scene.selected_visual_version_id,
      )
      return selected?.status !== 'approved'
    }).length,
)
const draftOutfits = computed(() => outfits.value.filter((item) => item.status === 'draft'))
const draftScenes = computed(() => sceneVersions.value.filter((item) => item.status === 'draft'))
const draftStyles = computed(() => styles.value.filter((item) => item.status === 'draft'))
const editableAssets = computed(() => assets.value.filter(asset => ['character', 'scene', 'prop'].includes(asset.entity_type) && asset.status !== 'archived'))
const draftAssetCount = computed(() => editableAssets.value.filter((item) => item.status === 'draft').length)
const filterByLibraryStatus = <T extends { status: string }>(items: T[]) =>
  libraryStatusFilter.value === 'all'
    ? items
    : items.filter((item) => item.status === libraryStatusFilter.value)
const filteredOutfits = computed(() => filterByLibraryStatus(outfits.value))
const filteredSceneVersions = computed(() => filterByLibraryStatus(sceneVersions.value))
const filteredStyles = computed(() => filterByLibraryStatus(styles.value))
const filteredAssets = computed(() =>
  assetStatusFilter.value === 'all'
    ? assets.value
    : assets.value.filter((item) => item.status === assetStatusFilter.value),
)
const workspaceQuery = computed(() => ({
  ...route.query,
  project_id: selectedProjectId.value === null ? undefined : String(selectedProjectId.value),
  script_task_id: selectedTaskId.value === null ? undefined : String(selectedTaskId.value),
}))

/** 通用参考任务记录固定归属，页面切换后任务中心仍可准确定位到原对象。 */
const syncReferenceImageActivity = (task: ReferenceImageTask, scriptTaskId: number | null) => {
  const knownActivity = activityCenter.activities?.find(activity => activity.id === `reference-image-${task.id}` && activity.projectId === task.project_id)
  const originalScriptTaskId = knownActivity?.scriptTaskId ?? scriptTaskId ?? null
  const query = { project_id: String(task.project_id), script_task_id: originalScriptTaskId ? String(originalScriptTaskId) : undefined,
    character_id: task.entity_type === 'character' && task.entity_id ? String(task.entity_id) : undefined,
    reference_subject_id: task.reference_subject_id ? String(task.reference_subject_id) : undefined,
    scene_visual_version_id: task.entity_type === 'scene' && task.entity_id ? String(task.entity_id) : undefined,
    reference_task_id: String(task.id), reference_task_kind: 'referenceImage', reference_category: task.entity_type, tab: 'references' }
  activityCenter.upsertActivity({ id: `reference-image-${task.id}`, kind: 'referenceImage',
    label: task.subject_name || task.character_name || t('referenceLibrary.title'), status: task.status,
    progress: task.progress.total ? Math.min(100, Math.round(((task.progress.completed || 0) + (task.progress.failed || 0)) / task.progress.total * 100)) : 0,
    route: router.resolve({ path: '/visual-bible', query }).fullPath, projectId: task.project_id,
    scriptTaskId: originalScriptTaskId ?? undefined, characterId: task.entity_type === 'character' ? task.entity_id ?? undefined : undefined,
    referenceSubjectId: task.reference_subject_id ?? undefined, entityType: task.entity_type,
    referenceTaskId: task.id, updatedAt: task.updated_at })
}
const handleReferenceSceneBound = (sceneId: number, subjectId: number | null) => {
  const scene = scenes.value.find(item => item.id === sceneId)
  if (scene) Object.assign(scene, { reference_subject_id: subjectId })
}
const readinessItems = computed<ReadinessItem[]>(() => [
  {
    key: 'assignments',
    label: t('visualBible.readiness.assignments'),
    detail:
      selectedTaskId.value === null
        ? t('visualBible.readiness.startScripts')
        : characters.value.length + scenes.value.length === 0
          ? t('ux.notRequired')
          : unresolvedOutfitCount.value + unresolvedSceneCount.value === 0
        ? t('visualBible.readiness.complete')
        : t('visualBible.readiness.assignmentPending', {
            count: unresolvedOutfitCount.value + unresolvedSceneCount.value,
          }),
    status:
      selectedTaskId.value === null ? 'notStarted'
        : characters.value.length + scenes.value.length === 0 ? 'notRequired'
          : unresolvedOutfitCount.value + unresolvedSceneCount.value === 0 ? 'ready' : 'blocked',
    to: selectedTaskId.value === null
      ? { path: '/scripts', query: { project_id: selectedProjectId.value ?? undefined } }
      : { path: '/visual-bible', query: { ...workspaceQuery.value, tab: 'assignments' } },
    actionLabel: t(selectedTaskId.value === null ? 'scripts.actions.generateBatch' : 'visualBible.readiness.review'),
  },
  {
    key: 'references',
    label: t('referenceLibrary.title'),
    detail: editableAssets.value.length === 0 ? t('ux.notStarted') : t('referenceLibrary.confirmedCount', {
      count: editableAssets.value.filter(asset => asset.status === 'approved').length,
    }),
    status: editableAssets.value.length === 0 ? 'notStarted'
      : editableAssets.value.some(asset => asset.status === 'draft') ? 'pending' : 'ready',
    to: { path: '/visual-bible', query: { ...workspaceQuery.value, tab: 'references' } },
    actionLabel: t('ux.uploadExisting'),
  },
  {
    key: 'drafts',
    label: t('visualBible.readiness.drafts'),
    detail: outfits.value.length + sceneVersions.value.length === 0 ? t('ux.notStarted') : t('visualBible.readiness.draftCount', {
      count: draftOutfits.value.length + draftScenes.value.length,
    }),
    status:
      outfits.value.length + sceneVersions.value.length === 0 ? 'notStarted'
        : draftOutfits.value.length + draftScenes.value.length === 0
        ? 'ready'
        : 'pending',
    to: selectedTaskId.value === null && outfits.value.length + sceneVersions.value.length === 0
      ? { path: '/scripts', query: { project_id: selectedProjectId.value ?? undefined } }
      : { path: '/visual-bible', query: { ...workspaceQuery.value, tab: 'library' } },
    actionLabel: t(selectedTaskId.value === null && outfits.value.length + sceneVersions.value.length === 0 ? 'scripts.actions.generateBatch' : 'visualBible.readiness.review'),
  },

])

const referencePreviewList = (candidate: CharacterReferenceCandidateSet) =>
  referenceRoles
    .map((role) => getReferenceRun(candidate, role)?.primary_image?.image_url)
    .filter((value): value is string => Boolean(value))

const sceneVersionLabel = (version: SceneVisualVersion) => {
  const scene = scenes.value.find((item) => item.id === version.script_scene_id)
  return scene ? `${scene.name} · v${version.version}` : `v${version.version}`
}

const entityLabel = (type: VisualEntityType) => t(`visualBible.entityLabels.${type}`)
const roleLabel = (role: VisualAssetRole) => t(`visualBible.roleLabels.${role}`)
const assetOwnerLabel = (asset: VisualAsset) => {
  if (asset.entity_type === 'character') {
    return outlineCharacterOptions.value.find((item) => item.id === asset.entity_id)?.label || entityLabel(asset.entity_type)
  }
  if (asset.entity_type === 'outfit') return outfits.value.find((item) => item.id === asset.entity_id)?.name || entityLabel(asset.entity_type)
  if (asset.entity_type === 'style') return styles.value.find((item) => item.id === asset.entity_id)?.name || entityLabel(asset.entity_type)
  if (asset.entity_type === 'scene') {
    const version = sceneVersions.value.find((item) => item.id === asset.entity_id)
    return version ? sceneVersionLabel(version) : entityLabel(asset.entity_type)
  }
  return asset.entity_key || entityLabel(asset.entity_type)
}
const referenceAssetsFor = (characterId: number, role: CharacterReferenceRole) =>
  assets.value.filter((asset) => asset.entity_type === 'character' && asset.entity_id === characterId && asset.role === role && asset.status === 'draft')

const openAssetUploader = (character?: { id: number }, role: CharacterReferenceRole = 'identity_face') => {
  assetEditorProjectId.value = selectedProjectId.value
  assetForm.mode = 'upload'
  assetForm.entity_type = 'character'
  assetForm.entity_id = character?.id ?? null
  assetForm.entity_key = ''
  assetForm.role = role
  assetForm.approve = false
  assetForm.renderer_locator = ''
  assetForm.sha256 = ''
  selectedFile.value = null
  assetInputKey.value += 1
  assetDialog.value = true
}

const openSettingDetails = (kind: SettingKind, value: SettingVersion, characterId?: number) => {
  detailKind.value = kind
  detailVersion.value = copyData(value)
  bindingCharacterId.value = characterId ?? null
  detailsDialog.value = true
}
const bindingCharacterOptions = computed(() => {
  if (detailKind.value !== 'outfit' || !detailVersion.value) return []
  const outfit = detailVersion.value as OutfitVariant
  return characters.value.filter((item) => item.outline_character_id === outfit.outline_character_id)
})
const canUseVersion = computed(() => {
  const item = detailVersion.value
  if (!item || item.status !== 'approved' || item.project_id !== selectedProjectId.value) return false
  if (detailKind.value === 'outfit') return bindingCharacterOptions.value.some((character) => character.id === bindingCharacterId.value)
  if (detailKind.value === 'scene') return scenes.value.some((scene) => scene.id === (item as SceneVisualVersion).script_scene_id)
  return false
})
const useSettingVersion = async () => {
  const item = detailVersion.value
  if (!item || !canUseVersion.value) return
  if (detailKind.value === 'outfit') {
    const character = bindingCharacterOptions.value.find((entry) => entry.id === bindingCharacterId.value)
    if (character) await assignCharacterOutfit(character, item.id)
  } else if (detailKind.value === 'scene') {
    const scene = scenes.value.find((entry) => entry.id === (item as SceneVisualVersion).script_scene_id)
    if (scene) await assignSceneVersion(scene, item.id)
  }
}

const openOutfitEditor = (item?: OutfitVariant) => {
  copiedOutfit.value = item ? copyData(item) : null
  outfitEditorProjectId.value = item?.project_id ?? selectedProjectId.value
  Object.assign(outfitForm, {
    outline_character_id: item?.outline_character_id ?? null,
    key: item?.key ?? `manual_${crypto.randomUUID()}`, name: item?.name ?? '',
    garments: arrayText(item?.garment_components ?? []), colors: arrayText(item?.colors ?? []),
    materials: arrayText(item?.materials ?? []), accessories: arrayText(item?.accessories ?? []),
    negative_constraints: item?.negative_constraints ?? '',
    layer_order: JSON.stringify(item?.layer_order ?? [], null, 2),
    patterns: JSON.stringify(item?.patterns ?? [], null, 2),
    trigger_tokens: JSON.stringify(item?.trigger_tokens ?? [], null, 2),
  })
  outfitDialog.value = true
}
const openStyleEditor = (item?: StyleProfile) => {
  copiedStyle.value = item ? copyData(item) : null
  styleEditorProjectId.value = item?.project_id ?? selectedProjectId.value
  Object.assign(styleForm, {
    key: item?.key ?? `manual_${crypto.randomUUID()}`, name: item?.name ?? '',
    positive_tag: item?.positive_tag ?? '', negative_tag: item?.negative_tag ?? '',
    positive_natural_language: item?.positive_natural_language ?? '',
    negative_natural_language: item?.negative_natural_language ?? '',
    color_palette: arrayText(item?.color_palette ?? []), lighting: item?.lighting ?? '',
  })
  styleDialog.value = true
}
const openSceneEditor = (item?: SceneVisualVersion) => {
  copiedScene.value = item ? copyData(item) : null
  sceneEditorProjectId.value = item?.project_id ?? selectedProjectId.value
  Object.assign(sceneForm, {
    script_scene_id: item?.script_scene_id ?? null, landmarks: arrayText(item?.landmarks ?? []),
    spatial_relations: JSON.stringify(item?.spatial_relations ?? {}, null, 2),
    object_states: JSON.stringify(item?.object_states ?? {}, null, 2),
    lighting_state: JSON.stringify(item?.lighting_state ?? {}, null, 2),
    camera_presets: JSON.stringify(item?.camera_presets ?? [], null, 2),
    color_palette: JSON.stringify(item?.color_palette ?? [], null, 2),
  })
  sceneDialog.value = true
}
const copySettingVersion = () => {
  if (!detailVersion.value) return
  if (detailKind.value === 'outfit') openOutfitEditor(detailVersion.value as OutfitVariant)
  else if (detailKind.value === 'scene') openSceneEditor(detailVersion.value as SceneVisualVersion)
  else openStyleEditor(detailVersion.value as StyleProfile)
  detailsDialog.value = false
}

const normalizeActivityStatus = (status: CharacterReferenceTask['status']): ActivityStatus => {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'suspended') return 'suspended'
  if (status === 'running') return 'running'
  return 'pending'
}

const referenceTasksFor = (characterId: number) => referenceTasks.value[characterId] ?? []

const displayedReferenceTask = (characterId: number) => {
  const tasksForCharacter = referenceTasksFor(characterId)
  const selectedId = selectedReferenceTaskIds[characterId]
  if (queryId(route.query.character_id) === characterId && queryId(route.query.reference_task_id) !== null) {
    return tasksForCharacter.find((task) => task.id === queryId(route.query.reference_task_id)) ?? null
  }
  return tasksForCharacter.find((task) => task.id === selectedId) ?? tasksForCharacter[0] ?? null
}

const approvedIdentityAsset = (characterId: number, role: CharacterReferenceRole) =>
  assets.value.find(
    (asset) =>
      asset.entity_type === 'character' &&
      asset.entity_id === characterId &&
      asset.role === role &&
      asset.status === 'approved',
  )

const getReferenceRun = (
  candidate: CharacterReferenceCandidateSet,
  role: CharacterReferenceRole,
): CharacterReferenceRun | undefined => candidate.roles[role]

const referenceProgressPercentage = (task: CharacterReferenceTask) => {
  const total = task.progress.total ?? task.candidate_count * 3
  if (total <= 0) return 0
  return Math.round((((task.progress.completed ?? 0) + (task.progress.failed ?? 0)) / total) * 100)
}

const referenceStatusTagType = (status: string) => {
  if (status === 'succeeded' || status === 'approved') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running' || status === 'queued') return 'primary'
  if (status === 'suspended' || status === 'archived') return 'warning'
  return 'info'
}

const referenceErrorMessage = (code: string | null) => {
  if (!code) return ''
  const key = `backendErrors.${code}`
  const translated = t(key)
  return translated === key ? t('visualBible.references.errors.task') : translated
}

const syncReferenceActivity = (task: CharacterReferenceTask, scriptTaskId: number | null) => {
  const contextTaskId = scriptTaskId ?? referenceTaskScriptContexts.get(task.id) ?? null
  referenceTaskScriptContexts.set(task.id, contextTaskId)
  const query = {
    project_id: String(task.project_id),
    script_task_id: contextTaskId === null ? undefined : String(contextTaskId),
    character_id: String(task.outline_character_id),
    reference_task_id: String(task.id), tab: 'references',
  }
  activityCenter.upsertActivity({
    id: `character-reference-${task.id}`, kind: 'characterReference',
    label: `${task.character_name} · ${task.candidate_count} × 3`,
    status: normalizeActivityStatus(task.status), progress: referenceProgressPercentage(task),
    route: router.resolve({ path: '/visual-bible', query }).fullPath,
    projectId: task.project_id, scriptTaskId: contextTaskId ?? undefined,
    characterId: task.outline_character_id, referenceTaskId: task.id,
    updatedAt: task.updated_at,
  })
}

const updateReferenceTask = (task: CharacterReferenceTask, scriptTaskId: number | null = null, select = false) => {
  syncReferenceActivity(task, scriptTaskId)
  // 后台任务属于创建时的项目，跨项目切换后只刷新任务中心，不能污染当前工作区。
  if (task.project_id !== selectedProjectId.value || !outlineCharacterOptions.value.some((item) => item.id === task.outline_character_id)) return
  const current = referenceTasks.value[task.outline_character_id] ?? []
  const next = [task, ...current.filter((item) => item.id !== task.id)].sort(
    (left, right) => right.id - left.id,
  )
  referenceTasks.value = {
    ...referenceTasks.value,
    [task.outline_character_id]: next,
  }
  if (select || selectedReferenceTaskIds[task.outline_character_id] == null) selectedReferenceTaskIds[task.outline_character_id] = task.id
}

const loadReferenceTasks = async () => {
  // 通用参考图由素材库定位和刷新；旧人物套组逻辑不能接管相同的任务参数。
  if (route.query.reference_task_kind === 'referenceImage') return
  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  const requestId = ++referenceLoadSequence
  const entries = await Promise.all(
    outlineCharacterOptions.value.map(async (character) => {
      const characterTasks = await listCharacterReferenceTasks(character.id)
      return [character.id, characterTasks] as const
    }),
  )
  if (route.query.reference_task_kind === 'referenceImage') return
  entries.flatMap(([, items]) => items).forEach((task) => syncReferenceActivity(task, taskId))
  if (requestId !== referenceLoadSequence || projectId !== selectedProjectId.value || taskId !== selectedTaskId.value) return
  entries.forEach(([characterId, items]) => {
    if (!items.some((task) => task.id === selectedReferenceTaskIds[characterId])) selectedReferenceTaskIds[characterId] = items[0]?.id ?? null
  })
  referenceTasks.value = Object.fromEntries(entries)
  applyReferenceLocation()
  entries
    .flatMap(([, tasksForCharacter]) => tasksForCharacter)
    .filter((task) => task.status === 'pending' || task.status === 'running')
    .forEach(watchReferenceTask)
}

const watchReferenceTask = (task: CharacterReferenceTask) => {
  const scriptTaskId = referenceTaskScriptContexts.get(task.id) ?? null
  referenceStreamStops.get(task.id)?.()
  const stop = watchCharacterReferenceTask(task.id, {
    onTask: (updated, terminal) => {
      updateReferenceTask(updated, scriptTaskId)
      if (terminal) referenceStreamStops.delete(updated.id)
    },
    onError: (error) => {
      ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.stream')))
      referenceStreamStops.delete(task.id)
    },
  })
  referenceStreamStops.set(task.id, stop)
}

const loadProjectData = async () => {
  const projectId = selectedProjectId.value
  const requestId = ++projectLoadSequence
  if (projectId === null) return
  loading.value = true
  try {
    const result = await Promise.all([
      listProjectScriptTasks(projectId, { status: 'succeeded' }),
      listOutfits(projectId),
      listStyles(projectId),
      listSceneVersions(projectId),
      listVisualAssets(projectId),
      listImageGenerationTools(),
      listProjectCharacterReferenceCharacters(projectId),
    ])
    if (requestId !== projectLoadSequence || projectId !== selectedProjectId.value) return
    ;[tasks.value, outfits.value, styles.value, sceneVersions.value, assets.value, generationTools.value, outlineCharacters.value] = result
    projectOutlineCharacters.value = result[6]
    const requestedTaskId = queryId(route.query.script_task_id)
    const requestedExists = tasks.value.some((item) => item.id === requestedTaskId)
    const nextTaskId = requestedTaskId !== null
      ? requestedExists ? requestedTaskId : null
      : route.query.activity_legacy === '1' || queryId(route.query.character_id) !== null || queryId(route.query.reference_task_id) !== null
        ? null
        : tasks.value.some((item) => item.id === selectedTaskId.value) ? selectedTaskId.value : tasks.value[0]?.id ?? null
    if (requestedTaskId !== null && !requestedExists) ElMessage.warning(t('visualBible.errors.targetUnavailable'))
    if (nextTaskId !== selectedTaskId.value) selectedTaskId.value = nextTaskId
    else await loadTaskVisuals()
  } catch (error) {
    if (requestId === projectLoadSequence && projectId === selectedProjectId.value) ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.load')))
  } finally {
    if (requestId === projectLoadSequence) loading.value = false
  }
}

const loadTaskVisuals = async () => {
  const projectId = selectedProjectId.value
  const taskId = selectedTaskId.value
  const requestId = ++taskLoadSequence
  referenceLoadSequence += 1
  if (projectId === null) return
  taskVisualLoading.value = true
  if (taskId === null) {
    characters.value = []
    scenes.value = []
    outlineCharacters.value = projectOutlineCharacters.value
    try { await loadReferenceTasks() }
    finally { if (requestId === taskLoadSequence) taskVisualLoading.value = false }
    return
  }
  try {
    const selectedTask = tasks.value.find((task) => task.id === taskId)
    const result = await Promise.all([
      listScriptTaskCharacters(taskId),
      listScriptTaskScenes(taskId),
      selectedTask?.outline_version_id
        ? listCharacterReferenceCharacters(selectedTask.outline_version_id)
        : Promise.resolve(outlineCharacters.value),
    ])
    if (requestId !== taskLoadSequence || projectId !== selectedProjectId.value || taskId !== selectedTaskId.value) return
    ;[characters.value, scenes.value, outlineCharacters.value] = result
    await loadReferenceTasks()
  } catch (error) {
    if (requestId === taskLoadSequence && projectId === selectedProjectId.value) ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.load')))
  } finally {
    if (requestId === taskLoadSequence) taskVisualLoading.value = false
  }
}

const saveOutfit = async () => {
  const projectId = outfitEditorProjectId.value
  if (projectId === null || outfitForm.outline_character_id === null || savingConfiguration.value !== null) return
  savingConfiguration.value = 'outfit'
  try {
    const created = await createOutfit(projectId, {
      outline_character_id: outfitForm.outline_character_id,
      key: outfitForm.key,
      name: outfitForm.name,
      garment_components: editedArray(outfitForm.garments, copiedOutfit.value?.garment_components),
      layer_order: parseArray(outfitForm.layer_order),
      colors: editedArray(outfitForm.colors, copiedOutfit.value?.colors),
      materials: editedArray(outfitForm.materials, copiedOutfit.value?.materials),
      patterns: parseArray(outfitForm.patterns),
      accessories: editedArray(outfitForm.accessories, copiedOutfit.value?.accessories),
      trigger_tokens: parseArray(outfitForm.trigger_tokens),
      negative_constraints: outfitForm.negative_constraints,
    })
    outfitDialog.value = false
    if (projectId === selectedProjectId.value) {
      await loadProjectData()
      activeBibleTab.value = 'library'
      activeLibraryTab.value = 'outfits'
      libraryStatusFilter.value = 'draft'
      openSettingDetails('outfit', created)
    }
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  } finally {
    savingConfiguration.value = null
  }
}

const saveStyle = async () => {
  const projectId = styleEditorProjectId.value
  if (projectId === null || savingConfiguration.value !== null) return
  savingConfiguration.value = 'style'
  try {
    const created = await createStyle(projectId, {
      key: styleForm.key,
      name: styleForm.name,
      positive_tag: styleForm.positive_tag,
      negative_tag: styleForm.negative_tag,
      positive_natural_language: styleForm.positive_natural_language,
      negative_natural_language: styleForm.negative_natural_language,
      color_palette: editedArray(styleForm.color_palette, copiedStyle.value?.color_palette),
      lighting: styleForm.lighting,
    })
    styleDialog.value = false
    if (projectId === selectedProjectId.value) {
      await loadProjectData()
      activeBibleTab.value = 'library'
      activeLibraryTab.value = 'styles'
      libraryStatusFilter.value = 'draft'
      openSettingDetails('style', created)
    }
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  } finally {
    savingConfiguration.value = null
  }
}

const saveScene = async () => {
  const projectId = sceneEditorProjectId.value
  if (projectId === null || sceneForm.script_scene_id === null || savingConfiguration.value !== null) return
  savingConfiguration.value = 'scene'
  try {
    const created = await createSceneVersion(projectId, {
      script_scene_id: sceneForm.script_scene_id,
      landmarks: editedArray(sceneForm.landmarks, copiedScene.value?.landmarks),
      spatial_relations: parseObject(sceneForm.spatial_relations, 'spatial_relations'),
      camera_presets: parseArray(sceneForm.camera_presets),
      object_states: parseObject(sceneForm.object_states, 'object_states'),
      color_palette: parseArray(sceneForm.color_palette),
      lighting_state: parseObject(sceneForm.lighting_state, 'lighting_state'),
    })
    sceneDialog.value = false
    if (projectId === selectedProjectId.value) {
      await loadProjectData()
      activeBibleTab.value = 'library'
      activeLibraryTab.value = 'scenes'
      libraryStatusFilter.value = 'draft'
      openSettingDetails('scene', created)
    }
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  } finally {
    savingConfiguration.value = null
  }
}

const fileChanged = (event: Event) => {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

const saveAsset = async () => {
  const projectId = assetEditorProjectId.value
  if (projectId === null || savingAsset.value) return
  savingAsset.value = true
  try {
    if (assetForm.mode === 'upload') {
      if (selectedFile.value === null) throw new Error(t('visualBible.errors.fileRequired'))
      const form = new FormData()
      form.append('file', selectedFile.value)
      form.append('entity_type', assetForm.entity_type)
      if (assetForm.entity_id !== null) form.append('entity_id', String(assetForm.entity_id))
      if (assetForm.entity_key.trim()) form.append('entity_key', assetForm.entity_key.trim())
      form.append('role', assetForm.role)
      form.append('approve', String(assetForm.approve))
      await uploadVisualAsset(projectId, form)
    } else {
      await registerVisualAsset(projectId, {
        entity_type: assetForm.entity_type,
        entity_id: assetForm.entity_id,
        entity_key: assetForm.entity_key.trim() || null,
        role: assetForm.role,
        renderer_locator: assetForm.renderer_locator,
        sha256: assetForm.sha256.trim() || null,
        approve: assetForm.approve,
      })
    }
    assetDialog.value = false
    selectedFile.value = null
    if (projectId === selectedProjectId.value) await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  } finally {
    savingAsset.value = false
  }
}

const approveConfig = async (kind: 'outfit' | 'style' | 'scene', id: number) => {
  const projectId = selectedProjectId.value
  try {
    await setConfigurationStatus(kind, id, 'approved')
    if (detailVersion.value?.id === id && detailKind.value === kind) detailVersion.value.status = 'approved'
    if (projectId === selectedProjectId.value) await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const approveAllDrafts = async (kind: 'outfit' | 'style' | 'scene') => {
  const projectId = selectedProjectId.value
  const items =
    kind === 'outfit'
      ? draftOutfits.value
      : kind === 'scene'
        ? draftScenes.value
        : draftStyles.value
  if (items.length === 0) return
  try {
    await ElMessageBox.confirm(
      t('visualBible.review.approveAllConfirm', { count: items.length }),
      t('visualBible.review.approveAll'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  batchApprovingKind.value = kind
  try {
    await Promise.all(items.map((item) => setConfigurationStatus(kind, item.id, 'approved')))
    if (projectId === selectedProjectId.value) await loadProjectData()
    ElMessage.success(t('visualBible.review.approvedCount', { count: items.length }))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  } finally {
    batchApprovingKind.value = null
  }
}

const approveAsset = async (id: number) => {
  const projectId = selectedProjectId.value
  try {
    await setVisualAssetStatus(id, 'approved')
    if (projectId === selectedProjectId.value) await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const assignCharacterOutfit = async (character: ScriptCharacter, value: number | null) => {
  try {
    await assignOutfitVariant(character.id, value)
    character.outfit_variant_id = value
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const assignSceneVersion = async (scene: ScriptScene, value: number | null) => {
  try {
    await selectSceneVisualVersion(scene.id, value)
    scene.selected_visual_version_id = value
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const handleCharacterOutfitChange = (character: ScriptCharacter, value: unknown) =>
  assignCharacterOutfit(character, typeof value === 'number' ? value : null)

const handleCharacterVisualTypeChange = async (characterId: number, value: unknown) => {
  if (value !== 'realistic_human' && value !== 'stylized_human' && value !== 'non_human') {
    return
  }
  savingCharacterTypeIds.value = [...savingCharacterTypeIds.value, characterId]
  try {
    const result = await updateOutlineCharacterVisualType(characterId, value)
    characters.value.forEach((character) => {
      if (character.outline_character_id === characterId) {
        character.outline_character = {
          ...character.outline_character,
          visual_type: result.visual_type,
        }
      }
    })
    const outlineCharacter = outlineCharacters.value.find((item) => item.id === characterId)
    if (outlineCharacter) outlineCharacter.visual_type = result.visual_type
    ElMessage.success(t('visualBible.messages.characterTypeSaved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.characterTypeSave')))
  } finally {
    savingCharacterTypeIds.value = savingCharacterTypeIds.value.filter((id) => id !== characterId)
  }
}

const handleSceneVersionChange = (scene: ScriptScene, value: unknown) =>
  assignSceneVersion(scene, typeof value === 'number' ? value : null)

const refreshReferencePrompts = async () => {
  if (selectedReferenceCharacter.value === null || referenceForm.tool_preset_id === null) {
    return
  }
  if (referencePromptBaseline.value && JSON.stringify(referenceForm.prompts) !== referencePromptBaseline.value) {
    try {
      await ElMessageBox.confirm(t('visualBible.references.replaceEditedPrompts'), t('visualBible.references.resetPrompts'), { type: 'warning' })
    } catch { return }
  }
  const requestId = ++promptLoadSequence
  const characterId = selectedReferenceCharacter.value.id
  const toolId = referenceForm.tool_preset_id
  const styleId = referenceForm.style_profile_id
  referencePromptLoading.value = true
  try {
    const preview = await previewCharacterReferencePrompts(characterId, {
      tool_preset_id: toolId,
      style_profile_id: styleId,
    })
    if (requestId !== promptLoadSequence || !referenceDialog.value || characterId !== selectedReferenceCharacter.value?.id || toolId !== referenceForm.tool_preset_id || styleId !== referenceForm.style_profile_id) return
    referenceForm.prompt_type = preview.prompt_type
    referenceRoles.forEach((role) => {
      referenceForm.prompts[role].positive = preview.prompts[role].positive
      referenceForm.prompts[role].negative = preview.prompts[role].negative
    })
    referencePromptBaseline.value = JSON.stringify(referenceForm.prompts)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.preview')))
  } finally {
    if (requestId === promptLoadSequence) referencePromptLoading.value = false
  }
}

const handleReferenceConfigurationChange = () => {
  referenceForm.prompt_type = selectedReferenceTool.value?.prompt_type ?? null
  if (referencePromptBaseline.value && JSON.stringify(referenceForm.prompts) !== referencePromptBaseline.value) {
    promptLoadSequence += 1
    referencePromptLoading.value = false
    ElMessage.info(t('visualBible.references.promptsKept'))
    return
  }
  void refreshReferencePrompts()
}

const openReferenceGenerator = async (character: { id: number; label: string }) => {
  if (txt2imgTools.value.length === 0) {
    ElMessage.warning(t('visualBible.references.errors.noTool'))
    return
  }
  selectedReferenceCharacter.value = character
  referenceEditorScriptTaskId.value = selectedTaskId.value
  const defaultTool = txt2imgTools.value.find((tool) => tool.is_default) ?? txt2imgTools.value[0]
  referenceForm.tool_preset_id = defaultTool?.id ?? null
  referenceForm.style_profile_id = null
  referenceForm.candidate_count = 2
  referenceForm.prompt_type = defaultTool?.prompt_type ?? null
  referenceForm.prompts = emptyReferencePrompts()
  referencePromptBaseline.value = ''
  activeReferenceRole.value = 'identity_face'
  referenceDialog.value = true
  await refreshReferencePrompts()
}

const submitReferenceTask = async () => {
  if (selectedReferenceCharacter.value === null || referenceForm.tool_preset_id === null) {
    return
  }
  const characterId = selectedReferenceCharacter.value.id
  const scriptTaskId = referenceEditorScriptTaskId.value
  referenceSubmitting.value = true
  try {
    const task = await createCharacterReferenceTask(characterId, {
      tool_preset_id: referenceForm.tool_preset_id,
      style_profile_id: referenceForm.style_profile_id,
      candidate_count: referenceForm.candidate_count,
      prompts: {
        identity_face: { ...referenceForm.prompts.identity_face },
        identity_half_body: { ...referenceForm.prompts.identity_half_body },
        identity_full_body: { ...referenceForm.prompts.identity_full_body },
      },
    })
    updateReferenceTask(task, scriptTaskId, true)
    watchReferenceTask(task)
    if (task.project_id === selectedProjectId.value) await router.replace({ query: { ...workspaceQuery.value, tab: 'references', character_id: String(characterId), reference_task_id: String(task.id) } })
    referenceDialog.value = false
    ElMessage.success(t('visualBible.references.messages.started'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.create')))
  } finally {
    referenceSubmitting.value = false
  }
}

const suspendReferenceTask = async (task: CharacterReferenceTask) => {
  const actionId = `suspend-${task.id}`
  referenceActionIds.value = [...referenceActionIds.value, actionId]
  try {
    updateReferenceTask(await suspendCharacterReferenceTask(task.id))
    ElMessage.success(t('visualBible.references.messages.suspended'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.suspend')))
  } finally {
    referenceActionIds.value = referenceActionIds.value.filter((id) => id !== actionId)
  }
}

const continueReferenceTask = async (task: CharacterReferenceTask) => {
  const actionId = `continue-${task.id}`
  referenceActionIds.value = [...referenceActionIds.value, actionId]
  try {
    const updated = await continueCharacterReferenceTask(task.id)
    updateReferenceTask(updated)
    watchReferenceTask(updated)
    ElMessage.success(t('visualBible.references.messages.continued'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.continue')))
  } finally {
    referenceActionIds.value = referenceActionIds.value.filter((id) => id !== actionId)
  }
}

const approveReferenceCandidate = async (
  task: CharacterReferenceTask,
  candidate: CharacterReferenceCandidateSet,
) => {
  const actionId = `approve-${task.id}-${candidate.candidate_index}`
  try {
    await ElMessageBox.confirm(
      t('visualBible.references.approveConfirm', { index: candidate.candidate_index }),
      t('visualBible.references.approve'),
      { type: 'warning' },
    )
  } catch {
    return
  }
  referenceActionIds.value = [...referenceActionIds.value, actionId]
  try {
    const updated = await approveCharacterReferenceSet(task.id, candidate.candidate_index)
    updateReferenceTask(updated)
    if (task.project_id === selectedProjectId.value) {
      const refreshedAssets = await listVisualAssets(task.project_id)
      if (task.project_id === selectedProjectId.value) assets.value = refreshedAssets
    }
    ElMessage.success(t('visualBible.references.messages.approved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.references.errors.approve')))
  } finally {
    referenceActionIds.value = referenceActionIds.value.filter((id) => id !== actionId)
  }
}

const applyReferenceLocation = () => {
  if (route.query.reference_task_kind === 'referenceImage') return
  const characterId = queryId(route.query.character_id)
  const referenceTaskId = queryId(route.query.reference_task_id)
  if (characterId !== null) {
    if (!outlineCharacterOptions.value.some((item) => item.id === characterId)) {
      expandedReferenceCharacter.value = null
      ElMessage.warning(t('visualBible.errors.targetUnavailable'))
      return
    }
    expandedReferenceCharacter.value = characterId
    if (referenceTaskId !== null) {
      selectedReferenceTaskIds[characterId] = referenceTaskId
      if (!referenceTasksFor(characterId).some((task) => task.id === referenceTaskId)) ElMessage.warning(t('visualBible.errors.targetUnavailable'))
    }
  } else if (referenceTaskId !== null) {
    const task = Object.values(referenceTasks.value).flat().find((item) => item.id === referenceTaskId)
    if (task) {
      expandedReferenceCharacter.value = task.outline_character_id
      selectedReferenceTaskIds[task.outline_character_id] = task.id
    } else ElMessage.warning(t('visualBible.errors.targetUnavailable'))
  }
}
const handleScriptTaskSelection = () => {
  void router.replace({ query: { ...workspaceQuery.value, character_id: undefined, reference_task_id: undefined } })
}
const selectReferenceHistory = (characterId: number, taskId: unknown) => {
  if (typeof taskId !== 'number') return
  void router.replace({ query: { ...workspaceQuery.value, tab: 'references', character_id: String(characterId), reference_task_id: String(taskId) } })
}
const handleReferenceExpanded = (characterId: unknown) => {
  const id = typeof characterId === 'number' ? characterId : null
  void router.replace({ query: { ...workspaceQuery.value, tab: 'references', character_id: id === null ? undefined : String(id), reference_task_id: id === null || !selectedReferenceTaskIds[id] ? undefined : String(selectedReferenceTaskIds[id]) } })
}

watch(selectedProjectId, () => {
  taskLoadSequence += 1
  referenceLoadSequence += 1
  referenceStreamStops.forEach((stop) => stop())
  referenceStreamStops.clear()
  tasks.value = []
  characters.value = []
  scenes.value = []
  outfits.value = []
  styles.value = []
  sceneVersions.value = []
  assets.value = []
  outlineCharacters.value = []
  projectOutlineCharacters.value = []
  referenceTasks.value = {}
  taskVisualLoading.value = false
  expandedReferenceCharacter.value = null
  selectedTaskId.value = null
  if (selectedProjectId.value === null) {
    projectLoadSequence += 1
    loading.value = false
    return
  }
  void loadProjectData()
})
watch(selectedTaskId, () => {
  characters.value = []
  scenes.value = []
  void loadTaskVisuals()
})
watch(activeBibleTab, (tab) => {
  if (route.query.tab === tab) return
  void router.replace({ query: { ...route.query, tab } })
})
watch(
  () => route.query,
  (query) => {
    const tab = query.tab
    if (['assignments', 'references', 'library', 'assets'].includes(String(tab))) {
      activeBibleTab.value = tab === 'assets' ? 'references' : String(tab) as typeof activeBibleTab.value
    }
    const projectId = queryId(query.project_id)
    if (projectId !== null && projectId !== selectedProjectId.value) {
      selectedProjectId.value = projectId
      return
    }
    const taskId = queryId(query.script_task_id)
    if (taskId !== null && taskId !== selectedTaskId.value && tasks.value.length > 0) {
      selectedTaskId.value = tasks.value.some((item) => item.id === taskId) ? taskId : null
      return
    }
    if (!loading.value && Object.keys(referenceTasks.value).length > 0) applyReferenceLocation()
  },
)
watch(
  () => assetForm.entity_type,
  () => {
    assetForm.entity_id = null
    assetForm.entity_key = ''
    assetForm.role = assetRolesByEntity[assetForm.entity_type][0] ?? 'identity_face'
  },
  { flush: 'sync' },
)
onMounted(async () => {
  const projectId = queryId(route.query.project_id)
  if (projectId !== null && projectId !== selectedProjectId.value) selectedProjectId.value = projectId
  else await loadProjectData()
})
onBeforeUnmount(() => {
  referenceStreamStops.forEach((stop) => stop())
  referenceStreamStops.clear()
})
</script>

<template>
  <div class="visual-bible-page" v-loading="loading || taskVisualLoading">
    <div class="page-header">
      <div class="selectors">
        <el-select
          v-model="selectedTaskId"
          @change="handleScriptTaskSelection"
          clearable
          filterable
          :placeholder="t('visualBible.scriptTaskPlaceholder')"
          :aria-label="t('visualBible.scriptTask')"
        >
          <template #prefix
            ><span class="selector-prefix">{{ t('visualBible.scriptTask') }}</span></template
          >
          <el-option
            v-for="task in tasks"
            :key="task.id"
            :label="`#${task.id} · ${task.total_pages} ${t('scripts.config.pagesUnit')}`"
            :value="task.id"
          />
        </el-select>
        <el-button :disabled="selectedTaskId === null" type="primary" plain @click="router.push({ path: '/image-specs', query: { project_id: selectedProjectId ?? undefined, script_task_id: selectedTaskId ?? undefined, tab: 'compile' } })">
          {{ t('visualBible.next.openSpecs') }}
        </el-button>
      </div>
    </div>

    <el-collapse class="readiness-summary"><el-collapse-item :title="t('referenceLibrary.readinessSummary', { count: editableAssets.filter(asset => asset.status === 'approved').length, pending: draftOutfits.length + draftScenes.length })" name="readiness">
    <WorkflowReadiness
      :title="t('visualBible.readiness.title')"
      :description="t('visualBible.readiness.description')"
      :items="readinessItems"
    />
    </el-collapse-item></el-collapse>

    <el-tabs v-model="activeBibleTab" class="workspace-tabs visual-bible-tabs">
      <el-tab-pane name="assignments">
        <template #label><el-icon><Setting /></el-icon>{{ t('visualBible.tabs.assignments') }}</template>
        <section class="panel">
          <header class="panel__heading">
            <div>
              <h2>{{ t('visualBible.assignments.title') }}</h2>
              <p>{{ t('visualBible.assignments.hint') }}</p>
            </div>
          </header>
          <div class="panel__body">
            <el-tabs v-model="activeAssignmentTab" class="nested-tabs">
              <el-tab-pane :label="t('visualBible.assignments.characters')" name="characters">
                <div class="character-type-grid">
                  <article
                    v-for="character in outlineCharacterOptions"
                    :key="`visual-type-${character.id}`"
                    class="character-type-card"
                  >
                    <div>
                       <strong>{{ character.label }}</strong>
                    </div>
                    <el-select
                      :model-value="character.visual_type"
                      :aria-label="`${character.label} ${t('visualBible.assignments.characterTypes')}`"
                      :loading="savingCharacterTypeIds.includes(character.id)"
                      @change="handleCharacterVisualTypeChange(character.id, $event)"
                    >
                      <el-option
                        v-for="value in ['realistic_human', 'stylized_human', 'non_human']"
                        :key="value"
                        :label="t(`visualBible.characterVisualTypes.${value}`)"
                        :value="value"
                      />
                    </el-select>
                  </article>
                </div>
                <el-alert
                  :title="t('visualBible.assignments.characterTypesHint')"
                  type="info"
                  :closable="false"
                  show-icon
                />
                <el-table :data="characters" height="480" class="assignment-table">
                  <el-table-column :label="t('visualBible.character')" min-width="210">
                    <template #default="{ row }">
                       <strong>{{ row.name }}</strong>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('visualBible.review.section')" width="90">
                    <template #default="{ row }">§{{ row.section_no ?? '-' }}</template>
                  </el-table-column>
                  <el-table-column :label="t('visualBible.outfits.title')" min-width="320">
                    <template #default="{ row }">
                      <el-select
                        :model-value="row.outfit_variant_id"
                        clearable
                        :aria-label="`${row.name} ${t('visualBible.outfits.title')}`"
                        :placeholder="t('visualBible.assignments.defaultOutfit')"
                        @change="handleCharacterOutfitChange(row, $event)"
                      >
                        <el-option
                          v-for="outfit in outfits.filter(
                            (item) =>
                              item.outline_character_id === row.outline_character_id &&
                              (item.status === 'approved' || item.id === row.outfit_variant_id),
                          )"
                          :key="outfit.id"
                          :label="`${outfit.name} · v${outfit.version} · ${t(`visualBible.status.${outfit.status}`)}`"
                          :value="outfit.id"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('ux.details')" width="105">
                    <template #default="{ row }">
                      <el-button v-if="outfits.find((item) => item.id === row.outfit_variant_id)" link type="primary" @click="openSettingDetails('outfit', outfits.find((item) => item.id === row.outfit_variant_id)!, row.id)">{{ t('ux.details') }}</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
              <el-tab-pane :label="t('visualBible.assignments.scenes')" name="scenes">
                <el-table :data="scenes" height="560" class="assignment-table">
                  <el-table-column :label="t('visualBible.scenes.scene')" min-width="260">
                    <template #default="{ row }">
                       <strong>{{ row.name }}</strong>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('visualBible.scenes.title')" min-width="340">
                    <template #default="{ row }">
                      <el-select
                        :model-value="row.selected_visual_version_id"
                        clearable
                        :aria-label="`${row.name} ${t('visualBible.scenes.title')}`"
                        :placeholder="t('visualBible.assignments.noSceneVersion')"
                        @change="handleSceneVersionChange(row, $event)"
                      >
                        <el-option
                          v-for="version in sceneVersions.filter(
                            (item) =>
                              item.script_scene_id === row.id &&
                              (item.status === 'approved' || item.id === row.selected_visual_version_id),
                          )"
                          :key="version.id"
                          :label="`v${version.version} · ${t(`visualBible.status.${version.status}`)}`"
                          :value="version.id"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column :label="t('ux.details')" width="105">
                    <template #default="{ row }">
                      <el-button v-if="sceneVersions.find((item) => item.id === row.selected_visual_version_id)" link type="primary" @click="openSettingDetails('scene', sceneVersions.find((item) => item.id === row.selected_visual_version_id)!)">{{ t('ux.details') }}</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-tab-pane>
            </el-tabs>
          </div>
        </section>
      </el-tab-pane>

      <el-tab-pane name="references">
        <template #label><el-icon><Picture /></el-icon>{{ t('referenceLibrary.title') }}</template>
        <ReferenceLibrary
          :project-id="selectedProjectId" :script-task-id="selectedTaskId"
          :characters="projectOutlineCharacters.map(character => ({ id: character.id, label: character.name }))"
          :outfits="outfits" :current-characters="characters" :scenes="scenes" :scene-versions="sceneVersions" :assets="assets" :tools="generationTools"
          @changed="loadProjectData" @task="syncReferenceImageActivity" @bound="handleReferenceSceneBound"
        />
      </el-tab-pane>

      <el-tab-pane name="library">
        <template #label>
          <el-icon><Collection /></el-icon>{{ t('visualBible.tabs.library') }}
          <el-badge
            :value="draftOutfits.length + draftScenes.length"
            :hidden="draftOutfits.length + draftScenes.length === 0"
          />
        </template>
        <section class="panel review-inbox">
          <header class="panel__heading">
            <div>
              <h2>{{ t('visualBible.review.title') }}</h2>
              <p>{{ t('visualBible.review.description') }}</p>
            </div>
            <el-segmented
              v-model="libraryStatusFilter"
              :options="[
                { label: t('visualBible.review.draft'), value: 'draft' },
                { label: t('visualBible.review.approved'), value: 'approved' },
                { label: t('visualBible.review.all'), value: 'all' },
              ]"
            />
          </header>
          <div class="panel__body">
            <el-tabs v-model="activeLibraryTab" class="nested-tabs">
              <el-tab-pane :label="`${t('visualBible.outfits.title')} (${filteredOutfits.length})`" name="outfits">
                <div class="review-toolbar">
                  <el-button :icon="Plus" :disabled="selectedProjectId === null" @click="openOutfitEditor()">{{ t('visualBible.add') }}</el-button>
                  <el-button
                    v-if="draftOutfits.length > 0"
                    type="success"
                    :icon="Check"
                    :loading="batchApprovingKind === 'outfit'"
                    @click="approveAllDrafts('outfit')"
                  >{{ t('visualBible.review.approveAllCount', { count: draftOutfits.length }) }}</el-button>
                </div>
                <div class="review-list">
                  <el-empty v-if="filteredOutfits.length === 0" :description="t('visualBible.empty')" />
                  <div v-for="item in filteredOutfits" :key="item.id" class="row">
                    <div>
                      <strong>{{ item.name }} · v{{ item.version }}</strong>
                      <p>{{ arrayText(item.garment_components) }}</p>
                      <el-button link type="primary" @click="openSettingDetails('outfit', item)">{{ t('ux.details') }}</el-button>
                      <el-button link type="primary" @click="openOutfitEditor(item)">{{ t('ux.copyAndEdit') }}</el-button>
                      <el-popover placement="bottom-start" :width="360" trigger="click">
                        <template #reference>
                          <el-button link :icon="InfoFilled">{{ t('visualBible.review.technicalDetails') }}</el-button>
                        </template>
                        <span class="technical-detail">{{ item.key }}</span>
                      </el-popover>
                    </div>
                    <el-button v-if="item.status === 'draft'" type="success" plain :icon="Check" @click="approveConfig('outfit', item.id)">
                      {{ t('visualBible.approve') }}
                    </el-button>
                    <el-tag v-else type="success">{{ t(`visualBible.status.${item.status}`) }}</el-tag>
                  </div>
                </div>
              </el-tab-pane>
              <el-tab-pane :label="`${t('visualBible.scenes.title')} (${filteredSceneVersions.length})`" name="scenes">
                <div class="review-toolbar">
                  <el-button :icon="Plus" :disabled="selectedProjectId === null" @click="openSceneEditor()">{{ t('visualBible.add') }}</el-button>
                  <el-button
                    v-if="draftScenes.length > 0"
                    type="success"
                    :icon="Check"
                    :loading="batchApprovingKind === 'scene'"
                    @click="approveAllDrafts('scene')"
                  >{{ t('visualBible.review.approveAllCount', { count: draftScenes.length }) }}</el-button>
                </div>
                <div class="review-list">
                  <el-empty v-if="filteredSceneVersions.length === 0" :description="t('visualBible.empty')" />
                  <div v-for="item in filteredSceneVersions" :key="item.id" class="row">
                    <div>
                      <strong>{{ sceneVersionLabel(item) }}</strong>
                      <p>{{ arrayText(item.landmarks) }}</p>
                      <el-button link type="primary" @click="openSettingDetails('scene', item)">{{ t('ux.details') }}</el-button>
                      <el-button link type="primary" @click="openSceneEditor(item)">{{ t('ux.copyAndEdit') }}</el-button>
                      <el-popover placement="bottom-start" :width="360" trigger="click">
                        <template #reference><el-button link :icon="InfoFilled">{{ t('visualBible.review.technicalDetails') }}</el-button></template>
                        <span class="technical-detail">scene #{{ item.script_scene_id }}</span>
                      </el-popover>
                    </div>
                    <el-button v-if="item.status === 'draft'" type="success" plain :icon="Check" @click="approveConfig('scene', item.id)">
                      {{ t('visualBible.approve') }}
                    </el-button>
                    <el-tag v-else type="success">{{ t(`visualBible.status.${item.status}`) }}</el-tag>
                  </div>
                </div>
              </el-tab-pane>
              <el-tab-pane v-if="styles.length" :label="t('referenceLibrary.historicalStyle')" name="styles">
                <p class="historical-style-help">{{ t('referenceLibrary.historicalStyleHelp') }}</p>
                <div class="review-list"><div v-for="item in styles" :key="item.id" class="row">
                  <div><strong>{{ item.name }} · v{{ item.version }}</strong><p>{{ item.positive_natural_language || item.positive_tag }}</p>
                    <el-button link type="primary" @click="openSettingDetails('style', item)">{{ t('ux.details') }}</el-button></div>
                  <el-tag>{{ t(`visualBible.status.${item.status}`) }}</el-tag>
                </div></div>
              </el-tab-pane>
            </el-tabs>
          </div>
        </section>
      </el-tab-pane>

    </el-tabs>

    <el-drawer v-model="detailsDialog" :title="t('visualBible.details.title')" size="min(640px, 96vw)" append-to-body>
      <template v-if="detailVersion">
        <h3>{{ detailKind === 'scene' ? sceneVersionLabel(detailVersion as SceneVisualVersion) : (detailVersion as OutfitVariant | StyleProfile).name }}</h3>
        <el-tag :type="referenceStatusTagType(detailVersion.status)">{{ t(`visualBible.status.${detailVersion.status}`) }} · v{{ detailVersion.version }}</el-tag>
        <VisualSettingDetails :kind="detailKind" :value="detailVersion" />
        <el-form v-if="detailKind === 'outfit' && detailVersion.status === 'approved'" label-position="top">
          <el-form-item :label="t('visualBible.details.selectCharacter')">
            <el-select v-model="bindingCharacterId" :placeholder="t('visualBible.details.selectCharacter')">
              <el-option v-for="character in bindingCharacterOptions" :key="character.id" :value="character.id" :label="`${character.name} · ${t('scripts.sections.sectionNo', { sectionNo: character.section_no ?? '?' })}`" />
            </el-select>
          </el-form-item>
        </el-form>
        <p v-if="detailKind === 'style'" class="muted">{{ t('referenceLibrary.historicalStyleHelp') }}</p>
        <el-collapse>
          <el-collapse-item :title="t('ux.advancedSettings')" name="technical">
            <dl class="setting-technical-details">
              <dt>{{ t('visualBible.key') }}</dt><dd>{{ 'key' in detailVersion ? detailVersion.key : (detailVersion as SceneVisualVersion).script_scene_id }}</dd>
              <dt>ID</dt><dd>{{ detailVersion.id }}</dd>
            </dl>
          </el-collapse-item>
        </el-collapse>
      </template>
      <template #footer>
        <div class="detail-actions" v-if="detailVersion">
          <el-button v-if="detailKind !== 'style'" @click="copySettingVersion">{{ t('ux.copyAndEdit') }}</el-button>
          <el-button v-if="detailKind !== 'style' && detailVersion.status === 'draft'" type="success" @click="approveConfig(detailKind, detailVersion.id)">{{ t('visualBible.approve') }}</el-button>
          <el-button v-if="detailKind !== 'style' && detailVersion.status === 'approved'" type="primary" :disabled="!canUseVersion" @click="useSettingVersion">{{ t('ux.useVersion') }}</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="outfitDialog" :title="copiedOutfit ? t('ux.copyAndEdit') : t('visualBible.outfits.add')" width="min(620px, 96vw)">
      <el-alert v-if="copiedOutfit" :title="t('visualBible.details.copyHint')" type="info" :closable="false" />
      <el-form label-position="top">
        <el-form-item :label="t('visualBible.character')"
          ><el-select v-model="outfitForm.outline_character_id" :disabled="copiedOutfit !== null"
            ><el-option
              v-for="option in outlineCharacterOptions"
              :key="option.id"
              :label="option.label"
              :value="option.id" /></el-select
        ></el-form-item>
        <div>
          <el-form-item :label="t('visualBible.name')"
            ><el-input v-model="outfitForm.name"
          /></el-form-item>
        </div>
        <el-form-item :label="t('visualBible.outfits.garments')"
          ><el-input v-model="outfitForm.garments"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('visualBible.outfits.colors')"
            ><el-input v-model="outfitForm.colors" /></el-form-item
          ><el-form-item :label="t('visualBible.outfits.materials')"
            ><el-input v-model="outfitForm.materials"
          /></el-form-item>
        </div>
        <el-form-item :label="t('visualBible.outfits.accessories')"
          ><el-input v-model="outfitForm.accessories"
        /></el-form-item>
        <el-form-item :label="t('visualBible.details.negativeConstraints')"><el-input v-model="outfitForm.negative_constraints" type="textarea" :rows="3" /></el-form-item>
        <el-collapse>
          <el-collapse-item :title="t('ux.advancedSettings')" name="advanced">
            <el-form-item :label="t('visualBible.key')"><el-input v-model="outfitForm.key" :disabled="copiedOutfit !== null" /></el-form-item>
            <el-form-item :label="t('visualBible.details.layerOrder')"><el-input v-model="outfitForm.layer_order" type="textarea" /></el-form-item>
            <el-form-item :label="t('visualBible.details.patterns')"><el-input v-model="outfitForm.patterns" type="textarea" /></el-form-item>
            <el-form-item :label="t('visualBible.details.triggerTokens')"><el-input v-model="outfitForm.trigger_tokens" type="textarea" /></el-form-item>
          </el-collapse-item>
        </el-collapse>
        </el-form
      ><template #footer
        ><el-button @click="outfitDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" :loading="savingConfiguration === 'outfit'" @click="saveOutfit">{{
          t('projects.save')
        }}</el-button></template
      >
    </el-dialog>

    <el-dialog v-model="sceneDialog" :title="copiedScene ? t('ux.copyAndEdit') : t('visualBible.scenes.add')" width="min(680px, 96vw)">
      <el-alert v-if="copiedScene" :title="t('visualBible.details.copyHint')" type="info" :closable="false" />
      <el-form label-position="top"
        ><el-form-item :label="t('visualBible.scenes.scene')"
          ><el-select v-model="sceneForm.script_scene_id" :disabled="copiedScene !== null"
            ><el-option
              v-for="scene in scenes"
              :key="scene.id"
              :label="scene.name"
              :value="scene.id" /></el-select></el-form-item
        ><el-form-item :label="t('visualBible.scenes.landmarks')"
          ><el-input v-model="sceneForm.landmarks" /></el-form-item
        ><el-form-item :label="t('visualBible.objectStates')"
          ><el-input v-model="sceneForm.object_states" type="textarea" /></el-form-item
        ><el-form-item :label="t('visualBible.spatialRelations')"
          ><el-input v-model="sceneForm.spatial_relations" type="textarea" /></el-form-item
        ><el-form-item :label="t('visualBible.details.lightingState')"><el-input v-model="sceneForm.lighting_state" type="textarea" /></el-form-item>
        <el-collapse><el-collapse-item :title="t('ux.advancedSettings')" name="advanced">
          <el-form-item :label="t('visualBible.details.cameraPresets')"><el-input v-model="sceneForm.camera_presets" type="textarea" /></el-form-item>
          <el-form-item :label="t('visualBible.details.colorPalette')"><el-input v-model="sceneForm.color_palette" type="textarea" /></el-form-item>
        </el-collapse-item></el-collapse>
      </el-form>
      <template #footer
        ><el-button @click="sceneDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" :loading="savingConfiguration === 'scene'" @click="saveScene">{{ t('projects.save') }}</el-button></template
      >
    </el-dialog>

  </div>
</template>

<style scoped>
.visual-bible-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
  gap: 18px;
}

.reference-upload-drafts h4 { margin: 12px 0; font-size: 14px; }
.reference-upload-draft { display: grid; gap: 8px; border: 1px solid var(--panel-border); border-radius: 8px; padding: 12px; }
.reference-upload-draft :deep(.el-image) { width: 100%; height: 160px; }
.detail-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.detail-actions :deep(.el-button) { margin-left: 0; }
.setting-technical-details { overflow-wrap: anywhere; }
.setting-technical-details dd { margin: 5px 0 12px; }

.visual-bible-tabs :deep(.el-tabs__item),
.nested-tabs :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.visual-bible-tabs :deep(.el-badge__content) {
  transform: translateY(-5px) translateX(6px) scale(0.82);
}

.page-header {
  margin-bottom: 6px;
}

.selectors,
.panel__heading,
.row,
.asset-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.selectors {
  width: min(100%, 620px);
  min-width: 0;
}

.selectors :deep(.el-select) {
  flex: 1;
  min-width: 0;
}

.selector-prefix {
  color: var(--text-soft);
  font-size: 12px;
}

.panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #ffffff;
  box-shadow: var(--panel-shadow);
}

.panel__heading {
  align-items: flex-start;
  padding: 20px 22px 16px;
  border-bottom: 1px solid var(--panel-border);
}

.panel__heading h2,
.panel__heading p,
.row p {
  margin: 0;
}

.panel__heading h2 {
  font-size: 18px;
}

.panel__heading p,
.row p {
  margin-top: 6px;
  color: var(--text-soft);
  line-height: 1.5;
}

.panel__body {
  padding: 18px 22px 22px;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  align-items: start;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.model-profile-alert {
  margin-bottom: 14px;
}

.card {
  display: grid;
  align-content: start;
  gap: 8px;
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fbff;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease,
    transform 0.2s ease;
}

.card:hover,
.card:focus-visible {
  border-color: rgba(23, 109, 255, 0.38);
  box-shadow: 0 10px 24px rgba(23, 109, 255, 0.1);
  transform: translateY(-1px);
}

.card:focus-visible {
  outline: 3px solid rgba(23, 109, 255, 0.2);
  outline-offset: 2px;
}

.card__action {
  color: var(--brand);
  font-size: 13px;
  font-weight: 700;
}

.card p,
.card small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card p {
  margin: 0;
  color: var(--text-regular);
}

.card small {
  color: var(--text-soft);
}

.panel__list {
  padding-top: 6px;
  padding-bottom: 6px;
}

.row {
  min-width: 0;
  padding: 12px 0;
  border-bottom: 1px solid var(--panel-border);
}

.row:last-child {
  border-bottom: 0;
}

.row > div {
  min-width: 0;
}

.row p {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-info {
  justify-content: flex-start;
  min-width: 0;
}

.asset-info img {
  width: 64px;
  height: 64px;
  flex: 0 0 auto;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  object-fit: cover;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.assignment-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}

.character-type-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.character-type-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 0.8fr);
  align-items: center;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fbff;
}

.character-type-card > div,
.assignment-table strong,
.assignment-table small,
.reference-collapse-title > div {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.assignment-table {
  margin-top: 14px;
}

.assignment-group h3 {
  margin: 0 0 8px;
  color: var(--text-strong);
  font-size: 15px;
}

.assignment-group .assignment-subheading {
  margin-top: 22px;
}

.assignment-hint {
  margin: 0 0 6px;
  color: var(--text-soft);
  font-size: 13px;
}

.assignment-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 0.7fr);
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid var(--panel-border);
}

.assignment-row:last-child {
  border-bottom: 0;
}

.reference-characters,
.reference-candidates,
.reference-prompt-list {
  display: grid;
  gap: 16px;
}

.reference-accordion :deep(.el-collapse-item__header) {
  min-height: 62px;
  height: auto;
  padding: 8px 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fbfcff;
}

.reference-accordion :deep(.el-collapse-item + .el-collapse-item) {
  margin-top: 10px;
}

.reference-accordion :deep(.el-collapse-item__wrap) {
  border-bottom: 0;
}

.reference-accordion :deep(.el-collapse-item__content) {
  padding: 12px 0 4px;
}

.reference-collapse-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 12px;
  padding-right: 14px;
}

.reference-character {
  display: grid;
  gap: 16px;
  padding: 18px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fbfcff;
}

.reference-character__heading,
.reference-task-toolbar,
.reference-candidate__meta,
.reference-run__footer {
  display: flex;
  align-items: center;
  gap: 10px;
}

.reference-character__heading {
  justify-content: space-between;
}

.reference-character__heading h3,
.reference-prompt-card h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
}

.reference-character__heading span,
.reference-candidate__meta > span {
  color: var(--text-soft);
  font-size: 12px;
}

.approved-reference-grid,
.reference-candidate__images,
.reference-prompt-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.approved-reference,
.reference-run {
  min-width: 0;
}

.approved-reference {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  color: var(--text-regular);
  font-size: 13px;
}

.approved-reference img,
.approved-reference .el-image,
.approved-reference .reference-image-placeholder {
  width: 64px;
  height: 64px;
  border-radius: 8px;
}

.reference-task-toolbar {
  flex-wrap: wrap;
}

.reference-task-toolbar :deep(.el-select) {
  width: min(100%, 360px);
}

.reference-task-error {
  margin-top: -6px;
}

.reference-candidate {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
}

.reference-candidate__meta {
  align-content: flex-start;
  align-items: flex-start;
  flex-direction: column;
}

.reference-run {
  overflow: hidden;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f5f7fb;
}

.reference-run > img,
.reference-run > .el-image,
.reference-run > .reference-image-placeholder {
  width: 100%;
  aspect-ratio: 4 / 5;
}

.reference-run > img,
.reference-run > .el-image,
.approved-reference img {
  display: block;
  object-fit: cover;
}

.reference-run > .el-image :deep(img),
.approved-reference .el-image :deep(img) {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.reference-image-placeholder {
  display: grid;
  place-items: center;
  box-sizing: border-box;
  padding: 10px;
  border: 1px dashed var(--panel-border);
  background: #f2f5fa;
  color: var(--text-soft);
  font-size: 12px;
  text-align: center;
}

.reference-run__footer {
  align-items: flex-start;
  flex-wrap: wrap;
  padding: 10px;
  font-size: 12px;
}

.reference-run__footer strong {
  width: 100%;
}

.reference-run__error {
  width: 100%;
  color: var(--el-color-danger);
  line-height: 1.4;
}

.reference-form-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 1.2fr) minmax(140px, 0.5fr);
  gap: 14px;
}

.reference-request-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.reference-request-summary > div {
  display: grid;
  gap: 4px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fbff;
}

.reference-request-summary span,
.prompt-character-count {
  color: var(--text-soft);
  font-size: 12px;
}

.reference-prompt-tabs {
  margin-top: 16px;
}

.reference-prompt-tabs :deep(.el-tabs__item) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.reference-prompt-card {
  max-width: 920px;
  margin: 0 auto;
}

.prompt-character-count {
  display: block;
  width: 100%;
  margin-top: 4px;
  text-align: right;
}

.review-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.review-list,
.asset-list {
  max-height: 610px;
  overflow: auto;
  padding-right: 6px;
}

.review-list .row,
.asset-list .row {
  padding: 14px 4px;
}

.review-list .el-button.is-link {
  margin-top: 4px;
  padding: 0;
}

.reference-prompt-list {
  margin-top: 16px;
}

.reference-prompt-card {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fbfcff;
}

.reference-prompt-card h3 {
  margin-bottom: 12px;
}

.license-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

@media (max-width: 1080px) {
  .grid,
  .assignment-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .selectors {
    width: 100%;
  }

  .reference-candidate,
  .reference-form-grid,
  .reference-request-summary {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .selectors {
    width: 100%;
    max-width: 100%;
  }

  .selectors,
  .panel__heading,
  .row {
    align-items: stretch;
    flex-direction: column;
  }

  .form-grid,
  .license-grid,
  .assignment-row,
  .approved-reference-grid,
  .reference-candidate__images,
  .reference-prompt-list {
    grid-template-columns: 1fr;
  }

  .reference-character__heading,
  .reference-task-toolbar,
  .review-toolbar,
  .character-type-card {
    align-items: stretch;
    flex-direction: column;
    grid-template-columns: 1fr;
  }
}
</style>

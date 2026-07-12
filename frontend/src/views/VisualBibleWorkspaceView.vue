<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Check, Plus, UploadFilled } from '@element-plus/icons-vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'

import { apiErrorMessage } from '@/api/errors'
import { listProjects, type Project } from '@/api/projects'
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
  uploadVisualAsset,
  type OutfitVariant,
  type SceneVisualVersion,
  type StyleProfile,
  type VisualAsset,
  type VisualAssetRole,
  type VisualEntityType,
} from '@/api/visualBible'
import { useProjectContextStore } from '@/stores/projectContext'

const { t } = useI18n()
const projectContext = useProjectContextStore()
const { selectedProjectId } = storeToRefs(projectContext)
const projects = ref<Project[]>([])
const tasks = ref<ScriptTask[]>([])
const characters = ref<ScriptCharacter[]>([])
const scenes = ref<ScriptScene[]>([])
const outfits = ref<OutfitVariant[]>([])
const styles = ref<StyleProfile[]>([])
const sceneVersions = ref<SceneVisualVersion[]>([])
const assets = ref<VisualAsset[]>([])
const selectedTaskId = ref<number | null>(null)
const loading = ref(false)

const outfitDialog = ref(false)
const styleDialog = ref(false)
const sceneDialog = ref(false)
const assetDialog = ref(false)
const selectedFile = ref<File | null>(null)

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
  scene: [
    'scene_master',
    'prop_reference',
    'depth',
    'canny',
    'lineart',
    'segmentation',
    'mask',
  ],
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
})
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
})
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

const parseObject = (value: string, label: string) => {
  const parsed = JSON.parse(value || '{}') as unknown
  if (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} must be a JSON object`)
  }
  return parsed as Record<string, unknown>
}

const ownerOptions = computed(() => {
  if (assetForm.entity_type === 'character') {
    const values = new Map<number, string>()
    characters.value.forEach((item) => {
      if (item.outline_character_id)
        values.set(item.outline_character_id, `${item.character_key} · ${item.name}`)
    })
    return [...values.entries()].map(([id, label]) => ({ id, label }))
  }
  if (assetForm.entity_type === 'outfit') {
    return outfits.value.map((item) => ({
      id: item.id,
      label: `${item.key} v${item.version} · ${item.name}`,
    }))
  }
  if (assetForm.entity_type === 'scene') {
    return sceneVersions.value.map((item) => ({
      id: item.id,
      label: `scene #${item.script_scene_id} v${item.version}`,
    }))
  }
  if (assetForm.entity_type === 'style') {
    return styles.value.map((item) => ({
      id: item.id,
      label: `${item.key} v${item.version} · ${item.name}`,
    }))
  }
  return []
})
const assetRoleOptions = computed(() => assetRolesByEntity[assetForm.entity_type])

const outlineCharacterOptions = computed(() => {
  const values = new Map<number, { id: number; label: string }>()
  characters.value.forEach((item) => {
    if (item.outline_character_id) {
      values.set(item.outline_character_id, {
        id: item.outline_character_id,
        label: `${item.character_key} · ${item.name}`,
      })
    }
  })
  return [...values.values()]
})

const loadProjectData = async () => {
  if (selectedProjectId.value === null) return
  loading.value = true
  try {
    ;[tasks.value, outfits.value, styles.value, sceneVersions.value, assets.value] =
      await Promise.all([
        listProjectScriptTasks(selectedProjectId.value, { status: 'succeeded' }),
        listOutfits(selectedProjectId.value),
        listStyles(selectedProjectId.value),
        listSceneVersions(selectedProjectId.value),
        listVisualAssets(selectedProjectId.value),
      ])
    const firstTask = tasks.value[0]
    if (!tasks.value.some((item) => item.id === selectedTaskId.value)) {
      selectedTaskId.value = firstTask?.id ?? null
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.load')))
  } finally {
    loading.value = false
  }
}

const loadTaskVisuals = async () => {
  if (selectedTaskId.value === null) {
    characters.value = []
    scenes.value = []
    return
  }
  try {
    ;[characters.value, scenes.value] = await Promise.all([
      listScriptTaskCharacters(selectedTaskId.value),
      listScriptTaskScenes(selectedTaskId.value),
    ])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.load')))
  }
}

const saveOutfit = async () => {
  if (selectedProjectId.value === null || outfitForm.outline_character_id === null) return
  try {
    await createOutfit(selectedProjectId.value, {
      outline_character_id: outfitForm.outline_character_id,
      key: outfitForm.key,
      name: outfitForm.name,
      garment_components: splitValues(outfitForm.garments),
      layer_order: [],
      colors: splitValues(outfitForm.colors),
      materials: splitValues(outfitForm.materials),
      patterns: [],
      accessories: splitValues(outfitForm.accessories),
      trigger_tokens: [],
      negative_constraints: outfitForm.negative_constraints,
    })
    outfitDialog.value = false
    await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const saveStyle = async () => {
  if (selectedProjectId.value === null) return
  try {
    await createStyle(selectedProjectId.value, {
      key: styleForm.key,
      name: styleForm.name,
      positive_tag: styleForm.positive_tag,
      negative_tag: styleForm.negative_tag,
      positive_natural_language: styleForm.positive_natural_language,
      negative_natural_language: styleForm.negative_natural_language,
      color_palette: splitValues(styleForm.color_palette),
      lighting: styleForm.lighting,
    })
    styleDialog.value = false
    await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const saveScene = async () => {
  if (selectedProjectId.value === null || sceneForm.script_scene_id === null) return
  try {
    await createSceneVersion(selectedProjectId.value, {
      script_scene_id: sceneForm.script_scene_id,
      landmarks: splitValues(sceneForm.landmarks),
      spatial_relations: parseObject(sceneForm.spatial_relations, 'spatial_relations'),
      camera_presets: [],
      object_states: parseObject(sceneForm.object_states, 'object_states'),
      color_palette: [],
      lighting_state: parseObject(sceneForm.lighting_state, 'lighting_state'),
    })
    sceneDialog.value = false
    await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const fileChanged = (event: Event) => {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

const saveAsset = async () => {
  if (selectedProjectId.value === null) return
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
      await uploadVisualAsset(selectedProjectId.value, form)
    } else {
      await registerVisualAsset(selectedProjectId.value, {
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
    await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const approveConfig = async (kind: 'outfit' | 'style' | 'scene', id: number) => {
  try {
    await setConfigurationStatus(kind, id, 'approved')
    await loadProjectData()
    ElMessage.success(t('visualBible.messages.saved'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.save')))
  }
}

const approveAsset = async (id: number) => {
  try {
    await setVisualAssetStatus(id, 'approved')
    await loadProjectData()
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

const handleSceneVersionChange = (scene: ScriptScene, value: unknown) =>
  assignSceneVersion(scene, typeof value === 'number' ? value : null)

watch(selectedProjectId, loadProjectData)
watch(selectedTaskId, loadTaskVisuals)
watch(
  () => assetForm.entity_type,
  () => {
    assetForm.entity_id = null
    assetForm.entity_key = ''
    assetForm.role = assetRolesByEntity[assetForm.entity_type][0] ?? 'identity_face'
  },
)
onMounted(async () => {
  try {
    const previousProjectId = selectedProjectId.value
    projects.value = await listProjects()
    if (!projects.value.some((project) => project.id === selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? null
    }
    if (selectedProjectId.value !== null && selectedProjectId.value === previousProjectId) {
      await loadProjectData()
    }
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('visualBible.errors.load')))
  }
})
</script>

<template>
  <div class="visual-bible-page" v-loading="loading">
    <div class="page-header">
      <div class="selectors">
        <el-select v-model="selectedProjectId" filterable :placeholder="t('visualBible.project')">
          <template #prefix
            ><span class="selector-prefix">{{ t('visualBible.project') }}</span></template
          >
          <el-option
            v-for="project in projects"
            :key="project.id"
            :label="project.title"
            :value="project.id"
          />
        </el-select>
        <el-select
          v-model="selectedTaskId"
          clearable
          filterable
          :placeholder="t('visualBible.scriptTask')"
        >
          <template #prefix
            ><span class="selector-prefix">{{ t('visualBible.scriptTask') }}</span></template
          >
          <el-option
            v-for="task in tasks"
            :key="task.id"
            :label="`#${task.id} · ${task.total_pages}p`"
            :value="task.id"
          />
        </el-select>
      </div>
    </div>

    <section v-if="selectedTaskId" class="panel">
      <header class="panel__heading">
        <div>
          <h2>{{ t('visualBible.assignments.title') }}</h2>
          <p>{{ t('visualBible.assignments.hint') }}</p>
        </div>
      </header>
      <div class="panel__body">
        <div class="assignment-grid">
          <div class="assignment-group">
            <h3>{{ t('visualBible.assignments.characters') }}</h3>
            <div v-for="character in characters" :key="character.id" class="assignment-row">
              <span
                >{{ character.character_key }} · {{ character.name }} · §{{
                  character.section_no
                }}</span
              >
              <el-select
                :model-value="character.outfit_variant_id"
                clearable
                :placeholder="t('visualBible.assignments.defaultOutfit')"
                @change="handleCharacterOutfitChange(character, $event)"
              >
                <el-option
                  v-for="outfit in outfits.filter(
                    (item) =>
                      item.outline_character_id === character.outline_character_id &&
                      (item.status === 'approved' || item.id === character.outfit_variant_id),
                  )"
                  :key="outfit.id"
                  :label="`${outfit.name} v${outfit.version} · ${t(`visualBible.status.${outfit.status}`)}`"
                  :value="outfit.id"
                />
              </el-select>
            </div>
          </div>
          <div class="assignment-group">
            <h3>{{ t('visualBible.assignments.scenes') }}</h3>
            <div v-for="scene in scenes" :key="scene.id" class="assignment-row">
              <span>{{ scene.scene_key }} · {{ scene.name }}</span>
              <el-select
                :model-value="scene.selected_visual_version_id"
                clearable
                :placeholder="t('visualBible.assignments.noSceneVersion')"
                @change="handleSceneVersionChange(scene, $event)"
              >
                <el-option
                  v-for="version in sceneVersions.filter(
                    (item) =>
                      item.script_scene_id === scene.id &&
                      (item.status === 'approved' || item.id === scene.selected_visual_version_id),
                  )"
                  :key="version.id"
                  :label="`v${version.version} · ${t(`visualBible.status.${version.status}`)}`"
                  :value="version.id"
                />
              </el-select>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="grid">
      <article class="panel">
        <header class="panel__heading">
          <div>
            <h2>{{ t('visualBible.outfits.title') }}</h2>
          </div>
          <el-button :icon="Plus" @click="outfitDialog = true">{{
            t('visualBible.add')
          }}</el-button>
        </header>
        <div class="panel__body panel__list">
          <el-empty v-if="outfits.length === 0" :description="t('visualBible.empty')" />
          <div v-for="item in outfits" :key="item.id" class="row">
            <div>
              <strong>{{ item.key }} v{{ item.version }} · {{ item.name }}</strong>
              <p>{{ item.garment_components.join(', ') }}</p>
            </div>
            <el-button
              v-if="item.status === 'draft'"
              link
              type="success"
              :icon="Check"
              @click="approveConfig('outfit', item.id)"
              >{{ t('visualBible.approve') }}</el-button
            >
            <el-tag v-else>{{ item.status }}</el-tag>
          </div>
        </div>
      </article>

      <article class="panel">
        <header class="panel__heading">
          <div>
            <h2>{{ t('visualBible.scenes.title') }}</h2>
          </div>
          <el-button :icon="Plus" @click="sceneDialog = true">{{ t('visualBible.add') }}</el-button>
        </header>
        <div class="panel__body panel__list">
          <el-empty v-if="sceneVersions.length === 0" :description="t('visualBible.empty')" />
          <div v-for="item in sceneVersions" :key="item.id" class="row">
            <div>
              <strong>#{{ item.script_scene_id }} v{{ item.version }}</strong>
              <p>{{ item.landmarks.join(', ') }}</p>
            </div>
            <el-button
              v-if="item.status === 'draft'"
              link
              type="success"
              @click="approveConfig('scene', item.id)"
              >{{ t('visualBible.approve') }}</el-button
            >
            <el-tag v-else>{{ item.status }}</el-tag>
          </div>
        </div>
      </article>

      <article class="panel">
        <header class="panel__heading">
          <div>
            <h2>{{ t('visualBible.styles.title') }}</h2>
          </div>
          <el-button :icon="Plus" @click="styleDialog = true">{{ t('visualBible.add') }}</el-button>
        </header>
        <div class="panel__body panel__list">
          <el-empty v-if="styles.length === 0" :description="t('visualBible.empty')" />
          <div v-for="item in styles" :key="item.id" class="row">
            <div>
              <strong>{{ item.key }} v{{ item.version }} · {{ item.name }}</strong>
              <p>{{ item.positive_natural_language || item.positive_tag }}</p>
            </div>
            <el-button
              v-if="item.status === 'draft'"
              link
              type="success"
              @click="approveConfig('style', item.id)"
              >{{ t('visualBible.approve') }}</el-button
            >
            <el-tag v-else>{{ item.status }}</el-tag>
          </div>
        </div>
      </article>

      <article class="panel">
        <header class="panel__heading">
          <div>
            <h2>{{ t('visualBible.assets.title') }}</h2>
          </div>
          <el-button :icon="UploadFilled" @click="assetDialog = true">{{
            t('visualBible.assets.add')
          }}</el-button>
        </header>
        <div class="panel__body panel__list">
          <el-empty v-if="assets.length === 0" :description="t('visualBible.empty')" />
          <div v-for="item in assets" :key="item.id" class="row">
            <div class="asset-info">
              <img
                v-if="item.local_path"
                :src="`/api/visual-bible/assets/${item.id}/file`"
                alt=""
              />
              <div>
                <strong>{{ item.entity_type }} · {{ item.role }} · v{{ item.version }}</strong>
                <p>{{ item.renderer_locator || item.sha256 }}</p>
              </div>
            </div>
            <el-button
              v-if="item.status === 'draft'"
              link
              type="success"
              @click="approveAsset(item.id)"
              >{{ t('visualBible.approve') }}</el-button
            >
            <el-tag v-else>{{ item.status }}</el-tag>
          </div>
        </div>
      </article>
    </section>

    <el-dialog v-model="outfitDialog" :title="t('visualBible.outfits.add')" width="620px">
      <el-form label-position="top">
        <el-form-item :label="t('visualBible.character')"
          ><el-select v-model="outfitForm.outline_character_id"
            ><el-option
              v-for="option in outlineCharacterOptions"
              :key="option.id"
              :label="option.label"
              :value="option.id" /></el-select
        ></el-form-item>
        <div class="form-grid">
          <el-form-item :label="t('visualBible.key')"
            ><el-input v-model="outfitForm.key" /></el-form-item
          ><el-form-item :label="t('visualBible.name')"
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
        /></el-form-item> </el-form
      ><template #footer
        ><el-button @click="outfitDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" @click="saveOutfit">{{
          t('projects.save')
        }}</el-button></template
      >
    </el-dialog>

    <el-dialog v-model="styleDialog" :title="t('visualBible.styles.add')" width="620px">
      <el-form label-position="top"
        ><div class="form-grid">
          <el-form-item :label="t('visualBible.key')"
            ><el-input v-model="styleForm.key" /></el-form-item
          ><el-form-item :label="t('visualBible.name')"
            ><el-input v-model="styleForm.name"
          /></el-form-item>
        </div>
        <el-form-item :label="t('visualBible.styles.positiveTag')"
          ><el-input v-model="styleForm.positive_tag" type="textarea" :rows="4" /></el-form-item
        ><el-form-item :label="t('visualBible.styles.negativeTag')"
          ><el-input v-model="styleForm.negative_tag" type="textarea" :rows="3" /></el-form-item
        ><el-form-item :label="t('visualBible.styles.positiveNaturalLanguage')"
          ><el-input v-model="styleForm.positive_natural_language" type="textarea" :rows="5" /></el-form-item
        ><el-form-item :label="t('visualBible.styles.negativeNaturalLanguage')"
          ><el-input v-model="styleForm.negative_natural_language" type="textarea" :rows="4" /></el-form-item
        ><el-form-item :label="t('visualBible.lighting')"
          ><el-input v-model="styleForm.lighting" /></el-form-item
      ></el-form>
      <template #footer
        ><el-button @click="styleDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" @click="saveStyle">{{ t('projects.save') }}</el-button></template
      >
    </el-dialog>

    <el-dialog v-model="sceneDialog" :title="t('visualBible.scenes.add')" width="680px">
      <el-form label-position="top"
        ><el-form-item :label="t('visualBible.scenes.scene')"
          ><el-select v-model="sceneForm.script_scene_id"
            ><el-option
              v-for="scene in scenes"
              :key="scene.id"
              :label="`${scene.scene_key} · ${scene.name}`"
              :value="scene.id" /></el-select></el-form-item
        ><el-form-item :label="t('visualBible.scenes.landmarks')"
          ><el-input v-model="sceneForm.landmarks" /></el-form-item
        ><el-form-item :label="t('visualBible.objectStates')"
          ><el-input v-model="sceneForm.object_states" type="textarea" /></el-form-item
        ><el-form-item :label="t('visualBible.spatialRelations')"
          ><el-input v-model="sceneForm.spatial_relations" type="textarea" /></el-form-item
      ></el-form>
      <template #footer
        ><el-button @click="sceneDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" @click="saveScene">{{ t('projects.save') }}</el-button></template
      >
    </el-dialog>

    <el-dialog v-model="assetDialog" :title="t('visualBible.assets.add')" width="680px">
      <el-form label-position="top"
        ><el-radio-group v-model="assetForm.mode"
          ><el-radio-button value="upload">{{ t('visualBible.uploadImage') }}</el-radio-button
          ><el-radio-button value="locator">{{
            t('visualBible.rendererLocator')
          }}</el-radio-button></el-radio-group
        >
        <div class="form-grid">
          <el-form-item :label="t('visualBible.entity')"
            ><el-select v-model="assetForm.entity_type"
              ><el-option
                v-for="value in ['character', 'outfit', 'scene', 'style', 'prop', 'control']"
                :key="value"
                :label="value"
                :value="value" /></el-select></el-form-item
          ><el-form-item :label="t('visualBible.owner')"
            ><el-select v-if="ownerOptions.length" v-model="assetForm.entity_id"
              ><el-option
                v-for="option in ownerOptions"
                :key="option.id"
                :label="option.label"
                :value="option.id" /></el-select
            ><el-input
              v-else
              v-model="assetForm.entity_key"
              :placeholder="t('visualBible.stableEntityKey')"
          /></el-form-item>
        </div>
        <el-form-item :label="t('visualBible.role')"
            ><el-select v-model="assetForm.role" filterable
              ><el-option
                v-for="value in assetRoleOptions"
                :key="value"
                :label="value"
                :value="value" /></el-select></el-form-item>
        <el-form-item v-if="assetForm.mode === 'upload'" :label="t('visualBible.image')"
          ><input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            @change="fileChanged" /></el-form-item
        ><template v-else
          ><el-form-item :label="t('visualBible.rendererLocator')"
            ><el-input v-model="assetForm.renderer_locator" /></el-form-item
          ><el-form-item :label="t('visualBible.sha256')"
            ><el-input v-model="assetForm.sha256" /></el-form-item></template
        ><el-checkbox v-model="assetForm.approve">{{
          t('visualBible.assets.approveNow')
        }}</el-checkbox></el-form
      >
      <template #footer
        ><el-button @click="assetDialog = false">{{ t('projects.cancel') }}</el-button
        ><el-button type="primary" @click="saveAsset">{{ t('projects.save') }}</el-button></template
      >
    </el-dialog>

  </div>
</template>

<style scoped>
.visual-bible-page {
  display: grid;
  gap: 18px;
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

.assignment-group h3 {
  margin: 0 0 8px;
  color: var(--text-strong);
  font-size: 15px;
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
}

@media (max-width: 640px) {
  .selectors,
  .panel__heading,
  .row {
    align-items: stretch;
    flex-direction: column;
  }

  .form-grid,
  .license-grid,
  .assignment-row {
    grid-template-columns: 1fr;
  }
}
</style>

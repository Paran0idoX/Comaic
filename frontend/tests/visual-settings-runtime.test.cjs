const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')

const sourcePath = path.resolve(__dirname, '../src/views/VisualBibleWorkspaceView.vue')
const { descriptor } = parse(fs.readFileSync(sourcePath, 'utf8'))
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'visual-settings-runtime-test' }).content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}
const fixtureOutfit = (projectId = 1) => ({
  id: projectId * 10, project_id: projectId, outline_character_id: projectId * 100,
  key: 'hero-outfit', version: 1, name: '旅行装', status: 'approved',
  garment_components: [{ garment: '外套', details: ['口袋', '袖口'] }],
  layer_order: ['衬衣', '外套'], colors: ['蓝'], materials: ['棉'], patterns: ['条纹'],
  accessories: ['手表'], trigger_tokens: ['travel'], negative_constraints: '不要改色',
})

// 执行真实 setup/watch；所有接口均使用内存 fixture，不请求模型、图片服务或真实数据库。
const harness = (query = { project_id: '1', script_task_id: '11' }) => {
  const route = vue.reactive({ path: '/visual-bible', query })
  const selectedProjectId = vue.ref(1)
  const lifecycle = {}
  const activities = new Map()
  const callbacks = new Map()
  const saved = { outfits: [], styles: [], scenes: [], assets: [], bindings: [] }
  const warnings = []
  const tasks = [11, 12, 21].map((id) => ({ id, project_id: id < 20 ? 1 : 2, outline_version_id: id * 10, status: 'succeeded', total_pages: 2 }))
  const outlineCharacter = (id) => ({ id, name: `角色 ${id}`, character_key: `character-${id}`, visual_type: 'stylized_human' })
  const characterIds = { 11: 100, 12: 120, 21: 200 }
  const character = (taskId) => ({ id: taskId * 100, outline_character_id: characterIds[taskId], name: `角色 ${characterIds[taskId]}`, character_key: `character-${characterIds[taskId]}`, section_no: 1, outfit_variant_id: taskId < 20 ? 10 : 20 })
  const referenceTask = (characterId, id, status) => ({
    id, project_id: characterId < 200 ? 1 : 2, outline_character_id: characterId,
    character_name: `角色 ${characterId}`, candidate_count: 2, progress: { total: 6, completed: status === 'succeeded' ? 6 : 0 },
    status, updated_at: '2026-10-01T00:00:00Z', candidates: [],
  })
  const referenceLists = new Map([100, 120, 200].map((id) => [id, [referenceTask(id, id + 3, 'succeeded'), referenceTask(id, id + 2, 'failed'), referenceTask(id, id + 1, 'running')]]))
  const outfits = [fixtureOutfit(1), fixtureOutfit(2)]
  let pendingCharacters = null
  const scene = { id: 1100, project_id: 1, script_scene_id: 110, version: 1, landmarks: ['灯塔'], spatial_relations: { path: ['港口', '灯塔'] }, camera_presets: [{ lens: 35 }], object_states: { door: 'open' }, color_palette: ['灰'], lighting_state: { time: 'dawn' }, status: 'approved' }
  const style = { id: 50, project_id: 1, key: 'comic', version: 1, name: '水彩', positive_tag: 'watercolor', negative_tag: 'photo', positive_natural_language: '柔和水彩', negative_natural_language: '避免写实', color_palette: ['蓝', '灰'], lighting: '柔和', status: 'approved' }
  const visualApi = {
    listOutfits: async (projectId) => outfits.filter((item) => item.project_id === projectId),
    listStyles: async (projectId) => projectId === 1 ? [style] : [],
    listSceneVersions: async (projectId) => projectId === 1 ? [scene] : [],
    listVisualAssets: async () => [],
    createOutfit: async (projectId, payload) => { saved.outfits.push({ projectId, payload }); const result = { ...payload, id: 15, project_id: projectId, version: 2, status: 'draft' }; outfits.push(result); return result },
    createStyle: async (projectId, payload) => { saved.styles.push({ projectId, payload }); return { ...payload, id: 51, project_id: projectId, version: 2, status: 'draft' } },
    createSceneVersion: async (projectId, payload) => { saved.scenes.push({ projectId, payload }); return { ...payload, id: 1101, project_id: projectId, version: 2, status: 'draft' } },
    uploadVisualAsset: async (projectId, form) => { saved.assets.push({ projectId, form }); return { id: 80, project_id: projectId } },
    setConfigurationStatus: async (kind, id, status) => { if (kind === 'outfit') outfits.find((item) => item.id === id).status = status; return { id, status } },
    assignOutfitVariant: async (characterId, versionId) => { saved.bindings.push({ characterId, versionId }); return { id: characterId, outfit_variant_id: versionId } },
  }
  const router = {
    replace: async (next) => { route.query = { ...next.query } },
    push: async (next) => { route.path = next.path; route.query = { ...next.query } },
    resolve: (next) => ({ fullPath: next.path + '?' + new URLSearchParams(Object.entries(next.query).filter(([, value]) => value !== undefined)).toString() }),
  }
  const stubs = {
    vue: { ...vue, onMounted: (fn) => { lifecycle.mounted = fn }, onBeforeUnmount: (fn) => { lifecycle.unmounted = fn } },
    pinia: { storeToRefs: (store) => store },
    'vue-router': { useRoute: () => route, useRouter: () => router },
    'vue-i18n': { useI18n: () => ({ t: (key) => key }) },
    'element-plus': { ElMessage: { error() {}, warning(message) { warnings.push(message) }, success() {}, info() {} }, ElMessageBox: { confirm: async () => {} } },
    '@element-plus/icons-vue': {},
    '@/api/errors': { apiErrorMessage: (_error, _t, fallback) => fallback },
    '@/api/scripts': {
      listProjectScriptTasks: async (projectId) => tasks.filter((item) => item.project_id === projectId),
      listScriptTaskCharacters: async (taskId) => pendingCharacters?.taskId === taskId ? pendingCharacters.promise : [character(taskId)],
      listScriptTaskScenes: async (taskId) => [{ id: taskId * 10, name: `场景 ${taskId}`, selected_visual_version_id: taskId === 11 ? scene.id : null }],
    },
    '@/api/characterReference': {
      listProjectCharacterReferenceCharacters: async (projectId) => (projectId === 1 ? [100, 120] : [200]).map(outlineCharacter),
      listCharacterReferenceCharacters: async (versionId) => [outlineCharacter(characterIds[versionId / 10])],
      listCharacterReferenceTasks: async (id) => referenceLists.get(id) || [],
      watchCharacterReferenceTask: (id, nextCallbacks) => { callbacks.set(id, nextCallbacks); return () => {} },
    },
    '@/api/imageGeneration': { listImageGenerationTools: async () => [] },
    '@/api/visualBible': visualApi,
    '@/stores/projectContext': { useProjectContextStore: () => ({ selectedProjectId }) },
    '@/stores/activityCenter': { useActivityCenterStore: () => ({ upsertActivity: (activity) => activities.set(activity.id, activity) }) },
    '@/components/workspace/WorkflowReadiness.vue': {},
    '@/components/workspace/VisualSettingDetails.vue': {},
    '@/components/referenceLibrary/ReferenceLibrary.vue': {},
    '@/utils/workspaceActivity': { positiveId: (value) => Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null },
  }
  const runtime = new Module(sourcePath, module)
  runtime.filename = sourcePath
  runtime.paths = module.paths
  runtime.require = (id) => Object.hasOwn(stubs, id) ? stubs[id] : require(id)
  runtime._compile(compiled, sourcePath)
  const scope = vue.effectScope()
  const state = scope.run(() => runtime.exports.default.setup({}, { expose() {} }))
  const flush = async () => { for (let i = 0; i < 10; i++) { await vue.nextTick(); await new Promise(setImmediate) } }
  return { state, route, selectedProjectId, tasks, activities, callbacks, saved, warnings, lifecycle, referenceTask, scene, style, flush,
    holdCharacters(taskId) { pendingCharacters = { taskId, ...deferred() }; return pendingCharacters },
    close() { lifecycle.unmounted?.(); scope.stop() },
  }
}

test('空工作区不误报就绪，可进入当前项目脚本或脚本前准备素材', async () => {
  const h = harness({ project_id: '1' })
  try {
    h.tasks.splice(0)
    await h.lifecycle.mounted(); await h.flush()
    h.state.outfits.value = []; h.state.styles.value = []; h.state.sceneVersions.value = []
    h.state.outlineCharacters.value = []; h.state.projectOutlineCharacters.value = []
    assert.ok(h.state.readinessItems.value.every((item) => item.status === 'notStarted'))
    assert.ok(h.state.readinessItems.value.every((item) => Number(item.to.query.project_id) === 1))
    assert.equal(h.state.readinessItems.value.find(item => item.key === 'assignments').to.path, '/scripts')
    assert.equal(h.state.readinessItems.value.find(item => item.key === 'references').to.path, '/visual-bible')
  } finally { h.close() }
})

test('人物直接上传预填归属与部位，切项目后提交仍归属于打开表单时的项目', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.assetForm.entity_type = 'style'
    h.state.openAssetUploader({ id: 100 }, 'identity_full_body')
    await h.flush()
    assert.equal(h.state.assetForm.entity_type, 'character')
    assert.equal(h.state.assetForm.entity_id, 100)
    assert.equal(h.state.assetForm.role, 'identity_full_body')
    assert.equal(h.state.assetForm.approve, false)
    h.state.selectedFile.value = new File(['fixture'], 'reference.png', { type: 'image/png' })
    h.route.query = { project_id: '2', script_task_id: '21' }
    await h.flush()
    await h.state.saveAsset()
    assert.equal(h.saved.assets[0].projectId, 1)
    assert.equal(h.saved.assets[0].form.get('entity_id'), '100')
    assert.equal(h.saved.assets[0].form.get('role'), 'identity_full_body')
    assert.equal(h.saved.assets[0].form.get('approve'), 'false')
  } finally { h.close() }
})

test('精准人物历史深链选中目标任务，含终态的全部任务同步任务中心', async () => {
  const h = harness({ project_id: '1', script_task_id: '11', character_id: '100', reference_task_id: '102', tab: 'references' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.expandedReferenceCharacter.value, 100)
    assert.equal(h.state.displayedReferenceTask(100).id, 102)
    assert.equal(h.activities.get('character-reference-103').status, 'succeeded')
    assert.equal(h.activities.get('character-reference-102').status, 'failed')
    h.route.query = { project_id: '1', script_task_id: '12', character_id: '120', reference_task_id: '122', tab: 'references' }
    await h.flush()
    assert.equal(h.state.selectedTaskId.value, 12)
    assert.equal(h.state.expandedReferenceCharacter.value, 120)
    assert.equal(h.state.displayedReferenceTask(120).id, 122)
    const target = h.activities.get('character-reference-122')
    assert.equal(target.characterId, 120)
    assert.equal(target.referenceTaskId, 122)
    assert.match(target.route, /project_id=1&script_task_id=12&character_id=120&reference_task_id=122/)
  } finally { h.close() }
})

test('通用参考图深链交给素材库，旧人物套组不会报失效或改选任务', async () => {
  const h = harness({ project_id: '1', script_task_id: '11', character_id: '100', reference_task_id: '1801', reference_task_kind: 'referenceImage', tab: 'references' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.deepEqual(h.warnings, []); assert.equal(h.state.expandedReferenceCharacter.value, null)
    assert.equal(h.callbacks.size, 0); assert.equal(h.activities.size, 0)
    h.route.query = { ...h.route.query, reference_task_id: '1802' }; await h.flush()
    await h.state.loadProjectData(); await h.flush()
    assert.deepEqual(h.warnings, []); assert.equal(h.route.query.reference_task_id, '1802')
  } finally { h.close() }
})

test('旧任务读取和后台回调不得串入新任务或新项目', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    const held = h.holdCharacters(11)
    const oldRead = h.state.loadTaskVisuals()
    h.route.query = { project_id: '1', script_task_id: '12' }
    await h.flush()
    held.resolve([{ id: 999, outline_character_id: 100 }])
    await oldRead; await h.flush()
    assert.equal(h.state.characters.value[0].outline_character_id, 120)
    const oldCallback = h.callbacks.get(101)
    h.route.query = { project_id: '2', script_task_id: '21' }
    await h.flush()
    oldCallback.onTask(h.referenceTask(100, 101, 'succeeded'), true)
    assert.equal(h.activities.get('character-reference-101').projectId, 1)
    assert.equal(h.activities.get('character-reference-101').status, 'succeeded')
    assert.equal(h.state.referenceTasks.value[100], undefined)
    assert.equal(h.state.characters.value[0].outline_character_id, 200)
  } finally { h.close() }
})

test('复制服装保留完整结构与原选择，新版本确认后还须显式绑定', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    const original = fixtureOutfit()
    h.state.openOutfitEditor(original)
    h.state.outfitForm.name = '旅行装调整版'
    await h.state.saveOutfit(); await h.flush()
    const payload = h.saved.outfits[0].payload
    for (const field of ['garment_components', 'layer_order', 'colors', 'materials', 'patterns', 'accessories', 'trigger_tokens', 'negative_constraints']) assert.deepEqual(payload[field], original[field])
    assert.equal(h.state.characters.value[0].outfit_variant_id, 10)
    assert.equal(h.saved.bindings.length, 0)
    assert.equal(h.state.detailVersion.value.status, 'draft')
    await h.state.approveConfig('outfit', 15); await h.flush()
    assert.equal(h.saved.bindings.length, 0)
    h.state.bindingCharacterId.value = 1100
    await h.state.useSettingVersion()
    assert.deepEqual(h.saved.bindings, [{ characterId: 1100, versionId: 15 }])
  } finally { h.close() }
})

test('复制场景与画风时保留光照、色彩及全部空间和提示词字段', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.openSceneEditor(h.scene)
    await h.state.saveScene(); await h.flush()
    for (const field of ['landmarks', 'spatial_relations', 'camera_presets', 'object_states', 'color_palette', 'lighting_state']) assert.deepEqual(h.saved.scenes[0].payload[field], h.scene[field])
    h.state.openStyleEditor(h.style)
    await h.state.saveStyle(); await h.flush()
    for (const field of ['key', 'name', 'positive_tag', 'negative_tag', 'positive_natural_language', 'negative_natural_language', 'color_palette', 'lighting']) assert.deepEqual(h.saved.styles[0].payload[field], h.style[field])
    assert.equal(h.saved.bindings.length, 0)
  } finally { h.close() }
})

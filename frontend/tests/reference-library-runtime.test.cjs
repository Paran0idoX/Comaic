const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')

const compile = file => ts.transpileModule(compileScript(parse(fs.readFileSync(file, 'utf8')).descriptor, { id: 'reference-library-test' }).content,
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const sourcePath = path.resolve(__dirname, '../src/components/referenceLibrary/ReferenceLibrary.vue')
const compiled = compile(sourcePath)
const helperPath = path.resolve(__dirname, '../src/components/referenceLibrary/referenceLibrary.ts')
const helper = new Module(helperPath, module)
helper._compile(ts.transpileModule(fs.readFileSync(helperPath, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, helperPath)
const roles = { character: ['identity_face', 'identity_half_body', 'identity_full_body', 'identity_side', 'identity_back'], scene: ['scene_master'], prop: ['prop_reference'] }
const asset = (id, overrides = {}) => ({ id, project_id: 1, entity_type: 'character', entity_id: 11, role: 'identity_face', status: 'approved', version: id, local_path: 'fixture.png', ...overrides })
const subject = (id, kind = 'scene', projectId = 1) => ({ id, entity_type: kind, project_id: projectId, key: `subject-${id}`, name: `对象 ${id}`, description: '蓝色', negative_constraints: '不改变颜色' })
const harness = (query = {}) => {
  const props = vue.reactive({ projectId: 1, scriptTaskId: null, characters: [{ id: 11, label: '林夏' }], outfits: [{ id: 51, outline_character_id: 11, name: '旅行装' }],
    scenes: [{ id: 71, name: '脚本场景', reference_subject_id: null }], assets: [asset(1)], tools: [{ id: 1, name: '文字工具', is_default: true, capabilities: { features: ['txt2img'] } }, { id: 2, name: '图片工具', capabilities: { features: ['txt2img', 'img2img'], reference_images: { max_images: 3, transport: 'multipart' } } }] })
  const route = vue.reactive({ path: '/visual-bible', query: { project_id: '1', ...query } })
  const lifecycle = {}; const events = []; const calls = { upload: [], previews: [], created: [], approved: [], subjects: [], bindings: [] }
  let held = null; let taskList = []; const subjects = [subject(21), subject(22, 'prop')]
  const api = {
    listReferenceCategories: async () => Object.entries(roles).map(([entity_type, values]) => ({ entity_type, roles: values.map(role => ({ role, label_key: role })) })),
    listReferenceSubjects: async id => held?.projectId === id ? held.promise : subjects.filter(item => item.project_id === id),
    listReferenceImageTasks: async () => taskList,
    createReferenceSubject: async (projectId, payload) => { const result = { ...payload, id: 31, project_id: projectId, key: 'created' }; calls.subjects.push(result); subjects.push(result); return result },
    updateReferenceSubject: async (id, payload) => ({ ...subject(id), ...payload }),
    bindSceneReferenceSubject: async (sceneId, subjectId) => { calls.bindings.push({ sceneId, subjectId }); return {} },
    previewReferencePrompts: async (projectId, payload) => { calls.previews.push({ projectId, payload }); return { prompts: Object.fromEntries(payload.roles.map(role => [role, { positive: `生成 ${role}`, negative: '不要拼图' }])) } },
    createReferenceImageTask: async (projectId, payload) => { calls.created.push({ projectId, payload }); const task = { ...payload, id: 100, project_id: projectId, status: 'succeeded', updated_at: '2026-10-01', progress: { total: 1, completed: 1 }, candidates: [] }; taskList = [task]; return task },
    approveReferenceImage: async imageId => { calls.approved.push(imageId); return asset(imageId) },
    watchReferenceImageTask: () => () => {},
  }
  const stubs = {
    vue: { ...vue, onMounted: fn => { lifecycle.mounted = fn }, onBeforeUnmount: fn => { lifecycle.unmounted = fn } },
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    'vue-router': { useRoute: () => route, useRouter: () => ({ replace: async next => { route.query = { ...next.query } } }) },
    'element-plus': { ElMessage: { success() {}, error() {} }, ElMessageBox: { confirm: async () => {} } }, '@element-plus/icons-vue': {},
    '@/api/errors': { apiErrorMessage: (_error, _t, fallback) => fallback }, '@/api/referenceImages': api,
    '@/api/visualBible': { uploadVisualAsset: async (projectId, form) => { calls.upload.push({ projectId, form }); return asset(99) }, setVisualAssetStatus: async () => asset(99) },
    './referenceLibrary': helper.exports,
  }
  const runtime = new Module(sourcePath, module); runtime.require = id => Object.hasOwn(stubs, id) ? stubs[id] : require(id); runtime._compile(compiled, sourcePath)
  const scope = vue.effectScope(); const state = scope.run(() => runtime.exports.default.setup(props, { emit: (...args) => events.push(args), expose() {} }))
  const flush = async () => { for (let i = 0; i < 8; i++) { await vue.nextTick(); await new Promise(setImmediate) } }
  return { props, route, state, calls, events, flush, subjects, api,
    hold(projectId) { let resolve; const promise = new Promise(done => { resolve = done }); held = { projectId, promise }; return { resolve } },
    close() { lifecycle.unmounted?.(); scope.stop() },
  }
}
global.window = { addEventListener() {}, removeEventListener() {} }

test('分类来自后端目录，五人物类可单独生成且原图不拼接', async () => {
  const h = harness()
  try {
    await h.flush(); assert.deepEqual(h.state.categories.value, ['character', 'scene', 'prop'])
    h.state.openGenerator('identity_side'); await h.flush(); h.state.generateForm.candidate_count = 4
    assert.equal(h.state.canSubmit.value, true); await h.state.submitGeneration()
    const payload = h.calls.created[0].payload
    assert.deepEqual(payload.roles, ['identity_side']); assert.equal(payload.candidate_count, 4)
    assert.deepEqual(Object.keys(payload.prompts), ['identity_side']); assert.equal(payload.source_mode, 'none')
  } finally { h.close() }
})
test('自动脸图在文字工具上回退；手工选图必须有图片输入能力', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openGenerator('identity_back'); await h.flush()
    assert.equal(h.state.autoSource.value.id, 1); assert.equal(h.state.canSubmit.value, true)
    h.state.generateForm.source_mode = 'manual'; h.state.generateForm.source_asset_ids = [1]
    assert.equal(h.state.canSubmit.value, false)
    h.state.generateForm.tool_preset_id = 2; assert.equal(h.state.canSubmit.value, true)
    assert.deepEqual(h.state.requestPayload().source_asset_ids, [1])
  } finally { h.close() }
})
test('上传编辑器固定原项目、人物、用途与适用服装，切项目后不串写', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openUpload('identity_full_body'); h.state.uploadForm.outfit_variant_id = 51
    h.state.selectedFiles.value = [new File(['fixture'], 'face.png', { type: 'image/png' })]
    h.props.projectId = 2; h.props.assets = [asset(9, { project_id: 2, entity_id: 12 })]; await h.flush()
    await h.state.saveUpload(); const call = h.calls.upload[0]
    assert.equal(call.projectId, 1); assert.equal(call.form.get('entity_id'), '11'); assert.equal(call.form.get('role'), 'identity_full_body')
    assert.equal(call.form.get('outfit_variant_id'), '51'); assert.equal(call.form.get('approve'), 'false')
    assert.ok(!h.events.some(event => event[0] === 'changed'))
  } finally { h.close() }
})
test('脚本前可新建场景或物品；场景图片明确绑定独立条目并显式用于脚本', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.selectCategory('scene'); h.state.openSubjectEditor()
    Object.assign(h.state.subjectForm, { name: '仓库', description: '木墙', negative_constraints: '无霓虹' })
    await h.state.saveSubject(); await h.flush(); assert.equal(h.calls.subjects[0].name, '仓库')
    h.state.openUpload('scene_master'); h.state.selectedFiles.value = [new File(['fixture'], 'scene.png', { type: 'image/png' })]
    await h.state.saveUpload(); const form = h.calls.upload[0].form
    assert.equal(form.get('reference_subject_id'), '31'); assert.equal(form.get('entity_id'), null)
    h.state.bindSceneId.value = 71; await h.state.bindScene(); assert.deepEqual(h.calls.bindings, [{ sceneId: 71, subjectId: 31 }])
  } finally { h.close() }
})
test('单图确认只提交对应图片，不要求其它用途或候选完成', async () => {
  const h = harness()
  try { await h.flush(); await h.state.approveImage(701, { id: 100, project_id: 1 }); assert.deepEqual(h.calls.approved, [701]); assert.ok(h.events.some(event => event[0] === 'changed')) }
  finally { h.close() }
})

test('场景通用与版本专用图片及候选分开；专用上传和生成保留两类归属 ID', async () => {
  const h = harness()
  try {
    h.props.scenes = [{ id: 71, name: '港口', reference_subject_id: 21 }, { id: 72, name: '其他场景', reference_subject_id: 99 }]
    h.props.sceneVersions = [{ id: 91, project_id: 1, script_scene_id: 71, version: 1, status: 'approved' },
      { id: 92, project_id: 1, script_scene_id: 71, version: 2, status: 'draft' }, { id: 93, project_id: 1, script_scene_id: 72, version: 1, status: 'approved' }]
    h.props.assets = [asset(11, { entity_type: 'scene', entity_id: null, reference_subject_id: 21, role: 'scene_master' }),
      asset(12, { entity_type: 'scene', entity_id: 91, reference_subject_id: 21, role: 'scene_master' }),
      asset(13, { entity_type: 'scene', entity_id: 92, reference_subject_id: 21, role: 'scene_master' })]
    await h.flush(); h.state.selectCategory('scene'); await h.flush()
    const baseTask = { project_id: 1, entity_type: 'scene', reference_subject_id: 21 }
    h.state.tasks.value = [{ ...baseTask, id: 81, entity_id: null }, { ...baseTask, id: 82, entity_id: 91 }, { ...baseTask, id: 83, entity_id: 92 }]
    assert.deepEqual(h.state.sceneScopeOptions.value.map(option => option.id), [91, 92])
    assert.deepEqual(h.state.currentAssets.value.map(item => item.id), [11]); assert.deepEqual(h.state.currentTasks.value.map(item => item.id), [81])
    h.state.selectSceneScope(91); await h.flush()
    assert.deepEqual(h.state.currentAssets.value.map(item => item.id), [12]); assert.deepEqual(h.state.currentTasks.value.map(item => item.id), [82])
    h.state.openGenerator('scene_master'); await h.flush(); await h.state.submitGeneration()
    assert.equal(h.calls.created[0].payload.entity_id, 91); assert.equal(h.calls.created[0].payload.reference_subject_id, 21)
    assert.equal(h.route.query.scene_visual_version_id, '91')
    h.state.openUpload('scene_master'); h.state.selectedFiles.value = [new File(['fixture'], 'scene.png', { type: 'image/png' })]
    await h.state.saveUpload()
    assert.equal(h.calls.upload[0].form.get('entity_id'), '91'); assert.equal(h.calls.upload[0].form.get('reference_subject_id'), '21')
    h.state.selectSceneScope(0); await h.flush(); h.state.openGenerator('scene_master'); await h.flush()
    assert.equal(h.state.requestPayload().entity_id, null); assert.equal(h.state.requestPayload().reference_subject_id, 21)
    h.state.openUpload('scene_master'); h.state.uploadForm.scene_scope = 92
    h.state.selectedFiles.value = [new File(['fixture'], 'night.png', { type: 'image/png' })]; await h.state.saveUpload(); await h.flush()
    assert.equal(h.state.selectedSceneScope.value, 92); assert.equal(h.route.query.scene_visual_version_id, '92')
  } finally { h.close() }
})

test('专用场景任务深链恢复版本；无效范围保持空结果并禁止新生成', async () => {
  const h = harness()
  try {
    h.props.scenes = [{ id: 71, name: '港口', reference_subject_id: 21 }]
    h.props.sceneVersions = [{ id: 91, project_id: 1, script_scene_id: 71, version: 2, status: 'approved' }]
    await h.flush()
    h.state.tasks.value = [{ id: 81, project_id: 1, entity_type: 'scene', reference_subject_id: 21, entity_id: 91 }]
    h.route.query = { project_id: '1', reference_subject_id: '21', reference_task_id: '81', reference_task_kind: 'referenceImage' }; await h.flush()
    assert.equal(h.state.selectedSceneScope.value, 91); assert.equal(h.state.displayedTask.value.id, 81)
    h.route.query = { project_id: '1', reference_subject_id: '21', scene_visual_version_id: '999' }; await h.flush()
    assert.equal(h.state.selectedSceneScope.value, 999); assert.equal(h.state.currentAssets.value.length, 0)
    assert.equal(h.state.sceneScopeEditable.value, false); assert.equal(h.state.locationUnavailable.value, true)
    h.state.openGenerator('scene_master'); await h.flush(); assert.equal(h.state.canCreate.value, false)
  } finally { h.close() }
})

test('从当前批次生成和确认后保持脚本定位，历史刷新不重新绑定其他批次', async () => {
  const h = harness()
  try {
    h.props.scriptTaskId = 101; await h.flush(); h.state.openGenerator('identity_face'); await h.flush()
    await h.state.submitGeneration(); assert.equal(h.route.query.script_task_id, '101')
    const task = h.state.tasks.value[0]
    h.props.scriptTaskId = 202; await h.state.refresh(); await h.flush()
    const lastSnapshot = h.events.filter(event => event[0] === 'task' && event[1].id === task.id).at(-1)
    assert.equal(lastSnapshot[2], 101)
    await h.state.approveImage(701, task); assert.equal(h.route.query.script_task_id, '101')
  } finally { h.close() }
})
test('精确历史定位失效时保持空选择，不跳到第一对象或第一任务', async () => {
  const h = harness({ reference_subject_id: '999', reference_category: 'scene', reference_task_id: '999' })
  try { await h.flush(); assert.equal(h.state.selectedOwner.value, null); assert.equal(h.state.displayedTask.value, null); assert.equal(h.state.locationUnavailable.value, true); assert.equal(h.route.query.reference_subject_id, '999') }
  finally { h.close() }
})

test('只有参考任务 ID 时从该任务恢复准确对象；失效 ID 不跳到第一人物', async () => {
  const h = harness()
  try {
    await h.flush()
    h.state.tasks.value = [{ id: 81, project_id: 1, entity_type: 'scene', entity_id: null, reference_subject_id: 21, selected_roles: ['scene_master'] }]
    h.route.query = { project_id: '1', reference_task_id: '81', reference_task_kind: 'referenceImage' }; await h.flush()
    assert.equal(h.state.selectedOwner.value.subjectId, 21); assert.equal(h.state.displayedTask.value.id, 81)
    h.route.query = { ...h.route.query, reference_task_id: '999' }; await h.flush()
    assert.equal(h.state.selectedOwner.value, null); assert.equal(h.state.displayedTask.value, null)
  } finally { h.close() }
})
test('晚到的旧项目目录响应不能覆盖新项目素材库', async () => {
  const h = harness()
  try {
    await h.flush(); const held = h.hold(1); const pending = h.state.refresh()
    h.props.projectId = 2; await h.flush(); held.resolve([subject(98)]); await pending; await h.flush()
    assert.deepEqual(h.state.subjects.value, []); assert.equal(h.state.selectedOwnerKey.value, 'character:11')
  } finally { h.close() }
})
test('同人自动脸图排除其它项目与人物，并优先新确认版本', () => {
  const owner = { category: 'character', characterId: 11, subjectId: null }
  const result = helper.exports.autoFaceAsset([asset(8, { project_id: 2 }), asset(7, { entity_id: 12 }), asset(5, { status: 'draft' }), asset(4), asset(2)], owner, 1)
  assert.equal(result.id, 4)
})

test('当前批次的唯一分段造型默认用于生成和上传，脚本前使用人物基准', async () => {
  const h = harness()
  try {
    h.props.currentCharacters = [{ outline_character_id: 11, outfit_variant_id: 51 }]
    await h.flush(); h.state.openGenerator('identity_back'); await h.flush()
    assert.equal(h.state.generateForm.outfit_variant_id, 51)
    h.state.openUpload('identity_side'); assert.equal(h.state.uploadForm.outfit_variant_id, 51)
    h.props.currentCharacters = []; h.state.openGenerator('identity_full_body'); await h.flush()
    assert.equal(h.state.generateForm.outfit_variant_id, null)
  } finally { h.close() }
})

test('多个分段造型不自动猜测；显式选用或深链造型才能提交非脸部参考', async () => {
  const h = harness()
  try {
    h.props.outfits.push({ id: 52, outline_character_id: 11, name: '雨衣', status: 'draft' })
    h.props.currentCharacters = [{ outline_character_id: 11, outfit_variant_id: 51 }, { outline_character_id: 11, outfit_variant_id: 52 }]
    await h.flush(); h.state.openGenerator('identity_back'); await h.flush()
    assert.equal(h.state.generateForm.outfit_variant_id, null); assert.equal(h.state.canCreate.value, false)
    h.state.generateForm.outfit_variant_id = 52; assert.equal(h.state.canCreate.value, true)
    h.route.query.outfit_variant_id = '51'; h.state.openGenerator('identity_side'); await h.flush()
    assert.equal(h.state.generateForm.outfit_variant_id, 51); assert.equal(h.state.canCreate.value, true)
  } finally { h.close() }
})
test('要求编辑画布的工具不猜脸图作为画布；明确选择后才能提交', async () => {
  const h = harness()
  try {
    h.props.tools[1].capabilities.reference_images = { max_images: 2, requires_canvas: true, transport: 'multipart' }
    await h.flush(); h.state.openGenerator('identity_side'); h.state.generateForm.tool_preset_id = 2; await h.flush()
    assert.equal(h.state.autoSource.value.id, 1); assert.equal(h.state.generateForm.canvas_asset_id, null)
    assert.equal(h.state.canCreate.value, false)
    h.state.generateForm.canvas_asset_id = 1; assert.equal(h.state.canCreate.value, true)
    assert.equal(h.state.requestPayload().canvas_asset_id, 1)
  } finally { h.close() }
})
test('目录读取失败时不悄悄回退硬编码创作类别，刷新后可恢复', async () => {
  const h = harness()
  try {
    await h.flush(); const list = h.api.listReferenceCategories; h.api.listReferenceCategories = async () => { throw new Error('offline') }
    await h.state.refresh(); assert.equal(h.state.catalogFailed.value, true); assert.deepEqual(h.state.categories.value, [])
    h.api.listReferenceCategories = list; await h.state.refresh(); assert.equal(h.state.catalogFailed.value, false)
    assert.deepEqual(h.state.categories.value, ['character', 'scene', 'prop'])
  } finally { h.close() }
})

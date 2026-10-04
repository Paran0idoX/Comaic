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
const roles = { character: ['identity_face', 'identity_full_body', 'identity_side', 'identity_back'], scene: ['scene_master'], prop: ['prop_reference'] }
const asset = (id, overrides = {}) => ({ id, project_id: 1, entity_type: 'character', entity_id: 11, role: 'identity_face', status: 'approved', version: id, local_path: 'fixture.png', ...overrides })
const subject = (id, kind = 'scene', projectId = 1) => ({ id, entity_type: kind, project_id: projectId, key: `subject-${id}`, name: `对象 ${id}`, description: '蓝色', negative_constraints: '不改变颜色' })
const referenceTask = (id, subjectId, overrides = {}) => {
  const values = { id, project_id: 1, entity_type: 'scene', entity_id: null, reference_subject_id: subjectId,
    status: 'succeeded', tool_name: '测试工具', outfit_variant_id: null, updated_at: '2026-10-03',
    selected_roles: ['scene_master'], progress: { completed: 1, total: 1 }, ...overrides }
  return { ...values, candidates: values.selected_roles.map((role, index) => ({ candidate_index: index + 1,
    roles: { [role]: { status: 'succeeded', review_status: 'draft', images: [{ id: id * 10 + index,
      image_url: 'fixture.png', promoted_asset_id: null }] } } })) }
}
const harness = (query = {}) => {
  const props = vue.reactive({ projectId: 1, scriptTaskId: null, characters: [{ id: 11, label: '林夏' }], outfits: [{ id: 51, outline_character_id: 11, name: '旅行装' }],
    scenes: [{ id: 71, name: '脚本场景', reference_subject_id: null }], assets: [asset(1)], tools: [{ id: 1, provider: 'openai_images_compatible', name: '文字工具', is_default: true, capabilities: { features: ['txt2img'] } }, { id: 2, provider: 'openai_images_compatible', name: '图片工具', capabilities: { features: ['txt2img', 'img2img'], reference_images: { max_images: 3, transport: 'multipart' } } }] })
  const route = vue.reactive({ path: '/visual-bible', query: { project_id: '1', ...query } })
  const lifecycle = {}; const events = []; const calls = { upload: [], previews: [], created: [], approved: [], assetStatuses: [], subjects: [], bindings: [], watchers: new Map(), stopped: [] }
  let held = null; let taskList = []; const subjects = [subject(21), subject(22, 'prop')]
  const api = {
    visualProfileRefs: profiles => profiles.map(({ id, revision, source_hash }) => ({ id, revision, source_hash })),
    listReferenceCategories: async () => Object.entries(roles).map(([entity_type, values]) => ({ entity_type, roles: values.map(role => ({ role, label_key: role })) })),
    listReferenceSubjects: async id => held?.projectId === id ? held.promise : subjects.filter(item => item.project_id === id),
    listReferenceImageTasks: async () => taskList,
    createReferenceSubject: async (projectId, payload) => { const result = { ...payload, id: 31, project_id: projectId, key: 'created' }; calls.subjects.push(result); subjects.push(result); return result },
    updateReferenceSubject: async (id, payload) => ({ ...subject(id), ...payload }),
    bindSceneReferenceSubject: async (sceneId, subjectId) => { calls.bindings.push({ sceneId, subjectId }); return {} },
    previewReferencePrompts: async (projectId, payload) => { calls.previews.push({ projectId, payload }); return { visual_profiles: [{ id: 1, revision: 1, source_hash: 'a'.repeat(64), kind: 'character', project_id: 1, owner_id: 11, format_version: 1, data: { human: true, facts: [] } }], prompts: Object.fromEntries(payload.roles.map(role => [role, { positive: `生成 ${role}`, negative: '不要拼图' }])) } },
    createReferenceImageTask: async (projectId, payload) => { calls.created.push({ projectId, payload }); const task = { ...payload, id: 100, project_id: projectId, status: 'succeeded', updated_at: '2026-10-01', progress: { total: 1, completed: 1 }, candidates: [] }; taskList = [task]; return task },
    approveReferenceImage: async imageId => {
      calls.approved.push(imageId)
      for (const task of taskList) for (const candidate of task.candidates || []) for (const [role, run] of Object.entries(candidate.roles)) {
        const image = run.images.find(item => item.id === imageId)
        if (image) {
          image.promoted_asset_id = imageId + 10000
          return asset(image.promoted_asset_id, { project_id: task.project_id, entity_type: task.entity_type, entity_id: task.entity_id,
            reference_subject_id: task.reference_subject_id, outfit_variant_id: task.outfit_variant_id, role })
        }
      }
      return asset(imageId)
    },
    watchReferenceImageTask: (id, callbacks) => { calls.watchers.set(id, callbacks); return () => calls.stopped.push(id) },
  }
  const visualApi = { uploadVisualAsset: async (projectId, form) => { calls.upload.push({ projectId, form }); return asset(99) },
    setVisualAssetStatus: async (id, status) => { calls.assetStatuses.push({ id, status }); return { ...(props.assets.find(item => item.id === id) || asset(id)), status } } }
  const stubs = {
    vue: { ...vue, onMounted: fn => { lifecycle.mounted = fn }, onBeforeUnmount: fn => { lifecycle.unmounted = fn } },
    '@/components/workspace/InfoTip.vue': {},
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    'vue-router': { useRoute: () => route, useRouter: () => ({ replace: async next => { route.query = { ...next.query } } }) },
    'element-plus': { ElMessage: { success() {}, error() {} }, ElMessageBox: { confirm: async () => {} } }, '@element-plus/icons-vue': {},
    '@/api/errors': { apiErrorMessage: (_error, _t, fallback) => fallback }, '@/api/referenceImages': api,
    '@/api/visualBible': visualApi,
    './referenceLibrary': helper.exports,
    './ReferenceBatchGenerator.vue': {}, './ReferenceQuickPicker.vue': {}, './VisualProfileEditor.vue': {},
  }
  const runtime = new Module(sourcePath, module); runtime.require = id => Object.hasOwn(stubs, id) ? stubs[id] : require(id); runtime._compile(compiled, sourcePath)
  const scope = vue.effectScope(); const state = scope.run(() => runtime.exports.default.setup(props, { emit: (...args) => events.push(args), expose() {} }))
  const flush = async () => { for (let i = 0; i < 8; i++) { await vue.nextTick(); await new Promise(setImmediate) } }
  return { props, route, state, calls, events, flush, subjects, api, visualApi,
    setTasks(value) { taskList = value },
    hold(projectId) { let resolve; const promise = new Promise(done => { resolve = done }); held = { projectId, promise }; return { resolve } },
    close() { lifecycle.unmounted?.(); scope.stop() },
  }
}
global.window = { addEventListener() {}, removeEventListener() {} }

// 初次目录读取在 setup 中已开始，补充测试数据后显式刷新，模拟真实接口的新响应。
const prepareQuickPicker = async h => {
  await h.flush(); await h.state.refresh(); await h.flush(); h.state.openQuickPicker(); await h.flush()
}

test('新场景忽略旧版本深链接，上传与生成仅归属条目，快速选图没有版本范围', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21', scene_visual_version_id: '81' })
  try {
    h.subjects[0].scene_definition_version = 2
    h.props.scenes[0].reference_subject_id = 21
    h.props.sceneVersions = [{ id: 81, script_scene_id: 71, status: 'approved', version: 1 }]
    await prepareQuickPicker(h)
    h.state.selectCategory('scene'); await h.flush()
    assert.equal(h.state.selectedOwner.value.subjectId, 21)
    assert.equal(h.state.selectedSceneScope.value, 0)
    assert.deepEqual(h.state.sceneScopeOptions.value, [])
    h.state.selectSceneScope(81)
    assert.equal(h.state.selectedSceneScope.value, 0)
    h.state.openGenerator('scene_master'); await h.flush()
    assert.equal(h.state.requestPayload().entity_id, null)
    await h.state.submitGeneration()
    assert.equal(h.calls.created[0].payload.reference_subject_id, 21)
    assert.equal(h.calls.created[0].payload.entity_id, null)
    h.state.openUpload('scene_master')
    h.state.selectedFiles.value = [new Blob(['fixture'], { type: 'image/png' })]
    await h.state.saveUpload()
    assert.equal(h.calls.upload[0].form.get('reference_subject_id'), '21')
    assert.equal(h.calls.upload[0].form.get('entity_id'), null)
  } finally { h.close() }
})

test('提炼失败保留手改描述及原摘要、禁止提交，重试成功后引用准确修订', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openGenerator('identity_face'); await h.flush()
    h.state.generateForm.prompts.identity_face.positive = '手改内容'
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async () => { throw new Error('reference.profile_extraction_failed') }
    await h.state.refreshPrompts(false, true)
    assert.equal(h.state.generateForm.prompts.identity_face.positive, '手改内容')
    assert.equal(h.state.visualProfiles.value[0].revision, 1)
    assert.equal(h.state.previewReady.value, false); assert.equal(h.state.canCreate.value, false)
    await h.state.submitGeneration(); assert.equal(h.calls.created.length, 0)
    h.api.previewReferencePrompts = original
    await h.state.refreshPrompts(false)
    await h.state.submitGeneration()
    assert.deepEqual(h.calls.created[0].payload.visual_profile_refs, [{ id: 1, revision: 1, source_hash: 'a'.repeat(64) }])
  } finally { h.close() }
})

test('未保存摘要禁止提交和自动重编译，保存修订后只重新准备描述', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openGenerator('identity_face'); await h.flush()
    h.state.visualDirty.value = true
    const count = h.calls.previews.length
    h.state.generateForm.roles = ['identity_face', 'identity_back']; h.state.configurationChanged()
    assert.equal(h.state.canCreate.value, false); assert.equal(h.calls.previews.length, count)
    await h.state.profileUpdated([{ ...h.state.visualProfiles.value[0], revision: 2 }])
    assert.equal(h.calls.previews.length, count + 1); assert.equal(h.calls.created.length, 0)
    assert.equal(h.state.visualDirty.value, false)
  } finally { h.close() }
})

test('用户刷新同步已确认素材，内部任务刷新不误报其它项目素材变化', async () => {
  const h = harness()
  try {
    await h.flush()
    h.events.length = 0
    await h.state.refresh()
    assert.equal(h.events.some(event => event[0] === 'changed'), false)
    await h.state.refreshLibrary()
    assert.equal(h.events.filter(event => event[0] === 'changed').length, 1)
    // 父页面响应 changed 后重新加载素材，列表应立即显示新确认版本。
    h.props.assets = [asset(1), asset(2, { role: 'identity_full_body' })]
    await h.flush()
    assert.equal(h.state.approvedCount(h.state.selectedOwner.value), 2)
  } finally { h.close() }
})

test('脸部和全身各自默认尺寸，修改尺寸在切换用途后保留并随请求提交', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openGenerator('identity_full_body'); await h.flush()
    assert.deepEqual({ ...h.state.generateForm.sizes.identity_full_body }, { width: 512, height: 768 })
    h.state.generateForm.sizes.identity_full_body = { width: 640, height: 960 }
    h.state.generateForm.roles = ['identity_face', 'identity_full_body']; h.state.rolesChanged(); await h.flush()
    assert.deepEqual(h.state.requestPayload().sizes, {
      identity_face: { width: 768, height: 768 }, identity_full_body: { width: 640, height: 960 },
    })
    h.state.generateForm.roles = ['identity_face']; h.state.rolesChanged(); await h.flush()
    assert.deepEqual(h.state.requestPayload().sizes, { identity_face: { width: 768, height: 768 } })
    h.state.generateForm.roles = ['identity_face', 'identity_full_body']; h.state.rolesChanged(); await h.flush()
    await h.state.submitGeneration()
    assert.deepEqual(h.calls.created[0].payload.sizes.identity_full_body, { width: 640, height: 960 })
    h.state.openGenerator('identity_face'); await h.flush()
    assert.deepEqual(h.state.requestPayload().sizes, { identity_face: { width: 768, height: 768 } })
  } finally { h.close() }
})

test('无尺寸绑定工具不会静默忽略宽高，非法尺寸禁止提交', async () => {
  const h = harness()
  try {
    await h.flush()
    h.props.tools[0].provider = 'comfyui'; h.props.tools[0].bindings = { bindings: [] }
    h.state.openGenerator('identity_face'); await h.flush()
    assert.equal(h.state.generateForm.tool_preset_id, 2)
    h.state.generateForm.tool_preset_id = 1
    assert.equal(h.state.canCreate.value, false)
    await h.state.submitGeneration(); assert.equal(h.calls.created.length, 0)
    h.state.generateForm.tool_preset_id = 2
    h.state.generateForm.sizes.identity_face.width = 513
    assert.equal(h.state.canCreate.value, false)
    h.state.generateForm.sizes.identity_face.width = 768
    assert.equal(h.state.canCreate.value, true)
  } finally { h.close() }
})

test('半身用途从旧目录、历史素材和新参考请求中排除', async () => {
  const h = harness()
  try {
    await h.flush()
    const historical = asset(99, { role: 'identity_half_body' })
    h.props.assets.push(historical)
    h.api.listReferenceCategories = async () => [
      { entity_type: 'character', roles: [...roles.character, 'identity_half_body'].map(role => ({ role, label_key: role })) },
    ]
    await h.state.refresh(); await h.flush()
    assert.deepEqual(h.state.categoryRoles('character'), ['identity_face', 'identity_full_body', 'identity_side', 'identity_back'])
    assert.equal(h.state.approvedCount(h.state.selectedOwner.value), 1)
    h.state.openGenerator('identity_full_body'); await h.flush()
    assert.equal(h.state.sourceOptions.value.some(item => item.id === 99), false)
    assert.equal(h.state.roleOptions.value.includes('identity_half_body'), false)
    await h.state.submitGeneration()
    assert.deepEqual(h.calls.created[0].payload.roles, ['identity_full_body'])
    assert.equal(h.props.assets.includes(historical), true)
  } finally { h.close() }
})

test('分类来自后端目录，四人物类可单独生成且原图不拼接', async () => {
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

test('自动脸图和手选来源排除没有本地原图的素材，与后端选图一致', async () => {
  const h = harness()
  try {
    h.props.assets = [asset(4, { local_path: null }), asset(2)]
    await h.flush(); h.state.openGenerator('identity_side'); await h.flush()
    assert.equal(h.state.autoSource.value.id, 2)
    assert.deepEqual(h.state.sourceOptions.value.map(item => item.id), [2])
  } finally { h.close() }
})

test('ComfyUI 手选保留 renderer locator 参考和画布，外部 API 仅提供本地原图', async () => {
  const h = harness()
  try {
    h.props.assets = [asset(4, { local_path: null, storage_kind: 'renderer_locator', renderer_locator: 'legacy/original.png' }), asset(2)]
    h.props.tools[1].provider = 'comfyui'
    h.props.tools[1].bindings = { bindings: [{ source: 'render.width' }, { source: 'render.height' }], reference_slots: [{ node_id: '1' }, { node_id: '2' }] }
    h.props.tools[1].capabilities.reference_images.requires_canvas = true
    await h.flush(); h.state.openGenerator('identity_side'); await h.flush()
    h.state.generateForm.tool_preset_id = 2
    assert.deepEqual(h.state.sourceOptions.value.map(item => item.id), [4, 2])
    assert.equal(h.state.autoSource.value.id, 2)
    h.state.generateForm.source_mode = 'manual'; h.state.generateForm.source_asset_ids = [4]
    h.state.generateForm.canvas_asset_id = 4
    assert.equal(h.state.canCreate.value, true)
    assert.deepEqual(h.state.requestPayload().source_asset_ids, [4])
    assert.equal(h.state.requestPayload().canvas_asset_id, 4)
    h.props.tools[1].provider = 'openai_images_compatible'
    assert.deepEqual(h.state.sourceOptions.value.map(item => item.id), [2])
    assert.equal(h.state.canCreate.value, false)
  } finally { h.close() }
})

test('由编辑工具切换到普通工具时，隐藏画布不占容量也不提交', async () => {
  const h = harness()
  try {
    h.props.tools[1].capabilities.reference_images.requires_canvas = true
    await h.flush(); h.state.openGenerator('identity_side'); await h.flush()
    h.state.generateForm.tool_preset_id = 2; h.state.generateForm.canvas_asset_id = 1
    assert.equal(h.state.requestPayload().canvas_asset_id, 1)
    h.state.generateForm.tool_preset_id = 1; h.state.configurationChanged(); await h.flush()
    assert.equal(h.state.canCreate.value, true)
    assert.equal(h.state.requestPayload().canvas_asset_id, null)
  } finally { h.close() }
})

test('批量上传中途失败立即刷新成功素材，重试仅提交剩余文件', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openUpload('identity_full_body')
    h.state.selectedFiles.value = [new File(['first'], 'first.png', { type: 'image/png' }), new File(['second'], 'second.png', { type: 'image/png' })]
    const upload = h.visualApi.uploadVisualAsset; let failed = false
    h.visualApi.uploadVisualAsset = async (projectId, form) => {
      if (form.get('file').name === 'second.png' && !failed) { failed = true; throw new Error('temporary failure') }
      return upload(projectId, form)
    }
    await h.state.saveUpload()
    assert.equal(h.state.uploadDialog.value, true)
    assert.deepEqual(h.state.selectedFiles.value.map(file => file.name), ['second.png'])
    assert.ok(h.events.some(event => event[0] === 'changed'))
    await h.state.saveUpload()
    assert.deepEqual(h.calls.upload.map(call => call.form.get('file').name), ['first.png', 'second.png'])
    assert.equal(h.state.uploadDialog.value, false)
  } finally { h.close() }
})


test('批量弹窗冻结打开时的项目和脚本上下文，晚到任务不串入新项目', async () => {
  const h = harness()
  try {
    h.props.scriptTaskId = 7
    await h.flush()
    h.state.openBatchGenerator()
    assert.equal(h.state.batchContext.value.projectId, 1)
    assert.equal(h.state.batchContext.value.scriptTaskId, 7)
    assert.equal(h.state.batchContext.value.subjects.length, 2)
    h.props.projectId = 2; h.props.scriptTaskId = 8
    await h.flush()
    const created = [{ id: 91, project_id: 1, entity_type: 'character', entity_id: 11, status: 'pending' }]
    h.state.batchSubmitted(created)
    assert.equal(h.state.tasks.value.some(task => task.id === 91), false)
    assert.ok(h.events.some(event => event[0] === 'task' && event[1].id === 91 && event[2] === 7))
    assert.equal(h.state.batchContext.value.projectId, 1)
  } finally { h.close() }
})

test('批量生成阶段复用素材库订阅，跨项目切换仍更新原批次，关闭后不停止后台任务', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openBatchGenerator()
    const task = { id: 92, project_id: 1, entity_type: 'character', entity_id: 11, status: 'pending' }
    h.state.batchSubmitted([task])
    assert.equal(h.calls.watchers.size, 1)
    assert.equal(h.state.batchContext.value.taskUpdates[0].status, 'pending')
    h.props.projectId = 2; await h.flush()
    assert.equal(h.calls.stopped.includes(92), false)
    h.calls.watchers.get(92).onTask({ ...task, status: 'running' }, false)
    assert.equal(h.state.batchContext.value.taskUpdates[0].status, 'running')
    assert.equal(h.state.tasks.value.some(item => item.id === 92), false)
    h.state.receiveTask({ ...task, project_id: 2, status: 'succeeded' }, null)
    assert.equal(h.state.batchContext.value.taskUpdates[0].status, 'running')
    h.state.batchContext.value = null
    h.calls.watchers.get(92).onTask({ ...task, status: 'succeeded' }, true)
    assert.ok(h.events.some(event => event[0] === 'task' && event[1].id === 92 && event[1].status === 'succeeded'))
    assert.equal(h.calls.stopped.includes(92), false)
  } finally { h.close() }
})

test('回退修改后提交新一批保留原批次订阅和实时进度', async () => {
  const h = harness()
  try {
    await h.flush(); h.state.openBatchGenerator()
    const first = { id: 93, project_id: 1, entity_type: 'character', entity_id: 11, status: 'pending' }
    const second = { ...first, id: 94 }
    h.state.batchSubmitted([first]); h.state.batchSubmitted([second])
    assert.deepEqual(h.state.batchContext.value.taskUpdates.map(task => task.id).sort(), [93, 94])
    h.calls.watchers.get(93).onTask({ ...first, status: 'succeeded' }, true)
    h.calls.watchers.get(94).onTask({ ...second, status: 'running' }, false)
    assert.equal(h.state.batchContext.value.taskUpdates.find(task => task.id === 93).status, 'succeeded')
    assert.equal(h.state.batchContext.value.taskUpdates.find(task => task.id === 94).status, 'running')
    h.props.projectId = 2; await h.flush()
    assert.equal(h.calls.stopped.includes(94), false)
  } finally { h.close() }
})

test('快速选图保持当前场景范围，默认最新记录，切历史和重开都不自动选图片', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21', scene_visual_version_id: '91' })
  try {
    h.props.scenes = [{ id: 71, name: '港口', reference_subject_id: 21 }]
    h.props.sceneVersions = [{ id: 91, project_id: 1, script_scene_id: 71, version: 1, status: 'approved' }]
    h.setTasks([referenceTask(82, 21), referenceTask(81, 21), referenceTask(90, 21, { entity_id: 91 }),
      referenceTask(999, 21, { project_id: 2 }), referenceTask(998, 23)])
    await prepareQuickPicker(h)
    assert.equal(h.state.selectedSceneScope.value, 91); assert.equal(h.state.selectedTaskId.value, 90)
    assert.equal(h.state.quickSelectedImageKey.value, null)
    assert.deepEqual(h.state.quickCandidates.value.map(item => item.target.id), [900])
    await h.state.quickChangeScope(0); await h.flush()
    assert.equal(h.state.selectedTaskId.value, 82)
    await h.state.quickChangeTask(81); await h.flush()
    assert.equal(h.route.query.reference_task_id, '81')
    h.state.quickSelectImage('image-810'); assert.equal(h.state.quickSelectedImageKey.value, 'image-810')
    h.state.closeQuickPicker(); h.state.openQuickPicker(); await h.flush()
    assert.equal(h.state.selectedTaskId.value, 82); assert.equal(h.state.quickSelectedImageKey.value, null)
    await h.state.confirmQuickImage(); assert.deepEqual(h.calls.approved, [])
  } finally { h.close() }
})

test('快速选图只显示当前对象及范围的有效用途，隔离跨项目、版本和历史控制图', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21' })
  try {
    h.props.scenes = [{ id: 71, name: '港口', reference_subject_id: 21 }]
    h.props.sceneVersions = [{ id: 91, project_id: 1, script_scene_id: 71, version: 1, status: 'approved' }]
    const sceneAsset = (id, extra = {}) => asset(id, { entity_type: 'scene', reference_subject_id: 21, entity_id: null, role: 'scene_master', ...extra })
    h.props.assets = [sceneAsset(10, { status: 'draft' }), sceneAsset(11), sceneAsset(12, { entity_id: 91 }),
      sceneAsset(13, { project_id: 2 }), sceneAsset(14, { reference_subject_id: 23 }), sceneAsset(15, { role: 'depth' }), sceneAsset(16, { status: 'archived' })]
    await prepareQuickPicker(h)
    assert.deepEqual(h.state.quickAssets.value.map(item => item.target.id), [11, 10])
    assert.equal(h.state.quickAssets.value[0].canApprove, false)
    assert.equal(h.state.quickAssets.value[1].canApprove, true)
    await h.state.quickChangeScope(91); await h.flush()
    assert.deepEqual(h.state.quickAssets.value.map(item => item.target.id), [12])
  } finally { h.close() }
})

test('场景草稿确认后进入下一个空场景，仍可继续查看已有参考图的场景', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21', script_task_id: '101' })
  try {
    h.props.scriptTaskId = 101; h.subjects.push(subject(23), subject(24))
    h.props.assets = [asset(10, { entity_type: 'scene', entity_id: null, reference_subject_id: 21, role: 'scene_master', status: 'draft' }),
      asset(11, { entity_type: 'scene', entity_id: null, reference_subject_id: 24, role: 'scene_master' })]
    await prepareQuickPicker(h)
    assert.equal(h.state.quickSelectedImageKey.value, null)
    await h.state.confirmQuickImage('asset-10'); await h.flush()
    assert.deepEqual(h.calls.assetStatuses, [{ id: 10, status: 'approved' }])
    assert.equal(h.state.quickDialog.value, true); assert.equal(h.state.selectedOwnerKey.value, 'scene:23')
    assert.equal(h.state.quickSelectedImageKey.value, null); assert.equal(h.state.quickAssets.value.length, 0)
    assert.equal(h.route.query.reference_subject_id, '23'); assert.equal(h.route.query.script_task_id, '101')
    await h.state.moveQuickOwner(1); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'scene:24'); assert.equal(h.state.quickAssets.value[0].approved, true)
    await h.state.moveQuickOwner(-1); await h.state.moveQuickOwner(-1); await h.flush()
    assert.equal(h.state.quickAssets.value[0].approved, true); assert.equal(h.state.quickOwners.value[0].approvedCount, 1)
    h.props.assets = h.props.assets.map(item => ({ ...item, status: 'approved' })); await h.flush(); await h.state.refresh(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'scene:21'); assert.equal(h.state.quickAssets.value[0].approved, true)
  } finally { h.close() }
})

test('场景版本候选确认后，下一场景恢复通用范围，刷新不回退原对象', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21', scene_visual_version_id: '91' })
  try {
    h.subjects.push(subject(23)); h.props.scenes = [{ id: 71, name: '港口', reference_subject_id: 21 }]
    h.props.sceneVersions = [{ id: 91, project_id: 1, script_scene_id: 71, version: 1, status: 'approved' }]
    h.setTasks([referenceTask(90, 21, { entity_id: 91 }), referenceTask(91, 23)])
    await prepareQuickPicker(h)
    h.state.quickSelectImage('image-900'); await h.state.confirmQuickImage(); await h.flush()
    assert.deepEqual(h.calls.approved, [900]); assert.equal(h.state.selectedOwnerKey.value, 'scene:23')
    assert.equal(h.state.selectedSceneScope.value, 0); assert.equal(h.route.query.scene_visual_version_id, undefined)
    assert.deepEqual(h.state.quickCandidates.value.map(item => item.target.id), [910])
    await h.state.refresh(); await h.flush(); assert.equal(h.state.selectedOwnerKey.value, 'scene:23')
    h.state.closeQuickPicker(); h.state.openQuickPicker(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'scene:23'); assert.equal(h.state.quickSelectedImageKey.value, null)
  } finally { h.close() }
})

test('人物确认后停留，可继续确认其他视角，造型标签完整且半身不可选', async () => {
  const h = harness()
  try {
    h.props.characters.push({ id: 12, label: '其他人物' })
    h.setTasks([referenceTask(100, null, { entity_type: 'character', entity_id: 11, outfit_variant_id: 51,
      selected_roles: ['identity_face', 'identity_full_body', 'identity_half_body'] })])
    await prepareQuickPicker(h)
    assert.deepEqual(h.state.quickCandidates.value.map(item => item.target.id), [1000, 1001])
    assert.equal(h.state.quickCandidates.value[0].applicability, null)
    assert.equal(h.state.quickCandidates.value[1].applicability, '旅行装')
    h.state.quickSelectImage('image-1002'); assert.equal(h.state.quickSelectedImageKey.value, null)
    h.state.quickSelectImage('image-1000'); await h.state.confirmQuickImage(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'character:11'); assert.equal(h.state.quickSelectedImageKey.value, null)
    assert.equal(h.state.quickCandidates.value[0].approved, true); assert.equal(h.state.quickCandidates.value[0].canApprove, false)
    h.state.quickSelectImage('image-1001'); await h.state.confirmQuickImage(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'character:11'); assert.deepEqual(h.calls.approved, [1000, 1001])
    await h.state.moveQuickOwner(1); await h.flush(); assert.equal(h.state.selectedOwnerKey.value, 'character:12')
  } finally { h.close() }
})

test('物品确认后自动前进，最后对象停留提示，不循环或跨类别', async () => {
  const h = harness({ reference_category: 'prop', reference_subject_id: '22' })
  try {
    h.subjects.push(subject(25, 'prop'))
    h.props.assets = [asset(10, { entity_type: 'prop', entity_id: null, reference_subject_id: 22, role: 'prop_reference', status: 'draft' }),
      asset(11, { entity_type: 'prop', entity_id: null, reference_subject_id: 25, role: 'prop_reference', status: 'draft' })]
    await prepareQuickPicker(h)
    h.state.quickSelectImage('asset-10'); await h.state.confirmQuickImage(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'prop:25')
    h.state.quickSelectImage('asset-11'); await h.state.confirmQuickImage(); await h.flush()
    assert.equal(h.state.quickReachedEnd.value, true); assert.equal(h.state.selectedOwnerKey.value, 'prop:25')
    await h.state.moveQuickOwner(1); assert.equal(h.state.selectedOwnerKey.value, 'prop:25'); assert.equal(h.state.category.value, 'prop')
    h.state.quickSelectImage('asset-11'); await h.state.confirmQuickImage(); assert.equal(h.calls.assetStatuses.length, 2)
  } finally { h.close() }
})

test('直接确认图片时禁止重复、切换和关闭；失败保留所选图片，重试成功才前进', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21' })
  try {
    h.subjects.push(subject(23)); h.setTasks([referenceTask(100, 21)])
    await prepareQuickPicker(h)
    const original = h.api.approveReferenceImage; let reject; let requests = 0
    h.api.approveReferenceImage = () => { requests++; return new Promise((_resolve, fail) => { reject = fail }) }
    const pending = h.state.confirmQuickImage('image-1000'); await h.flush()
    assert.equal(h.state.quickConfirming.value, true)
    await h.state.confirmQuickImage('image-1000'); h.state.closeQuickPicker(); await h.state.quickChangeCategory('prop')
    await h.state.quickChangeOwner('scene:23'); await h.state.moveQuickOwner(1)
    assert.equal(requests, 1); assert.equal(h.state.quickDialog.value, true); assert.equal(h.state.selectedOwnerKey.value, 'scene:21')
    reject(new Error('temporary failure')); await pending; await h.flush()
    assert.equal(h.state.quickConfirming.value, false); assert.equal(h.state.quickSelectedImageKey.value, 'image-1000')
    assert.equal(h.state.selectedOwnerKey.value, 'scene:21')
    h.api.approveReferenceImage = original; await h.state.confirmQuickImage(); await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'scene:23'); assert.deepEqual(h.calls.approved, [1000])
  } finally { h.close() }
})

test('图片按钮直接确认指定候选，不确认先前选中的图片，也不接受其他对象或退役用途', async () => {
  const h = harness()
  try {
    h.setTasks([referenceTask(100, null, { entity_type: 'character', entity_id: 11,
      selected_roles: ['identity_face', 'identity_full_body', 'identity_half_body'] })])
    await prepareQuickPicker(h)
    await h.state.confirmQuickImage('image-1002'); await h.state.confirmQuickImage('image-9999')
    assert.deepEqual(h.calls.approved, []); assert.equal(h.state.quickSelectedImageKey.value, null)
    h.state.quickSelectImage('image-1000')
    await h.state.confirmQuickImage('image-1001'); await h.flush()
    assert.deepEqual(h.calls.approved, [1001]); assert.equal(h.state.selectedOwnerKey.value, 'character:11')
    assert.equal(h.state.quickCandidates.value[0].approved, false)
    assert.equal(h.state.quickCandidates.value[1].approved, true)
    await h.state.confirmQuickImage('image-1001'); assert.deepEqual(h.calls.approved, [1001])
  } finally { h.close() }
})

test('同用途候选跨记录互斥确认，旧图可再次直接确认且不会重复转存', async () => {
  const h = harness()
  try {
    h.props.assets = []
    const first = referenceTask(100, null, { entity_type: 'character', entity_id: 11, selected_roles: ['identity_face'] })
    const second = referenceTask(101, null, { entity_type: 'character', entity_id: 11, selected_roles: ['identity_face'] })
    h.setTasks([first, second]); await prepareQuickPicker(h)
    await h.state.quickChangeTask(100); await h.flush(); await h.state.confirmQuickImage('image-1000'); await h.flush()
    const originalId = first.candidates[0].roles.identity_face.images[0].promoted_asset_id
    await h.state.quickChangeTask(101); await h.flush(); await h.state.confirmQuickImage('image-1010'); await h.flush()
    assert.equal(h.state.quickOwners.value[0].approvedCount, 1)
    await h.state.quickChangeTask(100); await h.flush()
    assert.equal(h.state.quickCandidates.value[0].approved, false); assert.equal(h.state.quickCandidates.value[0].canApprove, true)
    await h.state.confirmQuickImage('image-1000'); await h.flush()
    assert.equal(first.candidates[0].roles.identity_face.images[0].promoted_asset_id, originalId)
    assert.deepEqual(h.calls.approved, [1000, 1010, 1000])
    assert.equal(h.state.quickAssets.value.filter(item => item.approved).length, 1)
    assert.equal(h.state.quickAssets.value.length, 2)
    // 模拟父页面刷新后的素材列表；重开弹窗仍准确展示已退回的候选。
    h.props.assets = h.state.availableAssets.value.map(item => ({ ...item })); await h.flush()
    h.state.closeQuickPicker(); h.state.openQuickPicker(); await h.flush()
    assert.equal(h.state.quickCandidates.value[0].approved, false); assert.equal(h.state.quickCandidates.value[0].canApprove, true)
  } finally { h.close() }
})

test('身体图确认只撤回同用途同造型的旧图，不改变脸部、其他视角或其他造型', async () => {
  const h = harness()
  try {
    h.props.assets = [asset(1), asset(2, { role: 'identity_full_body', outfit_variant_id: 51 }),
      asset(3, { role: 'identity_side', outfit_variant_id: 51 }), asset(4, { role: 'identity_full_body', outfit_variant_id: 52 }),
      asset(5, { role: 'identity_full_body', outfit_variant_id: null })]
    h.setTasks([referenceTask(100, null, { entity_type: 'character', entity_id: 11, outfit_variant_id: 51, selected_roles: ['identity_full_body'] })])
    await prepareQuickPicker(h); await h.state.confirmQuickImage('image-1000'); await h.flush()
    assert.equal(h.state.quickAssets.value.find(item => item.key === 'asset-2').approved, false)
    for (const id of [1, 3, 4, 5]) assert.equal(h.state.quickAssets.value.find(item => item.key === `asset-${id}`).approved, true)
  } finally { h.close() }
})

test('确认上传草稿会把旧生成图退回可确认候选，主页面和弹窗共享当前状态', async () => {
  const h = harness()
  try {
    const task = referenceTask(100, null, { entity_type: 'character', entity_id: 11, selected_roles: ['identity_face'] })
    task.candidates[0].roles.identity_face.images[0].promoted_asset_id = 10
    task.candidates[0].roles.identity_face.images[0].promoted_asset_status = 'approved'
    h.props.assets = [asset(10), asset(11, { status: 'draft' })]; h.setTasks([task]); await prepareQuickPicker(h)
    await h.state.confirmQuickImage('asset-11'); await h.flush()
    assert.equal(h.state.quickCandidates.value[0].approved, false); assert.equal(h.state.quickCandidates.value[0].canApprove, true)
    assert.equal(h.state.referenceImageStatus(task.candidates[0].roles.identity_face.images[0]), 'draft')
    assert.equal(h.state.quickAssets.value.find(item => item.key === 'asset-10').approved, false)
  } finally { h.close() }
})

test('切项目关闭并重置弹窗，旧确认响应不能污染新项目或触发自动前进', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21' })
  try {
    h.setTasks([referenceTask(100, 21)]); await prepareQuickPicker(h)
    h.state.quickSelectImage('image-1000'); let resolve
    h.api.approveReferenceImage = () => new Promise(done => { resolve = done })
    const pending = h.state.confirmQuickImage(); h.props.projectId = 2
    h.route.query = { project_id: '2' }; await h.flush()
    assert.equal(h.state.quickDialog.value, false); assert.equal(h.state.quickSelectedImageKey.value, null)
    await h.state.quickChangeCategory('character'); h.state.openQuickPicker(); await h.flush()
    const key = h.state.selectedOwnerKey.value; h.events.length = 0
    resolve(asset(11000, { entity_type: 'scene', entity_id: null, reference_subject_id: 21, role: 'scene_master' }))
    await pending; await h.flush()
    assert.equal(h.state.quickDialog.value, true); assert.equal(h.state.selectedOwnerKey.value, key)
    assert.equal(h.state.quickAssets.value.length, 0); assert.equal(h.events.some(event => event[0] === 'changed'), false)
  } finally { h.close() }
})

test('切脚本上下文关闭弹窗；重新打开后旧确认不能清除新选择或锁定状态', async () => {
  const h = harness({ reference_category: 'scene', reference_subject_id: '21' })
  try {
    h.props.scriptTaskId = 101; h.subjects.push(subject(23)); h.setTasks([referenceTask(100, 21)])
    h.props.assets = [asset(11, { entity_type: 'scene', entity_id: null, reference_subject_id: 23, role: 'scene_master', status: 'draft' })]
    await prepareQuickPicker(h); h.state.quickSelectImage('image-1000')
    let resolve; h.api.approveReferenceImage = () => new Promise(done => { resolve = done })
    const pending = h.state.confirmQuickImage(); h.props.scriptTaskId = 202; await h.flush()
    assert.equal(h.state.quickDialog.value, false); assert.equal(h.state.quickConfirming.value, false)
    await h.state.quickChangeOwner('scene:23'); h.state.openQuickPicker(); await h.flush(); h.state.quickSelectImage('asset-11')
    resolve(asset(11000, { entity_type: 'scene', entity_id: null, reference_subject_id: 21, role: 'scene_master' }))
    await pending; await h.flush()
    assert.equal(h.state.selectedOwnerKey.value, 'scene:23'); assert.equal(h.state.quickSelectedImageKey.value, 'asset-11')
    assert.equal(h.state.quickConfirming.value, false); assert.equal(h.route.query.script_task_id, '202')
  } finally { h.close() }
})

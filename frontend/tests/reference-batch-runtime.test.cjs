const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')

const file = path.resolve(__dirname, '../src/components/referenceLibrary/ReferenceBatchGenerator.vue')
const compiled = ts.transpileModule(compileScript(parse(fs.readFileSync(file, 'utf8')).descriptor, { id: 'reference-batch-test' }).content,
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const roles = { character: ['identity_face', 'identity_full_body', 'identity_side', 'identity_back'], scene: ['scene_master'], prop: ['prop_reference'] }
const harness = (overrides = {}) => {
  const events = [], previews = [], batches = [], promptBatches = [], lifecycle = {}, confirmation = { allow: true, calls: [] }
  const props = vue.reactive({
    projectId: 1, characters: [{ id: 11, label: '林' }, { id: 12, label: '陈' }],
    subjects: [{ id: 21, entity_type: 'scene', name: '车站' }, { id: 22, entity_type: 'prop', name: '怀表' }],
    catalog: Object.entries(roles).map(([entity_type, list]) => ({ entity_type, roles: list.map(role => ({ role, label_key: role })) })),
    tools: [{ id: 1, name: '工具', provider: 'openai_images_compatible', is_default: true, capabilities: { features: ['txt2img'] } }],
    outfits: [{ id: 51, outline_character_id: 11, status: 'approved' }, { id: 52, outline_character_id: 11, status: 'draft' }],
    currentCharacters: [{ outline_character_id: 11, outfit_variant_id: 51 }],
    scenes: [{ id: 31, reference_subject_id: 21, name: '车站' }],
    sceneVersions: [{ id: 61, script_scene_id: 31, status: 'approved' }, { id: 62, script_scene_id: 31, status: 'archived' }],
    assets: [{ id: 81, project_id: 1, status: 'approved', entity_type: 'scene', role: 'scene_master', local_path: 'canvas.png' }],
    taskUpdates: [],
    ...overrides,
  })
  const api = {
    visualProfileRefs: profiles => profiles.map(({ id, revision, source_hash }) => ({ id, revision, source_hash })),
    previewReferencePrompts: async (projectId, request) => { previews.push({ projectId, request }); return { visual_profiles: [{ id: 1, revision: 1, source_hash: 'a'.repeat(64), kind: 'character', project_id: 1, owner_id: 11, format_version: 1, data: { human: true, facts: [] } }], prompts: Object.fromEntries(request.roles.map(role => [role, { positive: `${request.entity_type}-${role}`, negative: '' }])) } },
    previewReferencePromptBatch: async (projectId, items, onItem, signal) => {
      promptBatches.push({ projectId, items })
      // 后端事件替身，组件只提交一次，不调度并发。
      let next = 0
      await Promise.all(Array.from({ length: Math.min(5, items.length) }, async () => {
        while (!signal?.aborted) {
          const index = next++, request = items[index]
          if (!request) return
          onItem({ project_id: projectId, index, status: 'running' })
          try { onItem({ project_id: projectId, index, status: 'succeeded', preview: await api.previewReferencePrompts(projectId, request) }) }
          catch (error) { onItem({ project_id: projectId, index, status: 'failed', error: { message: error.message } }) }
        }
      }))
    },
    createReferenceImageBatch: async (projectId, items) => { batches.push({ projectId, items }); return items.map((item, index) => ({ ...item, selected_roles: item.roles, subject_name: `对象 ${index}`, progress: { completed: 0, failed: 0, total: item.roles.length * item.candidate_count }, id: index + batches.length * 100, project_id: projectId, status: 'pending' })) },
  }
  const runtime = new Module(file, module)
  runtime.require = id => ({
    './VisualProfileEditor.vue': {},
    vue: { ...vue, onBeforeUnmount: fn => { lifecycle.unmounted = fn } },
    '@/components/workspace/InfoTip.vue': {},
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    'element-plus': { ElMessage: { success() {}, error() {} }, ElMessageBox: { confirm: async (...args) => { confirmation.calls.push(args); if (!confirmation.allow) throw new Error('cancel') } } },
    '@/api/errors': { ApiError: Error, apiErrorMessage: error => error.message }, '@/api/referenceImages': api,
    './referenceLibrary': { defaultReferenceSize: role => role === 'identity_face' ? { width: 768, height: 768 } : ['identity_full_body', 'identity_side', 'identity_back'].includes(role) ? { width: 512, height: 768 } : { width: 1024, height: 1024 } },
  }[id] || require(id))
  runtime._compile(compiled, file)
  const scope = vue.effectScope()
  const state = scope.run(() => runtime.exports.default.setup(props, { emit: (...event) => events.push(event), expose() {} }))
  return { props, state, api, previews, batches, promptBatches, events, confirmation, close() { lifecycle.unmounted?.(); scope.stop() } }
}

test('新固定场景批量生成只提交条目，不消费隐藏的旧版本选择', async () => {
  const h = harness({ subjects: [{ id: 21, entity_type: 'scene', name: '储物间', scene_definition_version: 2 }] })
  try {
    h.state.form.keys.scene = ['scene:21']
    h.state.selections['scene:21'].sceneId = 61
    assert.deepEqual(h.state.sceneOptions(h.state.selectedOwners.value[0]), [])
    await h.state.prepare(); await h.state.submit()
    assert.equal(h.batches[0].items[0].entity_id, null)
    assert.equal(h.batches[0].items[0].reference_subject_id, 21)
  } finally { h.close() }
})

test('混合多选按对象创建请求，用途、尺寸、服装、场景和手改描述独立保存', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11', 'character:12']
    h.state.form.keys.scene = ['scene:21']; h.state.form.keys.prop = ['prop:22']
    h.state.form.roles.character = ['identity_face', 'identity_back']
    h.state.form.sizes.identity_back = { width: 640, height: 960 }
    h.state.selections['scene:21'].sceneId = 61
    assert.equal(h.state.selectionValid.value, true)
    assert.equal(h.state.requestCount.value, 12)
    await h.state.prepare()
    assert.equal(h.previews.length, 4)
    assert.equal(h.state.ready.value, true)
    h.state.rows.value[0].request.prompts.identity_back.positive = '用户编辑的背面描述'
    await h.state.submit()
    const { projectId, items } = h.batches[0]
    assert.equal(projectId, 1); assert.equal(items.length, 4)
    assert.deepEqual(items[0].roles, ['identity_face', 'identity_back'])
    assert.deepEqual(items[0].sizes.identity_back, { width: 640, height: 960 })
    assert.equal(items[0].outfit_variant_id, 51)
    assert.equal(items[1].outfit_variant_id, null)
    assert.equal(items[2].entity_id, 61); assert.equal(items[2].reference_subject_id, 21)
    assert.equal(items[3].entity_id, null); assert.equal(items[3].reference_subject_id, 22)
    assert.equal(items[0].prompts.identity_back.positive, '用户编辑的背面描述')
    assert.deepEqual(h.events.map(event => event[0]), ['submitted'])
    assert.equal(h.state.stage.value, 2)
  } finally { h.close() }
})

test('失败预览禁止整批提交，单项重试不覆盖已成功的手改描述', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async (id, request) => { if (request.entity_type === 'prop') throw new Error('bad prop'); return original(id, request) }
    await h.state.prepare()
    assert.equal(h.state.ready.value, false)
    await h.state.submit(); assert.equal(h.batches.length, 0)
    h.state.rows.value[0].request.prompts.identity_face.positive = '保留编辑'
    h.api.previewReferencePrompts = original
    await h.state.retryRow(h.state.rows.value[1])
    assert.equal(h.state.ready.value, true)
    assert.equal(h.state.rows.value[0].request.prompts.identity_face.positive, '保留编辑')
  } finally { h.close() }
})

test('空选择、缺少用途、非法尺寸和未选择编辑画布不能准备任务', async () => {
  const h = harness()
  try {
    assert.equal(h.state.selectionValid.value, false)
    h.state.form.keys.character = ['character:11']
    h.state.form.roles.character = []; assert.equal(h.state.selectionValid.value, false)
    h.state.form.roles.character = ['identity_face']
    h.state.form.sizes.identity_face.width = 513; assert.equal(h.state.selectionValid.value, false)
    h.state.form.sizes.identity_face.width = 768
    h.props.tools[0].capabilities.reference_images = { requires_canvas: true }
    // 生产 props 为响应式；触发本测试 computed 重新读取工具。
    h.state.form.toolId = null; h.state.selectionValid.value; h.state.form.toolId = 1
    assert.equal(h.state.selectionValid.value, false)
    h.state.selections['character:11'].canvasId = 81
    assert.equal(h.state.selectionValid.value, true)
    await h.state.prepare()
    assert.equal(h.previews[0].request.canvas_asset_id, 81)
  } finally { h.close() }
})

test('固定尺寸工作流允许批量生成且不提交宽高覆盖', async () => {
  const h = harness()
  try {
    h.props.tools[0].provider = 'comfyui'
    h.state.form.keys.character = ['character:11']
    assert.equal(h.state.customSizes.value, false)
    assert.equal(h.state.selectionValid.value, true)
    await h.state.prepare()
    assert.deepEqual(h.previews[0].request.sizes, {})
    await h.state.submit()
    assert.deepEqual(h.batches[0].items[0].sizes, {})
  } finally { h.close() }
})

test('前端重复点击只提交一次，后台响应前不能关闭弹窗', async () => {
  const h = harness()
  try {
    h.state.form.keys.scene = ['scene:21']
    await h.state.prepare()
    let resolve
    const wait = new Promise(done => { resolve = done })
    h.api.createReferenceImageBatch = async () => { h.batches.push({}); await wait; return [] }
    const first = h.state.submit()
    await h.state.submit(); h.state.close()
    assert.equal(h.batches.length, 1); assert.equal(h.events.length, 0)
    resolve(); await first
    assert.equal(h.state.submitting.value, false)
  } finally { h.close() }
})

test('任一对象的摘要未保存或重新编译失败都阻止整批提交，不影响其它对象手改内容', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    await h.state.prepare()
    const [character, object] = h.state.rows.value
    character.request.prompts.identity_face.positive = '保留人物编辑'
    object.dirty = true
    assert.equal(h.state.ready.value, false)
    await h.state.submit(); assert.equal(h.batches.length, 0)
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async () => { throw new Error('reference.profile_stale') }
    await h.state.profileUpdated(object, [{ ...object.profiles[0], revision: 2 }])
    assert.equal(object.ready, false); assert.equal(h.state.ready.value, false)
    assert.equal(character.request.prompts.identity_face.positive, '保留人物编辑')
    h.api.previewReferencePrompts = original
    await h.state.retryRow(object)
    assert.equal(h.state.ready.value, true)
    await h.state.submit()
    assert.ok(h.batches[0].items.every(item => item.visual_profile_refs.length === 1))
  } finally { h.close() }
})

test('首次准备按用途反馈等待、生成中、成功和失败，完成数与真实响应同步', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    let finishFirst
    const waiting = new Promise(resolve => { finishFirst = resolve })
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async (id, request) => {
      if (request.entity_type === 'prop') throw new Error('prop failed')
      await waiting; return original(id, request)
    }
    const prepare = h.state.prepare()
    const [character, prop] = h.state.rows.value
    assert.equal(character.states.identity_face.status, 'preparing')
    assert.equal(character.states.identity_full_body.status, 'preparing')
    assert.equal(prop.states.prop_reference.status, 'preparing')
    assert.deepEqual(h.state.progress.value, { total: 3, completed: 0, failed: 0, pending: 0, percentage: 0 })
    assert.match(h.state.currentPrompts.value, /林.*identity_face.*identity_full_body/)
    finishFirst(); await prepare
    assert.equal(character.states.identity_face.status, 'ready')
    assert.equal(prop.states.prop_reference.status, 'failed')
    assert.equal(prop.states.prop_reference.error, 'prop failed')
    assert.deepEqual(h.state.progress.value, { total: 3, completed: 2, failed: 1, pending: 0, percentage: 100 })
    assert.equal(h.state.currentPrompts.value, '')
    assert.equal(h.state.ready.value, false)
  } finally { h.close() }
})

test('逐条重生成只请求目标用途和尺寸，保留同对象其它手改 Prompt 与对象输入', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const row = h.state.rows.value[0]
    row.request.prompts.identity_full_body.positive = '保留全身编辑'
    await h.state.retryPrompt(row, 'identity_face')
    const last = h.previews.at(-1).request
    assert.deepEqual(last.roles, ['identity_face'])
    assert.deepEqual(last.sizes, { identity_face: { width: 768, height: 768 } })
    assert.equal(last.outfit_variant_id, 51)
    assert.equal(row.request.prompts.identity_full_body.positive, '保留全身编辑')
    assert.equal(h.confirmation.calls.length, 0)
    assert.equal(h.state.ready.value, true)
    row.request.prompts.identity_face.positive = '手改脸部'
    h.confirmation.allow = false
    const count = h.previews.length
    await h.state.retryPrompt(row, 'identity_face')
    assert.equal(h.previews.length, count)
    assert.equal(row.request.prompts.identity_face.positive, '手改脸部')
    assert.equal(h.confirmation.calls.length, 1)
    h.confirmation.allow = true
    await h.state.retryPrompt(row, 'identity_face')
    assert.equal(row.request.prompts.identity_face.positive, 'character-identity_face')
    assert.equal(row.request.prompts.identity_full_body.positive, '保留全身编辑')
  } finally { h.close() }
})

test('单用途失败保留上次文字并阻止提交，成功重试恢复就绪且不重复请求', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const row = h.state.rows.value[0], original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async () => { throw new Error('temporary failure') }
    await h.state.retryPrompt(row, 'identity_face')
    assert.equal(row.states.identity_face.status, 'failed')
    assert.equal(row.states.identity_full_body.status, 'ready')
    assert.equal(row.request.prompts.identity_face.positive, 'character-identity_face')
    assert.equal(h.state.ready.value, false)
    let finish
    const wait = new Promise(resolve => { finish = resolve })
    let count = 0
    h.api.previewReferencePrompts = async (id, request) => { count++; await wait; return original(id, request) }
    const retry = h.state.retryPrompt(row, 'identity_face')
    await Promise.resolve()
    assert.equal(row.states.identity_face.status, 'preparing')
    await h.state.retryPrompt(row, 'identity_face')
    await h.state.retryRow(row)
    await h.state.submit()
    assert.equal(count, 1); assert.equal(h.batches.length, 0)
    finish(); await retry
    assert.equal(row.states.identity_face.status, 'ready'); assert.equal(h.state.ready.value, true)
  } finally { h.close() }
})

test('局部重生成发现摘要修订变化时标记其它用途过期，保留编辑直到逐条修复', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const row = h.state.rows.value[0], original = h.api.previewReferencePrompts
    row.request.prompts.identity_full_body.positive = '保留旧修订手改内容'
    h.api.previewReferencePrompts = async (id, request) => {
      const result = await original(id, request); result.visual_profiles[0].revision = 2; return result
    }
    await h.state.retryPrompt(row, 'identity_face')
    assert.equal(row.states.identity_full_body.status, 'failed')
    assert.equal(row.states.identity_full_body.error, 'referenceLibrary.batch.profileChanged')
    assert.equal(row.request.prompts.identity_full_body.positive, '保留旧修订手改内容')
    assert.equal(h.state.ready.value, false)
    await h.state.retryPrompt(row, 'identity_full_body')
    assert.equal(h.confirmation.calls.length, 1)
    assert.equal(h.state.ready.value, true)
    assert.equal(row.request.visual_profile_refs[0].revision, 2)
  } finally { h.close() }
})

test('后续对象仍在准备时，前面已完成的用途可以单独重生成和修改摘要', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    const original = h.api.previewReferencePrompts
    let finish
    const wait = new Promise(resolve => { finish = resolve })
    h.api.previewReferencePrompts = async (id, request) => {
      if (request.entity_type === 'prop') await wait
      return original(id, request)
    }
    const prepare = h.state.prepare()
    for (let i = 0; i < 6; i++) await Promise.resolve()
    const row = h.state.rows.value[0]
    assert.equal(row.ready, true); assert.equal(h.state.preparing.value, true)
    await h.state.retryPrompt(row, 'identity_face')
    assert.equal(h.previews.filter(item => item.request.entity_type === 'character').length, 2)
    row.busy = true
    await h.state.profileUpdated(row, row.profiles)
    assert.equal(h.previews.filter(item => item.request.entity_type === 'character').length, 3)
    row.busy = false
    finish(); await prepare
    assert.equal(h.state.ready.value, true)
  } finally { h.close() }
})

test('关闭弹窗后迟到的预览结果不更新状态，也不继续生成后续对象', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    const original = h.api.previewReferencePrompts
    let finish
    const wait = new Promise(resolve => { finish = resolve })
    h.api.previewReferencePrompts = async (id, request) => { await wait; return original(id, request) }
    const prepare = h.state.prepare()
    h.state.close(); finish(); await prepare
    assert.equal(h.previews.length, 2)
    assert.equal(h.state.rows.value[0].request.prompts.identity_face, undefined)
    assert.deepEqual(h.events, [['close']])
    assert.equal(h.batches.length, 0)
  } finally { h.close() }
})

test('预览缺少某一用途时仅该 Prompt 失败，可逐条补齐后提交', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async (id, request) => {
      const result = await original(id, request); delete result.prompts.identity_full_body; return result
    }
    await h.state.prepare()
    const row = h.state.rows.value[0]
    assert.equal(row.states.identity_face.status, 'ready')
    assert.equal(row.states.identity_full_body.status, 'failed')
    assert.equal(row.request.prompts.identity_full_body, undefined)
    assert.equal(h.state.progress.value.failed, 1)
    h.api.previewReferencePrompts = original
    await h.state.retryPrompt(row, 'identity_full_body')
    assert.deepEqual(h.previews.at(-1).request.roles, ['identity_full_body'])
    assert.equal(h.state.progress.value.failed, 0)
    assert.equal(h.state.ready.value, true)
    await h.state.submit(); assert.equal(h.batches.length, 1)
  } finally { h.close() }
})

test('关闭后迟到的摘要保存事件不能再发起 Prompt 生成，重复关闭不重复通知', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const row = h.state.rows.value[0], count = h.previews.length
    h.state.close(); h.state.close()
    await h.state.profileUpdated(row, [{ ...row.profiles[0], revision: 2 }])
    await h.state.retryPrompt(row, 'identity_face')
    await h.state.retryRow(row)
    await h.state.prepare()
    await h.state.submit()
    assert.equal(h.previews.length, count)
    assert.equal(h.batches.length, 0)
    assert.deepEqual(h.events, [['close']])
  } finally { h.close() }
})

test('阶段从选择到 Prompt 再到图片生成，失败创建保留 Prompt 阶段，成功后不重复提交', async () => {
  const h = harness()
  try {
    assert.equal(h.state.stage.value, 0)
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    assert.equal(h.state.stage.value, 1)
    const original = h.api.createReferenceImageBatch
    h.api.createReferenceImageBatch = async () => { throw new Error('create failed') }
    await h.state.submit()
    assert.equal(h.state.stage.value, 1); assert.equal(h.state.ready.value, true)
    h.api.createReferenceImageBatch = original
    await h.state.submit()
    assert.equal(h.state.stage.value, 2); assert.equal(h.state.ready.value, false)
    assert.deepEqual(h.events.map(event => event[0]), ['submitted'])
    await h.state.submit(); await h.state.back(); await h.state.prepare()
    assert.equal(h.batches.length, 1); assert.equal(h.state.stage.value, 1)
    assert.equal(h.state.ready.value, false)
    await h.state.goToStage(2)
    assert.equal(h.state.stage.value, 2)
    h.state.close()
    assert.deepEqual(h.events.map(event => event[0]), ['submitted', 'close'])
  } finally { h.close() }
})

test('图片阶段只读取本批次同项目任务更新，成功失败暂停分别影响真实进度', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    await h.state.prepare(); await h.state.submit()
    const [character, prop] = h.state.createdTasks.value
    assert.deepEqual(h.state.generationProgress.value, { total: 6, completed: 0, failed: 0, percentage: 0 })
    h.props.taskUpdates = [
      { ...character, project_id: 2, status: 'succeeded', progress: { total: 4, completed: 4, failed: 0 } },
      { ...prop, id: 999, status: 'succeeded', progress: { total: 2, completed: 2, failed: 0 } },
    ]
    assert.equal(h.state.generationProgress.value.completed, 0)
    h.props.taskUpdates = [
      { ...character, status: 'succeeded', progress: { total: 4, completed: 4, failed: 0 } },
      { ...prop, status: 'failed', progress: { total: 2, completed: 1, failed: 1 } },
    ]
    assert.deepEqual(h.state.generationProgress.value, { total: 6, completed: 5, failed: 1, percentage: 100 })
    assert.equal(h.state.generationComplete.value, false); assert.equal(h.state.generationAttention.value, true)
    h.props.taskUpdates[1] = { ...prop, status: 'suspended', progress: { total: 2, completed: 1, failed: 0 } }
    assert.equal(h.state.generationAttention.value, true)
    h.props.taskUpdates[1] = { ...prop, status: 'succeeded', progress: { total: 2, completed: 2, failed: 0 } }
    assert.equal(h.state.generationComplete.value, true); assert.equal(h.state.generationAttention.value, false)
    assert.equal(h.state.generationProgress.value.completed, 6)
    assert.equal(h.batches.length, 1)
  } finally { h.close() }
})


const parallelCharacters = Array.from({ length: 8 }, (_, index) => ({ id: 100 + index, label: `人物 ${index}` }))
const flushPromises = () => new Promise(resolve => setImmediate(resolve))

test('五个对象并行准备，乱序完成立即补位，失败不阻塞其它对象或覆盖手改内容', async () => {
  const h = harness({ characters: parallelCharacters })
  try {
    h.state.form.keys.character = parallelCharacters.map(item => `character:${item.id}`)
    const original = h.api.previewReferencePrompts
    const gates = new Map(), started = []
    let active = 0, peak = 0
    h.api.previewReferencePrompts = async (id, request) => {
      started.push(request.entity_id); active++; peak = Math.max(peak, active)
      try {
        await new Promise((resolve, reject) => gates.set(request.entity_id, { resolve, reject }))
        return await original(id, request)
      } finally { active-- }
    }
    const preparing = h.state.prepare()
    assert.equal(h.promptBatches.length, 1)
    assert.equal(h.promptBatches[0].items.length, 8)
    assert.deepEqual(started, [100, 101, 102, 103, 104])
    assert.equal(h.state.progress.value.pending, 6)
    gates.get(103).resolve(); await flushPromises()
    assert.deepEqual(started, [100, 101, 102, 103, 104, 105])
    const edited = h.state.rows.value[3]
    edited.request.prompts.identity_face.positive = '保留并行准备期间的编辑'
    gates.get(101).reject(new Error('single failure')); await flushPromises()
    assert.equal(started.at(-1), 106)
    assert.equal(h.state.progress.value.failed, 2)
    gates.get(105).resolve(); await flushPromises()
    assert.equal(started.at(-1), 107)
    for (const id of [107, 104, 106, 102, 100]) gates.get(id).resolve()
    await preparing
    assert.equal(peak, 5); assert.equal(active, 0)
    assert.equal(new Set(started).size, 8)
    assert.equal(h.state.progress.value.completed, 14)
    assert.equal(h.promptBatches.length, 1)
    assert.equal(h.state.ready.value, false)
    await h.state.submit(); assert.equal(h.batches.length, 0)
    h.api.previewReferencePrompts = original
    await h.state.retryRow(h.state.rows.value[1])
    assert.equal(h.state.ready.value, true)
    assert.equal(edited.request.prompts.identity_face.positive, '保留并行准备期间的编辑')
    assert.equal(h.previews.length, 8)
  } finally { h.close() }
})

test('关闭并行准备弹窗不再领取等待对象，五个迟到结果不写回', async () => {
  const h = harness({ characters: parallelCharacters })
  try {
    h.state.form.keys.character = parallelCharacters.map(item => `character:${item.id}`)
    const original = h.api.previewReferencePrompts, finishes = [], started = []
    h.api.previewReferencePrompts = async (id, request) => {
      started.push(request.entity_id)
      await new Promise(resolve => finishes.push(resolve))
      return original(id, request)
    }
    const preparing = h.state.prepare()
    assert.equal(started.length, 5)
    h.state.close(); finishes.forEach(finish => finish()); await preparing
    assert.equal(started.length, 5)
    assert.ok(h.state.rows.value.every(row => Object.keys(row.request.prompts).length === 0))
    assert.deepEqual(h.events, [['close']])
  } finally { h.close() }
})

test('批量流断开只标记缺失项失败，已成功和手改 Prompt 保留，可逐项重试', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    h.api.previewReferencePromptBatch = async (projectId, items, onItem) => {
      onItem({ project_id: projectId, index: 0, status: 'succeeded', preview: await h.api.previewReferencePrompts(projectId, items[0]) })
      h.state.rows.value[0].request.prompts.identity_face.positive = '保留成功内容的人工修改'
      throw new Error('stream disconnected')
    }
    await h.state.prepare()
    assert.equal(h.state.rows.value[0].ready, true)
    assert.equal(h.state.rows.value[1].states.prop_reference.status, 'failed')
    assert.equal(h.state.ready.value, false)
    await h.state.retryRow(h.state.rows.value[1])
    assert.equal(h.state.ready.value, true)
    assert.equal(h.state.rows.value[0].request.prompts.identity_face.positive, '保留成功内容的人工修改')
  } finally { h.close() }
})

test('返回选择和 Prompt 保留输入、手改文字、摘要编辑状态和选中视角，不再请求模型', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const row = h.state.rows.value[0]
    row.request.prompts.identity_face.positive = '手改脸部'
    row.request.prompts.identity_face.negative = '手改排除'
    row.activeTab = 'character:11:identity_full_body'; row.dirty = true
    await h.state.back()
    assert.equal(h.state.stage.value, 0)
    assert.equal(h.state.selectionLocked.value, true)
    assert.deepEqual(h.state.form.keys.character, ['character:11'])
    assert.equal(h.state.selections['character:11'].outfitId, 51)
    await h.state.goToStage(1)
    assert.equal(h.state.rows.value[0], row)
    assert.equal(row.request.prompts.identity_face.positive, '手改脸部')
    assert.equal(row.request.prompts.identity_face.negative, '手改排除')
    assert.equal(row.activeTab, 'character:11:identity_full_body')
    assert.equal(row.dirty, true)
    assert.equal(h.promptBatches.length, 1); assert.equal(h.confirmation.calls.length, 0)
  } finally { h.close() }
})

test('修改对象选择只准备新增对象，取消勾选再选回恢复其手改内容', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; h.state.form.keys.prop = ['prop:22']
    await h.state.prepare()
    const prop = h.state.rows.value[1]
    prop.request.prompts.prop_reference.positive = '记住物品修改'
    await h.state.back(); h.state.form.keys.prop = []; await h.state.prepare()
    assert.equal(h.promptBatches.length, 1)
    await h.state.back(); h.state.form.keys.prop = ['prop:22']; h.state.form.keys.scene = ['scene:21']
    await h.state.prepare()
    assert.equal(h.promptBatches.length, 2)
    assert.equal(h.promptBatches[1].items.length, 1)
    assert.equal(h.promptBatches[1].items[0].entity_type, 'scene')
    assert.equal(h.state.rows.value[2], prop)
    assert.equal(prop.request.prompts.prop_reference.positive, '记住物品修改')
    assert.equal(h.state.ready.value, true)
  } finally { h.close() }
})

test('调整数量和尺寸保留手改 Prompt，切换服装方案后可恢复原方案', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare()
    const original = h.state.rows.value[0]
    original.request.prompts.identity_face.positive = '原方案脸部编辑'
    await h.state.back(); h.state.form.candidateCount = 3
    h.state.form.sizes.identity_full_body = { width: 640, height: 960 }
    await h.state.prepare()
    assert.equal(h.state.rows.value[0], original)
    assert.equal(original.request.candidate_count, 3)
    assert.deepEqual(original.request.sizes.identity_full_body, { width: 640, height: 960 })
    assert.equal(h.promptBatches.length, 1)
    await h.state.back(); h.state.selections['character:11'].outfitId = 52; await h.state.prepare()
    assert.equal(h.promptBatches.length, 2)
    assert.notEqual(h.state.rows.value[0], original)
    await h.state.back(); h.state.selections['character:11'].outfitId = 51; await h.state.prepare()
    assert.equal(h.state.rows.value[0], original)
    assert.equal(original.request.prompts.identity_face.positive, '原方案脸部编辑')
    assert.equal(h.promptBatches.length, 2)
  } finally { h.close() }
})

test('图片阶段回退保留实时进度，修改后显式新建批次，原任务的冻结 Prompt 不变', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']; await h.state.prepare(); await h.state.submit()
    const first = h.state.createdTasks.value[0]
    const frozen = first.prompts.identity_face.positive
    await h.state.goToStage(1)
    assert.equal(h.state.ready.value, false)
    await h.state.submit(); assert.equal(h.batches.length, 1)
    h.props.taskUpdates = [{ ...first, status: 'running', progress: { total: 4, completed: 1, failed: 0 } }]
    await h.state.back(); await h.state.goToStage(2)
    assert.equal(h.state.generationProgress.value.completed, 1)
    await h.state.goToStage(1)
    h.state.rows.value[0].request.prompts.identity_face.positive = '第二批修改'
    assert.equal(h.state.ready.value, true)
    assert.equal(first.prompts.identity_face.positive, frozen)
    await h.state.submit()
    assert.equal(h.batches.length, 2)
    assert.equal(h.state.createdTasks.value.length, 2)
    assert.equal(first.prompts.identity_face.positive, frozen)
    assert.equal(h.state.createdTasks.value[1].prompts.identity_face.positive, '第二批修改')
    assert.equal(h.promptBatches.length, 1)
    assert.equal(h.state.generationProgress.value.total, 8)
  } finally { h.close() }
})

test('准备中可以回退查看，阶段切换不关闭流或重复整批提交，失败状态也被记住', async () => {
  const h = harness()
  try {
    h.state.form.keys.character = ['character:11']
    let finish
    const original = h.api.previewReferencePrompts
    h.api.previewReferencePrompts = async (id, request) => { await new Promise(resolve => { finish = resolve }); return original(id, request) }
    const preparing = h.state.prepare()
    await h.state.back()
    assert.equal(h.state.stage.value, 0); assert.equal(h.state.selectionLocked.value, true)
    await h.state.goToStage(1)
    assert.equal(h.promptBatches.length, 1)
    finish(); await preparing
    h.api.previewReferencePrompts = async () => { throw new Error('keep failed state') }
    await h.state.retryPrompt(h.state.rows.value[0], 'identity_face')
    await h.state.back(); await h.state.prepare()
    assert.equal(h.promptBatches.length, 1)
    assert.equal(h.state.rows.value[0].states.identity_face.error, 'keep failed state')
    assert.equal(h.state.ready.value, false)
  } finally { h.close() }
})

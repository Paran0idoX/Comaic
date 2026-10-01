const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')

const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

// 运行实际组件的 setup 和 Vue watch，接口只返回本地 fixture，绝不调用生图服务。
const harness = (kind = 'image', query = {}) => {
  const filename = kind === 'image' ? 'ImageGenerationWorkspaceView.vue' : 'ImageSpecWorkspaceView.vue'
  const sourcePath = path.resolve(__dirname, '../src/views', filename)
  const { descriptor } = parse(fs.readFileSync(sourcePath, 'utf8'))
  const compiled = ts.transpileModule(compileScript(descriptor, { id: filename }).content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const local = new Map()
  global.localStorage = { getItem: (key) => local.get(key) ?? null, setItem: (key, value) => local.set(key, value) }
  const route = vue.reactive({ path: kind === 'image' ? '/image-generation' : '/image-specs', query: { project_id: '1', script_task_id: '11', ...query } })
  const selectedProjectId = vue.ref(1)
  const projects = vue.ref([])
  const loadingProjects = vue.ref(false)
  const projectContext = { selectedProjectId, projects, loadingProjects, refreshProjects: async () => { projects.value = [{ id: 1, title: '甲' }, { id: 2, title: '乙' }] } }
  const activities = new Map()
  const suspended = []
  const lifecycle = {}
  const tasks = [11, 12, 21].map((id) => ({ id, project_id: id < 20 ? 1 : 2, total_pages: 1, status: 'succeeded', mode: 'batch' }))
  const batches = [111, 121, 211].map((id) => ({ id, project_id: id < 200 ? 1 : 2, script_task_id: Math.floor(id / 10), tool_preset_id: 1, status: 'succeeded', candidate_count: 1, generation_mode: 'preview', seed_strategy: 'per_page', updated_at: '2026-10-01T00:00:00Z' }))
  const page = (taskId) => ({ page_id: taskId * 10, page_no: 1, images: [], selected_image_id: null, latest_spec_id: taskId, spec_warnings: [], positive_prompt: '页面', completed_candidates: 0 })
  const compilation = (taskId, id = taskId * 10 + 1) => ({ id, task_id: taskId, status: 'succeeded', total_pages: 1, completed_pages: 1, total_specs: 3, completed_specs: 3, failed_pages: [], source_hash: 'hash', updated_at: '2026-10-01T00:00:00Z' })
  const presets = [
    { id: 1, name: '规划规则', kind: 'shot_planner_system_prompt', is_default: true },
    { id: 2, name: '排除内容', kind: 'negative_prompt', is_default: true },
  ]
  let stream = deferred()
  const continued = []
  const compilationItems = tasks.flatMap((task) => [compilation(task.id, task.id * 10 + 2), compilation(task.id)])
  let callbacks = null
  let pendingPages = null
  const imageApi = {
    listImageGenerationTools: async () => [{ id: 1, name: '模拟工具', provider: 'comfyui', prompt_type: 'natural_language', is_default: true, seed_node_id: '1', seed_input_name: 'seed' }],
    listGenerationBatches: async (taskId) => batches.filter((item) => item.script_task_id === taskId),
    listImageGenerationPages: async (taskId) => pendingPages?.taskId === taskId ? pendingPages.promise : [page(taskId)],
    streamGenerateImagesForTask: async (_taskId, _payload, nextCallbacks) => { callbacks = nextCallbacks; await stream.promise },
    streamContinueImagesForBatch: async (batchId, _payload, nextCallbacks) => { continued.push(batchId); callbacks = nextCallbacks; await stream.promise },
    suspendImageGenerationTask: async (id) => { suspended.push(id) },
  }
  const specApi = {
    listImageSpecPresets: async () => presets,
    listImageSpecs: async (taskId) => [{ id: taskId, page_no: 1, prompt_type: 'natural_language', positive_prompt: '页面', negative_prompt: '', warnings: [] }],
    listContinuityCompilations: async () => [],
    listImageSpecCompilations: async (taskId) => compilationItems.filter((item) => item.task_id === taskId),
    streamCompileImageSpecs: async (_taskId, _payload, nextCallbacks) => { callbacks = nextCallbacks; await stream.promise },
  }
  const router = {
    replace: async (next) => { route.query = { ...next.query } },
    push: async (next) => { route.path = next.path; route.query = { ...next.query } },
  }
  const stubs = {
    vue: { ...vue, onMounted: (fn) => { lifecycle.mounted = fn }, onBeforeUnmount: (fn) => { lifecycle.unmounted = fn } },
    pinia: { storeToRefs: (store) => store },
    'vue-router': { useRoute: () => route, useRouter: () => router },
    'vue-i18n': { useI18n: () => ({ locale: vue.ref('zh'), t: (key) => key }) },
    'element-plus': { ElMessage: { error() {}, warning() {}, success() {}, info() {} }, ElMessageBox: { confirm: async () => {} } },
    '@element-plus/icons-vue': {},
    '@/api/projects': { listProjects: async () => [{ id: 1, title: '甲' }, { id: 2, title: '乙' }] },
    '@/api/scripts': { listProjectScriptTasks: async (projectId) => tasks.filter((item) => item.project_id === projectId) },
    '@/api/errors': { apiErrorMessage: (_error, _t, fallback) => fallback },
    '@/api/imageGeneration': imageApi,
    '@/api/imageSpecs': specApi,
    '@/api/characterReference': {},
    '@/api/referenceImages': {},
    '@/api/visualBible': { listStyles: async (projectId) => [{ id: projectId * 10, name: '画风', status: 'approved' }, { id: projectId * 10 + 1, name: '草稿', status: 'draft' }] },
    '@/api/consistencyEvaluation': { getConsistencyReadiness: async () => ({ ready: false, errors: [], warnings: [] }), listConsistencyEvaluations: async () => [], getConsistencyGate: async () => ({ passed: false }) },
    '@/utils/datetime': { formatLocalNowTime: () => '' },
    '@/stores/projectContext': { useProjectContextStore: () => projectContext },
    '@/stores/activityCenter': { useActivityCenterStore: () => ({ upsertActivity: (activity) => activities.set(activity.id, activity) }) },
    '@/components/workspace/WorkflowReadiness.vue': {},
    '@/components/workspace/ReferenceImagePlan.vue': {},
    '@/components/workspace/ReferenceToolConfiguration.vue': {},
  }
  const runtime = new Module(sourcePath, module)
  runtime.filename = sourcePath
  runtime.paths = module.paths
  runtime.require = (id) => Object.hasOwn(stubs, id) ? stubs[id] : require(id)
  runtime._compile(compiled, sourcePath)
  const scope = vue.effectScope()
  const state = scope.run(() => runtime.exports.default.setup({}, { expose() {} }))
  const flush = async () => { for (let i = 0; i < 12; i++) { await vue.nextTick(); await new Promise(setImmediate) } }
  return { state, route, selectedProjectId, projects, activities, suspended, continued, lifecycle, batches, presets, page, compilation, compilationItems, flush,
    get stream() { return stream },
    get callbacks() { return callbacks },
    resetStream() { stream = deferred() },
    holdPages(taskId) { pendingPages = { taskId, ...deferred() }; return pendingPages },
    close: () => scope.stop(),
  }
}

test('历史出图批次深链准确选择项目、脚本和批次；同路由切换也能恢复', async () => {
  const h = harness('image', { batch_id: '111', tab: 'results' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.selectedTaskId.value, 11)
    assert.equal(h.state.selectedBatchId.value, 111)
    h.route.query = { project_id: '2', script_task_id: '21', batch_id: '211', tab: 'results' }
    await h.flush()
    assert.equal(h.selectedProjectId.value, 2)
    assert.equal(h.state.selectedTaskId.value, 21)
    assert.equal(h.state.selectedBatchId.value, 211)
    assert.ok(h.state.pages.value.every((item) => item.page_id === 210))
  } finally { h.close() }
})

test('跨项目图片 SSE 不串写；返回原批次后暂停使用明确的批次 ID', async () => {
  const h = harness('image', { batch_id: '111', tab: 'generate' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const running = h.state.generateBatch(); await h.flush()
    h.batches.push({ ...h.batches[0], id: 112, status: 'running' })
    h.callbacks.onEvent('start', { task_id: 112, script_task_id: 11 }); await h.flush()
    h.selectedProjectId.value = 2; await h.flush()
    h.callbacks.onEvent('image', { id: 900, page_id: 110, page_no: 1, image_url: '/mock.png' }); await h.flush()
    assert.equal(h.state.pages.value[0].page_id, 210)
    assert.deepEqual(h.state.pages.value[0].images, [])
    h.route.query = { project_id: '1', script_task_id: '11', batch_id: '112', tab: 'generate' }; await h.flush()
    await h.state.suspendGeneration()
    assert.deepEqual(h.suspended, [112], JSON.stringify({ route: h.route.query, running: h.state.runningGeneration.value, selectedBatchId: h.state.selectedBatchId.value, selectedTaskId: h.state.selectedTaskId.value, generating: h.state.generating.value }))
    h.batches.find((item) => item.id === 112).status = 'succeeded'
    h.callbacks.onEvent('done', {}); h.stream.resolve(); await running; await h.flush()
    const activity = h.activities.get('image-generation-112')
    assert.equal(activity.status, 'succeeded')
    assert.equal(activity.projectId, 1)
    assert.equal(activity.scriptTaskId, 11)
    assert.match(activity.route, /project_id=1&script_task_id=11&batch_id=112/)
  } finally { h.close() }
})

test('过期出图页面查询不能覆盖后来选择的脚本', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    const old = h.holdPages(11)
    const loading = h.state.loadPages()
    h.route.query = { project_id: '1', script_task_id: '12', batch_id: '121', tab: 'results' }; await h.flush()
    old.resolve([h.page(11)]); await loading
    assert.equal(h.state.selectedTaskId.value, 12)
    assert.ok(h.state.pages.value.every((item) => item.page_id === 120))
  } finally { h.close() }
})

test('准备页按钮与规则缺项状态一致，恢复准确编译并忽略历史画风参数', async () => {
  const h = harness('spec', { compilation_id: '111', style_profile_id: '10', tab: 'results' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.latestSpecCompilation.value.id, 111, JSON.stringify({ route: h.route.query, selectedCompilationId: h.state.selectedCompilationId.value }))
    assert.equal(h.state.selectedStyleId, undefined)
    assert.equal(h.state.canCompile.value, true)
    h.state.negativePresetId.value = null
    assert.equal(h.state.canCompile.value, false)
    assert.equal(h.state.imageSpecReadinessItems.value.find((item) => item.key === 'presets').status, 'blocked')
    h.route.query = { project_id: '2', script_task_id: '21', compilation_id: '211', style_profile_id: '11', tab: 'results' }; await h.flush()
    assert.equal(h.state.selectedTaskId.value, 21)
    assert.equal(h.state.latestSpecCompilation.value.id, 211)
    assert.equal(h.state.selectedStyleId, undefined)
  } finally { h.close() }
})

test('继续生成提交所选历史批次，离页期间完成仍保存准确活动终态', async () => {
  const h = harness('image', { batch_id: '111', tab: 'generate' })
  try {
    h.batches.find((item) => item.id === 111).status = 'suspended'
    await h.lifecycle.mounted(); await h.flush()
    const continuing = h.state.continueBatch(); await h.flush()
    assert.deepEqual(h.continued, [111])
    h.lifecycle.unmounted()
    h.route.path = '/visual-bible'; h.route.query = { project_id: '2' }
    h.selectedProjectId.value = 2
    h.callbacks.onEvent('image', { id: 901, page_id: 110, page_no: 1 }); await h.flush()
    h.batches.find((item) => item.id === 111).status = 'succeeded'
    h.callbacks.onEvent('done', {}); h.stream.resolve(); await continuing
    const activity = h.activities.get('image-generation-111')
    assert.equal(activity.status, 'succeeded')
    assert.equal(activity.projectId, 1)
    assert.equal(activity.batchId, 111)
    assert.equal(h.route.path, '/visual-bible')
  } finally { h.close() }
})

test('准备页旧编译 SSE 不修改新项目结果，活动保持原项目及编译 ID', async () => {
  const h = harness('spec', { tab: 'compile' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const compiling = h.state.compile(); await h.flush()
    const batch = { ...h.compilation(11, 113), status: 'running' }
    h.compilationItems.unshift(batch)
    h.callbacks.onEvent('compilation', batch); await h.flush()
    h.selectedProjectId.value = 2; await h.flush()
    h.callbacks.onEvent('progress', { compilation_id: 113, completed: 3, total: 3 }); await h.flush()
    assert.equal(h.state.selectedTaskId.value, 21)
    assert.ok(h.state.specs.value.every((item) => item.id === 21))
    assert.equal(h.state.progressEvents.value.length, 0)
    batch.status = 'succeeded'
    h.callbacks.onEvent('done', { image_spec_compilation_id: 113 }); h.stream.resolve(); await compiling
    const activity = h.activities.get('image-spec-113')
    assert.equal(activity.status, 'succeeded')
    assert.equal(activity.projectId, 1)
    assert.equal(activity.compilationId, 113)
    assert.match(activity.route, /project_id=1&script_task_id=11&compilation_id=113/)
  } finally { h.close() }
})

for (const kind of ['image', 'spec']) {
  test(`${kind} 旧活动只展示任务列表；同路由旧记录清空精确选项，人工选择后恢复正常`, async () => {
    const h = harness(kind, { activity_legacy: '1' })
    try {
      await h.lifecycle.mounted(); await h.flush()
      assert.ok(h.state.tasks.value.length > 0)
      assert.equal(h.state.selectedTaskId.value, null)
      assert.equal(kind === 'image' ? h.state.selectedBatchId.value : h.state.selectedCompilationId.value, null)
      h.state.selectedTaskId.value = 11; await h.flush()
      assert.equal(h.state.selectedTaskId.value, 11)
      assert.equal(h.route.query.activity_legacy, undefined)
      assert.equal(kind === 'image' ? h.state.selectedBatchId.value : h.state.latestSpecCompilation.value.id, kind === 'image' ? 111 : 112)
      h.route.query = { project_id: '1', activity_legacy: '1', tab: 'results' }; await h.flush()
      assert.equal(h.state.selectedTaskId.value, null)
      assert.equal(kind === 'image' ? h.state.selectedBatchId.value : h.state.selectedCompilationId.value, null)
      assert.deepEqual(kind === 'image' ? h.state.pages.value : h.state.specs.value, [])
      assert.equal(h.route.query.activity_legacy, '1')
    } finally { h.close() }
  })

  test(`${kind} 全局新建和重命名项目会同步至工作台，无需重新加载页面`, async () => {
    const h = harness(kind)
    try {
      await h.lifecycle.mounted(); await h.flush()
      h.projects.value.find((item) => item.id === 1).title = '甲的新名称'
      assert.equal(h.state.projects.value.find((item) => item.id === 1).title, '甲的新名称')
      h.projects.value.push({ id: 3, title: '新项目' })
      h.selectedProjectId.value = 3; await h.flush()
      assert.equal(h.state.projects.value.find((item) => item.id === 3).title, '新项目')
      assert.equal(h.state.selectedProjectId.value, 3)
      if (kind === 'image') assert.equal(h.state.selectedProject.value.title, '新项目')
    } finally { h.close() }
  })

  test(`${kind} 精确脚本 ID 不存在时保留原 query 和空选择，不回退其他任务`, async () => {
    const h = harness(kind, { script_task_id: '999' })
    try {
      await h.lifecycle.mounted(); await h.flush()
      assert.equal(h.state.selectedTaskId.value, null)
      assert.equal(h.state.targetUnavailable.value, true)
      assert.equal(h.route.query.script_task_id, '999')
      assert.deepEqual(kind === 'image' ? h.state.pages.value : h.state.specs.value, [])
      h.route.query = { project_id: '1', script_task_id: '11' }; await h.flush()
      assert.equal(h.state.selectedTaskId.value, 11)
      assert.equal(h.state.targetUnavailable.value, false)
    } finally { h.close() }
  })

  test(`${kind} 精确批次或编译 ID 不存在时保持空结果；新有效链接可恢复`, async () => {
    const idKey = kind === 'image' ? 'batch_id' : 'compilation_id'
    const h = harness(kind, { [idKey]: '999', tab: 'results' })
    try {
      await h.lifecycle.mounted(); await h.flush()
      assert.equal(h.state.selectedTaskId.value, 11)
      assert.equal(kind === 'image' ? h.state.selectedBatchId.value : h.state.latestSpecCompilation.value, null)
      assert.equal(h.state.targetUnavailable.value, true)
      assert.equal(h.route.query[idKey], '999')
      assert.deepEqual(kind === 'image' ? h.state.pages.value : h.state.specs.value, [])
      h.route.query = { project_id: '1', script_task_id: '11', [idKey]: '111', tab: 'results' }; await h.flush()
      assert.equal(kind === 'image' ? h.state.selectedBatchId.value : h.state.latestSpecCompilation.value.id, 111)
      assert.equal(h.state.targetUnavailable.value, false)
      assert.ok((kind === 'image' ? h.state.pages.value : h.state.specs.value).length > 0)
    } finally { h.close() }
  })
}

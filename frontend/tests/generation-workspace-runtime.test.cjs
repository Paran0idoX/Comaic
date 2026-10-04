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
  const sourcePath = kind === 'tools' ? path.resolve(__dirname, '../src/components/settings/ImageToolManager.vue') : path.resolve(__dirname, '../src/views', filename)
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
  const notifications = []
  const translations = {}
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
  const generated = []
  const compileRequests = []
  const compilationItems = tasks.flatMap((task) => [compilation(task.id, task.id * 10 + 2), compilation(task.id)])
  let callbacks = null
  let pendingPages = null
  const imageApi = {
    listImageGenerationTools: async () => [{ id: 1, name: '模拟工具', provider: 'comfyui', prompt_type: 'natural_language', is_default: true, seed_node_id: '1', seed_input_name: 'seed' }],
    listGenerationBatches: async (taskId) => batches.filter((item) => item.script_task_id === taskId),
    listImageGenerationPages: async (taskId) => pendingPages?.taskId === taskId ? pendingPages.promise : [page(taskId)],
    streamGenerateImagesForTask: async (taskId, payload, nextCallbacks) => { generated.push({ taskId, payload }); callbacks = nextCallbacks; await stream.promise },
    streamGenerateImagesForPage: async (pageId, payload, nextCallbacks) => { generated.push({ pageId, payload }); callbacks = nextCallbacks; await stream.promise },
    streamContinueImagesForBatch: async (batchId, _payload, nextCallbacks) => { continued.push(batchId); callbacks = nextCallbacks; await stream.promise },
    suspendImageGenerationTask: async (id) => { suspended.push(id) },
  }
  const specApi = {
    listImageSpecPresets: async () => presets,
    listImageSpecs: async (taskId) => [{ id: taskId, page_no: 1, prompt_type: 'natural_language', positive_prompt: '页面', negative_prompt: '', warnings: [] }],
    listContinuityCompilations: async () => [],
    listImageSpecCompilations: async (taskId) => compilationItems.filter((item) => item.task_id === taskId),
    streamCompileImageSpecs: async (taskId, payload, nextCallbacks) => { compileRequests.push({ taskId, payload }); callbacks = nextCallbacks; await stream.promise },
  }
  const consistencyApi = { getConsistencyReadiness: async () => ({ ready: false, errors: [], warnings: [] }), listConsistencyEvaluations: async () => [], getConsistencyGate: async () => ({ passed: false }) }
  const router = {
    replace: async (next) => { route.query = { ...next.query } },
    push: async (next) => { route.path = next.path; route.query = { ...next.query } },
  }
  const modePath = path.resolve(__dirname, '../src/composables/usePromptLanguage.ts')
  const modeModule = new Module(modePath, module)
  modeModule.paths = module.paths
  modeModule._compile(ts.transpileModule(fs.readFileSync(modePath, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, modePath)
  const stubs = {
    '@/composables/usePromptLanguage': modeModule.exports,
    vue: { ...vue, onMounted: (fn) => { lifecycle.mounted = fn }, onBeforeUnmount: (fn) => { lifecycle.unmounted = fn } },
    pinia: { storeToRefs: (store) => store },
    'vue-router': { useRoute: () => route, useRouter: () => router },
    '@/components/workspace/InfoTip.vue': {},
    '@/components/workspace/ComicQuickPicker.vue': {},
    'vue-i18n': { useI18n: () => ({ locale: vue.ref('zh'), t: (key, values = {}) => Object.entries(values).reduce((message, [name, value]) => message.replaceAll(`{${name}}`, String(value)), translations[key] ?? key) }) },
    'element-plus': { ElMessage: Object.fromEntries(['error', 'warning', 'success', 'info'].map(level => [level, message => notifications.push({ level, message })])), ElMessageBox: { confirm: async () => {} } },
    '@element-plus/icons-vue': {},
    '@/api/projects': { listProjects: async () => [{ id: 1, title: '甲' }, { id: 2, title: '乙' }] },
    '@/api/scripts': { listProjectScriptTasks: async (projectId) => tasks.filter((item) => item.project_id === projectId) },
    '@/api/errors': { apiErrorMessage: (error, translate, fallback) => {
      const key = `backendErrors.${error?.code}`
      return error?.code && translate(key) !== key ? translate(key) : fallback
    } },
    '@/api/imageGeneration': imageApi,
    '@/api/imageSpecs': specApi,
    '@/api/characterReference': {},
    '@/api/referenceImages': {},
    '@/api/visualBible': { listStyles: async (projectId) => [{ id: projectId * 10, name: '画风', status: 'approved' }, { id: projectId * 10 + 1, name: '草稿', status: 'draft' }] },
    '@/api/consistencyEvaluation': consistencyApi,
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
  return { state, route, selectedProjectId, projects, activities, notifications, translations, suspended, continued, generated, modeModule, compileRequests, lifecycle, batches, presets, page, compilation, compilationItems, flush, imageApi, specApi, consistencyApi,
    get stream() { return stream },
    get callbacks() { return callbacks },
    resetStream() { stream = deferred() },
    holdPages(taskId) { pendingPages = { taskId, ...deferred() }; return pendingPages },
    close: () => { lifecycle.unmounted?.(); scope.stop() },
  }
}

// 快速选图复用真实终稿保存入口，验证跨页推进、互斥请求和上下文隔离。
test('漫画快速选图跨列表分页浏览全部筛选页，确认后更新终稿并前进，末页不循环', async () => {
  const h = harness()
  const selected = []
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = Array.from({ length: 24 }, (_, index) => ({
      ...h.page(11), page_id: 110 + index, page_no: index + 1,
      images: [{ id: 900 + index, page_id: 110 + index, is_selected: index === 0 }],
      selected_image_id: index === 0 ? 900 : null,
    }))
    h.imageApi.selectGeneratedImage = async (pageId, imageId) => {
      selected.push({ pageId, imageId })
      return { ...h.state.pages.value.find(page => page.page_id === pageId), selected_image_id: imageId,
        images: [{ id: imageId, page_id: pageId, is_selected: true }] }
    }
    h.state.openQuickPicker()
    assert.equal(h.state.quickPages.value.length, 24)
    assert.equal(h.state.quickPageId.value, 111, '优先定位有候选但未选终稿的页面')
    await h.state.confirmQuickImage(901)
    assert.deepEqual(selected, [{ pageId: 111, imageId: 901 }])
    assert.equal(h.state.pages.value[1].selected_image_id, 901)
    assert.equal(h.state.quickPageId.value, 112)
    h.state.changeQuickPage(133)
    await h.state.confirmQuickImage(923)
    assert.equal(h.state.quickPageId.value, 133)
    assert.equal(h.state.quickReachedEnd.value, true)
    h.state.moveQuickPage(1)
    assert.equal(h.state.quickPageId.value, 133)
    h.state.moveQuickPage(-1)
    assert.equal(h.state.quickReachedEnd.value, false)
    assert.equal(h.state.quickPageId.value, 132)
  } finally { h.close() }
})

test('快速选图冻结筛选范围，保留空候选页并允许跳过，不影响重画勾选', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [
      { ...h.page(11), page_id: 110, page_no: 1, positive_prompt: '目标', images: [{ id: 900 }] },
      { ...h.page(11), page_id: 111, page_no: 2, positive_prompt: '目标空页', images: [] },
      { ...h.page(11), page_id: 112, page_no: 3, positive_prompt: '其它', images: [{ id: 902 }] },
    ]
    h.state.pageSearch.value = '目标'
    h.state.selectedPageIds.value = [112]
    h.state.openQuickPicker()
    assert.deepEqual(h.state.quickPages.value.map(page => page.page_id), [110, 111])
    h.state.pageSearch.value = '其它'
    assert.deepEqual(h.state.quickPages.value.map(page => page.page_id), [110, 111])
    h.state.moveQuickPage(1)
    assert.equal(h.state.quickPage.value.images.length, 0)
    await h.state.confirmQuickImage(902)
    assert.equal(h.state.quickPageId.value, 111)
    h.state.moveQuickPage(-1)
    assert.equal(h.state.quickPageId.value, 110)
    assert.deepEqual(h.state.selectedPageIds.value, [112])
    h.state.closeQuickPicker()
    h.state.openQuickPicker()
    assert.deepEqual(h.state.quickPages.value.map(page => page.page_id), [112])
  } finally { h.close() }
})

test('快速选图保存失败留在原页，重复点击和请求期间切页不会重复保存', async () => {
  const h = harness()
  const pending = deferred()
  let saves = 0
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [
      { ...h.page(11), page_id: 110, page_no: 1, images: [{ id: 900 }, { id: 901 }] },
      { ...h.page(11), page_id: 111, page_no: 2, images: [{ id: 902 }] },
    ]
    h.imageApi.selectGeneratedImage = async () => { saves++; await pending.promise; throw new Error('offline failure') }
    h.state.openQuickPicker()
    const saving = h.state.confirmQuickImage(900)
    assert.equal(h.state.selectingImageId.value, 900)
    await h.state.confirmQuickImage(901)
    h.state.moveQuickPage(1)
    assert.equal(h.state.quickPageId.value, 110)
    assert.equal(saves, 1)
    pending.resolve(); await saving
    assert.equal(h.state.quickPageId.value, 110)
    assert.equal(h.state.pages.value[0].selected_image_id, null)
    assert.equal(h.state.selectingImageId.value, null)
    assert.ok(h.notifications.some(item => item.message === 'imageGeneration.errors.selectImageFailed'))
    h.imageApi.selectGeneratedImage = async (_pageId, imageId) => ({ ...h.state.pages.value[0], selected_image_id: imageId })
    await h.state.confirmQuickImage(901)
    assert.equal(h.state.quickPageId.value, 111)
  } finally { h.close() }
})

test('切换项目或关闭重开后，旧终稿响应不会移动新快速选图弹窗', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted(); await h.flush()
    const first = { ...h.page(11), page_id: 110, page_no: 1, images: [{ id: 900 }] }
    h.state.pages.value = [first, { ...h.page(11), page_id: 111, page_no: 2, images: [{ id: 901 }] }]
    const pending = deferred()
    h.imageApi.selectGeneratedImage = async () => pending.promise
    h.state.openQuickPicker()
    const saving = h.state.confirmQuickImage(900)
    h.state.closeQuickPicker()
    h.state.openQuickPicker()
    assert.equal(h.state.quickDialog.value, false, '保存中不能重开弹窗')
    pending.resolve({ ...first, selected_image_id: 900 }); await saving
    assert.equal(h.state.quickDialog.value, false, '旧响应不会重新打开弹窗')
    h.state.openQuickPicker()
    h.state.changeQuickPage(110)
    assert.equal(h.state.quickPageId.value, 110)
    const nextSaving = h.state.confirmQuickImage(900)
    assert.equal(h.state.selectingImageId.value, null, '已确认的同一张图不重复保存')
    await nextSaving
    const projectPending = deferred()
    h.state.changeQuickPage(111)
    h.imageApi.selectGeneratedImage = async () => projectPending.promise
    const projectSaving = h.state.confirmQuickImage(901)
    h.selectedProjectId.value = 2
    assert.equal(h.state.quickDialog.value, false)
    await h.flush()
    projectPending.resolve({ ...first, selected_image_id: 901 }); await projectSaving
    assert.ok(h.state.pages.value.every(page => page.page_id === 210))
    assert.equal(h.state.quickDialog.value, false)
  } finally { h.close() }
})

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

test('外部运行批次轮询摘要，仅图片进度变化拉完整页面，完成后停止', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  let summaryReads = 0; let pageReads = 0
  let imageItems = []
  Object.assign(h.batches[0], { status: 'running', batch_size: 2, progress: { completed_candidates: 0, images_count: 0, latest_image_id: null, active_runs: 1 } })
  h.imageApi.listGenerationBatches = async taskId => { summaryReads++; return structuredClone(h.batches.filter(item => item.script_task_id === taskId)) }
  h.imageApi.listImageGenerationPages = async taskId => { pageReads++; return [{ ...h.page(taskId), images: imageItems }] }
  try {
    await h.lifecycle.mounted(); await h.flush()
    const baselineReads = pageReads
    h.batches[0].updated_at = '2026-10-01T00:00:10Z'
    h.batches[0].progress.active_runs = 2
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(pageReads, baselineReads)
    imageItems = [{ id: 900, page_id: 110 }]
    h.batches[0].progress = { completed_candidates: 1, images_count: 1, latest_image_id: 900, active_runs: 1 }
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(pageReads, baselineReads + 1)
    assert.equal(h.state.pages.value[0].images[0].id, 900)
    assert.equal(h.activities.get('image-generation-111').progress, 50)
    h.batches[0].status = 'succeeded'
    h.batches[0].progress = { completed_candidates: 2, images_count: 2, latest_image_id: 901, active_runs: 0 }
    imageItems = [...imageItems, { id: 901, page_id: 110 }]
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(pageReads, baselineReads + 2)
    assert.equal(h.state.pages.value[0].images.length, 2)
    assert.equal(h.state.selectedBatch.value.status, 'succeeded')
    const stoppedReads = summaryReads
    t.mock.timers.tick(30000); await h.flush()
    assert.equal(summaryReads, stoppedReads)
  } finally { h.close() }
})

test('旧后端30秒更新一次页面，暂停只短期收尾，获焦后发现外部续跑', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  let summaryReads = 0; let pageReads = 0
  h.batches[0].status = 'running'
  h.imageApi.listGenerationBatches = async taskId => { summaryReads++; return structuredClone(h.batches.filter(item => item.script_task_id === taskId)) }
  h.imageApi.listImageGenerationPages = async taskId => { pageReads++; return [h.page(taskId)] }
  try {
    await h.lifecycle.mounted(); await h.flush()
    const baselineReads = pageReads
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(pageReads, baselineReads)
    t.mock.timers.tick(25000); await h.flush()
    assert.equal(pageReads, baselineReads + 1)
    h.batches[0].status = 'suspended'
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(h.state.selectedBatch.value.status, 'suspended')
    t.mock.timers.tick(90000); await h.flush()
    const stoppedReads = summaryReads
    t.mock.timers.tick(30000); await h.flush()
    assert.equal(summaryReads, stoppedReads)
    h.batches[0].status = 'running'
    h.state.refreshExternalBatchOnFocus(); await h.flush()
    assert.equal(h.state.selectedBatch.value.status, 'running')
    const resumedReads = summaryReads
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(summaryReads, resumedReads + 1)
  } finally { h.close() }
})

test('暂停后已知当前页仍活跃时超过90秒继续低频跟进，图片落库后停止且不续跑', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  let summaryReads = 0; let pageReads = 0
  let imageItems = []
  Object.assign(h.batches[0], { status: 'suspended', batch_size: 50, progress: { completed_candidates: 0, images_count: 0, latest_image_id: null, active_runs: 1 } })
  h.imageApi.listGenerationBatches = async taskId => { summaryReads++; return structuredClone(h.batches.filter(item => item.script_task_id === taskId)) }
  h.imageApi.listImageGenerationPages = async taskId => { pageReads++; return [{ ...h.page(taskId), images: imageItems }] }
  try {
    await h.lifecycle.mounted(); await h.flush()
    const initialPages = pageReads
    t.mock.timers.tick(90000); await h.flush()
    const backoffReads = summaryReads
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(summaryReads, backoffReads)
    t.mock.timers.tick(10000); await h.flush()
    assert.equal(summaryReads, backoffReads + 1)
    t.mock.timers.tick(120000); await h.flush()
    assert.equal(summaryReads, backoffReads + 2)
    assert.equal(pageReads, initialPages)
    imageItems = [{ id: 900, page_id: 110 }]
    h.batches[0].progress = { completed_candidates: 1, images_count: 1, latest_image_id: 900, active_runs: 0 }
    t.mock.timers.tick(15000); await h.flush()
    assert.equal(h.state.selectedBatch.value.status, 'suspended')
    assert.equal(h.state.pages.value[0].images[0].id, 900)
    assert.equal(pageReads, initialPages + 1)
    const stoppedReads = summaryReads
    t.mock.timers.tick(30000); await h.flush()
    assert.equal(summaryReads, stoppedReads)
    assert.equal(h.callbacks, null)
    assert.deepEqual(h.continued, [])
  } finally { h.close() }
})

test('后台页面慢响应不能覆盖接管后的本地 SSE 新候选', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  Object.assign(h.batches[0], { status: 'running', batch_size: 2, progress: { completed_candidates: 0, images_count: 0, latest_image_id: null, active_runs: 1 } })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const slowPages = h.holdPages(11)
    h.batches[0].progress = { completed_candidates: 1, images_count: 1, latest_image_id: 900, active_runs: 1 }
    t.mock.timers.tick(5000); await h.flush()
    const generating = h.state.generateBatch(); await h.flush()
    h.callbacks.onEvent('image', { id: 901, page_id: 110, page_no: 1 })
    slowPages.resolve([{ ...h.page(11), images: [{ id: 900, page_id: 110 }] }]); await h.flush()
    assert.deepEqual(h.state.pages.value[0].images.map(image => image.id), [901])
    h.lifecycle.unmounted()
    h.stream.resolve(); await generating
  } finally { h.close() }
})

test('外部批次摘要慢响应与定时器在切项目或卸载后失效', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  h.batches[0].status = 'running'
  let summaryReads = 0
  try {
    await h.lifecycle.mounted(); await h.flush()
    const slowSummary = deferred()
    h.imageApi.listGenerationBatches = async taskId => {
      summaryReads++
      return taskId === 11 ? slowSummary.promise : h.batches.filter(item => item.script_task_id === taskId)
    }
    t.mock.timers.tick(5000); await h.flush()
    h.selectedProjectId.value = 2; await h.flush()
    slowSummary.resolve([{ ...h.batches[0], status: 'succeeded' }]); await h.flush()
    assert.equal(h.state.selectedBatch.value.id, 211)
    assert.ok(h.state.pages.value.every(page => page.page_id === 210))
    h.lifecycle.unmounted()
    const stoppedReads = summaryReads
    t.mock.timers.tick(30000); await h.flush()
    assert.equal(summaryReads, stoppedReads)
  } finally { h.close() }
})

test('后台摘要和页面请求错误会保留候选并退避恢复，不触发生成', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  let failSummary = false; let failPages = false; let summaryReads = 0
  let imageItems = [{ id: 900, page_id: 110 }]
  Object.assign(h.batches[0], { status: 'running', batch_size: 2, progress: { completed_candidates: 1, images_count: 1, latest_image_id: 900, active_runs: 1 } })
  h.imageApi.listGenerationBatches = async taskId => {
    summaryReads++
    if (failSummary) throw new Error('summary unavailable')
    return structuredClone(h.batches.filter(item => item.script_task_id === taskId))
  }
  h.imageApi.listImageGenerationPages = async taskId => {
    if (failPages) throw new Error('pages unavailable')
    return [{ ...h.page(taskId), images: imageItems }]
  }
  try {
    await h.lifecycle.mounted(); await h.flush()
    failSummary = true
    t.mock.timers.tick(5000); await h.flush()
    assert.equal(h.state.pages.value[0].images[0].id, 900)
    const backoffReads = summaryReads
    t.mock.timers.tick(10000); await h.flush()
    assert.equal(summaryReads, backoffReads)
    failSummary = false; failPages = true
    h.batches[0].progress = { completed_candidates: 2, images_count: 2, latest_image_id: 901, active_runs: 1 }
    t.mock.timers.tick(20000); await h.flush()
    assert.deepEqual(h.state.pages.value[0].images.map(image => image.id), [900])
    assert.equal(h.state.loadingPages.value, false)
    failPages = false
    imageItems = [...imageItems, { id: 901, page_id: 110 }]
    t.mock.timers.tick(30000); await h.flush()
    assert.deepEqual(h.state.pages.value[0].images.map(image => image.id), [900, 901])
    assert.deepEqual(h.notifications, [])
    assert.equal(h.callbacks, null)
    assert.deepEqual(h.continued, [])
  } finally { h.close() }
})

test('同脚本切批次后后台 pages 慢响应不能覆盖新批次已刷新候选', async t => {
  t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 })
  const h = harness('image', { batch_id: '111', tab: 'results' })
  Object.assign(h.batches[0], { status: 'running', batch_size: 2, progress: { completed_candidates: 0, images_count: 0, latest_image_id: null, active_runs: 1 } })
  h.batches.push({ ...h.batches[0], id: 112, status: 'succeeded' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const slowPages = deferred()
    let holdNext = true
    h.imageApi.listImageGenerationPages = async taskId => {
      if (holdNext) { holdNext = false; return slowPages.promise }
      return [{ ...h.page(taskId), images: [{ id: 901, page_id: 110 }] }]
    }
    h.batches[0].progress = { completed_candidates: 1, images_count: 1, latest_image_id: 900, active_runs: 1 }
    t.mock.timers.tick(5000); await h.flush()
    h.state.selectedBatchId.value = 112; await h.flush()
    assert.equal(h.state.pages.value[0].images[0].id, 901)
    slowPages.resolve([{ ...h.page(11), images: [{ id: 900, page_id: 110 }] }]); await h.flush()
    assert.equal(h.state.selectedBatch.value.id, 112)
    assert.equal(h.state.pages.value[0].images[0].id, 901)
  } finally { h.close() }
})

test('设置中的工具必须绑定正向提示词，Seed 可选且不接受半填字段', async () => {
  const h = harness('tools')
  try {
    Object.assign(h.state.workflowForm, {
      name: 'Qwen 工作流', workflow_json: JSON.stringify({ 1: { class_type: 'TextEncode', inputs: { text: '' } }, 2: { class_type: 'RandomNoise', inputs: { noise_seed: 1 } } }),
      bindings_json: JSON.stringify({ schema_version: 1, bindings: [
        { source: 'prompt.positive', node_id: '1', input_name: 'text' },
        { source: 'render.seed', node_id: '2', input_name: 'noise_seed' },
      ] }),
    })
    assert.equal(h.state.canSaveWorkflow.value, true)
    h.state.workflowForm.bindings_json = JSON.stringify({ bindings: [{ source: 'prompt.negative', node_id: '1', input_name: 'text' }] })
    h.state.workflowForm.seed_node_id = '2'; h.state.workflowForm.seed_input_name = 'noise_seed'
    assert.equal(h.state.canSaveWorkflow.value, false)
    h.state.workflowForm.bindings_json = JSON.stringify({ bindings: [{ source: 'prompt.positive', node_id: '1', input_name: 'text' }] })
    assert.equal(h.state.canSaveWorkflow.value, true)
    h.state.workflowForm.bindings_json = JSON.stringify({ bindings: [] })
    h.state.workflowForm.positive_node_id = '1'; h.state.workflowForm.positive_input_name = 'text'
    h.state.workflowForm.seed_node_id = ''; h.state.workflowForm.seed_input_name = ''
    assert.equal(h.state.canSaveWorkflow.value, true)
    h.state.workflowForm.seed_node_id = '2'
    assert.equal(h.state.canSaveWorkflow.value, false)
  } finally { h.close() }
})

test('普通出图和逐页选图不请求旁路评测，评测服务不可用也不影响结果', async () => {
  const h = harness('image')
  let probes = 0
  try {
    h.consistencyApi.getConsistencyReadiness = async () => { probes += 1; throw Error('offline') }
    h.consistencyApi.getConsistencyGate = async () => { throw Error('retired gate') }
    h.imageApi.selectGeneratedImage = async (pageId, imageId) => ({ ...h.page(11), page_id: pageId, selected_image_id: imageId })
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(probes, 0)
    await h.state.selectFinalImage(h.state.pages.value[0], { id: 900 })
    assert.equal(h.state.pages.value[0].selected_image_id, 900)
    assert.equal(h.notifications.at(-1).level, 'success')
    h.state.activeGenerationTab.value = 'consistency'; await h.flush()
    assert.equal(probes, 1)
    assert.equal(h.state.pages.value[0].selected_image_id, 900)
  } finally { h.close() }
})

test('未达评测参考值的完整候选仍允许人工采用', async () => {
  const h = harness('image')
  const adopted = []
  try {
    await h.lifecycle.mounted(); await h.flush()
    const track = { id: 1, candidate_index: 1, status: 'failed', passed: false, image_ids: { 110: 900 }, details: {}, metrics: {} }
    h.state.consistencyTask.value = { id: 1, status: 'succeeded', tracks: [track], progress: {}, source_hash: 'test', metric_version: 'test' }
    h.consistencyApi.adoptConsistencyTrack = async id => { adopted.push(id); return { ...track, adopted_at: 'now' } }
    await h.state.adoptTrack(track)
    assert.deepEqual(adopted, [1])
    assert.equal(h.notifications.at(-1).level, 'success')
  } finally { h.close() }
})

test('生成批次标签使用生成状态，不能复用一致性评测中的状态文案', () => {
  const h = harness('image')
  try {
    const label = h.state.batchLabel({ ...h.batches[0], status: 'running' })
    assert.match(label, /imageGeneration\.batchStatuses\.running/)
    assert.doesNotMatch(label, /consistency\.statuses/)
  } finally { h.close() }
})

test('历史批次恢复工具，新提示词查询及续跑请求不携带模式选择', async () => {
  const h = harness('image', { batch_id: '111', tab: 'results' })
  const queries = []
  try {
    Object.assign(h.batches[0], { generation_mode: 'final', seed_strategy: 'shared_candidate', candidate_count: 3, tool_preset_id: 2 })
    h.imageApi.listImageGenerationTools = async () => [
      { id: 1, name: '默认文字工具', provider: 'comfyui', prompt_type: 'natural_language', is_default: true },
      { id: 2, name: '批次所用工具', provider: 'comfyui', prompt_type: 'hybrid', is_default: false },
    ]
    h.imageApi.listImageGenerationPages = async (taskId, options) => {
      queries.push(options)
      return [{ ...h.page(taskId), latest_spec_id: options.generationMode === 'final' && options.promptType === 'hybrid' ? 14 : null }]
    }
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.selectedBatchId.value, 111)
    assert.equal(h.state.generationForm.generation_mode, undefined)
    assert.equal(h.state.continuationPayload(h.state.selectedBatch.value).generation_mode, undefined)
    assert.equal(h.state.generationForm.seed_strategy, 'shared_candidate')
    assert.equal(h.state.generationForm.candidates_per_page, 3)
    assert.equal(h.state.selectedWorkflowId.value, 2)
    assert.deepEqual(queries.at(-1), { promptType: 'hybrid' })
    assert.equal(h.state.pages.value[0].latest_spec_id, null)
    assert.equal(h.state.specReadyPageCount.value, 0)
    h.state.selectedBatch.value.status = 'suspended'
    assert.equal(h.state.canContinueGeneration.value, true)
    await h.state.loadBatches(); await h.flush()
    assert.equal(h.state.generationForm.generation_mode, undefined)
  } finally { h.close() }
})

test('50页候选分页只渲染当前页，切短批次或增大页容量不会出现空白页', async () => {
  const h = harness('image')
  try {
    h.state.pages.value = Array.from({ length: 50 }, (_, index) => ({ ...h.page(11), page_id: index + 1, page_no: index + 1 }))
    h.state.pageTablePage.value = 3; await h.flush()
    assert.deepEqual(h.state.paginatedPages.value.map(page => page.page_no), Array.from({ length: 10 }, (_, index) => index + 41))
    h.state.pageTablePageSize.value = 50; await h.flush()
    assert.equal(h.state.pageTablePage.value, 1)
    assert.equal(h.state.paginatedPages.value.length, 50)
    h.state.pageTablePageSize.value = 20; h.state.pageTablePage.value = 3; await h.flush()
    h.state.pages.value = h.state.pages.value.slice(0, 2); await h.flush()
    assert.equal(h.state.pageTablePage.value, 1)
    assert.deepEqual(h.state.paginatedPages.value.map(page => page.page_no), [1, 2])
  } finally { h.close() }
})

test('控制降级不阻止生成，缺少提示词的所选页须先准备', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.generationForm.generation_mode = 'final'; await h.flush()
    h.state.pages.value = Array.from({ length: 50 }, (_, index) => ({
      ...h.page(11), page_id: index + 1, page_no: index + 1,
      spec_warnings: index < 23 ? [{ code: 'shot_plan.control_unavailable', message: 'Dropped unavailable shot controls: depth, pose.' }] : [],
    }))
    assert.equal(h.state.specReadyPageCount.value, 50)
    assert.equal(h.state.canGenerate.value, true)
    h.state.pageStatusFilter.value = 'ready'
    assert.equal(h.state.filteredPages.value.length, 50)
    assert.equal(h.state.pages.value[0].spec_warnings.length, 1)
    h.state.pages.value[49].latest_spec_id = null
    assert.equal(h.state.specReadyPageCount.value, 49)
    assert.equal(h.state.canGenerate.value, false)
    assert.equal(h.state.filteredPages.value.length, 49)
    h.state.pageStatusFilter.value = 'missing'
    assert.deepEqual(h.state.filteredPages.value.map(page => page.page_no), [50])
    h.state.pages.value[0].spec_stale = true
    assert.equal(h.state.specReadyPageCount.value, 48)
    assert.deepEqual(h.state.filteredPages.value.map(page => page.page_no), [1, 50])
  } finally { h.close() }
})

test('候选就绪度在所有页面人工选择终稿后完成，空列表或部分选择不误报', () => {
  const h = harness('image')
  const resultStatus = () => h.state.generationReadinessItems.value.find(item => item.key === 'results').status
  try {
    assert.equal(resultStatus(), 'pending')
    h.state.pages.value = [
      { ...h.page(11), images: [{ id: 1 }], selected_image_id: 1 },
      { ...h.page(12), images: [{ id: 2 }], selected_image_id: null },
    ]
    assert.equal(resultStatus(), 'info')
    h.state.pages.value[1].selected_image_id = 2
    assert.equal(resultStatus(), 'ready')
    h.state.pages.value[0].selected_image_id = null
    assert.equal(resultStatus(), 'info')
    h.state.pages.value = []
    assert.equal(resultStatus(), 'pending')
  } finally { h.close() }
})

test('跨项目图片 SSE 不串写；返回原批次后暂停使用明确的批次 ID', async () => {
  const h = harness('image', { batch_id: '111', tab: 'generate' })
  h.translations['imageGeneration.events.queuedText'] = '第 {pageNo} 页任务 ID：{promptId}'
  try {
    await h.lifecycle.mounted(); await h.flush()
    const running = h.state.generateBatch(); await h.flush()
    h.batches.push({ ...h.batches[0], id: 112, status: 'running' })
    h.callbacks.onEvent('start', { task_id: 112, script_task_id: 11 }); await h.flush()
    h.callbacks.onEvent('queued', { page_no: 1, external_request_id: 'current-provider-id', comfy_prompt_id: 'legacy-id' })
    assert.equal(h.state.progressEvents.value[0].content, '第 1 页任务 ID：current-provider-id')
    h.callbacks.onEvent('queued', { page_no: 1, comfy_prompt_id: 'legacy-only-id' })
    assert.equal(h.state.progressEvents.value[0].content, '第 1 页任务 ID：legacy-only-id')
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

for (const completion of [{ status: 'failed' }, { status: 'succeeded', failed: 1 }]) {
  test(`批次 done 按状态或失败数报告失败并保留成功候选：${JSON.stringify(completion)}`, async () => {
    const h = harness('image', { batch_id: '111', tab: 'generate' })
    try {
      await h.lifecycle.mounted(); await h.flush()
      const running = h.state.generateBatch(); await h.flush()
      const batch = { ...h.batches[0], id: 112, status: 'running' }
      h.batches.push(batch)
      h.callbacks.onEvent('start', { task_id: 112, script_task_id: 11 }); await h.flush()
      const image = { id: 900, page_id: 110, page_no: 1, image_url: '/mock.png' }
      h.callbacks.onEvent('image', image)
      assert.equal(h.state.pages.value[0].images[0].id, 900)
      h.imageApi.listImageGenerationPages = async taskId => [{ ...h.page(taskId), images: [image], completed_candidates: 1 }]
      batch.status = 'failed'
      h.callbacks.onEvent('done', { task_id: 112, total: 2, succeeded: 1, ...completion })
      assert.equal(h.activities.get('image-generation-112').status, 'failed')
      assert.equal(h.state.progressEvents.value[0].type, 'danger')
      assert.equal(h.state.progressEvents.value[0].content, 'imageGeneration.messages.generatedWithFailures')
      assert.deepEqual(h.notifications, [{ level: 'warning', message: 'imageGeneration.messages.generatedWithFailures' }])
      h.stream.resolve(); await running; await h.flush()
      assert.equal(h.state.activeGenerationTab.value, 'results')
      assert.equal(h.state.pages.value[0].images[0].id, 900)
      assert.equal(h.state.canContinueGeneration.value, true)
      assert.equal(h.activities.get('image-generation-112').status, 'failed')
    } finally { h.close() }
  })
}

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

for (const code of ['image_generation.batch_busy', 'image_generation.batch_recovery_unavailable', 'image_generation.batch_recovery_unsupported']) {
test(`继续请求保护拒绝只警告，不将原暂停批次伪装成失败：${code}`, async () => {
  const h = harness('image', { batch_id: '111', tab: 'generate' })
  h.translations[`backendErrors.${code}`] = `本次请求未执行：${code}`
  try {
    h.batches[0].status = 'suspended'
    await h.lifecycle.mounted(); await h.flush()
    const continuing = h.state.continueBatch(); await h.flush()
    assert.equal(h.activities.get('image-generation-111').status, 'suspended')
    h.callbacks.onError({ code })
    assert.equal(h.activities.get('image-generation-111').status, 'suspended')
    assert.equal(h.state.progressEvents.value[0].type, 'warning')
    assert.equal(h.state.progressEvents.value[0].content, `本次请求未执行：${code}`)
    assert.deepEqual(h.notifications, [{ level: 'warning', message: `本次请求未执行：${code}` }])
    h.stream.resolve(); await continuing; await h.flush()
    assert.equal(h.activities.get('image-generation-111').status, 'suspended')
    assert.equal(h.state.continuing.value, false)
  } finally { h.close() }
})
}

for (const fails of [false, true]) {
  test(`刷新后无本页 SSE 的暂停请求结束必清加载状态，成功时读取真实批次：失败=${fails}`, async () => {
    const h = harness('image', { batch_id: '111', tab: 'generate' })
    const request = deferred()
    try {
      h.batches[0].status = 'running'
      h.imageApi.suspendImageGenerationTask = async id => {
        h.suspended.push(id)
        await request.promise
        if (fails) throw new Error('pause request failed')
        h.batches[0].status = 'suspended'
        return h.batches[0]
      }
      await h.lifecycle.mounted(); await h.flush()
      assert.equal(h.state.runningGeneration.value, null)
      const pausing = h.state.suspendGeneration(); await h.flush()
      assert.equal(h.state.suspending.value, true)
      request.resolve(); await pausing; await h.flush()
      assert.deepEqual(h.suspended, [111])
      assert.equal(h.state.suspending.value, false)
      assert.equal(h.state.selectedBatch.value.status, fails ? 'running' : 'suspended')
      assert.equal(h.activities.get('image-generation-111').status, fails ? 'running' : 'suspended')
      assert.equal(h.callbacks, null)
      assert.deepEqual(h.notifications, [{ level: fails ? 'error' : 'info', message: fails ? 'imageGeneration.errors.suspendFailed' : 'imageGeneration.messages.suspendRequested' }])
    } finally { h.close() }
  })
}

test('准备页不查询历史快照，完成记录不能覆盖当前有效页数', async () => {
  const h = harness('spec', { tab: 'results' })
  let historyReads = 0
  h.specApi.listContinuityCompilations = async () => { historyReads++; throw new Error('history unavailable') }
  h.translations['imageSpecs.readiness.resultDetail'] = '{pages}/{total} 页'
  h.specApi.listImageSpecs = async () => ['tag', 'natural_language', 'hybrid'].map((prompt_type, i) => ({
    id: i + 1, page_no: 1, prompt_type, spec_stale: true, stale_reasons: ['scene_inputs_changed'],
    positive_prompt: '旧提示词', negative_prompt: '', warnings: [],
  }))
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(historyReads, 0)
    assert.equal(h.state.latestSpecCompilation.value.status, 'succeeded')
    assert.equal(h.state.validSpecPageCount.value, 0)
    assert.equal(h.state.staleSpecPageCount.value, 1)
    assert.equal(h.state.imageSpecReadinessItems.value.at(-1).detail, '0/1 页')
    assert.equal(h.state.imageSpecReadinessItems.value.at(-1).status, 'blocked')
    assert.deepEqual(h.state.staleReasonsForPage(h.state.specs.value), ['scene_inputs_changed'])
    h.state.specs.value.forEach(spec => { spec.spec_stale = false; spec.stale_reasons = [] })
    assert.equal(h.state.validSpecPageCount.value, 1)
    assert.equal(h.state.imageSpecReadinessItems.value.at(-1).status, 'ready')
    h.state.specs.value.pop()
    assert.equal(h.state.validSpecPageCount.value, 0)
    h.state.selectedTaskId.value = 12; await h.flush()
    assert.equal(h.state.validSpecPageCount.value, 0)
    assert.equal(historyReads, 0)
  } finally { h.close() }
})

test('准备页直接准备提示词并显示耗时，兼容旧事件且隔离两类编译 ID', async () => {
  const h = harness('spec', { tab: 'compile' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const compiling = h.state.compile(); await h.flush()
    h.callbacks.onEvent('start', { total_pages: 50 })
    assert.equal(h.state.visibleCompilation.value.phase, 'specs')
    assert.equal(h.state.visibleCompilation.value.totalPages, 50)
    assert.equal(h.state.canCompile.value, false)
    assert.equal(h.compileRequests[0].payload.generation_mode, undefined)
    assert.equal(Object.hasOwn(h.compileRequests[0].payload, 'regenerate_continuity'), false)
    h.state.compileClock.value = h.state.visibleCompilation.value.startedAt + 65000
    assert.equal(h.state.compilationElapsedTime.value, '1:05')
    h.callbacks.onEvent('continuity_progress', { total_pages: 50, elapsed_seconds: 120 })
    assert.equal(h.state.compilationElapsedTime.value, '2:00')
    h.callbacks.onEvent('continuity', { compilation_id: 999, event_count: 12 })
    assert.equal(h.state.visibleCompilation.value.phase, 'specs')
    assert.equal(h.state.visibleCompilation.value.compilationId, null)
    assert.equal(h.activities.has('image-spec-999'), false)
    const batch = { ...h.compilation(11, 113), status: 'running', total_pages: 50, total_specs: 150, completed_pages: 0, completed_specs: 0 }
    h.compilationItems.unshift(batch)
    h.callbacks.onEvent('compilation', batch)
    h.callbacks.onEvent('progress', { compilation_id: 113, completed: 3, total: 150 })
    assert.equal(h.state.visibleCompilation.value.completedSpecs, 3)
    assert.equal(h.activities.get('image-spec-113').progress, 2)
    Object.assign(batch, { status: 'succeeded', completed_specs: 150, completed_pages: 50 })
    h.callbacks.onEvent('done', { image_spec_compilation_id: 113 })
    h.stream.resolve(); await compiling; await h.flush()
    assert.equal(h.state.visibleCompilation.value, null)
    assert.equal(h.state.compiling.value, false)
    assert.equal(h.state.activeSpecTab.value, 'results')
    assert.deepEqual(h.notifications, [{ level: 'success', message: 'imageSpecs.messages.compiled' }])
  } finally { h.close() }
})

test('准备页编译错误退出后停止运行提示并允许重试，不报成功', async () => {
  const h = harness('spec', { tab: 'compile' })
  try {
    await h.lifecycle.mounted(); await h.flush()
    const compiling = h.state.compile(); await h.flush()
    h.callbacks.onEvent('start', { total_pages: 50 })
    h.callbacks.onError({ code: 'image_spec.compilation_failed' })
    h.stream.resolve(); await compiling; await h.flush()
    assert.equal(h.state.visibleCompilation.value, null)
    assert.equal(h.state.compiling.value, false)
    assert.equal(h.state.canCompile.value, true)
    assert.equal(h.state.activeSpecTab.value, 'compile')
    assert.deepEqual(h.notifications, [{ level: 'error', message: 'imageSpecs.errors.compile' }])
  } finally { h.close() }
})

test('历史连续性错误仍兼容稳定代码译文，新一轮准备才清除', async () => {
  const h = harness('spec', { tab: 'compile' })
  h.translations['backendErrors.image_spec.continuity_invalid'] = '连续性事件或视觉状态不合法。'
  try {
    await h.lifecycle.mounted(); await h.flush()
    const compiling = h.state.compile(); await h.flush()
    h.callbacks.onError({ code: 'image_spec.continuity_invalid', message: 'raw provider detail' })
    h.stream.resolve(); await compiling; await h.flush()
    assert.equal(h.state.visibleCompilation.value, null)
    assert.equal(h.state.compileFailure.value.code, 'image_spec.continuity_invalid')
    assert.equal(h.state.compileFailure.value.completedSpecs, 0)
    assert.equal(h.state.compileFailureMessage.value, '连续性事件或视觉状态不合法。')
    assert.equal(h.state.canCompile.value, true)
    h.resetStream()
    const retrying = h.state.compile(); await h.flush()
    assert.equal(h.state.compileFailure.value, null)
    h.callbacks.onEvent('done', {})
    h.stream.resolve(); await retrying; await h.flush()
    assert.equal(h.state.compileFailure.value, null)
  } finally { h.close() }
})

for (const completion of [{ status: 'failed' }, { failed_pages: [{ page_no: 2 }] }]) {
  test(`准备页含失败的 done 保留成功规格且不标100%成功：${JSON.stringify(completion)}`, async () => {
    const h = harness('spec', { tab: 'compile' })
    try {
      await h.lifecycle.mounted(); await h.flush()
      const compiling = h.state.compile(); await h.flush()
      const batch = { ...h.compilation(11, 113), status: 'running', total_pages: 12, total_specs: 36, completed_pages: 9, completed_specs: 27 }
      h.compilationItems.unshift(batch)
      h.callbacks.onEvent('compilation', batch)
      h.callbacks.onEvent('done', { image_spec_compilation_id: 113, ...completion })
      assert.equal(h.activities.get('image-spec-113').status, 'failed')
      assert.equal(h.activities.get('image-spec-113').progress, 75)
      Object.assign(batch, { status: 'failed', failed_pages: [12, 2, 10].map(page => ({ page_id: page, page_no: page })) })
      h.stream.resolve(); await compiling; await h.flush()
      assert.equal(h.state.visibleCompilation.value, null)
      assert.equal(h.state.specs.value[0].id, 11)
      assert.equal(h.state.canCompile.value, true)
      assert.equal(h.activities.get('image-spec-113').status, 'failed')
      assert.equal(h.state.compileFailure.value.completedSpecs, 27)
      assert.deepEqual(h.state.compileFailure.value.failedPages, [2, 10, 12])
      assert.deepEqual(h.state.sortedFailedPageNumbers(h.state.latestSpecCompilation.value.failed_pages), [2, 10, 12])
      assert.deepEqual(batch.failed_pages.map(item => item.page_no), [12, 2, 10])
      assert.deepEqual(h.notifications, [{ level: 'warning', message: 'imageSpecs.messages.compiledWithFailures' }])
      h.state.selectedTaskId.value = 12; await h.flush()
      assert.equal(h.state.compileFailure.value, null)
      h.callbacks.onError({ code: 'image_spec.compilation_failed' })
      assert.equal(h.state.compileFailure.value, null)
    } finally { h.close() }
  })
}

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


test('生成漫画默认只补无候选页，未选终稿的已有候选页不会重生成', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [
      { ...h.page(11), page_id: 110 },
      { ...h.page(11), page_id: 111, page_no: 2, images: [{ id: 800 }], selected_image_id: null },
      { ...h.page(11), page_id: 112, page_no: 3, images: [{ id: 801 }], selected_image_id: 801 },
    ]
    assert.equal(h.state.canGenerate.value, true)
    const running = h.state.generateBatch(); await h.flush()
    assert.deepEqual(h.generated[0].payload.page_ids, [110])
    assert.equal(h.state.runningGeneration.value.total, 1)
    h.stream.resolve(); await running
    h.state.pages.value = [{ ...h.page(11), images: [{ id: 800 }], selected_image_id: null }]
    assert.equal(h.state.canGenerate.value, false)
  } finally { h.close() }
})

test('按页码范围跨分页替换选择，忽略搜索过滤并仅提交范围内真实页面', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = Array.from({ length: 80 }, (_, i) => ({ ...h.page(11), page_id: 1000 + i * 3, page_no: i + 1 }))
    h.state.pages.value[20].images = [{ id: 800 }]
    h.state.selectedPageIds.value = [1000]
    h.state.pageSearch.value = '80'
    h.state.pageStatusFilter.value = 'generated'
    h.state.pageRangeStart.value = 20
    h.state.pageRangeEnd.value = 22
    assert.equal(h.state.canSelectPageRange.value, true)
    h.state.selectPageRange()
    assert.deepEqual(h.state.selectedPageIds.value, [1057, 1060, 1063])
    const running = h.state.generateBatch(); await h.flush()
    assert.deepEqual(h.generated[0].payload.page_ids, [1057, 1060, 1063])
    assert.equal(h.state.runningGeneration.value.total, 3)
    assert.equal(h.state.canSelectPageRange.value, false)
    h.stream.resolve(); await running
  } finally { h.close() }
})

test('无效范围不改变选择，单页和缺号范围只选择实际页码；切换脚本清除范围', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [1, 3, 5].map(n => ({ ...h.page(11), page_id: 100 + n, page_no: n }))
    h.state.selectedPageIds.value = [101]
    for (const [start, end] of [[null, 3], [1, null], [4, 2], [0, 3], [1, 6], [1.5, 3], [2, 2]]) {
      h.state.pageRangeStart.value = start; h.state.pageRangeEnd.value = end
      assert.equal(h.state.canSelectPageRange.value, false)
      h.state.selectPageRange()
      assert.deepEqual(h.state.selectedPageIds.value, [101])
    }
    h.state.pageRangeStart.value = 3; h.state.pageRangeEnd.value = 3
    h.state.selectPageRange()
    assert.deepEqual(h.state.selectedPageIds.value, [103])
    h.state.pageRangeEnd.value = 5
    h.state.selectPageRange()
    assert.deepEqual(h.state.selectedPageIds.value, [103, 105])
    h.state.selectedTaskId.value = 12; await h.flush()
    assert.equal(h.state.pageRangeStart.value, null)
    assert.equal(h.state.pageRangeEnd.value, null)
    assert.deepEqual(h.state.selectedPageIds.value, [])
  } finally { h.close() }
})

test('范围选择保留过期页供修复，不能绕过提示词校验或在加载期间改选', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [
      { ...h.page(11), page_id: 101, page_no: 1 },
      { ...h.page(11), page_id: 102, page_no: 2, spec_stale: true },
    ]
    h.state.pageRangeStart.value = 1; h.state.pageRangeEnd.value = 2
    h.state.loadingPages.value = true
    h.state.selectPageRange()
    assert.deepEqual(h.state.selectedPageIds.value, [])
    h.state.loadingPages.value = false
    h.state.selectPageRange()
    assert.deepEqual(h.state.selectedPageIds.value, [101, 102])
    assert.equal(h.state.canGenerate.value, false)
    await h.state.generateBatch()
    assert.equal(h.generated.length, 0)
  } finally { h.close() }
})

test('选中已准备页面批量追加，保留已有候选', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = [
      { ...h.page(11), page_id: 110, images: [{ id: 800 }] },
      { ...h.page(11), page_id: 111, page_no: 2, images: [] },
    ]
    h.state.togglePageSelection(110, true)
    h.state.activeGenerationTab.value = 'results'
    const running = h.state.generateBatch(); await h.flush()
    assert.deepEqual(h.generated[0].payload.page_ids, [110])
    assert.equal(h.state.activeGenerationTab.value, 'results')
    assert.equal(h.state.generating.value, true)
    assert.equal(h.state.activeGenerationTab.value, 'results')
    assert.equal(h.state.currentGenerationTaskId.value, null)
    assert.equal(h.state.pages.value[0].images[0].id, 800)
    assert.equal(h.notifications.length, 0)
    h.stream.resolve(); await running
  } finally { h.close() }
})

test('缺少提示词的单页禁止生成；切换脚本清除批量选择', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    const running = h.state.generatePage({ ...h.page(11), latest_spec_id: null }); await h.flush()
    assert.equal(h.generated.length, 0)
    assert.ok(h.notifications.length > 0)
    h.stream.resolve(); await running
    h.state.togglePageSelection(110, true)
    h.state.selectedTaskId.value = 12; await h.flush()
    assert.deepEqual([...h.state.selectedPageIds.value], [])
  } finally { h.close() }
})

test('旧浏览器严格偏好不影响新生成请求，工作台不再提供模式选择', async () => {
  const h = harness('image')
  try {
    localStorage.setItem('comaic-generation-mode-11', 'final')
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.generationMode, undefined)
    assert.equal(h.state.streamPayload().generation_mode, undefined)
    assert.equal(h.modeModule.exports.useGenerationMode, undefined)
  } finally { h.close() }
})

test('生图准备语言按脚本保存，与界面语言独立', () => {
  const h = harness('image')
  try {
    const first = h.modeModule.exports.usePromptLanguage(vue.ref(11))
    const same = h.modeModule.exports.usePromptLanguage(vue.ref(11))
    const other = h.modeModule.exports.usePromptLanguage(vue.ref(12))
    assert.equal(first.value, 'original')
    first.value = 'zh'
    assert.equal(same.value, 'zh')
    assert.equal(other.value, 'original')
    assert.equal(localStorage.getItem('comaic-prompt-language-11'), 'zh')
    same.value = 'en'
    assert.equal(first.value, 'en')
  } finally { h.close() }
})

test('出图仅使用已准备的提示词，不提供语言和准备重试入口', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    assert.equal(h.state.promptLanguage, undefined)
    assert.equal(h.state.retryPreparation, undefined)
    const running = h.state.generatePage(h.page(11)); await h.flush()
    assert.equal(h.generated[0].payload.prompt_language, undefined)
    h.stream.resolve(); await running
  } finally { h.close() }
})

test('冻结子集续跑进度由服务端剩余候选数校正，不使用任务全页数', async () => {
  const h = harness('image')
  try {
    h.batches[0].status = 'suspended'
    h.batches[0].candidate_count = 3
    h.batches[0].batch_size = 6
    h.batches[0].progress = { completed_candidates: 3 }
    await h.lifecycle.mounted(); await h.flush()
    h.state.pages.value = Array.from({ length: 10 }, (_, i) => ({ ...h.page(11), page_id: 110 + i, page_no: i + 1 }))
    const running = h.state.continueBatch(); await h.flush()
    assert.equal(h.state.runningGeneration.value.total, 3)
    h.callbacks.onEvent('start', { task_id: 111, total: 1, batch_size: 2 })
    assert.equal(h.state.runningGeneration.value.total, 2)
    h.stream.resolve(); await running
  } finally { h.close() }
})

test('浏览器禁用存储时提示词语言仍保留；页面刷新清除失效选择', async () => {
  const h = harness('image')
  try {
    await h.lifecycle.mounted(); await h.flush()
    global.localStorage = { getItem: () => { throw Error('disabled') }, setItem: () => { throw Error('disabled') } }
    const language = h.modeModule.exports.usePromptLanguage(vue.ref(90))
    assert.equal(language.value, 'original')
    language.value = 'en'
    assert.equal(h.modeModule.exports.usePromptLanguage(vue.ref(90)).value, 'en')
    h.state.togglePageSelection(110, true)
    h.state.togglePageSelection(999, true)
    await h.state.loadPages()
    assert.deepEqual([...h.state.selectedPageIds.value], [110])
  } finally { h.close() }
})


test('无 Seed 绑定时允许新生成和单页重画，冻结批次仍能续跑', async () => {
  const h = harness('image', { batch_id: '111', tab: 'generate' })
  try {
    h.batches[0].status = 'suspended'
    await h.lifecycle.mounted(); await h.flush()
    h.state.workflows.value[0].seed_node_id = null
    h.state.workflows.value[0].seed_input_name = null
    const generating = h.state.generateBatch(); await h.flush()
    assert.equal(h.generated.length, 1)
    h.stream.resolve(); await generating; h.resetStream()
    const redraw = h.state.generatePage(h.state.pages.value[0]); await h.flush()
    assert.equal(h.generated.length, 2)
    h.stream.resolve(); await redraw; h.resetStream()
    const continuing = h.state.continueBatch(); await h.flush()
    assert.deepEqual(h.continued, [111])
    h.stream.resolve(); await continuing
    h.state.workflows.value = []
    await h.state.continueBatch()
    assert.deepEqual(h.continued, [111])
    assert.equal(h.notifications.at(-1).message, 'imageGeneration.errors.selectWorkflow')
  } finally { h.close() }
})

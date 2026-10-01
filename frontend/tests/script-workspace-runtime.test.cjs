const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')

const sourcePath = path.resolve(__dirname, '../src/views/ScriptWorkspaceView.vue')
const { descriptor } = parse(fs.readFileSync(sourcePath, 'utf8'))
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'script-runtime-test' }).content, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

// 编译实际组件脚本并注入离线接口；保留真实 Vue watch，覆盖请求与 SSE 交错到达的场景。
const harness = () => {
  const local = new Map()
  global.localStorage = { getItem: (key) => local.get(key) ?? null, setItem: (key, value) => local.set(key, value) }
  const route = vue.reactive({ path: '/scripts', query: { project_id: '1', script_task_id: '11' } })
  const selectedProjectId = vue.ref(1)
  const projects = vue.ref([{ id: 1, title: '甲' }, { id: 2, title: '乙' }])
  const loadingProjects = vue.ref(false)
  const activities = new Map()
  const replacements = []
  const suspended = []
  const continued = []
  const lifecycle = {}
  const tasks = [
    { id: 12, project_id: 1, outline_version_id: 102, status: 'succeeded', mode: 'batch', total_pages: 2 },
    { id: 11, project_id: 1, outline_version_id: 101, status: 'succeeded', mode: 'batch', total_pages: 2 },
    { id: 21, project_id: 2, outline_version_id: 201, status: 'succeeded', mode: 'batch', total_pages: 2 },
    { id: 22, project_id: 2, outline_version_id: 201, status: 'succeeded', mode: 'batch', total_pages: 2 },
  ].map((item) => ({ ...item, updated_at: '2026-10-01T00:00:00Z' }))
  const page = (taskId, id = taskId * 10) => ({
    id, task_id: taskId, project_id: Math.floor(taskId / 10), page_no: 1,
    summary: '页面', script_review_status: 'passed', updated_at: '2026-10-01T00:00:00Z',
  })
  let pendingPages = null
  let streamCallbacks = null
  const stream = deferred()
  const confirm = { current: Promise.resolve() }
  const cleared = []
  const api = {
    listProjectScriptTasks: async (projectId, options = {}) => tasks.filter((item) => item.project_id === projectId && (!options.outlineVersionId || item.outline_version_id === options.outlineVersionId)),
    listScriptTaskPages: async (taskId) => pendingPages?.taskId === taskId ? pendingPages.promise : [page(taskId)],
    listScriptTaskSections: async () => [],
    listScriptTaskScenes: async () => [],
    listScriptTaskCharacters: async () => [],
    streamBatchScriptGeneration: async (_payload, callbacks) => { streamCallbacks = callbacks; await stream.promise },
    streamContinueScriptGeneration: async (id, _payload, callbacks) => { continued.push(id); streamCallbacks = callbacks; await stream.promise },
    suspendScriptTask: async (id) => { suspended.push(id) },
    clearPageScript: async (projectId, pageNo, taskId) => { cleared.push({ projectId, pageNo, taskId }); return page(taskId) },
  }
  const router = {
    replace: async (next) => { replacements.push(next); route.query = { ...next.query } },
    push: async (next) => { route.path = next.path; route.query = { ...next.query } },
  }
  const stubs = {
    vue: { ...vue, onMounted: (fn) => { lifecycle.mounted = fn }, onActivated: (fn) => { lifecycle.activated = fn }, onDeactivated: (fn) => { lifecycle.deactivated = fn } },
    pinia: { storeToRefs: (store) => store },
    'vue-router': { useRoute: () => route, useRouter: () => router },
    'vue-i18n': { useI18n: () => ({ locale: vue.ref('zh'), t: (key) => key }) },
    'element-plus': { ElMessage: { error() {}, warning() {}, success() {}, info() {} }, ElMessageBox: { confirm: () => confirm.current } },
    '@element-plus/icons-vue': {},
    '@/api/projects': { listProjects: async () => projects.value },
    '@/api/outline': { resolveOutlineSession: async (id) => ({ outline_versions: (id === 1 ? [102, 101] : [id * 100 + 1]).map((version_id) => ({ version_id, confirmed_at: 'yes', status: 'ready' })) }) },
    '@/api/errors': { ApiError: class extends Error {}, apiErrorMessage: (_error, _t, fallback) => fallback },
    '@/api/scripts': api,
    '@/utils/datetime': { formatLocalDateTime: () => '', formatLocalNowTime: () => '' },
    '@/stores/projectContext': { useProjectContextStore: () => ({ selectedProjectId, projects, loadingProjects, refreshProjects: async () => {} }) },
    '@/stores/activityCenter': { useActivityCenterStore: () => ({ upsertActivity: (activity) => activities.set(activity.id, activity) }) },
  }
  const runtime = new Module(sourcePath, module)
  runtime.filename = sourcePath
  runtime.paths = module.paths
  runtime.require = (id) => Object.hasOwn(stubs, id) ? stubs[id] : require(id)
  runtime._compile(compiled, sourcePath)
  const scope = vue.effectScope()
  const state = scope.run(() => runtime.exports.default.setup({}, { expose() {} }))
  const flush = async () => { for (let i = 0; i < 8; i++) { await vue.nextTick(); await new Promise(setImmediate) } }
  return { state, route, selectedProjectId, projects, tasks, activities, suspended, continued, replacements, lifecycle, stream, confirm, cleared, page,
    get callbacks() { return streamCallbacks },
    holdPages(taskId) { pendingPages = { taskId, ...deferred() }; return pendingPages },
    flush, close: () => scope.stop(),
  }
}

test('脚本工作台在同路由深链接中选择原批次所属大纲', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    assert.equal(h.state.selectedOutlineVersionId.value, 101)
    assert.equal(h.state.selectedTaskId.value, 11)
    h.route.query = { project_id: '1', script_task_id: '12' }
    await h.flush()
    assert.equal(h.state.selectedOutlineVersionId.value, 102)
    assert.equal(h.state.selectedTaskId.value, 12)
    assert.ok(h.state.pages.value.every((item) => item.task_id === 12))
  } finally { h.close() }
})

test('缓存工作台使用共享项目列表，新项目深链接与重命名即时可见', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    h.projects.value.push({ id: 3, title: '新项目' })
    h.tasks.push({ id: 31, project_id: 3, outline_version_id: 301, status: 'succeeded', mode: 'batch', total_pages: 2 })
    h.route.query = { project_id: '3', script_task_id: '31' }
    await h.flush()
    assert.equal(h.state.selectedTaskId.value, 31)
    assert.equal(h.state.selectedProject.value.title, '新项目')
    h.projects.value.find((item) => item.id === 3).title = '已重命名'
    assert.equal(h.state.selectedProject.value.title, '已重命名')
  } finally { h.close() }
})

test('缺少精确定位的旧活动只展示批次选项，不猜测或保留第一批次', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    h.route.query = { project_id: '1', activity_legacy: '1' }
    await h.flush()
    assert.equal(h.state.selectedTaskId.value, null)
    assert.equal(h.state.pages.value.length, 0)
    assert.ok(h.state.scriptTasks.value.length > 0)
    assert.equal(h.route.query.activity_legacy, '1')
    h.state.selectedTaskId.value = h.state.scriptTasks.value[0].id
    await h.flush()
    assert.equal(h.route.query.activity_legacy, undefined)
  } finally { h.close() }
})

test('精确定位的批次不存在时提示不可用，不打开其他批次', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    h.route.query = { project_id: '1', script_task_id: '999' }
    await h.flush()
    assert.equal(h.state.selectedTaskId.value, null)
    assert.equal(h.state.unavailableTaskId.value, 999)
    assert.equal(h.state.pages.value.length, 0)
    assert.equal(h.route.query.script_task_id, '999')
  } finally { h.close() }
})

test('切项目后旧 SSE 不串写，暂停仍针对原运行任务，终态记录可准确返回', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    const running = h.state.generateBatch()
    await h.flush()
    h.tasks.push({ id: 13, project_id: 1, outline_version_id: 101, status: 'running', mode: 'batch', total_pages: 2 })
    h.callbacks.onEvent('task', { task_id: 13 })
    await h.flush()
    h.selectedProjectId.value = 2
    await h.flush()
    const selected = h.state.selectedTaskId.value
    h.callbacks.onEvent('section_pages', { pages: [h.page(13)], section: { id: 130, task_id: 13, section_no: 1 } })
    await h.flush()
    assert.equal(h.state.selectedTaskId.value, selected)
    assert.ok(h.state.pages.value.every((item) => item.project_id === 2))
    assert.ok(h.state.sections.value.every((item) => item.task_id !== 13))
    await h.state.suspendBatch()
    assert.deepEqual(h.suspended, [13])
    h.tasks.find((item) => item.id === 13).status = 'succeeded'
    h.callbacks.onEvent('done', {})
    h.stream.resolve()
    await running
    const activity = h.activities.get('script-13')
    assert.equal(activity.status, 'succeeded')
    assert.equal(activity.projectId, 1)
    assert.match(activity.route, /project_id=1&script_task_id=13/)
  } finally { h.close() }
})

test('过期页面读取不得覆盖新批次；离页后的共享项目变化不得重写当前路由', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    const oldRead = h.holdPages(11)
    const loading = h.state.loadPages()
    h.route.query = { project_id: '1', script_task_id: '12' }
    await h.flush()
    oldRead.resolve([h.page(11, 999)])
    await loading
    assert.ok(h.state.pages.value.every((item) => item.task_id === 12))
    h.lifecycle.deactivated()
    h.route.path = '/visual-bible'
    h.route.query = {}
    const calls = h.replacements.length
    h.selectedProjectId.value = 2
    await h.flush()
    assert.equal(h.replacements.length, calls)
    assert.equal(h.route.path, '/visual-bible')
  } finally { h.close() }
})

test('继续生成捕获原暂停批次，切项目后仍可准确暂停该批次', async () => {
  const h = harness()
  try {
    h.tasks.find((item) => item.id === 11).status = 'suspended'
    await h.lifecycle.mounted()
    await h.flush()
    const running = h.state.continueBatch()
    await h.flush()
    h.selectedProjectId.value = 2
    await h.flush()
    assert.deepEqual(h.continued, [11])
    await h.state.suspendBatch()
    assert.deepEqual(h.suspended, [11])
    h.callbacks.onEvent('suspended', { task_id: 11 })
    h.stream.resolve()
    await running
    assert.equal(h.state.selectedProjectId.value, 2)
  } finally { h.close() }
})

test('清空确认期间切项目，提交仍携带最初点击页面的项目与任务', async () => {
  const h = harness()
  try {
    await h.lifecycle.mounted()
    await h.flush()
    const confirmation = deferred()
    h.confirm.current = confirmation.promise
    const clearing = h.state.clearManualScript(h.page(11))
    h.selectedProjectId.value = 2
    await h.flush()
    confirmation.resolve()
    await clearing
    assert.deepEqual(h.cleared, [{ projectId: 1, pageNo: 1, taskId: 11 }])
    assert.ok(h.state.pages.value.every((item) => item.project_id === 2))
  } finally { h.close() }
})

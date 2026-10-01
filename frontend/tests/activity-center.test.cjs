const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const vue = require('vue')

// 使用现有编译器与响应式运行时，所有查询都以注入的 mock 替代。
function loadTs(file, imports = {}, globals = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src', file), 'utf8')
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
  const exports = {}
  vm.runInNewContext(output, { exports, require: (name) => {
    if (name in imports) return imports[name]
    if (name === 'vue') return vue
    if (name === 'pinia') return { defineStore: (_name, setup) => setup }
    throw new Error(`Unexpected import: ${name}`)
  }, URL, URLSearchParams, Date, Map, ...globals })
  return exports
}
const helpers = loadTs('utils/workspaceActivity.ts')
const activity = (overrides = {}) => ({ id: 'reference-7', kind: 'characterReference', label: 'Hero',
  status: 'running', progress: 30, route: '/visual-bible?tab=references', projectId: 1,
  characterId: 4, referenceTaskId: 7, updatedAt: '2026-10-01T00:00:00Z', ...overrides })

test('activity deep link restores project A and exact character/task from project B', () => {
  const result = new URL(helpers.activityRoute(activity()), 'http://local')
  assert.equal(result.pathname, '/visual-bible')
  assert.equal(result.searchParams.get('project_id'), '1')
  assert.equal(result.searchParams.get('character_id'), '4')
  assert.equal(result.searchParams.get('reference_task_id'), '7')
  assert.equal(result.searchParams.get('tab'), 'references')
})
test('legacy activities open their own project list without silently choosing a batch', () => {
  const result = new URL(helpers.activityRoute(activity({ kind: 'imageGeneration', characterId: undefined,
    referenceTaskId: undefined, route: '/image-generation?tab=results' })), 'http://local')
  assert.equal(result.searchParams.get('project_id'), '1')
  assert.equal(result.searchParams.get('activity_legacy'), '1')
  assert.equal(result.searchParams.has('batch_id'), false)
})
test('existing query locators are compatible and invalid IDs are rejected', () => {
  assert.equal(helpers.positiveId('0'), null)
  assert.equal(helpers.positiveId('1.5'), null)
  assert.equal(helpers.positiveId(['12', '13']), 12)
  assert.equal(helpers.hasExactActivityLocation(activity({ kind: 'imageSpec',
    route: '/image-specs?project_id=1&script_task_id=20&compilation_id=30' })), true)
  assert.equal(helpers.normalizeActivityStatus('waiting_resource'), 'pending')
})

function storeWith(queries = {}, stored = []) {
  const storage = new Map([['comaic-workspace-activities', JSON.stringify(stored)]])
  const fallback = async () => { throw new Error('Unexpected query') }
  const imports = {
    '@/utils/workspaceActivity': helpers,
    '@/api/scripts': { getScriptTask: queries.getScriptTask ?? fallback },
    '@/api/characterReference': { getCharacterReferenceTask: queries.getCharacterReferenceTask ?? fallback },
    '@/api/referenceImages': { getReferenceImageTask: queries.getReferenceImageTask ?? fallback },
    '@/api/imageGeneration': { listGenerationBatches: queries.listGenerationBatches ?? fallback },
    '@/api/imageSpecs': { listImageSpecCompilations: queries.listImageSpecCompilations ?? fallback },
    '@/api/consistencyEvaluation': { getConsistencyEvaluation: queries.getConsistencyEvaluation ?? fallback },
  }
  return loadTs('stores/activityCenter.ts', imports, { localStorage: {
    getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value),
  } }).useActivityCenterStore()
}
test('opening the center refreshes a reference task that completed while away', async () => {
  const store = storeWith({ getCharacterReferenceTask: async (id) => {
    assert.equal(id, 7)
    return { id, project_id: 1, status: 'succeeded', progress: { completed: 3, total: 3 }, updated_at: '2026-10-01T01:00:00Z' }
  } }, [activity()])
  await store.refreshActivities()
  assert.equal(store.activities.value[0].status, 'succeeded')
  assert.equal(store.activities.value[0].progress, 100)
  assert.equal(store.activities.value[0].updatedAt, '2026-10-01T01:00:00Z')
})

test('scene reference activity restores its own project and subject and refreshes generic terminal state', async () => {
  const sceneActivity = activity({ kind: 'referenceImage', characterId: undefined, referenceSubjectId: 18, entityType: 'scene' })
  const url = new URL(helpers.activityRoute(sceneActivity), 'http://local')
  assert.equal(url.searchParams.get('reference_subject_id'), '18')
  assert.equal(url.searchParams.get('entity_type'), 'scene')
  assert.equal(url.searchParams.get('reference_task_kind'), 'referenceImage')
  const store = storeWith({ getReferenceImageTask: async () => ({ project_id: 1, reference_subject_id: 18, status: 'succeeded', progress: { completed: 2, total: 2 }, updated_at: '2026-10-01T01:00:00Z' }) }, [sceneActivity])
  await store.refreshActivities()
  assert.equal(store.activities.value[0].status, 'succeeded')
})
test('refresh never replaces a newer stream update or a foreign project snapshot', async () => {
  let resolve
  const store = storeWith({ getCharacterReferenceTask: () => new Promise((r) => { resolve = r }) }, [activity()])
  const refreshing = store.refreshActivities()
  store.upsertActivity(activity({ status: 'succeeded', progress: 100, updatedAt: '2026-10-01T02:00:00Z' }))
  resolve({ project_id: 1, status: 'running', progress: { total: 3, completed: 1 }, updated_at: '2026-10-01T01:00:00Z' })
  await refreshing
  assert.equal(store.activities.value[0].status, 'succeeded')
  const foreign = storeWith({ getCharacterReferenceTask: async () => ({ project_id: 2, status: 'succeeded' }) }, [activity()])
  await foreign.refreshActivities()
  assert.equal(foreign.activities.value[0].status, 'running')
  assert.equal(foreign.activities.value[0].refreshFailed, true)
})
test('multiple activities for one script share list reads and retain individual batch IDs', async () => {
  let calls = 0
  const store = storeWith({ listGenerationBatches: async () => {
    calls++
    return [10, 11].map((id) => ({ id, project_id: 1, status: id === 10 ? 'succeeded' : 'failed', updated_at: '2026-10-01T03:00:00Z' }))
  } }, [10, 11].map((id) => activity({ id: `batch-${id}`, kind: 'imageGeneration', scriptTaskId: 20, batchId: id })))
  await store.refreshActivities()
  assert.equal(calls, 1)
  assert.equal(store.activities.value[0].status, 'succeeded')
  assert.equal(store.activities.value[1].status, 'failed')
})

test('project mutation forces a new list after a pending read and preserves selection on errors', async () => {
  let firstResolve
  let calls = 0
  const store = loadTs('stores/projectContext.ts', { '@/api/projects': { listProjects: () => {
    calls++
    if (calls === 1) return new Promise((resolve) => { firstResolve = resolve })
    if (calls === 2) return Promise.resolve([{ id: 1, title: 'Original' }, { id: 2, title: 'New' }])
    return Promise.reject(new Error('Offline'))
  } } }, { localStorage: { getItem: () => '1', setItem: () => {}, removeItem: () => {} } }).useProjectContextStore()
  const beforeMutation = store.refreshProjects()
  const afterMutation = store.refreshProjects({ force: true })
  firstResolve([{ id: 1, title: 'Original' }])
  await Promise.all([beforeMutation, afterMutation])
  assert.equal(calls, 2)
  assert.equal(store.projects.value.length, 2)
  store.selectedProjectId.value = 2
  await assert.rejects(store.refreshProjects())
  assert.equal(store.selectedProjectId.value, 2)
  assert.equal(store.projects.value.length, 2)
})

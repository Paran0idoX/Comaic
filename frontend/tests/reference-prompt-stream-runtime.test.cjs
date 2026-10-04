const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const ts = require('typescript')

class ApiError extends Error { constructor(message, options = {}) { super(message); Object.assign(this, options) } }
const file = path.resolve(__dirname, '../src/api/referenceImages.ts')
const runtime = new Module(file, module)
runtime.require = id => id === './errors' ? {
  ApiError, apiHeaders: () => ({}), normalizeBackendError: payload => payload,
  parseApiErrorResponse: async response => new ApiError('HTTP error', { status: response.status }),
} : require(id)
runtime._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, file)
const { previewReferencePromptBatch } = runtime.exports
const frame = (event, payload) => `event: ${event}\r\ndata: ${JSON.stringify(payload)}\r\n\r\n`
const responseStream = text => {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream({ start(controller) {
    // 故意切断 CRLF 和多字节字符，验证逐块消费不会丢失状态或文字。
    for (let index = 0; index < bytes.length; index += 7) controller.enqueue(bytes.slice(index, index + 7))
    controller.close()
  } }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('整批一次 POST，无前端并发限制，逐项消费乱序状态和中文结果', async () => {
  const original = global.fetch, calls = [], events = []
  const items = Array.from({ length: 12 }, (_, index) => ({ entity_type: 'character', entity_id: index + 1, roles: ['identity_face'], tool_preset_id: 1 }))
  const text = ': ping\r\n\r\n' + frame('accepted', { project_id: 9, total: 12, concurrency: 5 }) +
    frame('item', { project_id: 9, index: 7, status: 'running' }) +
    frame('item', { project_id: 9, index: 7, status: 'succeeded', preview: { prompts: { identity_face: { positive: '用户文字保留' } } } }) +
    frame('item', { project_id: 9, index: 3, status: 'failed', error: { code: 'reference.owner_invalid', message: '对象不可用' } }) +
    frame('done', { project_id: 9, completed: 11, failed: 1 })
  const controller = new AbortController()
  global.fetch = async (...args) => { calls.push(args); return responseStream(text) }
  try {
    await previewReferencePromptBatch(9, items, item => events.push(item), controller.signal)
    assert.equal(calls.length, 1)
    assert.equal(calls[0][0], '/api/reference-images/projects/9/prompt-preview/batch')
    assert.deepEqual(JSON.parse(calls[0][1].body).items, items)
    assert.equal(calls[0][1].signal, controller.signal)
    assert.deepEqual(events.map(event => [event.index, event.status]), [[7, 'running'], [7, 'succeeded'], [3, 'failed']])
    assert.equal(events[1].preview.prompts.identity_face.positive, '用户文字保留')
  } finally { global.fetch = original }
})

test('连接提前结束不自动重新提交，已经收到的成功事件保留', async () => {
  const original = global.fetch, events = []
  let calls = 0
  global.fetch = async () => { calls++; return responseStream(frame('item', { project_id: 1, index: 0, status: 'succeeded', preview: { prompts: {} } })) }
  try {
    await assert.rejects(previewReferencePromptBatch(1, [{}], item => events.push(item)), /before completion/)
    assert.equal(calls, 1); assert.equal(events.length, 1)
  } finally { global.fetch = original }
})

test('流内错误保留稳定错误码，HTTP 错误在消费流前抛出', async () => {
  const original = global.fetch
  try {
    global.fetch = async () => responseStream(frame('error', { code: 'reference.owner_invalid', message: 'Owner invalid' }))
    await assert.rejects(previewReferencePromptBatch(1, [{}], () => {}), error => error.code === 'reference.owner_invalid')
    global.fetch = async () => new Response('{}', { status: 422 })
    await assert.rejects(previewReferencePromptBatch(1, [{}], () => {}), error => error.status === 422)
  } finally { global.fetch = original }
})

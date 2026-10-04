/** 快速选图离线验收：使用内存 API，不读取业务数据库，也不调用真实生成服务。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const net = require('node:net')
const { spawn } = require('node:child_process')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const root = path.resolve(__dirname, '../../..')
const artifacts = path.join(root, '.codex-artifacts', `reference-quick-picker-${Date.now()}`)
const base = 'http://127.0.0.1:15274', api = 'http://127.0.0.1:18124'
const children = [], logs = [], checks = [], geometry = [], errors = []
let context, page
fs.mkdirSync(artifacts, { recursive: true })

async function freePort(port) {
  await new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(port, '127.0.0.1', () => server.close(resolve))
  })
}
function start(command, args, name) {
  const log = fs.createWriteStream(path.join(artifacts, `${name}.log`)); logs.push(log)
  const child = spawn(command, args, { cwd: root, windowsHide: true, env: process.env })
  child.stdout.pipe(log); child.stderr.pipe(log); children.push(child)
}
async function waitFor(url) {
  let lastError
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(url)).ok) return } catch (error) { lastError = error.cause || error }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw Error(`Server did not start: ${url}: ${lastError}`)
}
async function request(route, data, method = 'POST') {
  const response = await fetch(`${api}${route}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  assert.ok(response.ok, `${method} ${route}: ${response.status}`)
  return response.json()
}
async function createTask(category, ownerId, count = 4, scope = null, roles) {
  roles ||= category === 'character' ? ['identity_face', 'identity_full_body', 'identity_side', 'identity_back'] : [category === 'scene' ? 'scene_master' : 'prop_reference']
  return request('/api/reference-images/projects/1/tasks', {
    entity_type: category, entity_id: category === 'character' ? ownerId : scope,
    reference_subject_id: category === 'character' ? null : ownerId, outfit_variant_id: category === 'character' ? 601 : null,
    tool_preset_id: 1, roles, candidate_count: count,
    prompts: Object.fromEntries(roles.map(role => [role, { positive: 'Offline fixture', negative: '' }])),
  })
}
const dialog = () => page.locator('.reference-quick-dialog:visible')
const cards = () => dialog().locator('.quick-image')
const confirm = (card = dialog().locator('.quick-image.is-selected')) => card.getByRole('button', { name: '确认可用', exact: true })
async function ready() {
  await page.waitForFunction(() => {
    return document.querySelector('.reference-quick-dialog') && !document.querySelector('.reference-quick-dialog .el-button.is-loading') &&
      ![...document.querySelectorAll('.el-loading-mask')].some(el => el.getBoundingClientRect().width && el.getBoundingClientRect().height)
  })
  await page.waitForTimeout(350)
}
async function choose(label, name, search) {
  const input = dialog().getByRole('combobox', { name: label, exact: true })
  await dialog().locator('.quick-field').filter({ hasText: label }).locator('.el-select__wrapper').click()
  if (search) await input.fill(search)
  await page.locator('.el-select-dropdown:visible').getByText(name, { exact: true }).click()
  await ready()
}
async function capture(name) {
  const bounds = await dialog().evaluate(el => {
    const rect = node => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right } }
    const body = el.querySelector('.el-dialog__body')
    return { dialog: rect(el), footer: rect(el.querySelector('.el-dialog__footer')), header: rect(el.querySelector('.el-dialog__header')),
      width: el.clientWidth, scrollWidth: el.scrollWidth, bodyHeight: body.clientHeight, bodyScrollHeight: body.scrollHeight,
      documentWidth: document.documentElement.clientWidth, documentScrollWidth: document.documentElement.scrollWidth }
  })
  const size = page.viewportSize(); geometry.push({ name, size, ...bounds })
  assert.ok(bounds.dialog.top >= 0 && bounds.dialog.bottom <= size.height + 1, `${name}: dialog stays in viewport`)
  assert.ok(bounds.footer.bottom <= size.height && bounds.bodyHeight > 0, `${name}: footer remains visible`)
  assert.ok(bounds.scrollWidth <= bounds.width + 1 && bounds.documentScrollWidth <= bounds.documentWidth + 1, `${name}: no horizontal overflow`)
  assert.equal(/\b(?:referenceLibrary|visualBible)\.[a-zA-Z]+/.test(await dialog().innerText()), false, `${name}: translated UI`)
  for (const button of await dialog().locator('.quick-approve').all()) {
    const position = await button.evaluate(el => {
      const button = el.getBoundingClientRect(), media = el.closest('.quick-image-media').getBoundingClientRect()
      return { left: button.left - media.left, right: media.right - button.right, top: button.top - media.top, bottom: media.bottom - button.bottom }
    })
    assert.ok(Object.values(position).every(value => value >= -1), `${name}: confirmation button stays on its image`)
  }
  await page.screenshot({ path: path.join(artifacts, `${name}.png`) })
  return bounds
}
async function check(name, fn) { await fn(); checks.push(name); console.log(`PASS ${name}`) }

;(async () => {
  await Promise.all([freePort(18124), freePort(15274)])
  start(process.env.COMAIC_TEST_PYTHON || 'python', [path.join(root, 'frontend/tests/mock_workspace_api.py'), '--port', '18124'], 'backend')
  start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--config', path.join(__dirname, 'vite.config.mjs')], 'frontend')
  await Promise.all([waitFor(`${api}/api/projects`), waitFor(base)])
  const scenes = []
  for (let i = 0; i < 40; i++) {
    scenes.push(await request('/api/reference-images/projects/1/subjects', { entity_type: 'scene', name: `${String(i + 1).padStart(2, '0')} · ${i === 2 ? '超长场景名称用于测试搜索和窄屏展示'.repeat(4) : '验收场景'}`, description: '离线测试场景', negative_constraints: '' }))
  }
  const old = await createTask('scene', 51, 1), latest = await createTask('scene', 51)
  const version = await createTask('scene', 51, 2, 501)
  let longHistory
  for (const scene of scenes.slice(1)) {
    if (scene === scenes[2]) longHistory = await createTask('scene', scene.id, 1)
    const task = await createTask('scene', scene.id, scene === scenes[1] ? 1 : 4)
    if (scene === scenes[1]) await request(`/api/reference-images/images/${task.candidates[0].roles.scene_master.images[0].id}/approve`)
  }
  const characterTask = await createTask('character', 11, 4)
  await createTask('prop', 52, 2)
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Z1kAAAAASUVORK5CYII=', 'base64')
  const upload = new FormData()
  for (const [key, value] of Object.entries({ entity_type: 'scene', reference_subject_id: '51', role: 'scene_master', approve: 'false' })) upload.set(key, value)
  upload.set('file', new Blob([png], { type: 'image/png' }), 'quick-picker-fixture.png')
  const uploadResponse = await fetch(`${api}/api/visual-bible/projects/1/assets/upload`, { method: 'POST', body: upload })
  assert.ok(uploadResponse.ok); const draft = await uploadResponse.json()
  // 多张上传草稿让桌面也产生图片滚动，验证头部选择器与底部操作不随图片移动。
  upload.set('reference_subject_id', String(scenes[2].id))
  for (let i = 0; i < 8; i++) {
    const response = await fetch(`${api}/api/visual-bible/projects/1/assets/upload`, { method: 'POST', body: upload })
    assert.ok(response.ok)
  }

  context = await chromium.launchPersistentContext(path.join(artifacts, 'browser-profile'), {
    headless: true, viewport: { width: 1440, height: 1000 },
    ...(process.env.COMAIC_BROWSER_EXECUTABLE ? { executablePath: process.env.COMAIC_BROWSER_EXECUTABLE } : {}),
  })
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  page = await context.newPage(); page.setDefaultTimeout(8000)
  page.on('pageerror', error => errors.push(String(error)))
  await page.addInitScript(() => localStorage.setItem('comaic-locale', 'zh'))
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())
  await page.goto(`${base}/visual-bible?project_id=1&script_task_id=101&tab=references&reference_category=scene&reference_subject_id=51`)
  await page.getByRole('button', { name: '快速选图', exact: true }).click(); await ready()

  await check('默认最新候选和上传草稿，无默认选中，支持历史记录及场景版本隔离', async () => {
    assert.equal(await cards().count(), 5); assert.equal(await dialog().locator('.quick-image.is-selected').count(), 0)
    assert.equal(await dialog().locator('.quick-approve').count(), 5)
    assert.equal(await confirm(cards().first()).isEnabled(), true)
    assert.equal(await dialog().locator('.el-dialog__footer').getByRole('button', { name: '确认可用', exact: true }).count(), 0)
    assert.ok((await dialog().locator('.quick-field').filter({ hasText: '生成记录' }).innerText()).includes(`#${latest.id}`))
    await choose('生成记录', `#${old.id} · 模拟生图工具 · 已完成`)
    assert.equal(await cards().count(), 2)
    await choose('适用场景', '雾港维修店 · 画面设定 v1 · 待确认草稿')
    assert.equal(await cards().count(), 2)
    assert.ok((await dialog().locator('.quick-field').filter({ hasText: '生成记录' }).innerText()).includes(`#${version.id}`))
    await choose('适用场景', '此场景条目通用'); assert.equal(await cards().count(), 5)
  })
  await check('大图预览独立于选中，键盘选图，失败停留并允许成功后重试', async () => {
    await cards().first().getByRole('button', { name: /放大预览/ }).click()
    await page.locator('.el-image-viewer__wrapper:visible').waitFor()
    await page.screenshot({ path: path.join(artifacts, 'large-preview.png') })
    await page.locator('.el-image-viewer__close').click(); assert.equal(await dialog().locator('.quick-image.is-selected').count(), 0)
    await cards().first().focus(); await page.keyboard.press('Enter'); assert.equal(await confirm().isEnabled(), true)
    const imageId = latest.candidates[0].roles.scene_master.images[0].id
    await page.route(`**/api/reference-images/images/${imageId}/approve`, route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'reference.input.file_changed', message: 'Offline failure' } }) }))
    await confirm().click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('reference_subject_id'), '51')
    assert.equal(await dialog().locator('.quick-image.is-selected').count(), 1)
    await page.unroute(`**/api/reference-images/images/${imageId}/approve`)
    await confirm().click(); await page.waitForURL(url => url.searchParams.get('reference_subject_id') === String(scenes[0].id)); await ready()
    assert.equal(await cards().count(), 0); assert.equal(await dialog().locator('.quick-approve').count(), 0)
    await dialog().getByRole('button', { name: '下一个', exact: true }).click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('reference_subject_id'), String(scenes[1].id))
    assert.equal(await dialog().getByText('已确认', { exact: true }).count(), 2)
  })
  await check('40 个场景搜索、长名称、桌面与窄屏，图片独立滚动且操作始终可见', async () => {
    await choose('参考对象', `${scenes[2].name} · 已确认 0 张`, '超长')
    await page.waitForFunction(() => !document.querySelector('.el-message'))
    for (const size of [{ width: 1440, height: 1000 }, { width: 1280, height: 900 }, { width: 390, height: 844 }, { width: 390, height: 600 }, { width: 360, height: 640 }]) {
      await page.setViewportSize(size); await page.waitForTimeout(150)
      const before = await capture(`long-name-${size.width}-${size.height}`)
      await dialog().locator('.el-dialog__body').evaluate(el => { el.scrollTop = el.scrollHeight })
      const after = await capture(`scrolled-${size.width}-${size.height}`)
      assert.equal(before.header.top, after.header.top); assert.equal(before.footer.bottom, after.footer.bottom)
      assert.ok(after.bodyScrollHeight > after.bodyHeight, 'Image body scrolls within the dialog')
    }
    await choose('生成记录', `#${longHistory.id} · 模拟生图工具 · 已完成`)
    assert.equal(await dialog().locator('.el-dialog__body').evaluate(el => el.scrollTop), 0, 'Changing history resets gallery scroll')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await choose('参考对象', `${scenes.at(-1).name} · 已确认 0 张`, '40')
    await confirm(cards().first()).click(); await ready()
    await dialog().getByText('已到本类别最后一个对象', { exact: true }).waitFor()
    assert.equal(await dialog().getByRole('button', { name: '下一个', exact: true }).isDisabled(), true)
  })
  await check('人物确认后停留，其他视角与造型可见，物品末尾停留及关闭重开', async () => {
    await dialog().getByText('人物', { exact: true }).click(); await ready()
    assert.equal(await cards().count(), 16)
    assert.ok(await dialog().getByText('维修工作服', { exact: true }).count() > 0)
    await confirm(cards().first()).click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('character_id'), '11')
    assert.equal(await dialog().locator('.quick-image.is-selected').count(), 0)
    const firstFaceId = characterTask.candidates[0].roles.identity_face.images[0].id
    const secondFaceId = characterTask.candidates[1].roles.identity_face.images[0].id
    const faceCard = id => dialog().locator(`[data-image-key="image-${id}"]`)
    await confirm(faceCard(secondFaceId)).click(); await ready()
    assert.equal(await faceCard(firstFaceId).getByText('待确认草稿', { exact: true }).count(), 1)
    assert.equal(await confirm(faceCard(firstFaceId)).isEnabled(), true)
    assert.equal(await faceCard(secondFaceId).getByText('已确认', { exact: true }).count(), 1)
    const assetsBefore = await (await fetch(`${api}/api/visual-bible/projects/1/assets`)).json()
    await confirm(faceCard(firstFaceId)).click(); await ready()
    const assetsAfter = await (await fetch(`${api}/api/visual-bible/projects/1/assets`)).json()
    assert.equal(assetsBefore.length, assetsAfter.length, 'Reselecting a candidate reuses its saved original')
    assert.equal(assetsAfter.filter(asset => asset.entity_type === 'character' && asset.role === 'identity_face' && asset.status === 'approved').length, 1)
    assert.equal(await confirm(faceCard(secondFaceId)).isEnabled(), true)
    await dialog().getByText('物品', { exact: true }).click(); await ready()
    await confirm(cards().first()).click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('reference_subject_id'), '52')
    await dialog().getByText('已到本类别最后一个对象', { exact: true }).waitFor()
    await dialog().getByRole('button', { name: '关闭', exact: true }).click()
    await page.locator('.reference-quick-dialog').waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: '快速选图', exact: true }).click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('reference_category'), 'prop')
    assert.equal(await dialog().locator('.quick-image.is-selected').count(), 0)
  })
  await check('上传草稿确认同步主页面，刷新保持对象，英文窄屏翻译完整', async () => {
    await dialog().getByText('场景', { exact: true }).click(); await ready()
    await choose('参考对象', '雾港维修店 · 已确认 1 张', '雾港')
    await confirm(dialog().locator(`[data-image-key="asset-${draft.id}"]`)).click(); await ready()
    const expected = String(scenes[0].id)
    assert.equal(new URL(page.url()).searchParams.get('reference_subject_id'), expected)
    await dialog().getByRole('button', { name: '关闭', exact: true }).click()
    await page.reload(); await page.getByRole('button', { name: '快速选图', exact: true }).click(); await ready()
    assert.equal(new URL(page.url()).searchParams.get('reference_subject_id'), expected)
    await page.evaluate(() => localStorage.setItem('comaic-locale', 'en'))
    // 后续刷新保留英文设置，覆盖完整的新弹窗文案。
    await page.addInitScript(() => localStorage.setItem('comaic-locale', 'en'))
    await page.reload(); await page.getByRole('button', { name: 'Quick image selection', exact: true }).click(); await ready()
    await choose('Reference subject', `${scenes[2].name} · 0 confirmed`, '超长')
    await dialog().locator('.el-dialog__body').evaluate(el => { el.scrollTop = 0 })
    await page.setViewportSize({ width: 390, height: 844 }); await capture('english-mobile')
    await page.setViewportSize({ width: 360, height: 640 }); await capture('english-mobile-narrow')
  })
  assert.deepEqual(errors, [])
})().catch(error => { errors.push(error.stack || String(error)); process.exitCode = 1 }).finally(async () => {
  if (page && errors.length) await page.screenshot({ path: path.join(artifacts, 'failure.png') }).catch(() => {})
  if (context) { await context.tracing.stop({ path: path.join(artifacts, 'trace.zip') }).catch(() => {}); await context.close() }
  children.forEach(child => child.kill()); logs.forEach(log => log.end())
  fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify({ checks, errors, geometry }, null, 2))
  console.log(JSON.stringify({ artifacts, checks: checks.length, errors }, null, 2))
})

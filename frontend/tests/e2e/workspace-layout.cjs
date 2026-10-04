/** 离线浏览器验收：覆盖工作区、弹窗、悬浮说明及响应式布局，不使用真实数据库或 Provider。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const root = path.resolve(__dirname, '../../..')
const artifacts = path.join(root, '.codex-artifacts', `workspace-layout-${Date.now()}`)
fs.mkdirSync(artifacts, { recursive: true })
const base = 'http://127.0.0.1:15274', api = 'http://127.0.0.1:18124'
const query = 'project_id=1&script_task_id=101'
const children = [], logs = [], checks = [], errors = [], snapshots = []
let context, page
function start(command, args, name) {
  const log = fs.createWriteStream(path.join(artifacts, `${name}.log`)); logs.push(log)
  const child = spawn(command, args, { cwd: root, windowsHide: true, env: process.env })
  child.stdout.pipe(log); child.stderr.pipe(log); children.push(child)
}
async function waitFor(url) {
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(url)).ok) return } catch {}
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw Error(`Server did not start: ${url}`)
}
async function open(route) {
  await page.goto(`${base}${route}`)
  await page.waitForTimeout(300)
  await page.locator('.el-loading-mask:visible').waitFor({ state: 'hidden' }).catch(() => {})
}
async function capture(name, modal = false) {
  const size = page.viewportSize()
  const geometry = await page.evaluate(() => {
    const visible = selector => [...document.querySelectorAll(selector)].filter(el => el.getBoundingClientRect().width && el.getBoundingClientRect().height)
    const rect = el => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, bottom: r.bottom } }
    return { width: document.documentElement.clientWidth, scrollWidth: document.documentElement.scrollWidth,
      dialogs: visible('.el-dialog').map(el => ({ ...rect(el), scrollWidth: el.scrollWidth, width: el.clientWidth,
        footer: el.querySelector('.el-dialog__footer') ? rect(el.querySelector('.el-dialog__footer')) : null })) }
  })
  snapshots.push({ name, size, geometry })
  await page.screenshot({ path: path.join(artifacts, `${name}.png`) })
  assert.ok(geometry.scrollWidth <= geometry.width + 1, `${name}: document overflows (${geometry.scrollWidth} > ${geometry.width})`)
  if (modal) {
    assert.equal(geometry.dialogs.length, 1, `${name}: one visible dialog`)
    const dialog = geometry.dialogs[0]
    assert.ok(dialog.top >= 0 && dialog.bottom <= size.height + 1, `${name}: dialog outside viewport`)
    assert.ok(dialog.scrollWidth <= dialog.width + 1, `${name}: dialog overflows horizontally`)
    if (dialog.footer) assert.ok(dialog.footer.bottom <= size.height, `${name}: footer hidden`)
  }
  const missing = await page.locator('body').innerText()
  assert.equal(/\b(?:ux|settings|referenceLibrary|visualBible|outline|scripts|imageSpecs|imageGeneration|activityCenter|toolReference|referenceInputs|projects)\.[a-zA-Z]+/.test(missing), false, `${name}: untranslated UI key`)
}
async function widths(name, modal = false) {
  for (const width of [1440, 1280, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 })
    await page.waitForTimeout(150)
    await capture(`${name}-${width}`, modal)
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
}
async function closeDialog() {
  await page.locator('.el-dialog:visible .el-dialog__headerbtn').click()
  await page.locator('.el-dialog:visible').waitFor({ state: 'hidden' })
}
async function check(name, fn) {
  try { await fn(); checks.push(name); console.log(`PASS ${name}`) }
  catch (error) { errors.push(`${name}: ${error.stack || error}`); await page.screenshot({ path: path.join(artifacts, `failure-${checks.length}-${errors.length}.png`) }); console.log(`FAIL ${name}: ${error.message}`) }
}

;(async () => {
  start(process.env.COMAIC_TEST_PYTHON || 'python', [path.join(root, 'frontend/tests/mock_workspace_api.py'), '--port', '18124'], 'backend')
  start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--config', path.join(__dirname, 'vite.config.mjs')], 'frontend')
  await Promise.all([waitFor(`${api}/api/projects`), waitFor(base)])
  context = await chromium.launchPersistentContext(path.join(artifacts, 'browser-profile'), {
    headless: true, viewport: { width: 1440, height: 1000 },
    ...(process.env.COMAIC_BROWSER_EXECUTABLE ? { executablePath: process.env.COMAIC_BROWSER_EXECUTABLE } : {}),
  })
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  page = await context.newPage(); page.setDefaultTimeout(5000)
  page.on('pageerror', error => errors.push(String(error)))
  page.on('response', response => { if (response.status() >= 400) errors.push(`HTTP ${response.status()} ${response.url()}`) })
  await page.addInitScript(() => { if (!localStorage.getItem('comaic-locale')) localStorage.setItem('comaic-locale', 'zh') })
  // 禁止测试浏览器访问外站，所有生成描述来自内存 mock。
  await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort())

  await check('大纲与角色页；说明支持悬停、聚焦、点击', async () => {
    await open('/outline?project_id=1'); await widths('01-outline')
    const composer = await page.locator('.conversation-panel__composer').boundingBox()
    assert.ok(composer.y + composer.height <= 1000, 'Desktop composer must remain in the viewport')
    const tip = page.getByRole('button', { name: '当前大纲说明', exact: true })
    assert.equal(await page.locator('.info-tip-popper:visible').count(), 0)
    await tip.hover(); await page.locator('.info-tip-popper:visible').waitFor(); await capture('01-hover')
    await page.mouse.move(0, 0); await page.waitForTimeout(350)
    await tip.focus(); await page.locator('.info-tip-popper:visible').waitFor()
    await page.keyboard.press('Tab'); await page.waitForTimeout(350)
    await tip.click(); await page.locator('.info-tip-popper:visible').waitFor()
    await page.keyboard.press('Escape'); await page.getByRole('tab', { name: /角色基准设定/ }).click()
    await widths('01-characters')
  })
  await check('项目新建、修改和删除确认弹窗', async () => {
    await open('/outline?project_id=1')
    await page.locator('.top-bar__project .el-select__wrapper').click()
    await page.getByRole('button', { name: '新建项目', exact: true }).click()
    await widths('02-new-project', true); await closeDialog()
    await page.locator('.top-bar__project .el-select__wrapper').click()
    await page.locator('.project-option').first().getByRole('button', { name: '编辑', exact: true }).click()
    await widths('02-edit-project', true); await closeDialog()
    await page.locator('.top-bar__project .el-select__wrapper').click()
    await page.locator('.project-option').first().getByRole('button', { name: '删除', exact: true }).click()
    await page.getByRole('button', { name: '取消', exact: true }).click()
  })
  await check('脚本列表、分段设定、详情与编辑弹窗', async () => {
    await open(`/scripts?${query}`); await widths('03-scripts')
    await page.locator('.script-results__table').getByRole('button', { name: '查看', exact: true }).first().click()
    await widths('03-script-detail', true); await closeDialog()
    await page.locator('.script-results__table').getByRole('button', { name: '编辑', exact: true }).first().click()
    await widths('03-script-edit', true)
    const body = page.locator('.el-dialog:visible .el-dialog__body')
    assert.ok(await body.evaluate(el => el.scrollHeight > el.clientHeight), 'Long script editor must scroll within the dialog')
    await body.evaluate(el => { el.scrollTop = el.scrollHeight })
    await capture('03-script-edit-bottom', true); await closeDialog()
    await page.getByRole('tab', { name: /分段设定/ }).click(); await widths('03-section-settings')
  })
  await check('画面设定、版本详情、服装与场景弹窗', async () => {
    await open(`/visual-bible?${query}&tab=assignments`); await widths('04-assignments')
    await page.getByRole('button', { name: '完整详情', exact: true }).first().click(); await widths('04-setting-details')
    await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
    await page.getByRole('button', { name: '复制并修改', exact: true }).first().click()
    await widths('04-outfit', true); await closeDialog()
    await page.getByRole('tab', { name: '场景设定', exact: true }).click()
    await page.getByRole('button', { name: '复制并修改', exact: true }).first().click()
    await widths('04-scene', true); await closeDialog()
    await page.getByRole('tab', { name: /待确认设定/ }).click(); await widths('04-setting-library')
  })
  await check('参考素材分类、上传、单个生成、新建对象与批量步骤', async () => {
    await open(`/visual-bible?${query}&tab=references`); await widths('05-reference-library')
    await page.getByRole('button', { name: '上传', exact: true }).first().click(); await widths('05-upload', true); await closeDialog()
    await page.getByRole('button', { name: '生成图片', exact: true }).first().click(); await page.waitForTimeout(300)
    await widths('05-single-reference', true)
    await page.getByText('视觉摘要', { exact: true }).click(); await capture('05-visual-summary', true); await closeDialog()
    await page.getByText('场景', { exact: true }).first().click(); await widths('05-scene-library')
    await page.getByRole('button', { name: '新增场景', exact: true }).click(); await widths('05-new-subject', true); await closeDialog()
    await page.getByText('物品', { exact: true }).first().click(); await widths('05-prop-library')
    await page.getByRole('button', { name: '批量生成', exact: true }).click(); await widths('05-batch-select', true)
    const batch = page.locator('.reference-batch-dialog')
    await batch.getByRole('button', { name: '全选此类', exact: true }).first().click()
    await batch.getByRole('button', { name: '准备提示词', exact: true }).click()
    await batch.getByRole('button', { name: '提交整批生成', exact: true }).waitFor()
    await widths('05-batch-review', true)
    await batch.getByRole('button', { name: '提交整批生成', exact: true }).click()
    await batch.getByRole('button', { name: '关闭', exact: true }).waitFor()
    await widths('05-batch-images', true); await closeDialog()
  })
  await check('准备提示词、规则管理与提示词详情', async () => {
    await open(`/image-specs?${query}&tab=compile`)
    if (await page.getByRole('button', { name: '展开配置', exact: true }).isVisible()) await page.getByRole('button', { name: '展开配置', exact: true }).click()
    await widths('06-prepare')
    assert.equal(await page.getByRole('button', { name: '准备每页提示词', exact: true }).count(), 1)
    await page.getByRole('button', { name: '收起配置', exact: true }).click()
    assert.equal(await page.getByRole('button', { name: '展开配置', exact: true }).isVisible(), true)
    await page.getByRole('button', { name: '管理提示词规则', exact: true }).click()
    assert.equal(await page.locator('.el-dialog:visible').count(), 0, 'Manage opens the rules tab')
    await widths('06-rules')
    await page.getByRole('button', { name: '新增配置', exact: true }).click(); await widths('06-rule-editor', true); await closeDialog()
    await page.getByRole('tab', { name: /提示词结果/ }).click(); await widths('06-results')
    await page.getByRole('button', { name: '查看提示词', exact: true }).first().click(); await widths('06-prompt-detail')
  })
  await check('漫画出图、评测、候选图片、查看图片与保存参考图弹窗', async () => {
    // 内存素材使 mock 返回可展示的候选图，生产数据不受影响。
    const form = new FormData()
    form.append('file', new Blob([Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/Z1kAAAAASUVORK5CYII=', 'base64')], { type: 'image/png' }), 'layout.png')
    for (const [key, value] of Object.entries({ entity_type: 'character', entity_id: '11', role: 'identity_face', approve: 'true' })) form.append(key, value)
    const response = await fetch(`${api}/api/visual-bible/projects/1/assets/upload`, { method: 'POST', body: form })
    assert.ok(response.ok)
    const asset = await response.json()
    assert.ok((await fetch(`${api}/api/visual-bible/assets/${asset.id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'approved' }) })).ok)
    await open(`/image-generation?${query}&tab=generate`); await widths('07-generation')
    await page.getByRole('tab', { name: /一致性评测/ }).click(); await widths('07-evaluation')
    await page.getByRole('tab', { name: /^候选图片/ }).click(); await widths('07-candidates')
    await page.locator('.image-card').first().getByRole('button', { name: '查看', exact: true }).click(); await widths('07-image-detail', true); await closeDialog()
    await page.locator('.image-card').first().getByRole('button', { name: /更多/ }).click()
    await page.getByRole('menuitem', { name: '保存为参考图', exact: true }).click(); await widths('07-save-reference', true); await closeDialog()
    await page.locator('.image-card').first().getByRole('button', { name: /更多/ }).click()
    await page.getByRole('menuitem', { name: '生成溯源', exact: true }).click(); await widths('07-provenance')
  })
  await check('设置通用、模型 API 与两类生图工具弹窗', async () => {
    await open('/settings?tab=general'); await widths('08-settings')
    await page.getByText('高级评测参考值', { exact: true }).click(); await widths('08-evaluation-settings')
    await open('/settings?tab=api'); await widths('08-api-settings')
    await open('/settings?tab=image-tools'); await widths('08-image-tools')
    await page.getByRole('button', { name: '编辑', exact: true }).click(); await widths('08-api-tool', true); await closeDialog()
    await page.getByRole('button', { name: '新增生图工具', exact: true }).click(); await widths('08-comfy-tool', true)
    assert.equal(await page.getByText('请补全标记为必填的字段，并修正 JSON 格式后再保存。', { exact: true }).isVisible(), true)
    await closeDialog()
  })
  await check('空项目及任务中心；英文界面不溢出', async () => {
    await open('/outline?project_id=2'); await widths('09-empty-project')
    await page.getByRole('button', { name: '后台任务', exact: true }).click(); await widths('09-activity')
    await page.locator('.el-drawer:visible .el-drawer__close-btn').click()
    await page.evaluate(() => localStorage.setItem('comaic-locale', 'en'))
    // 页面初始化固定中文，以当前窗口的语言选择器切换后继续导航。
    await page.locator('.top-bar__locale .el-select__wrapper').click()
    await page.getByRole('option', { name: 'English', exact: true }).click()
    for (const route of [`/scripts?${query}`, `/visual-bible?${query}&tab=references`, `/image-specs?${query}`, `/image-generation?${query}`, '/settings?tab=api']) {
      await page.goto(`${base}${route}`); await page.waitForTimeout(300)
      await page.locator('.top-bar__locale .el-select__wrapper').click()
      await page.getByRole('option', { name: 'English', exact: true }).click()
      await widths(`10-en-${route.split('?')[0].slice(1)}`)
    }
  })
  assert.deepEqual(errors, [])
})().catch(error => { errors.push(String(error.stack || error)); process.exitCode = 1 }).finally(async () => {
  try { await context?.tracing.stop({ path: path.join(artifacts, 'trace.zip') }) } catch {}
  await context?.close()
  children.forEach(child => child.kill()); logs.forEach(log => log.end())
  fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify({ artifacts, checks, errors, snapshots }, null, 2))
  console.log(JSON.stringify({ artifacts, checks: checks.length, errors }, null, 2))
})

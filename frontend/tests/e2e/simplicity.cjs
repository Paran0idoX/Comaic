/** 真实浏览器、真实 API/SQLite 的工作台验收；仅替换收费模型/Provider。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const root = path.resolve(__dirname, '../../..')
const artifacts = path.join(root, '.codex-artifacts', `simplicity-e2e-${Date.now()}`)
fs.mkdirSync(artifacts, { recursive: true })
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const backend = 'http://127.0.0.1:18124'
const frontend = 'http://127.0.0.1:15274'
const children = [], logs = [], errors = [], requests = [], checks = []
let browser, context, page
function start(command, args, name) {
  const log = fs.createWriteStream(path.join(artifacts, `${name}.log`)); logs.push(log)
  const child = spawn(command, args, { cwd: root, env: process.env, windowsHide: true })
  child.stdout.pipe(log); child.stderr.pipe(log); children.push(child)
  return child
}
async function waitFor(url) {
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(url)).ok) return } catch {}
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw Error(`Server did not start: ${url}`)
}
async function state() { return (await fetch(`${backend}/__e2e/state`)).json() }
async function control(data) {
  const response = await fetch(`${backend}/__e2e/control`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
  assert.equal(response.status, 200)
}
async function waitState(predicate) {
  for (let i = 0; i < 100; i++) { const value = await state(); if (predicate(value)) return value; await page.waitForTimeout(100) }
  throw Error('Database did not reach expected state')
}
async function open(route) { await page.goto(`${frontend}${route}`); await page.waitForTimeout(350) }
async function screenshot(name) { await page.screenshot({ path: path.join(artifacts, `${name}.png`), fullPage: true }) }
async function selectPage(number) {
  const checkbox = page.getByRole('checkbox', { name: `选择第 ${number} 页`, exact: true })
  for (let i = 0; i < 100 && !(await checkbox.isEnabled()); i++) await page.waitForTimeout(100)
  assert.equal(await checkbox.isEnabled(), true)
  await checkbox.locator('xpath=ancestor::label').click()
}
async function check(name, fn) { await fn(); checks.push(name); console.log(`PASS ${name}`) }

async function prepare(query, { language: value } = {}) {
  await open(`/image-specs?${query}&tab=compile`)
  const language = page.getByRole('combobox', { name: '最终提示词语言', exact: true })
  if (!(await language.isVisible())) await page.getByRole('button', { name: '展开配置', exact: true }).click()
  if (value) {
    await language.locator('xpath=ancestor::div[contains(@class, "el-select__wrapper")]').click()
    await page.getByRole('option', { name: value, exact: true }).click()
    await page.getByRole('option', { name: value, exact: true }).waitFor({ state: 'hidden' })
  }
  assert.equal(await page.getByText('严格', { exact: true }).count(), 0)
  assert.equal(await page.getByText('宽松', { exact: true }).count(), 0)
  const before = await state()
  await page.getByRole('button', { name: '准备每页提示词', exact: true }).first().click()
  const result = await waitState(s => s.compilations.length > before.compilations.length && ['succeeded', 'failed'].includes(s.compilations.at(-1)?.status))
  assert.equal(result.compilations.at(-1).status, 'succeeded')
  await page.waitForTimeout(250)
  return result
}

;(async () => {
  start(process.env.COMAIC_TEST_PYTHON || 'python', [path.join(root, 'backend/tests/e2e_simplicity_server.py'), '--artifacts', artifacts], 'backend')
  start(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--config', path.join(__dirname, 'vite.config.mjs')], 'frontend')
  await Promise.all([waitFor(`${backend}/health`), waitFor(frontend)])
  const fixture = await state()
  const query = `project_id=${fixture.project_id}&script_task_id=${fixture.task_id}`
  context = await chromium.launchPersistentContext(path.join(artifacts, 'browser-profile'), {
    headless: true, viewport: { width: 1440, height: 1000 },
    ...(process.env.COMAIC_BROWSER_EXECUTABLE ? { executablePath: process.env.COMAIC_BROWSER_EXECUTABLE } : {}),
  })
  browser = context.browser()
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  page = await context.newPage()
  page.setDefaultTimeout(15000)
  page.on('pageerror', error => errors.push(String(error)))
  page.on('response', response => { if (response.status() >= 400) errors.push(`HTTP ${response.status()} ${response.url()}`) })
  page.on('request', request => { if (request.method() === 'POST' && request.url().includes('/api/')) requests.push({ url: request.url(), data: request.postDataJSON() }) })
  await page.addInitScript(() => { localStorage.setItem('comaic-locale', 'zh') })

  await check('长短角色卡片顶部对齐、字段紧凑，窄屏可滚动', async () => {
    // 仅替换此页展示数据，使用明显不同的文本长度复现网格拉伸。
    const pattern = '**/api/outline/sessions/resolve'
    await page.route(pattern, async route => {
      const response = await route.fetch()
      const data = await response.json()
      const base = data.outline_versions[0].characters[0]
      data.outline_versions[0].characters = [
        { ...base, name: '短设定角色', role: '故事主角', background: '普通学生。' },
        { ...base, id: base.id + 1000, character_key: 'long-character', name: '长设定角色', role: '学校教导主任，负责纪律与日常管理。'.repeat(10), background: '长期承担学校管理职责，经历丰富，做事认真。'.repeat(30) },
      ]
      await route.fulfill({ response, json: data })
    })
    await page.setViewportSize({ width: 1920, height: 1000 })
    await open(`/outline?project_id=${fixture.project_id}`)
    await page.getByRole('tab', { name: /角色基准设定/ }).click()
    const cards = page.locator('.outline-panel__character')
    await cards.first().waitFor()
    const dimensions = await cards.evaluateAll(elements => elements.map(element => {
      const header = element.querySelector('header').getBoundingClientRect()
      const fields = [...element.querySelectorAll('p')].map(p => p.getBoundingClientRect())
      return { top: header.top, height: element.getBoundingClientRect().height, gaps: fields.map((field, i) => field.top - (i ? fields[i - 1].bottom : header.bottom)) }
    }))
    assert.equal(dimensions.length, 2)
    assert.ok(Math.abs(dimensions[0].top - dimensions[1].top) < 1)
    assert.ok(dimensions[0].height < dimensions[1].height)
    assert.ok(dimensions.every(card => card.gaps.every(gap => gap >= 7 && gap <= 9)))
    await screenshot('00-outline-desktop')
    await page.setViewportSize({ width: 390, height: 844 })
    assert.ok(await cards.evaluateAll(elements => elements.every(element => element.scrollWidth <= element.clientWidth)))
    const scroll = page.locator('.outline-panel__tab-scroll .el-scrollbar__wrap').filter({ visible: true })
    await scroll.evaluate(element => { element.scrollTop = element.scrollHeight })
    assert.ok(await scroll.evaluate(element => element.scrollTop > 0))
    await screenshot('00-outline-mobile')
    await page.setViewportSize({ width: 1440, height: 1000 })
    await page.unroute(pattern)
  })

  await check('脚本完成后进入生图准备', async () => {
    await open(`/scripts?${query}`)
    await page.getByRole('button', { name: '准备每页提示词', exact: true }).click()
    await page.waitForURL(/image-specs/)
  })
  await check('设置统一编辑工具，漫画出图和批量参考图只选择已有工具', async () => {
    const toolsUrl = `${backend}/api/image-generation/tools`
    const original = (await (await fetch(toolsUrl)).json()).items.find(item => item.id === fixture.tool_id)
    await open('/settings?tab=image-tools')
    assert.equal(await page.getByRole('button', { name: '新增生图工具', exact: true }).isVisible(), true)
    assert.equal(await page.locator('.settings-content .config-form').count(), 0)
    await page.locator('.workflow-item').filter({ hasText: original.name }).getByRole('button', { name: '编辑', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '生图工具配置', exact: true })
    const name = 'E2E shared image tool'
    await dialog.getByRole('textbox', { name: '名称', exact: true }).fill(name)
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    const saved = (await (await fetch(toolsUrl)).json()).items.find(item => item.id === fixture.tool_id)
    assert.equal(saved.name, name)
    assert.deepEqual(JSON.parse(saved.workflow_json), JSON.parse(original.workflow_json))
    assert.deepEqual(saved.bindings, original.bindings)
    assert.deepEqual(saved.capabilities, original.capabilities)
    const toolPanel = await page.locator('.workflow-panel').boundingBox()
    const toolRow = await page.locator('.workflow-item').first().boundingBox()
    assert.ok(toolRow.x - toolPanel.x >= 19)
    await screenshot('08-tools-settings')
    await open(`/image-generation?${query}&tab=generate`)
    assert.equal(await page.getByRole('button', { name: '新增生图工具', exact: true }).count(), 0)
    assert.equal(await page.getByRole('tab', { name: '生图工具', exact: true }).count(), 0)
    assert.equal(await page.getByText('严格', { exact: true }).count(), 0)
    await open(`/visual-bible?${query}&tab=references`)
    assert.equal(await page.getByRole('link', { name: '管理工具', exact: true }).getAttribute('href'), '/settings?tab=image-tools')
    await page.getByRole('button', { name: '批量生成', exact: true }).click()
    const batchDialog = page.getByRole('dialog', { name: '批量生成', exact: true })
    const toolSelect = batchDialog.locator('.el-form-item').filter({ hasText: '生图工具' }).locator('.el-select__wrapper')
    await toolSelect.click()
    await page.getByRole('option', { name, exact: true }).waitFor({ state: 'visible' })
    await page.getByRole('option', { name, exact: true }).click()
    assert.equal(await batchDialog.getByRole('button', { name: '新增生图工具', exact: true }).count(), 0)
    assert.equal(await batchDialog.getByRole('button', { name: '准备提示词', exact: true }).isVisible(), true)
    await screenshot('09-reference-batch-selector')
    await batchDialog.getByRole('button', { name: '取消', exact: true }).click()
  })
  await check('未准备时禁止出图，显式准备后仅生成缺图页', async () => {
    await open(`/image-generation?${query}&tab=generate`)
    assert.equal(await page.getByRole('button', { name: '生成漫画', exact: true }).isEnabled(), false)
    assert.equal((await state()).specs.length, 0)
    await prepare(query)
    assert.equal((await state()).specs.length, 6)
    assert.equal((await state()).queued.length, 0)
    await open(`/image-generation?${query}&tab=generate`)
    const before = await state()
    await page.getByRole('button', { name: '生成漫画', exact: true }).click()
    const result = await waitState(s => s.pages[1].images.length === 1 && s.batches.at(-1)?.status === 'succeeded')
    assert.deepEqual(requests.at(-1).data.page_ids, [fixture.page_ids[1]])
    assert.deepEqual(result.planned, before.planned)
    assert.equal(result.specs.length, before.specs.length)
    assert.equal(result.pages[0].selected_image_id, fixture.old_image_id)
    await page.getByRole('tab', { name: /^候选图片/ }).click()
    await screenshot('01-explicit-prepare')
  })
  await check('勾选重画只追加所选页，复用未变准备并保留终稿', async () => {
    await selectPage(2)
    const before = await state()
    await page.getByRole('button', { name: '生成所选 1 页', exact: true }).click()
    const after = await waitState(s => s.pages[1].images.length === 2 && s.batches.at(-1)?.status === 'succeeded')
    assert.equal(after.specs.length, before.specs.length)
    assert.deepEqual(after.planned, before.planned)
    assert.equal(after.pages[0].images.length, 1)
    assert.equal(after.pages[0].selected_image_id, fixture.old_image_id)
    await screenshot('02-selected-redraw')
  })
  await check('过期提示词零提交，返回准备后再显式生成', async () => {
    await control({ stale_page_no: 1 })
    await open(`/image-generation?${query}&tab=results`)
    const before = await state()
    assert.equal(await page.locator('.page-result').first().getByRole('button', { name: '生成本页', exact: true }).isEnabled(), false)
    assert.equal((await state()).queued.length, before.queued.length)
    assert.equal((await state()).specs.length, before.specs.length)
    await screenshot('03-stale-prompt')
    await prepare(query)
    await open(`/image-generation?${query}&tab=results`)
    await page.locator('.page-result').first().getByRole('button', { name: '生成本页', exact: true }).click()
    const after = await waitState(s => s.pages[0].images.length === 2 && s.batches.at(-1)?.status === 'succeeded')
    assert.equal(after.pages[1].images.length, before.pages[1].images.length)
    assert.equal(after.pages[0].selected_image_id, fixture.old_image_id)
  })
  await check('语言仅在生图准备中选择，漫画出图使用已有译文', async () => {
    await prepare(query, { language: '中文' })
    await screenshot('07-prompt-language')
    await open(`/image-generation?${query}&tab=results`)
    assert.equal(await page.getByRole('combobox', { name: '最终提示词语言', exact: true }).count(), 0)
    const before = await state()
    await page.locator('.page-result').nth(1).getByRole('button', { name: '生成本页', exact: true }).click()
    const after = await waitState(s => s.pages[1].images.length === before.pages[1].images.length + 1 && s.batches.at(-1)?.status === 'succeeded')
    assert.equal(requests.at(-1).data.prompt_language, undefined)
    assert.deepEqual(after.planned, before.planned)
    assert.equal(after.specs.length, before.specs.length)
    const frozen = after.batches.at(-1).snapshot.pages[String(fixture.page_ids[1])].spec
    assert.equal(frozen.prompt_language, 'zh')
    assert.ok(frozen.prompt.positive.includes('角色的琥珀色眼睛'))
    assert.ok(frozen.prompt.positive.includes('结合以下'))
    assert.ok(frozen.prompt.negative.includes('避免'))
  })
  await check('编辑造型保存并应用，一次批准并绑定', async () => {
    await open(`/visual-bible?${query}&tab=assignments`)
    await page.getByRole('button', { name: '复制并修改', exact: true }).first().click()
    const dialog = page.getByRole('dialog', { name: '复制并修改', exact: true })
    await dialog.locator('.el-form-item').filter({ hasText: '名称' }).locator('input').fill('E2E green outfit')
    await dialog.getByRole('button', { name: '保存并应用', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    const outfits = await (await fetch(`${backend}/api/visual-bible/projects/${fixture.project_id}/outfits`)).json()
    assert.equal(outfits[0].name, 'E2E green outfit')
    assert.equal(outfits[0].status, 'approved')
    const characters = (await (await fetch(`${backend}/api/scripts/tasks/${fixture.task_id}/characters`)).json()).items
    assert.equal(characters[0].outfit_variant_id, outfits[0].id)
    await screenshot('04-outfit-applied')
  })
  await check('场景保存并应用与仅存草稿使用不同路径', async () => {
    await page.getByRole('tab', { name: '场景设定', exact: true }).click()
    await page.getByRole('button', { name: '复制并修改', exact: true }).first().click()
    let dialog = page.getByRole('dialog', { name: '复制并修改', exact: true })
    await dialog.getByRole('button', { name: '保存并应用', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    const url = `${backend}/api/visual-bible/projects/${fixture.project_id}/scene-versions`
    const approved = (await (await fetch(url)).json())[0]
    assert.equal(approved.status, 'approved')
    await page.getByRole('button', { name: '复制并修改', exact: true }).first().click()
    dialog = page.getByRole('dialog', { name: '复制并修改', exact: true })
    await dialog.getByRole('button', { name: '保存草稿', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    const scenes = (await (await fetch(`${backend}/api/scripts/tasks/${fixture.task_id}/scenes`)).json()).items
    assert.equal(scenes[0].selected_visual_version_id, approved.id)
    assert.equal((await (await fetch(url)).json())[0].status, 'draft')
  })
  await check('无模式选择，旧冻结批次续跑保持原工具、Prompt 和 seed', async () => {
    await prepare(query)
    await open(`/image-generation?${query}&tab=results`)
    await selectPage(1)
    await selectPage(2)
    await control({ pause_next: true })
    await page.getByRole('button', { name: '生成所选 2 页', exact: true }).click()
    const paused = await waitState(s => s.batches.at(-1)?.status === 'suspended' && s.pages[0].images.length === 3)
    assert.equal(requests.at(-1).data.generation_mode, undefined)
    await control({ legacy_frozen_mode: true })
    const batch = (await state()).batches.at(-1), snapshot = JSON.stringify(batch.snapshot)
    assert.equal(batch.mode, 'final')
    assert.equal(batch.snapshot.pages[String(fixture.page_ids[1])].spec.prompt_language, 'zh')
    await prepare(query, { language: '英文' })
    await control({ change_tool: true, stale_page_no: 2, corrupt_original: true })
    await open(`/image-generation?${query}&batch_id=${batch.id}`)
    await page.getByRole('button', { name: '继续生成', exact: true }).click()
    await page.getByText(/图片原文件已改变/, { exact: false }).first().waitFor({ state: 'visible' })
    assert.equal((await state()).queued.length, paused.queued.length)
    checks.push('冻结原图变动在提交前失败')
    await screenshot('05-original-sha-rejected')
    await control({ restore_original: true })
    await page.getByRole('button', { name: '继续生成', exact: true }).click()
    const resumed = await waitState(s => s.batches.at(-1)?.status === 'succeeded')
    assert.equal(requests.at(-1).data.generation_mode, undefined)
    assert.equal(resumed.batches.at(-1).mode, 'final')
    assert.equal(JSON.stringify(resumed.batches.at(-1).snapshot), snapshot)
    assert.deepEqual(resumed.planned, paused.planned)
    const secondPage = batch.snapshot.pages[String(fixture.page_ids[1])]
    const lastWorkflow = resumed.queued.at(-1)
    assert.equal(lastWorkflow['2'].inputs.seed, secondPage.seeds[0][1])
    assert.equal(lastWorkflow['1'].inputs.text, secondPage.spec.prompt.positive)
    await screenshot('06-frozen-resumed')
  })
  await check('一致性评测低于参考值仍可采用整套，逐页选图独立于评测', async () => {
    const fullBatch = (await state()).batches.at(-1)
    await open(`/image-generation?${query}&batch_id=${fullBatch.id}&tab=consistency`)
    const evaluate = page.getByRole('button', { name: '开始一致性评测', exact: true })
    await evaluate.waitFor({ state: 'visible' })
    for (let i = 0; i < 50 && !(await evaluate.isEnabled()); i++) await page.waitForTimeout(100)
    assert.equal(await evaluate.isEnabled(), true)
    await evaluate.click()
    const evaluated = await waitState(s => s.evaluations.at(-1)?.status === 'succeeded')
    const track = evaluated.evaluations.at(-1).tracks[0]
    assert.equal(track.status, 'failed')
    await page.getByText('未达参考值', { exact: true }).waitFor({ state: 'visible' })
    const adopt = page.getByRole('button', { name: '采用这套候选', exact: true })
    assert.equal(await adopt.isEnabled(), true)
    await adopt.click()
    const adopted = await waitState(s => s.evaluations.at(-1).tracks[0].adopted)
    for (const value of adopted.pages) assert.equal(value.selected_image_id, track.image_ids[String(value.id)])
    await screenshot('10-advisory-evaluation')
    await open(`/image-generation?${query}&tab=results`)
    await page.locator('.page-result').first().locator('.image-card').filter({ hasText: '设为终稿' }).first().getByRole('button', { name: '设为终稿', exact: true }).click()
    const selected = await waitState(s => s.pages[0].selected_image_id !== track.image_ids[String(fixture.page_ids[0])])
    assert.equal(selected.evaluations.length, evaluated.evaluations.length)
    const completion = await (await fetch(`${backend}/api/consistency-evaluations/script-tasks/${fixture.task_id}/gate`)).json()
    assert.equal(completion.passed, true)
    assert.equal(completion.evaluation_required, false)
  })
  await check('缺参考图提示但可以生成，工具配置错误保持零上传零提交', async () => {
    await control({ restore_tool: true, missing_references: true })
    await prepare(query, { language: '保持原文' })
    await open(`/image-generation?${query}&tab=results`)
    const before = await state()
    const generate = page.locator('.page-result').nth(1).getByRole('button', { name: '生成本页', exact: true })
    assert.equal(await generate.isEnabled(), true)
    await generate.click()
    const after = await waitState(s => s.queued.length === before.queued.length + 1 && s.batches.at(-1).status === 'succeeded')
    const spec = after.batches.at(-1).snapshot.pages[String(fixture.page_ids[1])].spec
    assert.equal(spec.reference_inputs.items.length, 0)
    assert.ok(spec.reference_plan.warnings.length > 0)
    assert.ok(spec.prompt.positive.includes('amber eyes'))
    assert.equal(after.upload_count, before.upload_count)
    assert.deepEqual(after.planned, before.planned)
    await control({ change_tool: true })
    await open(`/image-generation?${query}&tab=results`)
    const rejectedResponse = page.waitForResponse(response => response.url().includes('/pages/2/generate/stream'))
    await page.locator('.page-result').nth(1).getByRole('button', { name: '生成本页', exact: true }).click()
    const responseText = await (await rejectedResponse).text()
    assert.match(responseText, /"code":\s*"(?:workflow\.binding_invalid|image_generation\.workflow_input_not_found|reference\.input\.configuration_invalid)"/)
    await page.getByText(/(?:Workflow|工作流).*(?:绑定|输入不存在)/, { exact: false }).first().waitFor({ state: 'visible' })
    const rejected = await state()
    assert.equal(rejected.queued.length, after.queued.length)
    assert.equal(rejected.upload_count, after.upload_count)
    assert.equal(rejected.batches.length, after.batches.length)
    await screenshot('11-optional-references')
  })
  assert.deepEqual(errors, [], 'Browser must have no uncaught errors')
})().catch(async error => {
  errors.push(error.stack || String(error)); console.error(error)
  if (page) await screenshot('failure').catch(() => {})
  process.exitCode = 1
}).finally(async () => {
  await state().then(value => fs.writeFileSync(path.join(artifacts, 'final-state.json'), JSON.stringify(value, null, 2))).catch(() => {})
  if (context) await context.tracing.stop({ path: path.join(artifacts, 'trace.zip') }).catch(() => {})
  if (context) await context.close()
  if (browser?.isConnected()) await browser.close()
  for (const child of children) child.kill()
  for (const log of logs) log.end()
  fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify({ checks, errors, requests }, null, 2))
  console.log(`Artifacts: ${artifacts}`)
})

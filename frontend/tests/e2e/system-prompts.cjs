/** 设置提示词树的离线浏览器回归；实际数据库与模型注入另由后端测试覆盖。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const root = path.resolve(__dirname, '../../..')
const build = path.resolve(root, process.env.COMAIC_TEST_FRONTEND_BUILD || 'frontend/dist')
const artifacts = path.join(root, '.codex-artifacts', `system-prompts-${Date.now()}`)
fs.mkdirSync(artifacts, { recursive: true })
const prompt = (key, content) => ({ key, content, default_content: content, is_overridden: false, default_files: [`${key}.md`] })
const tasks = ['outline_conversation', 'outline_update', 'outline_character', 'outline_snapshot',
  'script_planning', 'script_writer', 'script_supervisor', 'shot_planner', 'shot_language'].map(key => prompt(key, `DEFAULT ${key}`))
const models = [prompt('same/model', 'DEFAULT GLOBAL'), prompt('other-model', '')]
const config = { id: 1, name: 'Local API', provider: 'deepseek', base_url: '', model_names: models.map(item => item.key),
  default_model: 'same/model', api_key: null, api_key_set: false, is_active: true, updated_at: '2026-10-04T00:00:00Z' }
const errors = []
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname
  const file = pathname.startsWith('/assets/') ? path.join(build, 'assets', path.basename(pathname)) : path.join(build, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html')
  fs.createReadStream(file).on('error', () => { res.statusCode = 404; res.end() }).pipe(res)
})
let context
;(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  context = await chromium.launchPersistentContext(path.join(artifacts, 'profile'), {
    headless: true, viewport: { width: 1440, height: 1000 },
    ...(process.env.COMAIC_BROWSER_EXECUTABLE ? { executablePath: process.env.COMAIC_BROWSER_EXECUTABLE } : {}),
  })
  await context.addInitScript(() => { if (!localStorage.getItem('comaic-locale')) localStorage.setItem('comaic-locale', 'zh') })
  const page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    const send = data => route.fulfill({ contentType: 'application/json', body: JSON.stringify(data) })
    if (pathname === '/api/settings/llm') return send({ items: [config], active_config_id: 1 })
    if (pathname === '/api/settings/llm/providers') return send([])
    if (pathname === '/api/settings/app') return send({ script_section_max_concurrency: 3 })
    if (pathname === '/api/settings/system-prompts' && request.method() === 'GET') return send(tasks)
    if (pathname === '/api/settings/llm/configs/1/system-prompts') {
      if (request.method() === 'GET') return send(models)
      const body = request.postDataJSON(), item = models.find(item => item.key === body.model)
      item.content = body.content === null ? item.default_content : body.content
      item.is_overridden = body.content !== null
      return send(item)
    }
    if (pathname.startsWith('/api/settings/system-prompts/') && request.method() === 'PUT') {
      const item = tasks.find(item => item.key === pathname.split('/').pop()), body = request.postDataJSON()
      item.content = body.content === null ? item.default_content : body.content
      item.is_overridden = body.content !== null
      return send(item)
    }
    if (pathname === '/api/projects') return send({ items: [] })
    return send({})
  })
  await page.goto(`http://127.0.0.1:${server.address().port}/settings?tab=prompts`)
  const panel = page.locator('.prompt-manager')
  const nav = panel.locator('.prompt-manager__navigator')
  const select = async label => { await nav.getByText(label, { exact: true }).click() }
  await panel.getByRole('button', { name: '全部展开', exact: true }).click()
  await select('分页脚本编写')
  const writer = panel.getByRole('textbox', { name: '分页脚本编写', exact: true })
  await writer.fill('CUSTOM WRITER')
  await select('Shot 规划')
  assert.equal(await panel.locator('textarea').count(), 1)
  await select('分页脚本编写')
  assert.equal(await writer.inputValue(), 'CUSTOM WRITER', 'Changing selection preserves draft')
  const editor = panel.locator('.prompt-editor')
  await editor.getByRole('button', { name: '保存提示词', exact: true }).click()
  await assertEventually(() => tasks.find(item => item.key === 'script_writer').content === 'CUSTOM WRITER')
  assert.equal(tasks.find(item => item.key === 'script_planning').content, 'DEFAULT script_planning')
  await editor.getByRole('tab', { name: '查看默认提示词', exact: true }).click()
  assert.equal(await editor.locator('pre').innerText(), 'DEFAULT script_writer')
  await editor.getByRole('button', { name: '恢复默认', exact: true }).click()
  await assertEventually(() => tasks.find(item => item.key === 'script_writer').content === 'DEFAULT script_writer')
  await editor.getByRole('tab', { name: '编辑提示词', exact: true }).click()
  await select('same/model')
  const global = panel.getByRole('textbox', { name: 'same/model', exact: true })
  await global.fill('GLOBAL TEXT')
  await editor.getByRole('button', { name: '保存提示词', exact: true }).click()
  await assertEventually(() => models[0].content === 'GLOBAL TEXT')
  await global.fill('')
  await editor.getByRole('button', { name: '保存提示词', exact: true }).click()
  await assertEventually(() => models[0].content === '')
  await editor.getByRole('button', { name: '恢复默认', exact: true }).click()
  await assertEventually(() => models[0].content === 'DEFAULT GLOBAL')
  await panel.getByRole('button', { name: '全部折叠', exact: true }).click()
  await nav.getByText('分页脚本编写', { exact: true }).waitFor({ state: 'hidden' })
  assert.equal(await global.isVisible(), true, 'Collapsing the directory keeps editor open')
  await panel.getByRole('button', { name: '全部展开', exact: true }).click()
  const search = nav.getByRole('textbox', { name: '搜索提示词' })
  await search.fill('审查')
  await nav.getByText('分页脚本编写', { exact: true }).waitFor({ state: 'hidden' })
  await select('脚本监督审查')
  await search.fill('')
  await nav.getByText('大纲生成', { exact: true }).waitFor({ state: 'visible' })
  await nav.getByText('same/model', { exact: true }).waitFor({ state: 'visible' })
  await select('分页脚本编写')
  await writer.fill('CUSTOM WRITER DRAFT')
  await page.mouse.move(1250, 40)
  await page.getByRole('tooltip').first().waitFor({ state: 'hidden' })
  await page.locator('.el-message').evaluateAll(nodes => nodes.forEach(node => node.remove()))
  await page.screenshot({ path: path.join(artifacts, 'desktop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1280, height: 850 })
  await page.screenshot({ path: path.join(artifacts, 'laptop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(artifacts, 'mobile.png'), animations: 'disabled' })
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
  assert.ok(widths[0] <= widths[1] + 1, `Page overflows: ${widths}`)
  await page.evaluate(() => localStorage.setItem('comaic-locale', 'en'))
  await page.reload()
  await panel.getByRole('button', { name: 'Expand All', exact: true }).click()
  await select('Page Script Writing')
  await panel.getByRole('textbox', { name: 'Page Script Writing', exact: true }).waitFor({ state: 'visible' })
  await page.screenshot({ path: path.join(artifacts, 'mobile-en.png'), animations: 'disabled' })
  const enWidths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth])
  assert.ok(enWidths[0] <= enWidths[1] + 1, `English page overflows: ${enWidths}`)
  assert.equal((await panel.innerText()).includes('systemPrompts.'), false)
  assert.deepEqual(errors, [])
  console.log('PASS compact tree, one editor, preserved drafts, search, save/reset/default preview, empty global prompt and responsive layout')
  fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify({ errors, widths }, null, 2))
})().catch(error => { console.error(error); process.exitCode = 1 }).finally(async () => {
  await context?.close()
  await new Promise(resolve => server.close(resolve))
})

async function assertEventually(check) {
  for (let count = 0; count < 50; count++) {
    if (check()) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  assert.ok(check())
}

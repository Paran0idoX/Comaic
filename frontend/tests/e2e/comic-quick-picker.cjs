/** 漫画快速选图离线验收：真实前端配内存 API，候选与终稿不写入业务数据库。 */
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const root = path.resolve(__dirname, '../../..')
const build = path.resolve(root, process.env.COMAIC_TEST_FRONTEND_BUILD || '.codex-artifacts/comic-quick-frontend-build')
const artifacts = path.join(root, '.codex-artifacts', `comic-quick-picker-${Date.now()}`)
fs.mkdirSync(artifacts, { recursive: true })
const checks = [], geometry = [], errors = [], selections = []
const stamp = { created_at: '2026-10-04T01:00:00Z', updated_at: '2026-10-04T01:00:00Z' }
const pages = [16, 0, 2, 1].map((count, index) => ({
  page_id: 100 + index, page_no: index + 1, status: 'spec_ready', selected_image_id: null,
  latest_spec_id: index + 1, positive_prompt: '离线候选画面', prompt_type: 'natural_language', spec_warnings: [], completed_candidates: count,
  images: Array.from({ length: count }, (_, imageIndex) => ({ id: 1000 + index * 100 + imageIndex,
    page_id: 100 + index, image_url: `/api/fixtures/${index}-${imageIndex}.svg`,
    is_selected: false, generation_run_id: null, seed: imageIndex, ...stamp })),
}))
let context, page, failNext = false
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname
  const file = pathname.startsWith('/assets/') ? path.join(build, path.basename('assets'), path.basename(pathname)) : path.join(build, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.svg') ? 'image/svg+xml' : 'text/html')
  fs.createReadStream(file).on('error', () => { res.statusCode = 404; res.end() }).pipe(res)
})
const dialog = () => page.locator('.comic-quick-dialog:visible')
const card = id => dialog().locator(`[data-image-id="${id}"]`)
const confirm = id => card(id).getByRole('button', { name: '设为终稿', exact: true })
async function check(name, fn) { await fn(); checks.push(name); console.log(`PASS ${name}`) }
async function capture(name) {
  const bounds = await dialog().evaluate(el => {
    const rect = node => { const r = node.getBoundingClientRect(); return { top: r.top, bottom: r.bottom } }
    const body = el.querySelector('.el-dialog__body')
    return { ...rect(el), footer: rect(el.querySelector('.el-dialog__footer')), width: el.clientWidth,
      scrollWidth: el.scrollWidth, bodyHeight: body.clientHeight, bodyScrollHeight: body.scrollHeight,
      documentWidth: document.documentElement.clientWidth, documentScrollWidth: document.documentElement.scrollWidth }
  })
  geometry.push({ name, size: page.viewportSize(), ...bounds })
  assert.ok(bounds.top >= 0 && bounds.bottom <= page.viewportSize().height + 1)
  assert.ok(bounds.footer.bottom <= page.viewportSize().height && bounds.bodyHeight > 0)
  assert.ok(bounds.scrollWidth <= bounds.width + 1 && bounds.documentScrollWidth <= bounds.documentWidth + 1)
  assert.equal(/\b(?:imageGeneration|visualBible)\.[a-zA-Z]+/.test(await dialog().innerText()), false)
  for (const button of await dialog().locator('.quick-confirm').all()) {
    assert.ok(await button.evaluate(el => {
      const r = el.getBoundingClientRect(), media = el.closest('.quick-image-media').getBoundingClientRect()
      return r.left >= media.left && r.right <= media.right + 1 && r.top >= media.top && r.bottom <= media.bottom + 1
    }), `${name}: confirm fits in candidate`)
  }
  await page.screenshot({ path: path.join(artifacts, `${name}.png`) })
}

;(async () => {
  assert.ok(fs.existsSync(path.join(build, 'index.html')), 'Build the frontend before running E2E')
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  context = await chromium.launchPersistentContext(path.join(artifacts, 'browser-profile'), { headless: true,
    viewport: { width: 1440, height: 1000 },
    ...(process.env.COMAIC_BROWSER_EXECUTABLE ? { executablePath: process.env.COMAIC_BROWSER_EXECUTABLE } : {}) })
  await context.tracing.start({ screenshots: true, snapshots: true })
  await context.addInitScript(() => { localStorage.setItem('comaic-locale', 'zh') })
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) })
    if (pathname.startsWith('/api/fixtures/')) return route.fulfill({ contentType: 'image/svg+xml', body:
      '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="480"><rect width="360" height="480" fill="#dfebf4"/><rect x="24" y="24" width="312" height="300" rx="12" fill="#97bcd0"/><circle cx="180" cy="160" r="65" fill="#f9d7a6"/><path d="M85 310Q180 190 275 310" fill="#466477"/><text x="30" y="420" font-size="26" fill="#466477">Offline comic candidate</text></svg>' })
    if (pathname === '/api/projects') return send({ items: [{ id: 1, title: '漫画快速选图验收', ...stamp }] })
    if (pathname === '/api/projects/1/script-tasks') return send([{ id: 11, project_id: 1, status: 'succeeded', mode: 'batch', total_pages: 4, ...stamp }])
    if (pathname === '/api/image-generation/tools') return send({ items: [{ id: 1, name: '离线工具', provider: 'comfyui', prompt_type: 'natural_language', is_default: true, capabilities: {}, ...stamp }] })
    if (pathname.endsWith('/batches')) return send({ items: [] })
    if (pathname === '/api/image-generation/script-tasks/11/pages') return send({ items: pages })
    const match = pathname.match(/^\/api\/image-generation\/pages\/(\d+)\/images\/(\d+)\/select$/)
    if (match) {
      assert.equal(request.method(), 'POST')
      selections.push({ pageId: Number(match[1]), imageId: Number(match[2]) })
      await new Promise(resolve => setTimeout(resolve, 150))
      if (failNext) { failNext = false; return send({ code: 'image_generation.select_failed', message: 'Offline failure' }, 500) }
      const selectedPage = pages.find(item => item.page_id === Number(match[1]))
      assert.ok(selectedPage.images.some(image => image.id === Number(match[2])))
      selectedPage.selected_image_id = Number(match[2])
      selectedPage.images.forEach(image => { image.is_selected = image.id === selectedPage.selected_image_id })
      return send(selectedPage)
    }
    errors.push(`Unexpected API: ${request.method()} ${pathname}`)
    return send({}, 404)
  })
  const base = `http://127.0.0.1:${server.address().port}`
  await page.goto(`${base}/image-generation?project_id=1&script_task_id=11&tab=results`)
  await page.getByRole('button', { name: '快速选图', exact: true }).click()
  await card(1000).waitFor()
  await check('桌面及窄屏保持图片独立滚动、底部按钮可见，文案完整', async () => {
    for (const [width, height] of [[1440, 1000], [1280, 900], [390, 844], [360, 640]]) {
      await page.setViewportSize({ width, height }); await capture(`zh-${width}`)
    }
    await page.setViewportSize({ width: 1440, height: 1000 })
    const size = geometry[0]
    assert.ok(size.bodyScrollHeight > size.bodyHeight)
  })
  await check('键盘候选高亮和放大预览，不触发终稿保存', async () => {
    await card(1000).focus(); await page.keyboard.press('Enter')
    assert.equal(await card(1000).getAttribute('aria-pressed'), 'true')
    await card(1000).getByRole('button', { name: '放大预览 · 候选 1', exact: true }).click()
    await page.locator('.el-image-viewer__wrapper').waitFor()
    await page.locator('.el-image-viewer__close').click()
    assert.equal(selections.length, 0)
  })
  await check('成功确认同步列表并进入空页，下一页可跳过空候选', async () => {
    await dialog().locator('.el-dialog__body').evaluate(el => { el.scrollTop = 400 })
    await confirm(1000).click()
    await dialog().getByText('暂无图片', { exact: true }).waitFor()
    assert.equal(await dialog().locator('.el-dialog__body').evaluate(el => el.scrollTop), 0)
    await dialog().getByRole('button', { name: '下一页', exact: true }).click()
    await card(1200).waitFor()
    assert.equal(pages[0].selected_image_id, 1000)
  })
  await check('保存失败留在原页，重试成功才前进，末页不循环', async () => {
    failNext = true
    await confirm(1200).click()
    await page.getByText('最终图片选择失败', { exact: true }).waitFor()
    assert.equal(await card(1200).count(), 1)
    await confirm(1201).click(); await card(1300).waitFor()
    await confirm(1300).click()
    await dialog().getByText('已到最后一页', { exact: true }).waitFor()
    assert.equal(await dialog().getByRole('button', { name: '下一页', exact: true }).isDisabled(), true)
    assert.equal(await card(1300).locator('.quick-confirm').count(), 0)
    await dialog().getByRole('button', { name: '关闭', exact: true }).click()
    await page.locator('.comic-quick-dialog').waitFor({ state: 'hidden' })
    assert.equal(await page.locator('.image-card--selected').count(), 3)
  })
  await check('英文手机布局与页面下拉搜索', async () => {
    await page.evaluate(() => localStorage.setItem('comaic-locale', 'en'))
    await context.addInitScript(() => localStorage.setItem('comaic-locale', 'en'))
    await page.reload()
    await page.getByRole('button', { name: 'Quick image selection', exact: true }).click()
    await card(1000).waitFor()
    await dialog().locator('.el-select__wrapper').click()
    await dialog().getByRole('combobox', { name: 'Comic page', exact: true }).fill('Page 4')
    await page.locator('.el-select-dropdown:visible').getByText('Page 4 · Final · 1 candidates', { exact: true }).click()
    await card(1300).waitFor()
    await dialog().getByRole('button', { name: 'Previous page', exact: true }).click()
    await card(1200).waitFor()
    for (const [width, height] of [[390, 844], [360, 640]]) {
      await page.setViewportSize({ width, height }); await capture(`en-${width}`)
    }
  })
  assert.deepEqual(errors, [])
})().catch(error => { errors.push(error.stack || String(error)); process.exitCode = 1 }).finally(async () => {
  if (page && errors.length) await page.screenshot({ path: path.join(artifacts, 'failure.png') }).catch(() => {})
  if (context) {
    await context.tracing.stop({ path: path.join(artifacts, 'trace.zip') }).catch(() => {})
    const browser = context.browser(); await context.close(); await browser?.close()
  }
  await new Promise(resolve => server.close(resolve))
  fs.writeFileSync(path.join(artifacts, 'report.json'), JSON.stringify({ checks, geometry, errors, selections }, null, 2))
  console.log(JSON.stringify({ artifacts, checks: checks.length, errors }, null, 2))
})

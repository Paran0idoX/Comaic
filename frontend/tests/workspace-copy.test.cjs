const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const ts = require('typescript')
const source = fs.readFileSync(require('node:path').join(__dirname, '../src/i18n/messages.ts'), 'utf8')
const exportsObject = {}
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
  { exports: exportsObject })
const { zh, en } = exportsObject.messages
function flatten(object, prefix = '') {
  return Object.entries(object).flatMap(([key, value]) =>
    typeof value === 'object' && !Array.isArray(value) ? flatten(value, `${prefix}${key}.`) : [`${prefix}${key}`])
}
test('Chinese and English workspaces expose the same translation keys', () => {
  assert.deepEqual(flatten(zh).sort(), flatten(en).sort())
})
test('metric explanations match style, character-count and reference-reuse calculations', () => {
  assert.match(zh.imageGeneration.consistency.metricHelp.csd_cross, /画风/)
  assert.match(zh.imageGeneration.consistency.metricHelp.occm, /人物数量/)
  assert.match(zh.imageGeneration.consistency.metricHelp.copy_paste, /不能定位跨页复制/)
  assert.match(zh.imageGeneration.consistency.metricHelp.copy_paste, /原参考图相对其镜像/)
  assert.match(zh.imageGeneration.consistency.metricHelp.copy_paste, /不是复制概率/)
  assert.match(en.imageGeneration.consistency.metricHelp.csd_cross, /Style/)
  assert.match(en.imageGeneration.consistency.metricHelp.occm, /character counts/)
  assert.match(en.imageGeneration.consistency.metricHelp.copy_paste, /original reference relative to its mirror/)
  assert.match(en.imageGeneration.consistency.metricHelp.copy_paste, /not a probability of copying/)
  assert.doesNotMatch(en.imageGeneration.consistency.metrics.occm, /[\u4e00-\u9fff]/)
})
test('all five creator-facing navigation names agree with route titles', () => {
  for (const key of ['outline', 'scripts', 'visualBible', 'imageSpecs', 'imageGeneration']) {
    assert.equal(zh.nav[key], zh.routeTitles[key])
    assert.equal(en.nav[key], en.routeTitles[key])
  }
})

test('generation and evaluation running states have distinct localized labels', () => {
  assert.equal(zh.imageGeneration.batchStatuses.running, '生成中')
  assert.equal(zh.imageGeneration.consistency.statuses.running, '评测中')
  assert.equal(en.imageGeneration.batchStatuses.running, 'Generating')
  assert.equal(en.imageGeneration.consistency.statuses.running, 'Evaluating')
  assert.match(zh.backendErrors.image_generation.batch_busy, /处理完成后刷新/)
  assert.match(en.backendErrors.image_generation.batch_busy, /refresh and continue/)
  assert.match(zh.backendErrors.image_generation.batch_recovery_unavailable, /暂时无法确认.*未重新提交/)
  assert.match(zh.backendErrors.image_generation.batch_recovery_unsupported, /人工核查原结果后另建批次/)
  assert.match(en.backendErrors.image_generation.batch_recovery_unavailable, /Nothing was resubmitted/)
  assert.match(en.backendErrors.image_generation.batch_recovery_unsupported, /Manually verify the original result, then start a new batch/)
  assert.match(zh.imageGeneration.messages.suspendRequested, /当前页生成完成后/)
  assert.match(en.imageGeneration.messages.suspendRequested, /after the current page finishes/)
})

test('references are optional and evaluation benchmarks never gate image selection', () => {
  assert.match(zh.imageSpecs.subtitle, /参考图可选/)
  assert.match(en.imageSpecs.subtitle, /Reference images are optional/)
  assert.match(zh.ux.optionalReferencesHelp, /无法读取的图片或错误的工具配置会阻止提交/)
  assert.match(en.ux.optionalReferencesHelp, /files and tool configuration must be valid/)
  assert.match(zh.settings.consistency.thresholdHint, /未达标仍可人工选用/)
  assert.match(en.settings.consistency.thresholdHint, /regardless of scores/)
  assert.equal(zh.settings.tabs.imageTools, '生图工具')
  assert.equal(en.settings.tabs.imageTools, 'Image Tools')
})

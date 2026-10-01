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
  assert.match(en.imageGeneration.consistency.metricHelp.csd_cross, /Style/)
  assert.match(en.imageGeneration.consistency.metricHelp.occm, /character counts/)
  assert.doesNotMatch(en.imageGeneration.consistency.metrics.occm, /[\u4e00-\u9fff]/)
})
test('all five creator-facing navigation names agree with route titles', () => {
  for (const key of ['outline', 'scripts', 'visualBible', 'imageSpecs', 'imageGeneration']) {
    assert.equal(zh.nav[key], zh.routeTitles[key])
    assert.equal(en.nav[key], en.routeTitles[key])
  }
})

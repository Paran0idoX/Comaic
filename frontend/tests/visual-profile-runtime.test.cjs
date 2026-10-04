const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const Module = require('node:module')
const test = require('node:test')
const vue = require('vue')
const { parse, compileScript } = require('@vue/compiler-sfc')
const ts = require('typescript')
const file = path.resolve(__dirname, '../src/components/referenceLibrary/VisualProfileEditor.vue')
const compiled = ts.transpileModule(compileScript(parse(fs.readFileSync(file, 'utf8')).descriptor, { id: 'visual-profile-test' }).content,
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText

const harness = () => {
  const events = [], updates = [], errors = []
  const props = vue.reactive({ disabled: false, confirmReplacement: async () => true, profiles: [{ id: 7, revision: 1, source_hash: 'a'.repeat(64),
    kind: 'character', project_id: 1, owner_id: 11, format_version: 1, data: { human: true, facts: [{ kind: 'head', attribute: 'hair_color', polarity: 'required',
      source_field: 'default_hairstyle', source_excerpt: '黑或冷褐', views: ['identity_face', 'identity_back'], selected: 0, default_index: 0,
      selection_reason: 'First candidate', options: [{ natural: 'Black hair.', tags: ['black hair'] }, { natural: 'Cool brown hair.', tags: ['cool brown hair'] }] }] } }] })
  const api = { updateVisualProfile: async profile => { updates.push(JSON.parse(JSON.stringify(profile))); return { ...profile, revision: profile.revision + 1 } } }
  const stubs = { vue, '@/components/workspace/InfoTip.vue': {},
    'vue-i18n': { useI18n: () => ({ t: key => key }) },
    'element-plus': { ElMessage: { error: error => errors.push(error) } }, '@/api/errors': { apiErrorMessage: error => error.message }, '@/api/referenceImages': api }
  const runtime = new Module(file, module); runtime.require = id => Object.hasOwn(stubs, id) ? stubs[id] : require(id); runtime._compile(compiled, file)
  const scope = vue.effectScope()
  const state = scope.run(() => runtime.exports.default.setup(props, { emit: (...event) => events.push(event), expose() {} }))
  return { props, state, events, updates, errors, api, close: () => scope.stop() }
}

test('摘要选项和英文修正使用原修订保存，原输入不变，成功后发出新修订供重新编译', async () => {
  const h = harness()
  try {
    const fact = h.state.drafts.value[0].data.facts[0]
    fact.selected = 1; fact.options[1].natural = 'Cool brown straight hair.'
    await vue.nextTick()
    assert.equal(h.state.dirty.value, true)
    assert.equal(h.props.profiles[0].data.facts[0].selected, 0)
    assert.ok(h.events.some(event => event[0] === 'dirty' && event[1] === true))
    await h.state.save()
    assert.equal(h.updates.length, 1); assert.equal(h.updates[0].revision, 1)
    const updated = h.events.find(event => event[0] === 'updated')[1][0]
    assert.equal(updated.revision, 2); assert.equal(updated.data.facts[0].selected, 1)
    assert.equal(h.state.dirty.value, false)
    assert.deepEqual(h.events.filter(event => event[0] === 'busy').map(event => event[1]), [true, false])
  } finally { h.close() }
})

test('取消覆盖手改 Prompt 时不保存摘要、不替换外观选择', async () => {
  const h = harness()
  try {
    h.props.confirmReplacement = async () => false
    h.state.drafts.value[0].data.facts[0].selected = 1
    await h.state.save()
    assert.equal(h.updates.length, 0); assert.equal(h.state.dirty.value, true)
    assert.equal(h.events.some(event => event[0] === 'updated'), false)
  } finally { h.close() }
})

test('修订冲突保留未保存修改且清除忙状态，放弃修改可恢复原预览', async () => {
  const h = harness()
  try {
    h.api.updateVisualProfile = async () => { throw new Error('reference.profile_conflict') }
    h.state.drafts.value[0].data.facts[0].selected = 1
    await h.state.save()
    assert.equal(h.state.dirty.value, true); assert.equal(h.state.saving.value, false)
    assert.equal(h.errors[0], 'reference.profile_conflict')
    assert.equal(h.events.some(event => event[0] === 'updated'), false)
    h.state.reset(); await vue.nextTick()
    assert.equal(h.state.dirty.value, false); assert.equal(h.state.drafts.value[0].data.facts[0].selected, 0)
  } finally { h.close() }
})

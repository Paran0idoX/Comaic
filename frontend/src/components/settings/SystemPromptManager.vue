<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, type TreeInstance } from 'element-plus'
import { ArrowDown, ArrowUp, Document, Folder, FolderOpened, Search } from '@element-plus/icons-vue'
import { apiErrorMessage } from '@/api/errors'
import { listLLMConfigs, listSystemPrompts, listModelSystemPrompts, type SystemPrompt } from '@/api/settings'
import SystemPromptEditor from './SystemPromptEditor.vue'

type PromptNode = {
  id: string
  label: string
  path: string[]
  children?: PromptNode[]
  item?: SystemPrompt
  configId?: number
}
const { t } = useI18n()
const loading = ref(false)
const loaded = ref(false)
const tasks = ref<SystemPrompt[]>([])
const modelGroups = ref<{ id: number; name: string; prompts: SystemPrompt[] }[]>([])
const tree = ref<TreeInstance>()
const search = ref('')
const selectedId = ref('task-outline_conversation')
// 草稿按节点保留，切换树节点和折叠目录不会丢失正在编辑的内容。
const drafts = ref<Record<string, string>>({})
const pending = ref(new Set<string>())
const taskGroups = [
  { key: 'outline', items: ['outline_conversation', 'outline_update', 'outline_character', 'outline_snapshot'] },
  { key: 'script', items: ['script_planning', 'script_writer', 'script_supervisor'] },
  { key: 'shot', items: ['shot_planner', 'shot_language'] },
]
const treeData = computed<PromptNode[]>(() => [
  { id: 'models', label: t('systemPrompts.models'), path: [], children: modelGroups.value.map(group => ({
    id: `api-${group.id}`, label: group.name, path: [t('systemPrompts.models')],
    children: group.prompts.map(item => ({ id: `model-${group.id}-${item.key}`, label: item.key,
      path: [t('systemPrompts.models'), group.name], item, configId: group.id })),
  })) },
  { id: 'tasks', label: t('systemPrompts.tasks'), path: [], children: taskGroups.map(group => ({
    id: group.key, label: t(`systemPrompts.groups.${group.key}`), path: [t('systemPrompts.tasks')],
    children: tasks.value.filter(item => group.items.includes(item.key)).map(item => ({
      id: `task-${item.key}`, label: t(`systemPrompts.labels.${item.key}`),
      path: [t('systemPrompts.tasks'), t(`systemPrompts.groups.${group.key}`)], item,
    })),
  })) },
])
const flatten = (nodes: PromptNode[]): PromptNode[] => nodes.flatMap(node => [node, ...flatten(node.children ?? [])])
const allNodes = computed(() => flatten(treeData.value))
const selected = computed(() => allNodes.value.find(node => node.id === selectedId.value && node.item))
const promptCount = computed(() => allNodes.value.filter(node => node.item).length)
const expandedKeys = computed(() => ['models', 'tasks', 'outline', 'script', 'shot', ...modelGroups.value.map(group => `api-${group.id}`)])
const isDirty = (node: PromptNode) => node.item && drafts.value[node.id] !== undefined && drafts.value[node.id] !== node.item.content
const visibleTreeData = computed(() => {
  const query = search.value.trim().toLowerCase()
  if (!query) return treeData.value
  // 直接筛选目录数据并保留父级，避免快速搜索/清空时异步树过滤留下隐藏节点。
  const filter = (nodes: PromptNode[]): PromptNode[] => nodes.flatMap(node => {
    if ([...node.path, node.label].join(' ').toLowerCase().includes(query)) return [node]
    const children = filter(node.children ?? [])
    return children.length ? [{ ...node, children }] : []
  })
  return filter(treeData.value)
})

const load = async () => {
  loading.value = true
  try {
    const [taskPrompts, configs] = await Promise.all([listSystemPrompts(), listLLMConfigs()])
    modelGroups.value = await Promise.all(configs.items.map(async config => ({
      id: config.id, name: config.name, prompts: await listModelSystemPrompts(config.id),
    })))
    tasks.value = taskPrompts
    loaded.value = true
    if (!selected.value) selectedId.value = allNodes.value.find(node => node.item)?.id ?? ''
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('systemPrompts.loadFailed')))
  } finally {
    loading.value = false
  }
}
const toggleAll = (expand: boolean) => {
  allNodes.value.filter(node => node.children).forEach(node => {
    const current = tree.value?.getNode(node.id)
    if (expand) current?.expand()
    else current?.collapse()
  })
}
const selectNode = (node: PromptNode) => { if (node.item) selectedId.value = node.id }
const saved = ({ nodeId, item }: { nodeId: string; item: SystemPrompt }) => {
  const node = allNodes.value.find(node => node.id === nodeId)
  const items = node?.configId === undefined ? tasks.value : modelGroups.value.find(group => group.id === node.configId)?.prompts
  const index = items?.findIndex(value => value.key === item.key) ?? -1
  if (items && index >= 0) items[index] = item
  drafts.value[nodeId] = item.content
}
const setBusy = ({ nodeId, busy }: { nodeId: string; busy: boolean }) => {
  if (busy) pending.value.add(nodeId)
  else pending.value.delete(nodeId)
}
onMounted(load)
</script>

<template>
  <section v-loading="loading" class="panel prompt-manager">
    <header class="prompt-manager__header">
      <div class="prompt-manager__heading">
        <span class="prompt-manager__icon"><el-icon><Document /></el-icon></span>
        <div><h2>{{ t('systemPrompts.title') }}</h2><p>{{ t('systemPrompts.description') }}</p></div>
      </div>
      <span class="prompt-manager__count">{{ t('systemPrompts.count', { count: promptCount }) }}</span>
    </header>
    <el-button v-if="!loaded && !loading" class="prompt-manager__retry" @click="load">{{ t('systemPrompts.retry') }}</el-button>
    <div v-if="loaded" class="prompt-manager__layout">
      <aside class="prompt-manager__navigator" :aria-label="t('systemPrompts.directory')">
        <el-input v-model="search" clearable :prefix-icon="Search" :placeholder="t('systemPrompts.search')" :aria-label="t('systemPrompts.search')" />
        <div class="prompt-manager__tree-toolbar">
          <span>{{ t('systemPrompts.directory') }}</span>
          <div>
            <el-tooltip :content="t('systemPrompts.expandAll')"><el-button text :icon="ArrowDown" :aria-label="t('systemPrompts.expandAll')" @click="toggleAll(true)" /></el-tooltip>
            <el-tooltip :content="t('systemPrompts.collapseAll')"><el-button text :icon="ArrowUp" :aria-label="t('systemPrompts.collapseAll')" @click="toggleAll(false)" /></el-tooltip>
          </div>
        </div>
        <div class="prompt-manager__tree-scroll">
          <el-tree ref="tree" :data="visibleTreeData" node-key="id" highlight-current :current-node-key="selectedId"
            :default-expanded-keys="expandedKeys" :indent="14"
            :empty-text="t('systemPrompts.noResults')" @node-click="selectNode">
            <template #default="{ node, data }">
              <span class="prompt-manager__node" :title="data.label">
                <el-icon class="prompt-manager__node-icon"><Document v-if="data.item" /><FolderOpened v-else-if="node.expanded" /><Folder v-else /></el-icon>
                <span class="prompt-manager__node-label">{{ data.label }}</span>
                <span v-if="isDirty(data)" class="prompt-manager__dot prompt-manager__dot--dirty" :title="t('systemPrompts.unsaved')" />
                <span v-else-if="data.item?.is_overridden" class="prompt-manager__dot" :title="t('systemPrompts.custom')" />
                <span v-else-if="data.children" class="prompt-manager__node-count">{{ data.children.length }}</span>
              </span>
            </template>
          </el-tree>
        </div>
        <div class="prompt-manager__nav-note"><span class="prompt-manager__dot" />{{ t('systemPrompts.customLegend') }}</div>
      </aside>
      <SystemPromptEditor v-if="selected?.item" :key="selected.id" :node-id="selected.id"
        :item="selected.item" :title="selected.label" :path="selected.path" :config-id="selected.configId"
        :draft="drafts[selected.id] ?? selected.item.content" :saving="pending.has(selected.id)"
        @change="drafts[$event.nodeId] = $event.value" @saved="saved" @busy="setBusy" />
    </div>
  </section>
</template>

<style scoped>
.prompt-manager { min-width: 0; overflow: hidden; box-shadow: 0 8px 30px rgba(22, 47, 111, .06); }
.prompt-manager__header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 22px 24px; border-bottom: 1px solid #edf0f5; }
.prompt-manager__heading { display: flex; align-items: center; gap: 12px; min-width: 0; }
.prompt-manager__icon { display: grid; place-items: center; flex: 0 0 40px; height: 40px; border-radius: 10px; background: #edf4ff; color: #3c72d9; font-size: 21px; }
h2 { margin: 0; font-size: 18px; font-weight: 650; line-height: 1.4; }
.prompt-manager__heading p { margin: 5px 0 0; color: #7a8598; font-size: 13px; line-height: 1.5; }
.prompt-manager__count { flex-shrink: 0; font-size: 12px; color: #7a8598; padding: 5px 9px; border-radius: 6px; background: #f5f7fa; }
.prompt-manager__layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); height: clamp(620px, calc(100vh - 230px), 850px); }
.prompt-manager__navigator { display: flex; flex-direction: column; gap: 16px; min-height: 0; min-width: 0; padding: 20px 12px 16px; background: #f9fafc; border-right: 1px solid #edf0f5; }
.prompt-manager__navigator > :deep(.el-input) { width: auto; margin: 0 4px; }
.prompt-manager__navigator :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px #e5e9f1 inset; background: #fff; border-radius: 7px; }
.prompt-manager__tree-toolbar { display: flex; align-items: center; justify-content: space-between; padding-left: 10px; font-size: 11px; color: #929bad; letter-spacing: .06em; }
.prompt-manager__tree-toolbar .el-button { margin: 0; width: 28px; height: 26px; padding: 4px; color: #778398; }
.prompt-manager__tree-scroll { flex: 1; min-height: 0; overflow: auto; }
.prompt-manager__tree-scroll :deep(.el-tree) { background: transparent; --el-tree-node-hover-bg-color: #eef1f7; }
.prompt-manager__tree-scroll :deep(.el-tree-node__content) { height: 36px; margin: 2px 0; border-radius: 6px; padding-right: 10px; font-size: 12px; }
.prompt-manager__tree-scroll :deep(.el-tree-node.is-current > .el-tree-node__content) { color: #285fc4; background: #e9f0ff; font-weight: 600; }
.prompt-manager__tree-scroll :deep(.el-tree-node__expand-icon) { color: #9aa4b5; }
.prompt-manager__node { display: flex; align-items: center; gap: 7px; width: 100%; min-width: 0; }
.prompt-manager__node-icon { flex-shrink: 0; color: #8e9bb0; font-size: 15px; }
.prompt-manager__node-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.prompt-manager__node-count { margin-left: auto; color: #a0a9b8; font-size: 11px; font-weight: 400; }
.prompt-manager__dot { width: 5px; height: 5px; border-radius: 50%; background: #7196d4; flex-shrink: 0; margin-left: auto; }
.prompt-manager__dot--dirty { background: #deaa4d; }
.prompt-manager__nav-note { display: flex; align-items: center; gap: 6px; padding: 10px 8px 0; color: #929bad; font-size: 11px; border-top: 1px solid #edf0f5; }
.prompt-manager__nav-note .prompt-manager__dot { margin-left: 0; }
.prompt-manager__retry { margin: 24px; }
@media (max-width: 1100px) { .prompt-manager__layout { grid-template-columns: 220px minmax(0, 1fr); } }
@media (max-width: 760px) {
  .prompt-manager__header { padding: 16px; align-items: flex-start; }
  .prompt-manager__icon { display: none; }
  .prompt-manager__count { margin-top: 2px; }
  .prompt-manager__layout { grid-template-columns: minmax(0, 1fr); height: auto; }
  .prompt-manager__navigator { height: 260px; gap: 10px; padding: 12px; border-right: 0; border-bottom: 1px solid #edf0f5; }
  .prompt-manager__nav-note { display: none; }
}
</style>

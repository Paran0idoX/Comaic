<script setup lang="ts">
import { Bell, Check, Clock, Close, Delete, EditPen, Plus, Refresh, Setting, Warning } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import { setLocale, type SupportedLocale } from '@/i18n'
import { useActivityCenterStore, type ActivityStatus } from '@/stores/activityCenter'
import type { WorkspaceActivity } from '@/stores/activityCenter'
import { useProjectContextStore } from '@/stores/projectContext'
import { createProject, updateProject, deleteProject, type Project } from '@/api/projects'
import { activityLocator, activityRoute, hasExactActivityLocation, positiveId } from '@/utils/workspaceActivity'

defineProps<{
  title: string
}>()

const { locale, t } = useI18n()
const router = useRouter()
const route = useRoute()
const activityCenter = useActivityCenterStore()
const activityDrawerVisible = ref(false)
const projectContext = useProjectContextStore()
const { projects, selectedProjectId, loadingProjects } = storeToRefs(projectContext)
const projectDialogVisible = ref(false)
const editingProjectId = ref<number | null>(null)
const projectTitle = ref('')
const savingProject = ref(false)
let activityTimer: ReturnType<typeof setInterval> | undefined

// 切项目时清除旧批次定位；任务流保留自己的上下文，浏览上下文可以独立切换。
const switchProject = async (projectId: number | null) => {
  await router.replace({ query: {
    ...(route.query.tab ? { tab: route.query.tab } : {}),
    ...(projectId ? { project_id: String(projectId) } : {}),
  } })
  selectedProjectId.value = projectId
}

const refreshProjects = async (force = false) => {
  try { await projectContext.refreshProjects({ force }) }
  catch { ElMessage.error(t('projects.loadError')) }
}

const openProjectDialog = (project?: Project) => {
  editingProjectId.value = project?.id ?? null
  projectTitle.value = project?.title ?? ''
  projectDialogVisible.value = true
}

const saveProject = async () => {
  const title = projectTitle.value.trim()
  if (!title || savingProject.value) return
  savingProject.value = true
  try {
    const editing = editingProjectId.value
    const project = editing ? await updateProject(editing, { title }) : await createProject({ title })
    await refreshProjects(true)
    projectDialogVisible.value = false
    if (!editing) {
      await router.push({ path: '/outline', query: { project_id: String(project.id) } })
      selectedProjectId.value = project.id
    }
    ElMessage.success(t(editing ? 'projects.updateSuccess' : 'projects.createSuccess'))
  } catch { ElMessage.error(t('projects.saveError')) }
  finally { savingProject.value = false }
}

const confirmDeleteProject = async (project: Project) => {
  try {
    await ElMessageBox.confirm(t('projects.deleteConfirm', { title: project.title }), t('projects.deleteDialogTitle'), {
      confirmButtonText: t('projects.delete'), cancelButtonText: t('projects.cancel'), type: 'warning',
    })
    await deleteProject(project.id)
    await refreshProjects(true)
    await switchProject(selectedProjectId.value)
    ElMessage.success(t('projects.deleteSuccess'))
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(t('projects.deleteError'))
  }
}

watch(() => route.query.project_id, (value) => {
  const id = positiveId(value)
  if (id) selectedProjectId.value = id
}, { immediate: true })

const refreshOnFocus = () => {
  void refreshProjects()
  void activityCenter.refreshActivities()
}
onMounted(() => {
  void refreshProjects()
  void activityCenter.refreshActivities()
  window.addEventListener('focus', refreshOnFocus)
})
onBeforeUnmount(() => {
  window.removeEventListener('focus', refreshOnFocus)
  if (activityTimer) clearInterval(activityTimer)
})
watch(activityDrawerVisible, (open) => {
  if (activityTimer) clearInterval(activityTimer)
  if (open) {
    void activityCenter.refreshActivities()
    activityTimer = setInterval(() => void activityCenter.refreshActivities(), 5000)
  }
})

const currentLocale = computed({
  get: () => locale.value as SupportedLocale,
  set: (value: SupportedLocale) => setLocale(value),
})

const activeActivityCount = computed(
  () =>
    activityCenter.activities.filter((item) =>
      ['pending', 'running', 'suspended', 'failed'].includes(item.status),
    ).length,
)

const activityIcon = (status: ActivityStatus) => {
  if (status === 'succeeded') return Check
  if (status === 'failed') return Close
  if (status === 'suspended') return Warning
  return Clock
}

const activityTagType = (status: ActivityStatus) => {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'suspended') return 'warning'
  if (status === 'running') return 'primary'
  return 'info'
}

const openActivity = async (activity: WorkspaceActivity) => {
  if (!activityLocator(activity).projectId) {
    ElMessage.info(t('activityCenter.unknownLocation'))
    return
  }
  activityDrawerVisible.value = false
  if (!hasExactActivityLocation(activity)) ElMessage.info(t('activityCenter.legacyLocation'))
  await router.push(activityRoute(activity))
}
const projectName = (projectId: number | null) =>
  projects.value.find((project) => project.id === projectId)?.title ?? t('activityCenter.projectUnknown')
const formatUpdatedAt = (value: string) => {
  const date = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US')
}
</script>

<template>
  <header class="top-bar">
    <div class="top-bar__context">
      <h2>{{ title }}</h2>
      <el-select
        :model-value="selectedProjectId"
        :loading="loadingProjects"
        filterable
        class="top-bar__project"
        :aria-label="t('ux.currentProject')"
        :placeholder="t('outline.projectPlaceholder')"
        @change="switchProject"
        @visible-change="(open: boolean) => open && refreshProjects()"
      >
        <el-option v-for="project in projects" :key="project.id" :label="project.title" :value="project.id">
          <div class="project-option">
            <span>{{ project.title }}</span>
            <span class="project-option__actions">
              <el-button link :icon="EditPen" :aria-label="t('projects.edit')"
                @mousedown.stop.prevent @click.stop="openProjectDialog(project)" />
              <el-button link type="danger" :icon="Delete" :aria-label="t('projects.delete')"
                @mousedown.stop.prevent @click.stop="confirmDeleteProject(project)" />
            </span>
          </div>
        </el-option>
        <template #footer>
          <el-button text :icon="Plus" @click="openProjectDialog()">{{ t('projects.create') }}</el-button>
        </template>
        <template #empty>
          <el-button text :icon="Plus" @click="openProjectDialog()">{{ t('projects.create') }}</el-button>
        </template>
      </el-select>
    </div>

    <div class="top-bar__actions">
      <el-select v-model="currentLocale" class="top-bar__locale" size="small" aria-label="Language">
        <el-option :label="t('language.zh')" value="zh" />
        <el-option :label="t('language.en')" value="en" />
      </el-select>
      <el-tag effect="plain" type="success">{{ t('app.env') }}</el-tag>
      <el-badge :value="activeActivityCount" :hidden="activeActivityCount === 0" :max="9">
        <el-button
          :icon="Bell"
          circle
          :aria-label="t('activityCenter.title')"
          @click="activityDrawerVisible = true"
        />
      </el-badge>
      <el-button
        :icon="Setting"
        circle
        :aria-label="t('app.settings')"
        @click="router.push('/settings')"
      />
    </div>

    <el-drawer
      v-model="activityDrawerVisible"
      :title="t('activityCenter.title')"
      size="min(420px, 92vw)"
      append-to-body
    >
      <template #header>
        <div class="activity-drawer__header">
          <div>
            <strong>{{ t('activityCenter.title') }}</strong>
            <span>{{ t('activityCenter.description') }}</span>
          </div>
          <el-button link :icon="Refresh" :loading="activityCenter.refreshing" @click="activityCenter.refreshActivities">
            {{ t('activityCenter.refresh') }}
          </el-button>
          <el-button
            v-if="activityCenter.activities.some((item) => item.status === 'succeeded')"
            link
            type="danger"
            :icon="Delete"
            @click="activityCenter.clearFinished"
          >
            {{ t('activityCenter.clearFinished') }}
          </el-button>
        </div>
      </template>
      <el-empty
        v-if="activityCenter.activities.length === 0"
        :description="t('activityCenter.empty')"
      />
      <div v-else class="activity-list">
        <button
          v-for="activity in activityCenter.activities"
          :key="activity.id"
          class="activity-item"
          type="button"
          @click="openActivity(activity)"
        >
          <el-icon :class="`activity-item__icon activity-item__icon--${activity.status}`">
            <component :is="activityIcon(activity.status)" />
          </el-icon>
          <div class="activity-item__content">
            <div class="activity-item__title">
              <strong>{{ t(`activityCenter.kinds.${activity.kind}`) }}</strong>
              <el-tag :type="activityTagType(activity.status)" size="small" effect="light">
                {{ t(`activityCenter.status.${activity.status}`) }}
              </el-tag>
            </div>
            <span>{{ activity.label }}</span>
            <span>{{ projectName(activity.projectId) }}</span>
            <small>{{ t('activityCenter.updatedAt') }} {{ formatUpdatedAt(activity.updatedAt) }}</small>
            <small v-if="activity.refreshFailed" class="activity-item__refresh-error">{{ t('activityCenter.refreshFailed') }}</small>
            <el-progress
              v-if="activity.progress !== null"
              :percentage="activity.progress"
              :show-text="false"
              :stroke-width="5"
            />
          </div>
        </button>
      </div>
    </el-drawer>
    <el-dialog v-model="projectDialogVisible" :title="t(editingProjectId ? 'projects.editDialogTitle' : 'projects.dialogTitle')" width="420px">
      <el-form label-position="top" @submit.prevent="saveProject">
        <el-form-item :label="t('projects.projectName')" required>
          <el-input v-model="projectTitle" maxlength="255" show-word-limit :placeholder="t('projects.projectNamePlaceholder')" @keyup.enter="saveProject" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="projectDialogVisible = false">{{ t('projects.cancel') }}</el-button>
        <el-button type="primary" :loading="savingProject" :disabled="!projectTitle.trim()" @click="saveProject">{{ t('projects.save') }}</el-button>
      </template>
    </el-dialog>
  </header>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 100%;
  gap: 18px;
  padding: 0 28px;
}

.top-bar h2 {
  margin: 0;
  font-size: 18px;
  color: #101828;
}

.top-bar__context { display: flex; align-items: center; gap: 16px; min-width: 0; }
.top-bar__project { width: 220px; }
.project-option { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.project-option > span:first-child { overflow: hidden; text-overflow: ellipsis; }
.project-option__actions { display: flex; flex: 0 0 auto; }
.activity-item__content small { color: var(--text-soft); font-size: 11px; }
.activity-item__content .activity-item__refresh-error { color: var(--el-color-warning-dark-2); }

.top-bar__actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.activity-drawer__header,
.activity-item,
.activity-item__title {
  display: flex;
  align-items: center;
}

.activity-drawer__header {
  justify-content: space-between;
  width: 100%;
  gap: 12px;
}

.activity-drawer__header > div {
  display: grid;
  gap: 4px;
}

.activity-drawer__header span {
  color: var(--text-soft);
  font-size: 12px;
  font-weight: 400;
}

.activity-list {
  display: grid;
  gap: 10px;
}

.activity-item {
  width: 100%;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.activity-item:hover,
.activity-item:focus-visible {
  border-color: rgba(23, 109, 255, 0.45);
  background: #f8fbff;
}

.activity-item:focus-visible {
  outline: 3px solid rgba(23, 109, 255, 0.16);
}

.activity-item__icon {
  width: 32px;
  height: 32px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: rgba(23, 109, 255, 0.1);
  color: var(--brand);
}

.activity-item__icon--succeeded {
  background: rgba(25, 169, 116, 0.12);
  color: var(--success);
}

.activity-item__icon--failed {
  background: rgba(245, 108, 108, 0.12);
  color: var(--el-color-danger);
}

.activity-item__icon--suspended {
  background: rgba(230, 162, 60, 0.12);
  color: var(--el-color-warning);
}

.activity-item__content {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 6px;
}

.activity-item__title {
  justify-content: space-between;
  gap: 8px;
}

.activity-item__content > span {
  overflow: hidden;
  color: var(--text-soft);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.top-bar__locale {
  width: 112px;
}

.top-bar :deep(.el-button.is-circle) {
  border-color: rgba(85, 120, 255, 0.18);
  background: rgba(255, 255, 255, 0.72);
  color: #475467;
}

.top-bar :deep(.el-button.is-circle:hover) {
  border-color: rgba(23, 109, 255, 0.38);
  color: var(--brand);
  box-shadow: 0 8px 20px rgba(23, 109, 255, 0.12);
}

.top-bar :deep(.el-tag) {
  border-color: rgba(25, 169, 116, 0.3);
  background: rgba(25, 169, 116, 0.08);
}

@media (max-width: 640px) {
  .top-bar {
    gap: 8px;
    padding: 0 12px;
  }

  .top-bar h2 {
    font-size: 14px;
    line-height: 1.15;
  }
  .top-bar__context { flex-direction: column; align-items: flex-start; gap: 3px; flex: 1; }
  .top-bar__project { width: min(180px, 42vw); }

  .top-bar__actions {
    gap: 6px;
  }

  .top-bar__locale {
    width: 80px;
  }

  .top-bar__actions > .el-tag {
    display: none;
  }
}
</style>

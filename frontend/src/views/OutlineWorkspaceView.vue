<script setup lang="ts">
import { Delete, EditPen, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { storeToRefs } from 'pinia'
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import ConversationPanel, {
  type ConversationMessage,
} from '@/components/outline/ConversationPanel.vue'
import OutlinePanel, { type OutlineVersionItem } from '@/components/outline/OutlinePanel.vue'
import { apiErrorMessage } from '@/api/errors'
import {
  confirmOutlineVersion,
  resolveOutlineSession,
  streamOutlineChat,
  type OutlineVersion,
} from '@/api/outline'
import {
  createProject,
  deleteProject,
  listProjects,
  updateProject,
  type Project,
} from '@/api/projects'
import { useProjectContextStore } from '@/stores/projectContext'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const projectContext = useProjectContextStore()
const { selectedProjectId } = storeToRefs(projectContext)

const loading = ref(false)
const loadingProjects = ref(false)
const streaming = ref(false)
const confirming = ref(false)
const savingProject = ref(false)
const projectDialogVisible = ref(false)
const editingProjectId = ref<number | null>(null)
const projectTitle = ref('')
const projects = ref<Project[]>([])
const threadId = ref('')
const messages = ref<ConversationMessage[]>([])
const versions = ref<OutlineVersionItem[]>([])
const messageId = ref(1)

const routeProjectId = computed(() => {
  const rawProjectId = route.query.project_id
  const value = Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const currentOutline = computed(() => versions.value[0]?.outline ?? '')
const isDisabled = computed(() => loading.value || selectedProjectId.value === null || !threadId.value)
const isEditingProject = computed(() => editingProjectId.value !== null)
const projectDialogTitle = computed(() =>
  isEditingProject.value ? t('projects.editDialogTitle') : t('projects.dialogTitle'),
)

const resetSessionState = () => {
  threadId.value = ''
  messages.value = []
  versions.value = []
}

const toOutlineVersionItem = (version: OutlineVersion): OutlineVersionItem => ({
  version_id: version.version_id,
  version_no: version.version_no,
  outline: version.outline,
  status: version.status,
  created_at: version.created_at,
  confirmed_at: version.confirmed_at,
  characters: version.characters,
})

const loadOutlineSession = async () => {
  if (selectedProjectId.value === null) {
    resetSessionState()
    return
  }

  loading.value = true
  try {
    const session = await resolveOutlineSession(selectedProjectId.value)
    threadId.value = session.thread_id
    versions.value = session.outline_versions.map(toOutlineVersionItem)
    messages.value = session.messages.map((message) => ({
      id: messageId.value++,
      role: message.role,
      content: message.content,
    }))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('outline.errors.loadSession')))
  } finally {
    loading.value = false
  }
}

const loadProjects = async (preferredProjectId?: number | null) => {
  loadingProjects.value = true
  try {
    projects.value = await listProjects()
    const routeProject = routeProjectId.value
    const candidates = [
      preferredProjectId,
      routeProject,
      selectedProjectId.value,
      projects.value[0]?.id ?? null,
    ]
    selectedProjectId.value =
      candidates.find((projectId) =>
        projectId !== null && projects.value.some((project) => project.id === projectId),
      ) ?? null
  } catch {
    projects.value = []
    selectedProjectId.value = null
    ElMessage.error(t('projects.loadError'))
  } finally {
    loadingProjects.value = false
  }
}

const openCreateProjectDialog = () => {
  editingProjectId.value = null
  projectTitle.value = ''
  projectDialogVisible.value = true
}

const openEditProjectDialog = (project: Project) => {
  editingProjectId.value = project.id
  projectTitle.value = project.title
  projectDialogVisible.value = true
}

const saveProject = async () => {
  const title = projectTitle.value.trim()
  if (!title) {
    ElMessage.error(t('projects.projectNamePlaceholder'))
    return
  }

  savingProject.value = true
  try {
    const previousSelectedProjectId = selectedProjectId.value
    const savedProject =
      editingProjectId.value === null
        ? await createProject({ title })
        : await updateProject(editingProjectId.value, { title })
    ElMessage.success(
      editingProjectId.value === null ? t('projects.createSuccess') : t('projects.updateSuccess'),
    )
    projectDialogVisible.value = false
    await loadProjects(editingProjectId.value === null ? savedProject.id : previousSelectedProjectId)
  } catch {
    ElMessage.error(t('projects.saveError'))
  } finally {
    savingProject.value = false
  }
}

const confirmDeleteProject = async (project: Project) => {
  try {
    await ElMessageBox.confirm(
      t('projects.deleteConfirm', { title: project.title }),
      t('projects.deleteDialogTitle'),
      {
        confirmButtonText: t('projects.delete'),
        cancelButtonText: t('projects.cancel'),
        type: 'warning',
      },
    )
    const wasSelected = project.id === selectedProjectId.value
    await deleteProject(project.id)
    ElMessage.success(t('projects.deleteSuccess'))
    if (wasSelected) {
      selectedProjectId.value = null
      resetSessionState()
    }
    await loadProjects(wasSelected ? null : selectedProjectId.value)
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    ElMessage.error(t('projects.deleteError'))
  }
}

const appendVersion = (version: OutlineVersion) => {
  const nextVersion = toOutlineVersionItem(version)
  versions.value = [
    nextVersion,
    ...versions.value
      .filter((item) => item.version_id !== nextVersion.version_id)
      .map((item) => ({
        ...item,
        status: 'archived',
      })),
  ].slice(0, 5)
}

const confirmCurrentOutline = async () => {
  const currentVersion = versions.value[0]
  if (!currentVersion || confirming.value) {
    return
  }
  confirming.value = true
  try {
    const confirmed = await confirmOutlineVersion(currentVersion.version_id)
    appendVersion(confirmed)
    ElMessage.success(t('outline.panel.confirmSuccess'))
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t, t('outline.errors.confirm')))
  } finally {
    confirming.value = false
  }
}

const updateMessage = (messageId: number, update: (message: ConversationMessage) => ConversationMessage) => {
  // token 流式到达时必须更新响应式数组里的对象，避免外部原始对象变更不触发渲染。
  messages.value = messages.value.map((message) =>
    message.id === messageId ? update(message) : message,
  )
}

const sendMessage = async (content: string) => {
  if (!threadId.value || streaming.value) {
    return
  }

  const userMessage: ConversationMessage = {
    id: messageId.value++,
    role: 'user',
    content,
  }
  const agentMessage: ConversationMessage = {
    id: messageId.value++,
    role: 'agent',
    content: '',
    streaming: true,
  }
  messages.value.push(userMessage, agentMessage)
  const agentMessageId = agentMessage.id

  streaming.value = true
  try {
    await streamOutlineChat({
      threadId: threadId.value,
      message: content,
      onToken: (text) => {
        updateMessage(agentMessageId, (message) => ({
          ...message,
          content: message.content + text,
        }))
      },
      onOutline: (outline) => {
        appendVersion(outline)
      },
      onDone: () => {
        updateMessage(agentMessageId, (message) => ({
          ...message,
          streaming: false,
        }))
      },
      onError: (error) => {
        updateMessage(agentMessageId, (currentMessage) => ({
          ...currentMessage,
          streaming: false,
        }))
        ElMessage.error(apiErrorMessage(error, t, t('outline.errors.stream')))
      },
    })
  } catch (error) {
    updateMessage(agentMessageId, (message) => ({
      ...message,
      streaming: false,
    }))
    ElMessage.error(apiErrorMessage(error, t, t('outline.errors.stream')))
  } finally {
    updateMessage(agentMessageId, (message) => ({
      ...message,
      streaming: false,
    }))
    streaming.value = false
  }
}

onMounted(async () => {
  const previousProjectId = selectedProjectId.value
  await loadProjects()
  if (selectedProjectId.value !== null && selectedProjectId.value === previousProjectId) {
    await loadOutlineSession()
  }
})

watch(selectedProjectId, (nextProjectId, previousProjectId) => {
  if (nextProjectId === previousProjectId) {
    return
  }
  resetSessionState()
  if (nextProjectId === null) {
    return
  }
  if (routeProjectId.value !== nextProjectId) {
    void router.replace({
      query: {
        ...route.query,
        project_id: String(nextProjectId),
      },
    })
  }
  void loadOutlineSession()
})

watch(routeProjectId, (nextProjectId) => {
  if (nextProjectId === selectedProjectId.value) {
    return
  }
  const matchedProject = projects.value.find((project) => project.id === nextProjectId)
  if (matchedProject !== undefined) {
    selectedProjectId.value = matchedProject.id
  }
})
</script>

<template>
  <section :aria-busy="loadingProjects || loading">
    <div class="page-header">
      <div class="page-actions">
        <el-select
          v-model="selectedProjectId"
          class="project-select"
          :loading="loadingProjects"
          :disabled="streaming"
          filterable
          :placeholder="t('outline.projectPlaceholder')"
        >
          <template #prefix>
            <span class="project-select__prefix">{{ t('outline.manageProjects') }}</span>
          </template>
          <el-option
            v-for="project in projects"
            :key="project.id"
            :label="project.title"
            :value="project.id"
          >
            <div class="project-option">
              <span class="project-option__title">{{ project.title }}</span>
              <span class="project-option__actions">
                <el-button
                  link
                  type="primary"
                  :icon="EditPen"
                  :disabled="streaming"
                  :aria-label="t('projects.edit')"
                  @mousedown.stop.prevent
                  @click.stop="openEditProjectDialog(project)"
                />
                <el-button
                  link
                  type="danger"
                  :icon="Delete"
                  :disabled="streaming"
                  :aria-label="t('projects.delete')"
                  @mousedown.stop.prevent
                  @click.stop="confirmDeleteProject(project)"
                />
              </span>
            </div>
          </el-option>
          <template #footer>
            <el-button
              class="project-select__create"
              text
              :icon="Plus"
              :disabled="streaming"
              @click="openCreateProjectDialog"
            >
              {{ t('projects.create') }}
            </el-button>
          </template>
        </el-select>
        <el-button :icon="Plus" :disabled="streaming" @click="openCreateProjectDialog">
          {{ t('projects.create') }}
        </el-button>
      </div>
    </div>

    <el-skeleton
      v-if="loadingProjects && selectedProjectId === null"
      class="outline-workspace__loading panel"
      :rows="9"
      animated
    />

    <el-empty
      v-else-if="selectedProjectId === null"
      class="outline-workspace__empty panel"
      :description="projects.length === 0 ? t('outline.emptyProjects') : t('outline.errors.missingProject')"
    >
      <el-button type="primary" :icon="Plus" @click="openCreateProjectDialog">
        {{ t('projects.create') }}
      </el-button>
    </el-empty>

    <div v-else class="outline-workspace">
      <ConversationPanel
        :messages="messages"
        :thread-id="threadId"
        :loading="loading"
        :streaming="streaming"
        :disabled="isDisabled"
        @send="sendMessage"
      />
      <OutlinePanel
        :outline="currentOutline"
        :versions="versions"
        :loading="loading"
        :confirming="confirming"
        @confirm="confirmCurrentOutline"
      />
    </div>

    <el-dialog v-model="projectDialogVisible" :title="projectDialogTitle" width="420px">
      <el-form label-position="top" @submit.prevent>
        <el-form-item :label="t('projects.projectName')" required>
          <el-input
            v-model="projectTitle"
            maxlength="255"
            show-word-limit
            :placeholder="t('projects.projectNamePlaceholder')"
            @keyup.enter="saveProject"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="savingProject" @click="projectDialogVisible = false">
          {{ t('projects.cancel') }}
        </el-button>
        <el-button type="primary" :loading="savingProject" @click="saveProject">
          {{
            savingProject
              ? t('projects.saving')
              : isEditingProject
                ? t('projects.save')
                : t('projects.createPlaceholder')
          }}
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.outline-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 22px;
}

.outline-workspace__empty {
  padding: 56px 18px;
}

.outline-workspace__loading {
  min-height: 620px;
  padding: 32px;
}

.page-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.project-select {
  width: 360px;
}

.project-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-width: 0;
  gap: 12px;
}

.project-option__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-option__actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  opacity: 0.78;
}

.project-select__create {
  width: 100%;
  justify-content: flex-start;
}

.project-select__prefix {
  color: var(--text-soft);
  font-size: 12px;
}

@media (max-width: 1100px) {
  .outline-workspace {
    grid-template-columns: 1fr;
  }

  .page-header,
  .page-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .project-select {
    width: 100%;
  }
}
</style>

<script setup lang="ts">
import { ElMessage } from 'element-plus'
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
import { useProjectContextStore } from '@/stores/projectContext'
import WorkflowReadiness, {
  type ReadinessItem,
} from '@/components/workspace/WorkflowReadiness.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const projectContext = useProjectContextStore()
const { selectedProjectId, projects, loadingProjects } = storeToRefs(projectContext)

const loading = ref(false)
const streaming = ref(false)
const confirming = ref(false)
const threadId = ref('')
const messages = ref<ConversationMessage[]>([])
const versions = ref<OutlineVersionItem[]>([])
const messageId = ref(1)
let sessionLoadToken = 0

const routeProjectId = computed(() => {
  const rawProjectId = route.query.project_id
  const value = Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const currentOutline = computed(() => versions.value[0]?.outline ?? '')
const currentOutlineVersion = computed(() => versions.value[0] ?? null)
const outlineReadinessItems = computed<ReadinessItem[]>(() => [
  {
    key: 'outline',
    label: t('outline.readiness.outline'),
    detail: currentOutline.value
      ? t('outline.readiness.snapshotReady')
      : t('outline.readiness.snapshotMissing'),
    status: currentOutline.value ? 'ready' : 'pending',
  },
  {
    key: 'characters',
    label: t('outline.readiness.characters'),
    detail: t('outline.readiness.characterCount', {
      count: currentOutlineVersion.value?.characters.length ?? 0,
    }),
    status: (currentOutlineVersion.value?.characters.length ?? 0) > 0 ? 'ready' : 'pending',
  },
  {
    key: 'confirmation',
    label: t('outline.readiness.confirmation'),
    detail: currentOutlineVersion.value?.confirmed_at
      ? t('outline.panel.confirmed')
      : t('outline.readiness.confirmationPending'),
    status: currentOutlineVersion.value?.confirmed_at ? 'ready' : 'blocked',
  },
  {
    key: 'next',
    label: t('outline.readiness.next'),
    detail: currentOutlineVersion.value?.confirmed_at
      ? t('outline.readiness.canPlanScripts')
      : t('outline.readiness.confirmFirst'),
    status: currentOutlineVersion.value?.confirmed_at ? 'ready' : 'info',
    to: currentOutlineVersion.value?.confirmed_at ? { path: '/scripts', query: { project_id: String(selectedProjectId.value), outline_version_id: String(currentOutlineVersion.value.version_id) } } : undefined,
    actionLabel: currentOutlineVersion.value?.confirmed_at
      ? t('outline.readiness.openScripts')
      : undefined,
  },
])
const isDisabled = computed(() => loading.value || selectedProjectId.value === null || !threadId.value)
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
  const projectId = selectedProjectId.value
  const token = ++sessionLoadToken
  if (selectedProjectId.value === null) {
    resetSessionState()
    return
  }

  loading.value = true
  try {
    const session = await resolveOutlineSession(projectId!)
    if (token !== sessionLoadToken || projectId !== selectedProjectId.value) return
    threadId.value = session.thread_id
    versions.value = session.outline_versions.map(toOutlineVersionItem)
    messages.value = session.messages.map((message) => ({
      id: messageId.value++,
      role: message.role,
      content: message.content,
    }))
  } catch (error) {
    if (token === sessionLoadToken) ElMessage.error(apiErrorMessage(error, t, t('outline.errors.loadSession')))
  } finally {
    if (token === sessionLoadToken) loading.value = false
  }
}

const loadProjects = async () => {
  try { await projectContext.refreshProjects() }
  catch { ElMessage.error(t('projects.loadError')) }
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
  const projectId = selectedProjectId.value
  const currentVersion = versions.value[0]
  if (!currentVersion || confirming.value) {
    return
  }
  confirming.value = true
  try {
    const confirmed = await confirmOutlineVersion(currentVersion.version_id)
    if (projectId !== selectedProjectId.value) return
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
  const projectId = selectedProjectId.value
  const conversationThread = threadId.value
  const isCurrentConversation = () => projectId === selectedProjectId.value && conversationThread === threadId.value

  streaming.value = true
  try {
    await streamOutlineChat({
      threadId: conversationThread,
      message: content,
      onToken: (text) => {
        if (!isCurrentConversation()) return
        updateMessage(agentMessageId, (message) => ({
          ...message,
          content: message.content + text,
        }))
      },
      onOutline: (outline) => {
        if (!isCurrentConversation()) return
        appendVersion(outline)
      },
      onDone: () => {
        if (!isCurrentConversation()) return
        updateMessage(agentMessageId, (message) => ({
          ...message,
          streaming: false,
        }))
      },
      onError: (error) => {
        if (!isCurrentConversation()) return
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
    if (isCurrentConversation()) ElMessage.error(apiErrorMessage(error, t, t('outline.errors.stream')))
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
    <WorkflowReadiness
      v-if="selectedProjectId !== null"
      class="outline-readiness"
      :title="t('outline.readiness.title')"
      :description="t('outline.readiness.description')"
      :items="outlineReadinessItems"
    />

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
      <span>{{ t('ux.createProjectHint') }}</span>
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

  </section>
</template>

<style scoped>
.outline-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr);
  gap: 22px;
}

.outline-readiness {
  margin-bottom: 18px;
}

.outline-workspace__empty {
  padding: 56px 18px;
}

.outline-workspace__loading {
  min-height: 620px;
  padding: 32px;
}

@media (max-width: 980px) {
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

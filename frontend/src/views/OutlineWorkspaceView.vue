<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import ConversationPanel, {
  type ConversationMessage,
} from '@/components/outline/ConversationPanel.vue'
import OutlinePanel, { type OutlineVersionItem } from '@/components/outline/OutlinePanel.vue'
import { resolveOutlineSession, streamOutlineChat, type OutlineVersion } from '@/api/outline'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const loading = ref(false)
const streaming = ref(false)
const threadId = ref('')
const messages = ref<ConversationMessage[]>([])
const versions = ref<OutlineVersionItem[]>([])
const messageId = ref(1)

const projectId = computed(() => {
  const rawProjectId = route.query.project_id
  const value = Array.isArray(rawProjectId) ? rawProjectId[0] : rawProjectId
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const currentOutline = computed(() => versions.value[0]?.outline ?? '')
const isDisabled = computed(() => loading.value || projectId.value === null || !threadId.value)

const goProjects = () => {
  void router.push('/projects')
}

const toOutlineVersionItem = (version: OutlineVersion): OutlineVersionItem => ({
  version_id: version.version_id,
  version_no: version.version_no,
  outline: version.outline,
  status: version.status,
  created_at: version.created_at,
})

const loadOutlineSession = async () => {
  if (projectId.value === null) {
    return
  }

  loading.value = true
  try {
    const session = await resolveOutlineSession(projectId.value)
    threadId.value = session.thread_id
    versions.value = session.outline_versions.map(toOutlineVersionItem)
    messages.value = session.messages.map((message) => ({
      id: messageId.value++,
      role: message.role,
      content: message.content,
    }))
  } catch {
    ElMessage.error(t('outline.errors.loadSession'))
  } finally {
    loading.value = false
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
      onError: (message) => {
        updateMessage(agentMessageId, (currentMessage) => ({
          ...currentMessage,
          streaming: false,
        }))
        ElMessage.error(message || t('outline.errors.stream'))
      },
    })
  } catch {
    updateMessage(agentMessageId, (message) => ({
      ...message,
      streaming: false,
    }))
    ElMessage.error(t('outline.errors.stream'))
  } finally {
    updateMessage(agentMessageId, (message) => ({
      ...message,
      streaming: false,
    }))
    streaming.value = false
  }
}

onMounted(() => {
  if (projectId.value === null) {
    ElMessage.warning(t('outline.errors.missingProject'))
    return
  }
  void loadOutlineSession()
})
</script>

<template>
  <section>
    <div class="page-header">
      <div>
        <h1 class="page-title">{{ t('outline.title') }}</h1>
        <p class="page-subtitle">{{ t('outline.subtitle') }}</p>
      </div>
      <el-button @click="goProjects">{{ t('outline.viewProject') }}</el-button>
    </div>

    <el-alert
      v-if="projectId === null"
      class="outline-workspace__alert"
      type="warning"
      :title="t('outline.errors.missingProject')"
      show-icon
      :closable="false"
    />

    <div v-else class="outline-workspace">
      <ConversationPanel
        :messages="messages"
        :thread-id="threadId"
        :streaming="streaming"
        :disabled="isDisabled"
        @send="sendMessage"
      />
      <OutlinePanel
        :outline="currentOutline"
        :versions="versions"
        :loading="loading"
      />
    </div>
  </section>
</template>

<style scoped>
.outline-workspace {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  gap: 22px;
}

.outline-workspace__alert {
  margin-bottom: 18px;
}

@media (max-width: 1100px) {
  .outline-workspace {
    grid-template-columns: 1fr;
  }
}
</style>

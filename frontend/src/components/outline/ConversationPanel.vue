<script setup lang="ts">
import { Promotion } from '@element-plus/icons-vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

export type ConversationMessage = {
  id: number
  role: 'user' | 'agent'
  content: string
  streaming?: boolean
}

const props = defineProps<{
  messages: ConversationMessage[]
  threadId: string
  streaming: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  send: [message: string]
}>()

const { t } = useI18n()
const draft = ref('')
const bottomAnchorRef = ref<HTMLElement | null>(null)
const panelHeight = ref(760)
const isResizing = ref(false)
const resizeStartY = ref(0)
const resizeStartHeight = ref(0)

const minPanelHeight = 620
const maxPanelHeight = 1100

const canSend = computed(() => draft.value.trim().length > 0 && !props.disabled && !props.streaming)
const panelStyle = computed(() => ({
  height: `${panelHeight.value}px`,
}))

const messageScrollKey = computed(() =>
  props.messages
    .map((message) => `${message.id}:${message.content.length}:${message.streaming ? '1' : '0'}`)
    .join('|'),
)

const scrollToBottom = async () => {
  // 历史消息加载和 token 流式更新都会触发 DOM 变化，等渲染完成后再滚动。
  await nextTick()
  bottomAnchorRef.value?.scrollIntoView({
    block: 'end',
  })
}

const sendMessage = () => {
  const message = draft.value.trim()
  if (!message || !canSend.value) {
    return
  }
  draft.value = ''
  emit('send', message)
}

const clampHeight = (height: number) => {
  const viewportMaxHeight = Math.max(minPanelHeight, window.innerHeight - 120)
  return Math.min(Math.max(height, minPanelHeight), Math.min(maxPanelHeight, viewportMaxHeight))
}

const stopResize = () => {
  isResizing.value = false
  document.body.classList.remove('is-resizing-conversation')
  window.removeEventListener('mousemove', resizePanel)
  window.removeEventListener('mouseup', stopResize)
}

const resizePanel = (event: MouseEvent) => {
  if (!isResizing.value) {
    return
  }
  const deltaY = event.clientY - resizeStartY.value
  panelHeight.value = clampHeight(resizeStartHeight.value + deltaY)
}

const startResize = (event: MouseEvent) => {
  isResizing.value = true
  resizeStartY.value = event.clientY
  resizeStartHeight.value = panelHeight.value
  document.body.classList.add('is-resizing-conversation')
  window.addEventListener('mousemove', resizePanel)
  window.addEventListener('mouseup', stopResize)
}

watch(messageScrollKey, () => {
  void scrollToBottom()
})

onMounted(() => {
  panelHeight.value = clampHeight(window.innerHeight - 170)
  void scrollToBottom()
})

onBeforeUnmount(() => {
  stopResize()
})
</script>

<template>
  <section class="conversation-panel panel" :style="panelStyle">
    <header class="conversation-panel__header">
      <div>
        <h3>{{ t('outline.conversation.title') }}</h3>
        <p>{{ t('outline.conversation.description') }}</p>
      </div>
      <el-tag type="info" effect="plain">
        {{ threadId || t('outline.conversation.noThread') }}
      </el-tag>
    </header>

    <el-scrollbar class="conversation-panel__body" always>
      <div class="conversation-panel__messages">
        <el-empty
          v-if="messages.length === 0"
          :description="t('outline.conversation.empty')"
        />
        <div
          v-for="message in messages"
          v-else
          :key="message.id"
          class="conversation-panel__message"
          :class="`conversation-panel__message--${message.role}`"
        >
          <div class="conversation-panel__bubble">
            <p>{{ message.content || t('outline.conversation.streaming') }}</p>
            <el-icon v-if="message.streaming" class="conversation-panel__loading">
              <Promotion />
            </el-icon>
          </div>
        </div>
        <div ref="bottomAnchorRef" class="conversation-panel__bottom-anchor" />
      </div>
    </el-scrollbar>

    <footer class="conversation-panel__composer">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="4"
        resize="none"
        :disabled="disabled || streaming"
        :placeholder="t('outline.conversation.placeholder')"
        @keydown.enter.exact.prevent="sendMessage"
      />
      <div class="conversation-panel__composer-actions">
        <el-text type="info">
          {{ streaming ? t('outline.conversation.streamingHint') : t('outline.conversation.readyHint') }}
        </el-text>
        <el-button
          type="primary"
          :icon="Promotion"
          :loading="streaming"
          :disabled="!canSend"
          @click="sendMessage"
        >
          {{ t('outline.conversation.send') }}
        </el-button>
      </div>
    </footer>
    <div
      class="conversation-panel__resize-handle"
      role="separator"
      aria-orientation="horizontal"
      @mousedown.prevent="startResize"
    />
  </section>
</template>

<style scoped>
.conversation-panel {
  position: relative;
  display: flex;
  min-height: 620px;
  flex-direction: column;
}

.conversation-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px;
  border-bottom: 1px solid var(--panel-border);
}

.conversation-panel__header h3,
.conversation-panel__header p,
.conversation-panel__bubble p {
  margin: 0;
}

.conversation-panel__header h3 {
  font-size: 18px;
}

.conversation-panel__header p {
  margin-top: 6px;
  color: var(--text-soft);
}

.conversation-panel__body {
  flex: 1;
  min-height: 0;
}

.conversation-panel__messages {
  min-height: 100%;
  padding: 24px;
}

.conversation-panel__message {
  display: flex;
  margin-bottom: 18px;
}

.conversation-panel__bottom-anchor {
  height: 1px;
}

.conversation-panel__message--user {
  justify-content: flex-end;
}

.conversation-panel__bubble {
  max-width: min(620px, 82%);
  padding: 14px 16px;
  border-radius: 8px;
  background: #f1f5ff;
  color: var(--text-regular);
  line-height: 1.7;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.conversation-panel__message--user .conversation-panel__bubble {
  background: #4f6bff;
  color: #fff;
}

.conversation-panel__loading {
  margin-top: 10px;
  color: var(--brand);
}

.conversation-panel__composer {
  padding: 18px 24px 22px;
  border-top: 1px solid var(--panel-border);
}

.conversation-panel__composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 12px;
}

.conversation-panel__resize-handle {
  position: absolute;
  right: 0;
  bottom: -8px;
  left: 0;
  height: 16px;
  cursor: ns-resize;
}

.conversation-panel__resize-handle::after {
  position: absolute;
  top: 6px;
  left: 50%;
  width: 58px;
  height: 4px;
  border-radius: 999px;
  background: #c8d0dd;
  content: '';
  transform: translateX(-50%);
}

:global(body.is-resizing-conversation) {
  cursor: ns-resize;
  user-select: none;
}
</style>

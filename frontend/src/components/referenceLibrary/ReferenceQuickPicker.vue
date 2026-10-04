<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Check, ZoomIn } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import type { ReferenceCategory, ReferenceImageTask } from '@/api/referenceImages'
import type { QuickReferenceImage, ReferenceOwner } from './referenceLibrary'

// 对象与图片选择由素材库统一维护；弹窗只处理预览和用户操作。
const props = defineProps<{
  categories: ReferenceCategory[]
  category: ReferenceCategory
  owners: Array<ReferenceOwner & { approvedCount: number }>
  ownerKey: string | null
  sceneScope: number
  showSceneScope?: boolean
  sceneScopeOptions: Array<{ id: number; label: string }>
  tasks: ReferenceImageTask[]
  taskId: number | null
  candidates: QuickReferenceImage[]
  assets: QuickReferenceImage[]
  selectedImageKey: string | null
  busy: boolean
  loading: boolean
  unavailable: boolean
  reachedEnd: boolean
}>()
const emit = defineEmits<{
  close: []
  category: [value: ReferenceCategory]
  owner: [key: string]
  sceneScope: [id: number]
  task: [id: number]
  select: [key: string]
  move: [direction: -1 | 1]
  confirm: [key: string]
}>()
const { t } = useI18n()
const previewUrl = ref<string | null>(null)
const gallery = ref<HTMLElement | null>(null)
const ownerIndex = computed(() => props.owners.findIndex((owner) => owner.key === props.ownerKey))
const sections = computed(() => [
  { key: 'candidates', title: t('referenceLibrary.quick.candidates'), images: props.candidates },
  { key: 'assets', title: t('referenceLibrary.images'), images: props.assets },
])
const locked = computed(() => props.busy || props.loading)
const selectImage = (key: string) => {
  if (!locked.value) emit('select', key)
}
watch(
  () => [props.category, props.ownerKey, props.sceneScope, props.taskId],
  () => {
    previewUrl.value = null
    // 每个对象从首排候选开始，避免沿用上一对象的图片滚动位置。
    gallery.value?.closest('.el-dialog__body')?.scrollTo({ top: 0 })
  },
  { flush: 'post' },
)
</script>

<template>
  <el-dialog
    class="reference-quick-dialog"
    :model-value="true"
    append-to-body
    :title="t('referenceLibrary.quick.title')"
    width="min(1100px, calc(100vw - 28px))"
    top="24px"
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    :show-close="!busy"
    @close="emit('close')"
  >
    <template #header>
      <h2>{{ t('referenceLibrary.quick.title') }}</h2>
      <p class="quick-help">
        {{
          t(
            category === 'character'
              ? 'referenceLibrary.quick.characterHelp'
              : 'referenceLibrary.quick.autoHelp',
          )
        }}
      </p>
      <div class="quick-controls">
        <el-segmented
          class="quick-category"
          :model-value="category"
          :disabled="locked"
          :options="
            categories.map((value) => ({ value, label: t(`referenceLibrary.categories.${value}`) }))
          "
          @change="emit('category', $event as ReferenceCategory)"
        />
        <label class="quick-field">
          <span>{{ t('referenceLibrary.owner') }}</span>
          <el-select
            :model-value="ownerKey"
            filterable
            :disabled="locked"
            :aria-label="t('referenceLibrary.owner')"
            @change="emit('owner', $event)"
          >
            <el-option
              v-for="owner in owners"
              :key="owner.key"
              :value="owner.key"
              :label="`${owner.name} · ${t('referenceLibrary.confirmedCount', { count: owner.approvedCount })}`"
            />
          </el-select>
        </label>
        <label class="quick-field">
          <span>{{ t('referenceLibrary.history') }}</span>
          <el-select
            :model-value="taskId"
            :disabled="locked || tasks.length === 0"
            :placeholder="t('referenceLibrary.quick.noRecords')"
            :aria-label="t('referenceLibrary.history')"
            @change="emit('task', $event)"
          >
            <el-option
              v-for="task in tasks"
              :key="task.id"
              :value="task.id"
              :label="`#${task.id} · ${task.tool_name} · ${t(`visualBible.references.status.${task.status}`)}`"
            />
          </el-select>
        </label>
        <label v-if="category === 'scene' && showSceneScope !== false" class="quick-field quick-scope">
          <span>{{ t('referenceLibrary.sceneScope') }}</span>
          <el-select
            :model-value="sceneScope"
            :disabled="locked"
            :aria-label="t('referenceLibrary.sceneScope')"
            @change="emit('sceneScope', $event)"
          >
            <el-option :value="0" :label="t('referenceLibrary.sceneGeneral')" />
            <el-option
              v-for="option in sceneScopeOptions"
              :key="option.id"
              :value="option.id"
              :label="option.label"
            />
          </el-select>
        </label>
      </div>
    </template>

    <div ref="gallery" class="quick-images" :aria-busy="locked">
      <el-alert
        v-if="unavailable"
        type="warning"
        :closable="false"
        :title="t('visualBible.errors.targetUnavailable')"
      />
      <el-empty
        v-else-if="candidates.length + assets.length === 0"
        :image-size="64"
        :description="t('referenceLibrary.quick.noImages')"
      />
      <template v-else>
        <section
          v-for="section in sections.filter((item) => item.images.length)"
          :key="section.key"
          class="quick-section"
        >
          <h3>
            {{ section.title }} <span>({{ section.images.length }})</span>
          </h3>
          <div class="quick-grid">
            <article
              v-for="image in section.images"
              :key="image.key"
              class="quick-image"
              :class="{ 'is-selected': selectedImageKey === image.key }"
              :data-image-key="image.key"
              role="button"
              :tabindex="locked ? -1 : 0"
              :aria-pressed="selectedImageKey === image.key"
              :aria-disabled="locked"
              :aria-label="[image.label, image.applicability].filter(Boolean).join(' · ')"
              @click="selectImage(image.key)"
              @keydown.enter.prevent="selectImage(image.key)"
              @keydown.space.prevent="selectImage(image.key)"
            >
              <div class="quick-image-media">
                <el-image
                  v-if="image.imageUrl"
                  :src="image.imageUrl"
                  :alt="image.label"
                  fit="contain"
                  lazy
                />
                <div v-else class="quick-placeholder">
                  {{ t('visualBible.assets.noLocalPreview') }}
                </div>
                <el-button
                  v-if="!image.approved"
                  class="quick-approve"
                  type="success"
                  size="small"
                  :icon="Check"
                  :loading="busy && selectedImageKey === image.key"
                  :disabled="locked || unavailable || !image.canApprove"
                  @click.stop="emit('confirm', image.key)"
                  @keydown.stop
                >
                  {{ t('visualBible.approve') }}
                </el-button>
              </div>
              <strong>{{ image.label }}</strong>
              <span v-if="image.applicability" class="quick-applicability">{{
                image.applicability
              }}</span>
              <div class="quick-image-actions">
                <el-tag :type="image.approved ? 'success' : 'info'">{{
                  t(image.approved ? 'visualBible.status.approved' : 'visualBible.status.draft')
                }}</el-tag>
                <el-button
                  v-if="image.imageUrl"
                  size="small"
                  :icon="ZoomIn"
                  :aria-label="`${t('referenceLibrary.quick.preview')} · ${image.label}`"
                  @click.stop="previewUrl = image.imageUrl"
                  @keydown.stop
                >
                  {{ t('referenceLibrary.quick.preview') }}
                </el-button>
              </div>
            </article>
          </div>
        </section>
      </template>
    </div>

    <template #footer>
      <div class="quick-footer">
        <div class="quick-position" aria-live="polite">
          <span>{{
            t('referenceLibrary.quick.position', { current: ownerIndex + 1, total: owners.length })
          }}</span>
          <span v-if="reachedEnd">{{ t('referenceLibrary.quick.end') }}</span>
        </div>
        <div class="quick-navigation">
          <el-button
            :icon="ArrowLeft"
            :disabled="locked || ownerIndex <= 0"
            @click="emit('move', -1)"
            >{{ t('referenceLibrary.quick.previous') }}</el-button
          >
          <el-button
            :icon="ArrowRight"
            :disabled="locked || ownerIndex < 0 || ownerIndex >= owners.length - 1"
            @click="emit('move', 1)"
            >{{ t('referenceLibrary.quick.next') }}</el-button
          >
        </div>
        <div class="quick-close">
          <el-button :disabled="busy" @click="emit('close')">{{
            t('referenceLibrary.quick.close')
          }}</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
  <el-image-viewer
    v-if="previewUrl"
    :url-list="[previewUrl]"
    teleported
    @close="previewUrl = null"
  />
</template>

<style scoped>
:global(.reference-quick-dialog) {
  display: flex;
  flex-direction: column;
  height: min(840px, calc(100dvh - 48px));
  margin-bottom: 24px;
}
:global(.reference-quick-dialog .el-dialog__header),
:global(.reference-quick-dialog .el-dialog__footer) {
  flex-shrink: 0;
}
:global(.reference-quick-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
:global(.reference-quick-dialog .el-dialog__footer) {
  border-top: 1px solid var(--panel-border);
  padding-top: 12px;
}
h2,
h3,
p {
  margin: 0;
}
h2 {
  font-size: 18px;
}
h3 {
  font-size: 15px;
  margin-bottom: 12px;
}
h3 span,
.quick-help,
.quick-applicability,
.quick-position {
  color: var(--text-soft);
  font-size: 12px;
  line-height: 1.5;
}
.quick-help {
  margin: 6px 0 12px;
}
.quick-controls {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
}
.quick-category,
.quick-scope {
  grid-column: 1 / -1;
}
.quick-category {
  justify-self: start;
}
.quick-field {
  display: grid;
  min-width: 0;
  gap: 4px;
  font-size: 12px;
}
.quick-field .el-select {
  width: 100%;
}
.quick-section + .quick-section {
  margin-top: 22px;
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 210px), 1fr));
  gap: 14px;
}
.quick-image {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 10px;
  min-width: 0;
  border: 2px solid var(--panel-border);
  border-radius: 9px;
  cursor: pointer;
  font-size: 13px;
}
.quick-image:hover {
  border-color: var(--el-color-primary-light-5);
}
.quick-image.is-selected {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.quick-image:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}
.quick-image[aria-disabled='true'] {
  cursor: default;
}
.quick-image-media {
  position: relative;
  height: 200px;
}
.quick-image-media .el-image,
.quick-placeholder {
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  border-radius: 5px;
}
.quick-approve {
  position: absolute;
  right: 6px;
  bottom: 6px;
  max-width: calc(100% - 12px);
  height: auto;
  min-height: 24px;
  padding: 5px 6px;
}
.quick-approve :deep(span) {
  min-width: 0;
  white-space: normal;
}
.quick-placeholder {
  display: grid;
  place-items: center;
  color: var(--text-soft);
}
.quick-image strong,
.quick-applicability {
  overflow-wrap: anywhere;
}
.quick-image-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}
.quick-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  text-align: left;
}
.quick-position {
  display: grid;
  margin-right: auto;
}
.quick-navigation,
.quick-close {
  display: flex;
  gap: 8px;
}
.quick-footer .el-button + .el-button {
  margin-left: 0;
}
@media (max-width: 600px) {
  .quick-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .quick-image {
    padding: 7px;
    gap: 7px;
  }
  .quick-image-media {
    height: 155px;
  }
  .quick-footer {
    gap: 8px;
  }
  .quick-position {
    flex-basis: 100%;
  }
  .quick-close {
    margin-left: auto;
  }
  .quick-footer .el-button {
    padding: 7px 9px;
  }
}
</style>

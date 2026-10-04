<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Check, ZoomIn } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'
import type { ImageGenerationPage } from '@/api/imageGeneration'

// 工作台负责保存终稿与切换页面；弹窗只维护预览和候选高亮。
const props = defineProps<{
  pages: ImageGenerationPage[]
  pageId: number | null
  savingImageId: number | null
  loading: boolean
  reachedEnd: boolean
}>()
const emit = defineEmits<{
  close: []
  page: [id: number]
  move: [direction: -1 | 1]
  confirm: [imageId: number]
}>()
const { t } = useI18n()
const previewUrl = ref<string | null>(null)
const highlightedImageId = ref<number | null>(null)
const gallery = ref<HTMLElement | null>(null)
const pageIndex = computed(() => props.pages.findIndex((page) => page.page_id === props.pageId))
const currentPage = computed(() => props.pages[pageIndex.value] ?? null)
const locked = computed(() => props.savingImageId !== null || props.loading)
const highlight = (id: number) => {
  if (!locked.value) highlightedImageId.value = id
}
watch(
  () => props.pageId,
  () => {
    highlightedImageId.value = null
    previewUrl.value = null
    gallery.value?.closest('.el-dialog__body')?.scrollTo({ top: 0 })
  },
  { flush: 'post' },
)
</script>

<template>
  <el-dialog
    class="comic-quick-dialog"
    :model-value="true"
    append-to-body
    :title="t('imageGeneration.quick.title')"
    width="min(1100px, calc(100vw - 28px))"
    top="24px"
    :close-on-click-modal="savingImageId === null"
    :close-on-press-escape="savingImageId === null"
    :show-close="savingImageId === null"
    @close="emit('close')"
  >
    <template #header>
      <h2>{{ t('imageGeneration.quick.title') }}</h2>
      <p class="quick-help">{{ t('imageGeneration.quick.help') }}</p>
      <label class="quick-field">
        <span>{{ t('imageGeneration.quick.page') }}</span>
        <el-select
          :model-value="pageId"
          filterable
          :disabled="locked"
          :aria-label="t('imageGeneration.quick.page')"
          @change="emit('page', $event)"
        >
          <el-option
            v-for="page in pages"
            :key="page.page_id"
            :value="page.page_id"
            :label="`${t('imageGeneration.pages.pageLabel', { page: page.page_no })} · ${t(page.selected_image_id !== null ? 'imageGeneration.pages.selected' : 'imageGeneration.quick.unselected')} · ${t('imageGeneration.quick.candidateCount', { count: page.images.length })}`"
          />
        </el-select>
      </label>
    </template>

    <div ref="gallery" v-loading="loading" class="quick-images" :aria-busy="locked">
      <el-empty
        v-if="!currentPage?.images.length"
        :image-size="64"
        :description="t('imageGeneration.pages.noImages')"
      />
      <div v-else class="quick-grid">
        <article
          v-for="(image, index) in currentPage.images"
          :key="image.id"
          class="quick-image"
          :class="{
            'is-highlighted': highlightedImageId === image.id,
            'is-final': currentPage.selected_image_id === image.id,
          }"
          :data-image-id="image.id"
          role="button"
          :tabindex="locked ? -1 : 0"
          :aria-pressed="highlightedImageId === image.id"
          :aria-disabled="locked"
          :aria-label="
            t('imageGeneration.pages.candidateImage', {
              page: currentPage.page_no,
              index: index + 1,
            })
          "
          @click="highlight(image.id)"
          @keydown.enter.prevent="highlight(image.id)"
          @keydown.space.prevent="highlight(image.id)"
        >
          <div class="quick-image-media">
            <el-image
              v-if="image.image_url"
              :src="image.image_url"
              fit="contain"
              lazy
              :alt="
                t('imageGeneration.pages.candidateImage', {
                  page: currentPage.page_no,
                  index: index + 1,
                })
              "
            />
            <div v-else class="quick-placeholder">{{ t('visualBible.assets.noLocalPreview') }}</div>
            <el-button
              v-if="currentPage.selected_image_id !== image.id"
              class="quick-confirm"
              type="success"
              size="small"
              :icon="Check"
              :loading="savingImageId === image.id"
              :disabled="locked"
              @click.stop="emit('confirm', image.id)"
              @keydown.stop
            >
              {{ t('imageGeneration.actions.select') }}
            </el-button>
          </div>
          <strong>{{ t('imageGeneration.quick.candidate', { index: index + 1 }) }}</strong>
          <div class="quick-image-actions">
            <el-tag :type="currentPage.selected_image_id === image.id ? 'success' : 'info'">
              {{
                t(
                  currentPage.selected_image_id === image.id
                    ? 'imageGeneration.pages.selected'
                    : 'imageGeneration.quick.unselected',
                )
              }}
            </el-tag>
            <el-button
              v-if="image.image_url"
              size="small"
              :icon="ZoomIn"
              :aria-label="`${t('imageGeneration.quick.preview')} · ${t('imageGeneration.quick.candidate', { index: index + 1 })}`"
              @click.stop="previewUrl = image.image_url"
              @keydown.stop
            >
              {{ t('imageGeneration.quick.preview') }}
            </el-button>
          </div>
        </article>
      </div>
    </div>

    <template #footer>
      <div class="quick-footer">
        <div class="quick-position" aria-live="polite">
          <span>{{
            t('imageGeneration.quick.position', { current: pageIndex + 1, total: pages.length })
          }}</span>
          <span v-if="reachedEnd">{{ t('imageGeneration.quick.end') }}</span>
        </div>
        <div class="quick-navigation">
          <el-button
            :icon="ArrowLeft"
            :disabled="locked || pageIndex <= 0"
            @click="emit('move', -1)"
          >
            {{ t('imageGeneration.quick.previous') }}
          </el-button>
          <el-button
            :icon="ArrowRight"
            :disabled="locked || pageIndex < 0 || pageIndex >= pages.length - 1"
            @click="emit('move', 1)"
          >
            {{ t('imageGeneration.quick.next') }}
          </el-button>
        </div>
        <el-button class="quick-close" :disabled="savingImageId !== null" @click="emit('close')">
          {{ t('imageGeneration.quick.close') }}
        </el-button>
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
:global(.comic-quick-dialog) {
  display: flex;
  flex-direction: column;
  height: min(840px, calc(100dvh - 48px));
  margin-bottom: 24px;
}
:global(.comic-quick-dialog .el-dialog__header),
:global(.comic-quick-dialog .el-dialog__footer) {
  flex-shrink: 0;
}
:global(.comic-quick-dialog .el-dialog__body) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
:global(.comic-quick-dialog .el-dialog__footer) {
  border-top: 1px solid var(--panel-border);
  padding-top: 12px;
}
h2,
p {
  margin: 0;
}
h2 {
  font-size: 18px;
}
.quick-help,
.quick-position {
  color: var(--text-soft);
  font-size: 12px;
  line-height: 1.5;
}
.quick-help {
  margin: 6px 0 12px;
}
.quick-field {
  display: grid;
  gap: 4px;
  font-size: 12px;
}
.quick-field .el-select {
  width: 100%;
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
.quick-image.is-final {
  border-color: var(--el-color-success);
}
.quick-image.is-highlighted {
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
  height: 260px;
}
.quick-image-media .el-image,
.quick-placeholder {
  width: 100%;
  height: 100%;
  background: var(--el-fill-color-light);
  border-radius: 5px;
}
.quick-confirm {
  position: absolute;
  right: 6px;
  bottom: 6px;
  max-width: calc(100% - 12px);
  height: auto;
  min-height: 24px;
  padding: 5px 6px;
}
.quick-confirm :deep(span) {
  min-width: 0;
  white-space: normal;
}
.quick-placeholder {
  display: grid;
  place-items: center;
  color: var(--text-soft);
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
.quick-navigation {
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
    height: 185px;
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

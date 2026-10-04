<script setup lang="ts">
import { InfoFilled } from '@element-plus/icons-vue'
import { useI18n } from 'vue-i18n'

defineProps<{ content: string; label: string }>()
const { t } = useI18n()
</script>

<template>
  <!-- 说明按需展示；键盘和触屏也能打开，不占用正文空间。 -->
  <el-tooltip :content="content" :trigger="['hover', 'focus', 'click']" placement="top" popper-class="info-tip-popper" :show-after="150">
    <button type="button" class="info-tip" :aria-label="t('ux.informationFor', { label })" @click.stop @keydown.stop>
      <el-icon><InfoFilled /></el-icon>
    </button>
  </el-tooltip>
</template>

<style scoped>
.info-tip {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-soft);
  vertical-align: middle;
  cursor: help;
}
.info-tip:hover, .info-tip:focus-visible { background: var(--el-color-primary-light-9); color: var(--brand); }
</style>

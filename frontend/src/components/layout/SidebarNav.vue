<script setup lang="ts">
import { ChatLineRound, FolderOpened, MagicStick, Picture, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

const route = useRoute()
const { t } = useI18n()

// Element Plus 的 menu 通过 active path 高亮当前模块。
const activePath = computed(() => route.path)
</script>

<template>
  <aside class="sidebar-nav">
    <div class="sidebar-nav__brand">
      <div class="sidebar-nav__mark">C</div>
      <div>
        <strong>{{ t('app.productName') }}</strong>
        <span>{{ t('app.productSubtitle') }}</span>
      </div>
    </div>

    <el-menu
      :default-active="activePath"
      router
      background-color="#111827"
      text-color="#cbd5e1"
      active-text-color="#ffffff"
      class="sidebar-nav__menu"
    >
      <el-menu-item index="/projects">
        <el-icon><FolderOpened /></el-icon>
        <span>{{ t('nav.projects') }}</span>
      </el-menu-item>
      <el-menu-item index="/outline">
        <el-icon><ChatLineRound /></el-icon>
        <span>{{ t('nav.outline') }}</span>
      </el-menu-item>
      <el-menu-item index="/scripts" disabled>
        <el-icon><Tickets /></el-icon>
        <span>{{ t('nav.scripts') }}</span>
      </el-menu-item>
      <el-menu-item index="/prompts" disabled>
        <el-icon><MagicStick /></el-icon>
        <span>{{ t('nav.prompts') }}</span>
      </el-menu-item>
      <el-menu-item index="/gallery" disabled>
        <el-icon><Picture /></el-icon>
        <span>{{ t('nav.gallery') }}</span>
      </el-menu-item>
    </el-menu>
  </aside>
</template>

<style scoped>
.sidebar-nav {
  min-height: 100%;
  padding: 22px 14px;
}

.sidebar-nav__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 10px 24px;
}

.sidebar-nav__mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 8px;
  background: #4f6bff;
  font-weight: 800;
}

.sidebar-nav__brand strong,
.sidebar-nav__brand span {
  display: block;
}

.sidebar-nav__brand span {
  margin-top: 4px;
  color: #94a3b8;
  font-size: 12px;
}

.sidebar-nav__menu {
  border-right: 0;
}

:deep(.el-menu-item) {
  border-radius: 8px;
}

@media (max-width: 860px) {
  .sidebar-nav {
    min-height: auto;
    padding-bottom: 10px;
  }
}
</style>

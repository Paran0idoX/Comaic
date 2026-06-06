<script setup lang="ts">
import { ChatLineRound, MagicStick, Picture, Tickets } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import logoUrl from '@/assets/logo/logo.svg'

const route = useRoute()
const { t } = useI18n()

// Element Plus 的 menu 通过 active path 高亮当前模块。
const activePath = computed(() => route.path)
</script>

<template>
  <aside class="sidebar-nav">
    <div class="sidebar-nav__brand">
      <img class="sidebar-nav__mark" :src="logoUrl" :alt="t('app.productName')" />
      <div>
        <strong>{{ t('app.productName') }}</strong>
        <span>{{ t('app.productSubtitle') }}</span>
      </div>
    </div>

    <el-menu
      :default-active="activePath"
      router
      background-color="transparent"
      text-color="#aebfd6"
      active-text-color="#ffffff"
      class="sidebar-nav__menu"
    >
      <el-menu-item index="/outline">
        <el-icon><ChatLineRound /></el-icon>
        <span>{{ t('nav.outline') }}</span>
      </el-menu-item>
      <el-menu-item index="/scripts">
        <el-icon><Tickets /></el-icon>
        <span>{{ t('nav.scripts') }}</span>
      </el-menu-item>
      <el-menu-item index="/prompts">
        <el-icon><MagicStick /></el-icon>
        <span>{{ t('nav.prompts') }}</span>
      </el-menu-item>
      <el-menu-item index="/image-generation">
        <el-icon><Picture /></el-icon>
        <span>{{ t('nav.imageGeneration') }}</span>
      </el-menu-item>
    </el-menu>
  </aside>
</template>

<style scoped>
.sidebar-nav {
  min-height: 100%;
  padding: 22px 14px;
  background: transparent;
}

.sidebar-nav__brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 10px 24px;
}

.sidebar-nav__mark {
  width: 38px;
  height: 38px;
  object-fit: contain;
}

.sidebar-nav__brand strong,
.sidebar-nav__brand span {
  display: block;
}

.sidebar-nav__brand span {
  margin-top: 4px;
  color: #93a8c7;
  font-size: 12px;
}

.sidebar-nav__menu {
  border-right: 0;
  background: transparent;
}

:deep(.el-menu-item) {
  height: 46px;
  margin: 4px 0;
  border-radius: 8px;
  color: #aebfd6;
}

:deep(.el-menu-item:hover) {
  background: rgba(16, 181, 244, 0.1);
  color: #ffffff;
}

:deep(.el-menu-item.is-active) {
  background: linear-gradient(135deg, #10b5f4, #176dff, #8b1cff);
  box-shadow: none;
}

:deep(.el-menu-item.is-active .el-icon) {
  color: #ffffff;
}

@media (max-width: 860px) {
  .sidebar-nav {
    min-height: auto;
    padding-bottom: 10px;
  }
}
</style>

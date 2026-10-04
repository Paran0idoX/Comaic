<script setup lang="ts">
import { ChatLineRound, Collection, MagicStick, Picture, Tickets } from '@element-plus/icons-vue'
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
        <span class="sidebar-nav__step">1</span>
        <el-icon><ChatLineRound /></el-icon>
        <span>{{ t('nav.outline') }}</span>
      </el-menu-item>
      <el-menu-item index="/scripts">
        <span class="sidebar-nav__step">2</span>
        <el-icon><Tickets /></el-icon>
        <span>{{ t('nav.scripts') }}</span>
      </el-menu-item>
      <el-menu-item index="/visual-bible">
        <span class="sidebar-nav__step">3</span>
        <el-icon><Collection /></el-icon>
        <span>{{ t('nav.visualBible') }}</span>
      </el-menu-item>
      <el-menu-item index="/image-specs">
        <span class="sidebar-nav__step">4</span>
        <el-icon><MagicStick /></el-icon>
        <span>{{ t('nav.imageSpecs') }}</span>
      </el-menu-item>
      <el-menu-item index="/image-generation">
        <span class="sidebar-nav__step">5</span>
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
  position: relative;
  height: 46px;
  margin: 4px 0;
  border-radius: 8px;
  color: #aebfd6;
}

.sidebar-nav__step {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 auto;
  place-items: center;
  margin-right: 8px;
  border: 1px solid rgba(174, 191, 214, 0.36);
  border-radius: 50%;
  color: #aebfd6;
  font-size: 11px;
  line-height: 1;
}

:deep(.el-menu-item.is-active) .sidebar-nav__step {
  border-color: rgba(255, 255, 255, 0.55);
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
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
    padding: 10px 12px;
  }

  .sidebar-nav__brand {
    padding: 0 6px 8px;
  }

  .sidebar-nav__mark {
    width: 30px;
    height: 30px;
  }

  .sidebar-nav__menu {
    display: flex;
    overflow-x: auto;
    gap: 4px;
    scrollbar-width: none;
  }

  .sidebar-nav__menu::-webkit-scrollbar {
    display: none;
  }

  :deep(.el-menu-item) {
    min-width: max-content;
    flex: 0 0 auto;
    padding: 0 14px;
  }
}
</style>
